#!/usr/bin/env node
'use strict';

const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const { fileURLToPath } = require('url');
const { execFile } = require('child_process');

const SERVER_VERSION = '1.0.2';

function parseArgs(argv) {
  let slug = process.env.SLUG_BIN || 'slug';
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--slug') {
      if (i + 1 >= argv.length) throw new Error('missing --slug value');
      slug = argv[++i];
    } else if (a === '--help' || a === '-h') {
      process.stderr.write('usage: slug-lsp.js [--slug <compiler>]\n');
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${a}`);
    }
  }
  return { slug };
}

let config;
try {
  config = parseArgs(process.argv);
} catch (e) {
  process.stderr.write(`slug-lsp: ${e.message}\n`);
  process.exit(64);
}

const documents = new Map();
const validationTimers = new Map();
let input = Buffer.alloc(0);
let shuttingDown = false;
let shadowCounter = 0;
let toolingInfo = null;

function send(payload) {
  const body = JSON.stringify(payload);
  const header = `Content-Length: ${Buffer.byteLength(body, 'utf8')}\r\n\r\n`;
  process.stdout.write(header + body);
}

function reply(id, result) {
  send({ jsonrpc: '2.0', id, result });
}

function replyError(id, code, message, data) {
  const error = { code, message };
  if (data !== undefined) error.data = data;
  send({ jsonrpc: '2.0', id, error });
}

function notify(method, params) {
  send({ jsonrpc: '2.0', method, params });
}

function runSlug(args, cwd, inputText) {
  return new Promise((resolve) => {
    const child = execFile(config.slug, args, {
      cwd,
      encoding: 'utf8',
      windowsHide: true,
      maxBuffer: 16 * 1024 * 1024,
      env: process.env,
    }, (error, stdout, stderr) => {
      let code = 0;
      if (error) {
        if (typeof error.code === 'number') code = error.code;
        else code = 70;
      }
      resolve({ code, stdout: stdout || '', stderr: stderr || '' });
    });
    if (inputText !== undefined) child.stdin.end(inputText);
  });
}

function uriToPath(uri) {
  if (!uri || typeof uri !== 'string' || !uri.startsWith('file:')) {
    throw new Error('SLUG LSP currently supports file:// document URIs only');
  }
  return fileURLToPath(uri);
}

function endPosition(text) {
  const lines = text.split('\n');
  return { line: lines.length - 1, character: lines[lines.length - 1].length };
}

function fullDocumentRange(text) {
  return { start: { line: 0, character: 0 }, end: endPosition(text) };
}

function lspPositionFromSlug(text, line1, column1) {
  const lines = text.split('\n');
  const li = Math.max(0, Math.min(lines.length - 1, Number(line1 || 1) - 1));
  const scalarColumn = Math.max(0, Number(column1 || 1) - 1);
  const prefix = Array.from(lines[li]).slice(0, scalarColumn).join('');
  return { line: li, character: prefix.length };
}

function parseFailureLocation(stdout, text) {
  const lines = String(stdout || '').replace(/\r/g, '').split('\n');
  if (lines[0] !== '1' || lines.length < 6) return null;
  const line = Number(lines[1]);
  const column = Number(lines[2]);
  const endLine = Number(lines[3]);
  const endColumn = Number(lines[4]);
  if (![line, column, endLine, endColumn].every(Number.isFinite)) return null;
  const start = lspPositionFromSlug(text, line, column);
  let end = lspPositionFromSlug(text, endLine, endColumn);
  if (end.line === start.line && end.character <= start.character) {
    end = { line: start.line, character: start.character + 1 };
  }
  return { start, end };
}

async function withShadowFile(doc, fn) {
  const realPath = uriToPath(doc.uri);
  const dir = path.dirname(realPath);
  const base = path.basename(realPath);
  const shadow = path.join(dir, `.${base}.slug-lsp-${process.pid}-${++shadowCounter}.slg`);
  await fsp.writeFile(shadow, doc.text, { encoding: 'utf8', flag: 'wx' });
  try {
    return await fn(shadow, dir);
  } finally {
    try { await fsp.unlink(shadow); } catch (_) {}
  }
}

function parseDiagnostic(stderr, fallbackFile) {
  const trimmed = stderr.trim();
  if (!trimmed) return null;
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    try {
      const obj = JSON.parse(lines[i]);
      if (obj && obj.schema === 1 && obj.severity === 'error') {
        const s = obj.span && obj.span.start ? obj.span.start : { line: 1, column: 1 };
        const e = obj.span && obj.span.end ? obj.span.end : s;
        const sl = Math.max(0, Number(s.line || 1) - 1);
        const sc = Math.max(0, Number(s.column || 1) - 1);
        const el = Math.max(sl, Number(e.line || s.line || 1) - 1);
        const ec0 = Math.max(0, Number(e.column || s.column || 1) - 1);
        const ec = (el === sl && ec0 === sc) ? sc + 1 : ec0;
        return {
          range: { start: { line: sl, character: sc }, end: { line: el, character: ec } },
          severity: 1,
          source: 'slug',
          code: obj.kind || 'compile',
          message: String(obj.message || 'SLUG compilation error'),
          data: { schema: 1, file: obj.file || fallbackFile || '' },
        };
      }
    } catch (_) {}
  }
  return null;
}

async function validateDocument(doc) {
  const validationVersion = doc.version;
  const realPath = uriToPath(doc.uri);
  const cwd = path.dirname(realPath);
  let result;
  if (toolingInfo && toolingInfo.capabilities && toolingInfo.capabilities.stdin_overlay) {
    result = await runSlug(['tooling-check', realPath, '--diagnostic-format', 'json'], cwd, doc.text);
  } else {
    result = await withShadowFile(doc, async (shadow, shadowCwd) => {
      return runSlug(['check', shadow, '--diagnostic-format', 'json'], shadowCwd);
    });
  }
  const current = documents.get(doc.uri);
  if (!current || current.version !== validationVersion) return;

  let diagnostics = [];
  if (result.code !== 0) {
    const d = parseDiagnostic(result.stderr, uriToPath(doc.uri));
    if (d && toolingInfo && toolingInfo.capabilities && toolingInfo.capabilities.failure_locator) {
      const located = await runSlug(['tooling-locate', realPath], cwd, doc.text);
      if (located.code === 0) {
        const range = parseFailureLocation(located.stdout, doc.text);
        if (range) { d.range = range; d.data = { ...(d.data || {}), positionMode: 'failure-provenance-v2' }; }
      }
    }
    if (d) diagnostics = [d];
    else diagnostics = [{
      range: { start: { line: 0, character: 0 }, end: { line: 0, character: 1 } },
      severity: 1,
      source: 'slug-lsp',
      code: 'tooling',
      message: (result.stderr || `slug check failed with exit ${result.code}`).trim(),
    }];
  }
  notify('textDocument/publishDiagnostics', { uri: doc.uri, version: validationVersion, diagnostics });
}

function scheduleValidation(doc, delayMs = 150) {
  const prior = validationTimers.get(doc.uri);
  if (prior) clearTimeout(prior);
  const timer = setTimeout(() => {
    validationTimers.delete(doc.uri);
    const current = documents.get(doc.uri);
    if (!current || current.version !== doc.version) return;
    validateDocument(current).catch((e) => process.stderr.write(`slug-lsp diagnostics: ${e.message}\n`));
  }, delayMs);
  validationTimers.set(doc.uri, timer);
}

async function formatDocument(doc) {
  const realPath = uriToPath(doc.uri);
  const cwd = path.dirname(realPath);
  let result;
  if (toolingInfo && toolingInfo.capabilities && toolingInfo.capabilities.stdin_overlay) {
    result = await runSlug(['tooling-format', realPath], cwd, doc.text);
  } else {
    result = await withShadowFile(doc, async (shadow, shadowCwd) => runSlug(['fmt', shadow], shadowCwd));
  }
  if (result.code !== 0) throw new Error((result.stderr || `slug fmt failed with exit ${result.code}`).trim());
  if (result.stdout === doc.text) return [];
  return [{ range: fullDocumentRange(doc.text), newText: result.stdout }];
}

async function getToolingInfo() {
  const r = await runSlug(['tooling-info'], process.cwd());
  if (r.code !== 0) throw new Error((r.stderr || 'slug tooling-info failed').trim());
  const info = JSON.parse(r.stdout);
  toolingInfo = info;
  return info;
}

async function getProjectInfo(params) {
  const args = ['project-info'];
  let cwd = process.cwd();
  if (params && params.uri) {
    const p = uriToPath(params.uri);
    args.push(p);
    cwd = path.dirname(p);
  }
  const r = await runSlug(args, cwd);
  if (r.code !== 0) throw new Error((r.stderr || 'slug project-info failed').trim());
  return JSON.parse(r.stdout);
}

async function handleRequest(msg) {
  const id = msg.id;
  try {
    switch (msg.method) {
      case 'initialize': {
        const tooling = await getToolingInfo();
        reply(id, {
          capabilities: {
            textDocumentSync: { openClose: true, change: 1, save: { includeText: false } },
            documentFormattingProvider: true,
            experimental: {
              slugToolingInfo: true,
              slugProjectInfo: true,
              unsavedBufferMode: tooling.capabilities && tooling.capabilities.stdin_overlay ? 'stdin-overlay' : 'same-directory-shadow',
              nativeDiagnosticSchema: tooling.diagnostic_schema,
              nativeDiagnosticPositions: tooling.capabilities && tooling.capabilities.semantic_provenance && tooling.capabilities.lexical_provenance ? 'failure-provenance-v2' : (tooling.capabilities && tooling.capabilities.failure_locator ? 'failure-pass-v1' : 'placeholder-v1'),
            },
          },
          serverInfo: { name: 'slug-lsp', version: SERVER_VERSION },
        });
        return;
      }
      case 'shutdown':
        shuttingDown = true;
        reply(id, null);
        return;
      case 'textDocument/formatting': {
        const uri = msg.params && msg.params.textDocument && msg.params.textDocument.uri;
        const doc = documents.get(uri);
        if (!doc) { replyError(id, -32602, 'document is not open'); return; }
        reply(id, await formatDocument(doc));
        return;
      }
      case 'slug/toolingInfo':
        reply(id, await getToolingInfo());
        return;
      case 'slug/projectInfo':
        reply(id, await getProjectInfo(msg.params || {}));
        return;
      default:
        replyError(id, -32601, `method not found: ${msg.method}`);
        return;
    }
  } catch (e) {
    replyError(id, -32603, e && e.message ? e.message : String(e));
  }
}

function handleNotification(msg) {
  const p = msg.params || {};
  switch (msg.method) {
    case 'initialized':
      return;
    case 'exit':
      process.exit(shuttingDown ? 0 : 1);
      return;
    case 'textDocument/didOpen': {
      const td = p.textDocument;
      if (!td || typeof td.uri !== 'string') return;
      const doc = { uri: td.uri, languageId: td.languageId || 'slug', version: Number(td.version || 0), text: String(td.text || '') };
      documents.set(doc.uri, doc);
      scheduleValidation(doc, 0);
      return;
    }
    case 'textDocument/didChange': {
      const td = p.textDocument;
      const old = td && documents.get(td.uri);
      if (!old || !Array.isArray(p.contentChanges) || p.contentChanges.length === 0) return;
      const change = p.contentChanges[p.contentChanges.length - 1];
      if (typeof change.text !== 'string') return;
      const doc = { ...old, version: Number(td.version || old.version + 1), text: change.text };
      documents.set(doc.uri, doc);
      scheduleValidation(doc, 150);
      return;
    }
    case 'textDocument/didSave': {
      const td = p.textDocument;
      const doc = td && documents.get(td.uri);
      if (doc) scheduleValidation(doc, 0);
      return;
    }
    case 'textDocument/didClose': {
      const td = p.textDocument;
      if (!td) return;
      const timer = validationTimers.get(td.uri); if (timer) clearTimeout(timer); validationTimers.delete(td.uri);
      documents.delete(td.uri);
      notify('textDocument/publishDiagnostics', { uri: td.uri, diagnostics: [] });
      return;
    }
    case '$/cancelRequest':
      return;
    default:
      return;
  }
}

async function handleMessage(msg) {
  if (!msg || msg.jsonrpc !== '2.0' || typeof msg.method !== 'string') return;
  if (Object.prototype.hasOwnProperty.call(msg, 'id')) await handleRequest(msg);
  else handleNotification(msg);
}

function pump() {
  while (true) {
    const marker = input.indexOf('\r\n\r\n');
    if (marker < 0) return;
    const header = input.subarray(0, marker).toString('ascii');
    const m = /(?:^|\r\n)Content-Length:\s*(\d+)/i.exec(header);
    if (!m) {
      process.stderr.write('slug-lsp: malformed LSP header\n');
      process.exit(70);
    }
    const length = Number(m[1]);
    const bodyStart = marker + 4;
    if (input.length < bodyStart + length) return;
    const body = input.subarray(bodyStart, bodyStart + length).toString('utf8');
    input = input.subarray(bodyStart + length);
    let msg;
    try { msg = JSON.parse(body); }
    catch (e) {
      process.stderr.write(`slug-lsp: malformed JSON: ${e.message}\n`);
      continue;
    }
    handleMessage(msg).catch((e) => process.stderr.write(`slug-lsp: ${e.message}\n`));
  }
}

process.stdin.on('data', (chunk) => {
  input = Buffer.concat([input, chunk]);
  pump();
});
process.stdin.on('end', () => process.exit(shuttingDown ? 0 : 1));
process.stdin.resume();

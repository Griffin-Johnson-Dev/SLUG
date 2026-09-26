'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');
const { LspClient } = require('../src/lsp-client');

function fail(msg) { throw new Error(msg); }
function waitForNotification(client, method, pred, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error(`timeout waiting for ${method}`)); }, timeoutMs);
    const handler = (m, p) => {
      if (m !== method || (pred && !pred(p))) return;
      cleanup(); resolve(p);
    };
    function cleanup() { clearTimeout(timer); client.off('notification', handler); }
    client.on('notification', handler);
  });
}

async function main() {
  const serverJs = process.env.SLUG_LSP_JS;
  const slugBin = process.env.SLUG_BIN;
  if (!serverJs || !slugBin) fail('SLUG_LSP_JS and SLUG_BIN are required');
  const spec = {
    command: process.execPath,
    args: [serverJs, '--slug', slugBin],
    options: { env: process.env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] },
  };
  const c = new LspClient(spec, { requestTimeoutMs: 20000 });
  let stderr = '';
  c.on('stderr', (s) => { stderr += s; });
  c.start();
  const init = await c.request('initialize', { processId: process.pid, rootUri: null, capabilities: {} });
  if (!init || !init.capabilities || !init.capabilities.documentFormattingProvider) fail('formatting capability missing');
  if (!init.capabilities.experimental || init.capabilities.experimental.unsavedBufferMode !== 'stdin-overlay') fail('stdin-overlay not advertised');
  c.notify('initialized', {});

  const tooling = await c.request('slug/toolingInfo', {});
  if (!tooling || tooling.schema !== 1) fail('tooling info schema mismatch');

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'slug-vscode-k9h-'));
  const file = path.join(tmp, 'main.slg');
  fs.writeFileSync(file, "co['disk']\n", 'utf8');
  const uri = pathToFileURL(file).toString();
  c.notify('textDocument/didOpen', { textDocument: { uri, languageId: 'slug', version: 1, text: "co['live']\n" } });
  const valid = await waitForNotification(c, 'textDocument/publishDiagnostics', (p) => p && p.uri === uri && p.version === 1);
  if ((valid.diagnostics || []).length !== 0) fail('valid unsaved source produced diagnostics');
  if (fs.readFileSync(file, 'utf8') !== "co['disk']\n") fail('disk source mutated by diagnostics');

  c.notify('textDocument/didChange', { textDocument: { uri, version: 2 }, contentChanges: [{ text: "co['broken'\n" }] });
  const invalid = await waitForNotification(c, 'textDocument/publishDiagnostics', (p) => p && p.uri === uri && p.version === 2);
  if ((invalid.diagnostics || []).length < 1) fail('invalid unsaved source produced no diagnostic');

  c.notify('textDocument/didChange', { textDocument: { uri, version: 3 }, contentChanges: [{ text: "co[ 'fmt' ]\n" }] });
  await waitForNotification(c, 'textDocument/publishDiagnostics', (p) => p && p.uri === uri && p.version === 3);
  const edits = await c.request('textDocument/formatting', { textDocument: { uri }, options: { tabSize: 2, insertSpaces: true } });
  if (!Array.isArray(edits)) fail('formatting result is not an array');
  if (fs.readFileSync(file, 'utf8') !== "co['disk']\n") fail('disk source mutated by formatting');

  const project = await c.request('slug/projectInfo', { uri });
  if (!project || project.schema !== 1) fail('project info schema mismatch');

  c.notify('textDocument/didClose', { textDocument: { uri } });
  await c.stop();
  fs.rmSync(tmp, { recursive: true, force: true });
  if (stderr.trim()) process.stderr.write(stderr);
  process.stdout.write('SLUG CLIENT SMOKE PASS\n');
}

main().catch((e) => { process.stderr.write(`${e.stack || e.message}\n`); process.exit(1); });

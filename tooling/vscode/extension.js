'use strict';

const vscode = require('vscode');
const { discoverServer } = require('./src/discovery');
const { LspClient } = require('./src/lsp-client');
const EXTENSION_VERSION = require('./package.json').version;

let client = null;
let diagnostics = null;
let output = null;
let status = null;
let disposables = [];

function cfg() { return vscode.workspace.getConfiguration('slug'); }
function isSlug(doc) { return doc && doc.languageId === 'slug' && doc.uri.scheme === 'file'; }
function position(p) { return new vscode.Position(p.line || 0, p.character || 0); }
function range(r) { return new vscode.Range(position(r.start || {}), position(r.end || {})); }

function toVscodeDiagnostic(d) {
  const severityMap = {
    1: vscode.DiagnosticSeverity.Error,
    2: vscode.DiagnosticSeverity.Warning,
    3: vscode.DiagnosticSeverity.Information,
    4: vscode.DiagnosticSeverity.Hint,
  };
  const x = new vscode.Diagnostic(range(d.range || { start: {}, end: {} }), String(d.message || 'SLUG diagnostic'), severityMap[d.severity] || vscode.DiagnosticSeverity.Error);
  x.source = d.source || 'slug';
  if (d.code !== undefined) x.code = d.code;
  return x;
}

function trace(direction, payload) {
  if (!cfg().get('trace.server', false)) return;
  output.appendLine(`[${direction}] ${JSON.stringify(payload)}`);
}

function documentItem(doc) {
  return { uri: doc.uri.toString(), languageId: 'slug', version: doc.version, text: doc.getText() };
}

function sendOpen(doc) {
  if (client && isSlug(doc)) client.notify('textDocument/didOpen', { textDocument: documentItem(doc) });
}

function sendChange(event) {
  if (!client || !isSlug(event.document)) return;
  client.notify('textDocument/didChange', {
    textDocument: { uri: event.document.uri.toString(), version: event.document.version },
    contentChanges: [{ text: event.document.getText() }],
  });
}

function sendSave(doc) {
  if (client && isSlug(doc)) client.notify('textDocument/didSave', { textDocument: { uri: doc.uri.toString() } });
}

function sendClose(doc) {
  if (!isSlug(doc)) return;
  if (client) client.notify('textDocument/didClose', { textDocument: { uri: doc.uri.toString() } });
  diagnostics.delete(doc.uri);
}

async function startServer() {
  await stopServer();
  const config = cfg();
  const spec = discoverServer({
    lspPath: config.get('lspPath', '').trim(),
    compilerPath: config.get('compilerPath', '').trim(),
    electronExecutable: process.execPath,
  });
  output.appendLine(`Starting SLUG LSP (${spec.mode}): ${spec.serverPath}`);
  client = new LspClient(spec, { trace });
  client.on('stderr', (s) => output.append(s));
  client.on('protocolError', (e) => output.appendLine(`Protocol error: ${e.message}`));
  client.on('exit', (code, signal) => {
    status.text = '$(error) SLUG';
    status.tooltip = `SLUG language server exited (${code === null ? signal : code})`;
  });
  client.on('notification', (method, params) => {
    if (method !== 'textDocument/publishDiagnostics' || !params || !params.uri) return;
    const uri = vscode.Uri.parse(params.uri);
    diagnostics.set(uri, (params.diagnostics || []).map(toVscodeDiagnostic));
  });
  client.start();
  const folders = vscode.workspace.workspaceFolders || [];
  const rootUri = folders.length ? folders[0].uri.toString() : null;
  const init = await client.request('initialize', {
    processId: process.pid,
    clientInfo: { name: 'slug-vscode', version: EXTENSION_VERSION },
    rootUri,
    capabilities: { workspace: {}, textDocument: { publishDiagnostics: {}, formatting: {} } },
  });
  client.notify('initialized', {});
  status.text = '$(check) SLUG';
  status.tooltip = `SLUG LSP ${init && init.serverInfo ? init.serverInfo.version : ''}`.trim();
  for (const doc of vscode.workspace.textDocuments) sendOpen(doc);
}

async function stopServer() {
  const old = client;
  client = null;
  if (old) await old.stop();
  if (status) { status.text = '$(circle-slash) SLUG'; status.tooltip = 'SLUG language server stopped'; }
}

async function withClient(fn) {
  if (!client) await startServer();
  return fn(client);
}

function pretty(value) { return JSON.stringify(value, null, 2); }

async function activate(context) {
  output = vscode.window.createOutputChannel('SLUG');
  diagnostics = vscode.languages.createDiagnosticCollection('slug');
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.command = 'slug.restartLanguageServer';
  status.text = '$(sync~spin) SLUG';
  status.show();
  context.subscriptions.push(output, diagnostics, status);

  disposables = [
    vscode.workspace.onDidOpenTextDocument(sendOpen),
    vscode.workspace.onDidChangeTextDocument(sendChange),
    vscode.workspace.onDidSaveTextDocument(sendSave),
    vscode.workspace.onDidCloseTextDocument(sendClose),
    vscode.workspace.onDidChangeConfiguration(async (e) => {
      if (e.affectsConfiguration('slug.lspPath') || e.affectsConfiguration('slug.compilerPath')) {
        try { await startServer(); } catch (err) { vscode.window.showErrorMessage(`SLUG LSP: ${err.message}`); }
      }
    }),
    vscode.languages.registerDocumentFormattingEditProvider({ language: 'slug', scheme: 'file' }, {
      provideDocumentFormattingEdits: async (doc, options) => withClient(async (c) => {
        const edits = await c.request('textDocument/formatting', {
          textDocument: { uri: doc.uri.toString() },
          options: { tabSize: options.tabSize, insertSpaces: options.insertSpaces },
        });
        return (edits || []).map((e) => vscode.TextEdit.replace(range(e.range), e.newText));
      }),
    }),
    vscode.commands.registerCommand('slug.restartLanguageServer', async () => {
      try { await startServer(); vscode.window.showInformationMessage('SLUG language server restarted.'); }
      catch (err) { vscode.window.showErrorMessage(`SLUG LSP: ${err.message}`); }
    }),
    vscode.commands.registerCommand('slug.showToolingInfo', async () => {
      try {
        const info = await withClient((c) => c.request('slug/toolingInfo', {}));
        output.appendLine(`tooling-info\n${pretty(info)}`); output.show(true);
      } catch (err) { vscode.window.showErrorMessage(`SLUG tooling info: ${err.message}`); }
    }),
    vscode.commands.registerCommand('slug.showProjectInfo', async () => {
      try {
        const editor = vscode.window.activeTextEditor;
        const uri = editor && isSlug(editor.document) ? editor.document.uri.toString() : undefined;
        const info = await withClient((c) => c.request('slug/projectInfo', uri ? { uri } : {}));
        output.appendLine(`project-info\n${pretty(info)}`); output.show(true);
      } catch (err) { vscode.window.showErrorMessage(`SLUG project info: ${err.message}`); }
    }),
  ];
  context.subscriptions.push(...disposables);

  try { await startServer(); }
  catch (err) {
    status.text = '$(warning) SLUG';
    status.tooltip = err.message;
    output.appendLine(`SLUG LSP not started: ${err.message}`);
  }
}

async function deactivate() { await stopServer(); }

module.exports = { activate, deactivate };

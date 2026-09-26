'use strict';

const Module = require('module');
const path = require('path');

const slugBin = process.env.SLUG_BIN;
const serverJs = process.env.SLUG_LSP_JS;
if (!slugBin || !serverJs) throw new Error('SLUG_BIN and SLUG_LSP_JS are required');

const commandHandlers = new Map();
const disposables = [];
let formatterProvider = null;
let outputText = '';
let infoMessages = [];
let errorMessages = [];

function disposable() { return { dispose() {} }; }
class Position { constructor(line=0, character=0){ this.line=line; this.character=character; } }
class Range { constructor(start,end){ this.start=start; this.end=end; } }
class Diagnostic { constructor(range,message,severity){ this.range=range; this.message=message; this.severity=severity; } }
class Uri {
  constructor(value){ this.value=value; this.scheme=value.startsWith('file:')?'file':''; }
  toString(){ return this.value; }
  static parse(v){ return new Uri(v); }
}
const vscode = {
  Position, Range, Diagnostic, Uri,
  DiagnosticSeverity: { Error:0, Warning:1, Information:2, Hint:3 },
  StatusBarAlignment: { Left:1 },
  TextEdit: { replace: (range,newText)=>({range,newText}) },
  workspace: {
    workspaceFolders: [], textDocuments: [],
    getConfiguration(section){
      if(section!=='slug') throw new Error('unexpected config section');
      return { get(key,def){
        if(key==='lspPath') return serverJs;
        if(key==='compilerPath') return slugBin;
        if(key==='trace.server') return false;
        return def;
      }};
    },
    onDidOpenTextDocument(){ return disposable(); },
    onDidChangeTextDocument(){ return disposable(); },
    onDidSaveTextDocument(){ return disposable(); },
    onDidCloseTextDocument(){ return disposable(); },
    onDidChangeConfiguration(){ return disposable(); },
  },
  languages: {
    createDiagnosticCollection(){ return { set(){}, delete(){}, dispose(){} }; },
    registerDocumentFormattingEditProvider(_selector,provider){ formatterProvider=provider; return disposable(); },
  },
  commands: {
    registerCommand(name,handler){ commandHandlers.set(name,handler); return disposable(); },
  },
  window: {
    activeTextEditor: null,
    createOutputChannel(){ return { append(s){outputText+=s;}, appendLine(s){outputText+=s+'\n';}, show(){}, dispose(){} }; },
    createStatusBarItem(){ return { text:'', tooltip:'', command:null, show(){}, dispose(){} }; },
    showInformationMessage(msg){ infoMessages.push(msg); return Promise.resolve(msg); },
    showErrorMessage(msg){ errorMessages.push(msg); return Promise.resolve(msg); },
  },
};

const originalLoad = Module._load;
Module._load = function(request,parent,isMain){ if(request==='vscode') return vscode; return originalLoad.call(this,request,parent,isMain); };

async function main(){
  const extensionPath=path.resolve(__dirname,'..','extension.js');
  const ext=require(extensionPath);
  const context={ subscriptions:{ push(...xs){ disposables.push(...xs); } } };
  await ext.activate(context);
  if(!formatterProvider) throw new Error('formatting provider not registered');
  for(const name of ['slug.restartLanguageServer','slug.showToolingInfo','slug.showProjectInfo']) {
    if(!commandHandlers.has(name)) throw new Error(`command not registered: ${name}`);
  }
  await commandHandlers.get('slug.showToolingInfo')();
  if(!outputText.includes('tooling-info') || !outputText.includes('stdin_overlay')) throw new Error('tooling info command did not query real server');
  if(errorMessages.length) throw new Error(`extension reported errors: ${errorMessages.join(' | ')}`);
  await ext.deactivate();
  for(const d of disposables.reverse()) { try { d.dispose(); } catch(_){} }
  process.stdout.write('SLUG EXTENSION ACTIVATE PASS\n');
}

main().catch((e)=>{ process.stderr.write(`${e.stack||e.message}\n`); process.exit(1); });

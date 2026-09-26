#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, tempfile, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'tooling'/'vscode'

class Gate:
    def __init__(self): self.n=0
    def ok(self, cond, label, detail=''):
        if not cond: raise AssertionError(f'{label}: {detail}')
        self.n+=1

def run(cmd, **kw):
    return subprocess.run(cmd, text=True, encoding='utf-8', errors='strict', stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

def sha(p:Path): return hashlib.sha256(p.read_bytes()).hexdigest()

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--prefix', type=Path, help='installed SLUG prefix for real client/LSP smoke')
    ns=ap.parse_args(); g=Gate()

    pkg=json.loads((EXT/'package.json').read_text())
    g.ok(pkg['name']=='slug-language' and pkg['publisher']=='slug-lang','extension identity')
    g.ok(pkg['version']=='0.9.0' and pkg.get('preview') is True,'extension preview version')
    g.ok(pkg['engines']['vscode'].startswith('^1.'),'VS Code engine constraint')
    langs=pkg['contributes']['languages']; g.ok(any(x['id']=='slug' and '.slg' in x['extensions'] and '.slgc' in x['extensions'] for x in langs),'SLUG language registration')
    g.ok(pkg['contributes']['grammars'][0]['scopeName']=='source.slug','TextMate grammar registration')
    cmds={x['command'] for x in pkg['contributes']['commands']}; g.ok({'slug.restartLanguageServer','slug.showToolingInfo','slug.showProjectInfo'}<=cmds,'editor commands')
    g.ok('dependencies' not in pkg and 'devDependencies' not in pkg,'dependency-free extension runtime')

    lang=json.loads((EXT/'language-configuration.json').read_text())
    g.ok(lang['comments']['lineComment']=='##' and lang['comments']['blockComment']==['#*','*#'],'language comment syntax')
    grammar=json.loads((EXT/'syntaxes/slug.tmLanguage.json').read_text())
    g.ok(grammar['scopeName']=='source.slug' and 'repository' in grammar,'grammar JSON')
    grammar_text=json.dumps(grammar)
    g.ok(all(x in grammar_text for x in ('co','ci','ty','cv','in','iv','ln','sl','by')),'root builtins highlighted')
    comment_patterns=[x.get('match','') or x.get('begin','') for x in grammar['repository']['comments']['patterns']]
    g.ok(any('##!?' in x for x in comment_patterns) and any('#\\*!?' in x for x in comment_patterns),'ordinary/preserved comments highlighted')

    js_check_files=(
        EXT/'extension.js',
        EXT/'src'/'discovery.js',
        EXT/'src'/'lsp-client.js',
        EXT/'test'/'client-smoke.js',
        EXT/'test'/'discovery-smoke.js',
        EXT/'test'/'extension-activate-smoke.js',
    )
    for js in js_check_files:
        p=run(['node','--check',str(js)],cwd=ROOT,timeout=30)
        g.ok(p.returncode==0,f'extension JavaScript syntax {js.relative_to(EXT)}',p.stderr)
    p=run(['node',str(EXT/'test'/'discovery-smoke.js')],cwd=ROOT,timeout=20); g.ok(p.returncode==0 and 'PASS' in p.stdout,'cross-platform discovery smoke',p.stderr)

    canonical_vsix_sha=None
    with tempfile.TemporaryDirectory(prefix='slug-vsix-') as td:
        a=Path(td)/'a.vsix'; b=Path(td)/'b.vsix'
        for out in (a,b):
            p=run([os.fspath(Path(os.sys.executable)),str(ROOT/'tools'/'build_vscode_vsix.py'),'--root',str(ROOT),'--out',str(out)],cwd=ROOT,timeout=30)
            g.ok(p.returncode==0,'deterministic VSIX build',p.stderr)
        g.ok(sha(a)==sha(b),'deterministic VSIX bytes')
        canonical_vsix_sha=sha(a)
        with zipfile.ZipFile(a) as z:
            names=set(z.namelist())
            required={'[Content_Types].xml','extension.vsixmanifest','extension/package.json','extension/extension.js','extension/src/discovery.js','extension/src/lsp-client.js','extension/syntaxes/slug.tmLanguage.json','extension/LICENSE.txt'}
            g.ok(required<=names,'VSIX required payload')
            g.ok(not any('/test/' in x or x.startswith('extension/test/') for x in names),'VSIX excludes tests')
            epkg=json.loads(z.read('extension/package.json')); g.ok(epkg['name']=='slug-language','VSIX embedded package manifest')
            xm=ET.fromstring(z.read('extension.vsixmanifest'))
            nsxml={'v':'http://schemas.microsoft.com/developer/vsx-schema/2011'}
            asset=xm.find(".//v:Asset[@Type='Microsoft.VisualStudio.Code.Manifest']",nsxml)
            g.ok(asset is not None and asset.attrib.get('Path')=='extension/package.json','VSIX code manifest asset')
            prop=xm.find(".//v:Property[@Id='Microsoft.VisualStudio.Code.PreRelease']",nsxml)
            g.ok(prop is not None and prop.attrib.get('Value')=='true','VSIX prerelease marker')

    layout=json.loads((ROOT/'INSTALL_LAYOUT.json').read_text())
    g.ok(layout.get('vscode_extension')=='share/slug/1.0/tooling/vscode/slug-language.vsix','install-layout VSIX contract')

    if ns.prefix:
        prefix=ns.prefix.resolve(); slug=prefix/'bin'/('slug.exe' if os.name=='nt' else 'slug'); server=prefix/'share/slug/1.0/tooling/slug-lsp.js'; vsix=prefix/'share/slug/1.0/tooling/vscode/slug-language.vsix'
        g.ok(slug.is_file() and server.is_file(),'installed compiler/LSP pair')
        g.ok(vsix.is_file(),'installed VSIX present')
        g.ok(sha(vsix)==canonical_vsix_sha,'installed VSIX matches deterministic package')
        env={**os.environ,'SLUG_BIN':str(slug),'SLUG_LSP_JS':str(server)}
        p=run(['node',str(EXT/'test'/'client-smoke.js')],cwd=ROOT,env=env,timeout=60)
        g.ok(p.returncode==0 and 'SLUG CLIENT SMOKE PASS' in p.stdout,'real installed-prefix LSP client smoke',p.stderr)
        p=run(['node',str(EXT/'test'/'extension-activate-smoke.js')],cwd=ROOT,env=env,timeout=60)
        g.ok(p.returncode==0 and 'SLUG EXTENSION ACTIVATE PASS' in p.stdout,'real extension activation smoke',p.stderr)
    else:
        print('NOTE: installed-prefix client smoke skipped (no --prefix)')

    print(f'SLUG VSCODE EXTENSION PASS {g.n}/{g.n}')
    return 0

if __name__=='__main__': raise SystemExit(main())

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
    g.ok(pkg['name']=='slug-devkit' and pkg['publisher']=='griffinjohnson','extension identity')
    g.ok(pkg['version']=='1.0.3' and pkg.get('preview') is False,'extension public version')
    g.ok(pkg['engines']['vscode'].startswith('^1.'),'VS Code engine constraint')
    g.ok(pkg.get('icon')=='icon.png' and (EXT/'icon.png').is_file(),'Marketplace icon payload')
    langs=pkg['contributes']['languages']; g.ok(any(x['id']=='slug' and '.slg' in x['extensions'] and '.slgc' in x['extensions'] for x in langs),'SLUG language registration')
    g.ok(pkg['contributes']['grammars'][0]['scopeName']=='source.slug','TextMate grammar registration')
    cmds={x['command'] for x in pkg['contributes']['commands']}; g.ok({'slug.restartLanguageServer','slug.showToolingInfo','slug.showProjectInfo'}<=cmds,'editor commands')
    g.ok('dependencies' not in pkg and 'devDependencies' not in pkg,'dependency-free extension runtime')

    lang=json.loads((EXT/'language-configuration.json').read_text())
    g.ok(lang['comments']['lineComment']=='##' and lang['comments']['blockComment']==['#*','*#'],'language comment syntax')
    grammar=json.loads((EXT/'syntaxes/slug.tmLanguage.json').read_text())
    g.ok(grammar['scopeName']=='source.slug' and 'repository' in grammar,'grammar JSON')
    import re
    grammar_text=json.dumps(grammar)
    builtin_rx=grammar['repository']['builtins']['patterns'][0]['match']
    g.ok(all(re.search(builtin_rx,x) for x in ('co','ci','ty','cv','in','iv','ln','sl','by')),'root builtins highlighted')
    g.ok(all(re.search(builtin_rx,' '.join(x)) for x in ('co','ci','ty','cv','in','iv','ln','sl','by')),'spaced root builtins highlighted')
    comment_patterns=[x.get('match','') or x.get('begin','') for x in grammar['repository']['comments']['patterns']]
    g.ok(any('##!?' in x for x in comment_patterns) and any('#\\*!?' in x for x in comment_patterns),'ordinary/preserved comments highlighted')
    operator_rx=grammar['repository']['operators']['patterns'][0]['match']
    g.ok('[ \\t]*' in builtin_rx and 'c[ \\t]*i' in builtin_rx,'whitespace-aware builtin highlighting')
    g.ok(':[ \\t]*=' in operator_rx and '\\+\\+' in operator_rx,'compatibility-aware operator highlighting')
    g.ok(all(re.fullmatch(operator_rx,x) for x in (': =',': : =','= =','! =','< =','> =','< :')),'spaced structural operators highlighted')
    g.ok(all(re.fullmatch(operator_rx,x) for x in ('++','--','^^','~-','~~','//')),'contiguous compound operators highlighted')
    g.ok(all(re.fullmatch(operator_rx,x) is None for x in ('+ +','- -','^ ^','~ -','~ ~','/ /')),'separated executable punctuation not falsely fused')
    keyword_rx=grammar['repository']['keywords']['patterns'][0]['match']
    class_rx=grammar['repository']['classes']['patterns'][1]['match']
    g.ok(all(re.search(keyword_rx,x) for x in ('i f','e i','e e','r v')),'spaced reserved words highlighted')
    g.ok(re.search(class_rx,'A B') is not None,'spaced class highlighted')

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
            required={'[Content_Types].xml','extension.vsixmanifest','extension/package.json','extension/extension.js','extension/src/discovery.js','extension/src/lsp-client.js','extension/syntaxes/slug.tmLanguage.json','extension/icon.png','extension/LICENSE.txt'}
            g.ok(required<=names,'VSIX required payload')
            g.ok(not any('/test/' in x or x.startswith('extension/test/') for x in names),'VSIX excludes tests')
            epkg=json.loads(z.read('extension/package.json')); g.ok(epkg['name']=='slug-devkit' and epkg.get('icon')=='icon.png','VSIX embedded package manifest')
            xm=ET.fromstring(z.read('extension.vsixmanifest'))
            nsxml={'v':'http://schemas.microsoft.com/developer/vsx-schema/2011'}
            asset=xm.find(".//v:Asset[@Type='Microsoft.VisualStudio.Code.Manifest']",nsxml)
            g.ok(asset is not None and asset.attrib.get('Path')=='extension/package.json','VSIX code manifest asset')
            prop=xm.find(".//v:Property[@Id='Microsoft.VisualStudio.Code.PreRelease']",nsxml)
            g.ok(prop is not None and prop.attrib.get('Value')=='false','VSIX public release marker')
            icon_asset=xm.find(".//v:Asset[@Type='Microsoft.VisualStudio.Services.Icons.Default']",nsxml)
            g.ok(icon_asset is not None and icon_asset.attrib.get('Path')=='extension/icon.png','VSIX Marketplace icon asset')
            flags=xm.find('.//v:GalleryFlags',nsxml)
            g.ok(flags is not None and flags.text=='Public','VSIX public gallery flag')
            ct=ET.fromstring(z.read('[Content_Types].xml'))
            nsct={'c':'http://schemas.openxmlformats.org/package/2006/content-types'}
            declared={x.attrib.get('Extension') for x in ct.findall('c:Default',nsct)}
            payload_exts={Path(x).suffix.lower().lstrip('.') for x in names if x not in {'[Content_Types].xml'} and Path(x).suffix}
            g.ok('png' in declared,'VSIX PNG content type')
            g.ok(payload_exts<=declared,'VSIX content types cover every payload extension',f'missing={sorted(payload_exts-declared)}')

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

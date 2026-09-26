#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shutil, subprocess
from pathlib import Path

def need(c, label, detail=''):
    if not c: raise AssertionError(f'{label}: {detail}')

def run(exe, args, cwd):
    env=os.environ.copy(); env.pop('SLUG_RUNTIME',None)
    return subprocess.run([str(exe),*args], cwd=cwd, env=env, text=True, encoding='utf-8', errors='strict', stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--prefix',required=True); ns=ap.parse_args()
    prefix=Path(ns.prefix).resolve(); root=Path.cwd().resolve(); exe=prefix/'bin'/('slug.exe' if os.name=='nt' else 'slug')
    lsp=prefix/'share/slug/1.0/tooling/slug-lsp.js'; launcher=prefix/'bin'/('slug-lsp.cmd' if os.name=='nt' else 'slug-lsp'); vsix=prefix/'share/slug/1.0/tooling/vscode/slug-language.vsix'; must=[exe,prefix/'lib/slug/1.0/runtime_stage2.c',prefix/'share/slug/1.0/PUBLIC_CONTRACT.json',prefix/'share/slug/1.0/INSTALL_LAYOUT.json',prefix/'share/slug/1.0/std/registry.json',prefix/'share/slug/1.0/LICENSE',prefix/'share/slug/1.0/SECURITY.md',prefix/'share/slug/1.0/README.md',prefix/'share/slug/1.0/examples/hello.slg',lsp,launcher,vsix]
    for p in must: need(p.is_file(),'installed file',str(p))
    layout=json.loads((prefix/'share/slug/1.0/INSTALL_LAYOUT.json').read_text()); need(layout['language_version']=='1.0','layout language version')
    registry=json.loads((prefix/'share/slug/1.0/std/registry.json').read_text()); need('@std/sys' in registry['modules'] and '@std/fs' in registry['modules'],'std registry')
    td=root/'build'/'k9d_install_project'; shutil.rmtree(td,ignore_errors=True); (td/'src/lib').mkdir(parents=True); (td/'src/@std').mkdir(parents=True); (td/'build').mkdir()
    # Deliberately invalid fake std file: reserved @std/sys must never read it.
    (td/'src/@std/sys').write_text("if ? {\n",encoding='utf-8')
    (td/'src/lib/base.slg').write_text("~ad x { rv x 1 +; }\n",encoding='utf-8')
    (td/'src/lib/calc.slg').write_text(">'base.slg'\n~tw x { rv ad[x] 2 *; }\n",encoding='utf-8')
    # Alias the user-source module from an installed-project layout while its own
    # dependency remains a nested direct import. This exercises provider-aware
    # alias resolution outside the compiler source tree.
    (td/'src/main.slg').write_text(">'lib/calc.slg':CA\n>'@std/sys':SY\nco[CA.tw[20]]\nco[SY.cp['@std/fs.fr']]\n",encoding='utf-8')
    p=run(exe,['--language-version'],td); need(p.returncode==0 and p.stdout.strip()=='1.0','installed language query',repr((p.returncode,p.stdout,p.stderr)))
    p=run(exe,['check','src/main.slg'],td); need(p.returncode==0 and not p.stdout and not p.stderr,'installed project check',repr((p.returncode,p.stdout,p.stderr)))
    out=td/'build'/('demo.exe' if os.name=='nt' else 'demo')
    p=run(exe,['build','src/main.slg','-o',str(out)],td); need(p.returncode==0 and out.is_file() and not p.stderr,'installed project build',repr((p.returncode,p.stdout,p.stderr)))
    p=subprocess.run([str(out)],cwd=td,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE); need(p.returncode==0 and p.stdout.splitlines()==['42','true'],'built multi-module app',repr((p.returncode,p.stdout,p.stderr)))
    p=run(exe,['run','src/main.slg'],td); need(p.returncode==0 and p.stdout.splitlines()==['42','true'],'installed project run',repr((p.returncode,p.stdout,p.stderr)))
    print('INSTALL LAYOUT PASS 13/13')
    return 0
if __name__=='__main__': raise SystemExit(main())

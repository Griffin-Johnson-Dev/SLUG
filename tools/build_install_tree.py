#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, shutil, subprocess, sys, tempfile
from pathlib import Path

LANG='1.0'

def _msvc_style_driver(cc:str)->bool:
    return Path(cc).name.lower() in {'cl','cl.exe','clang-cl','clang-cl.exe'}

def compile_command(cc:str, seed:Path, exe:Path, windows:bool)->list[str]:
    if windows and _msvc_style_driver(cc):
        return [cc,'/nologo','/std:c11','/O2',str(seed),f'/Fe:{exe}',
                'ws2_32.lib','shell32.lib','user32.lib','gdi32.lib','winmm.lib']
    cmd=[cc,str(seed),'-std=c11','-O2','-o',str(exe)]
    if windows: cmd += ['-lws2_32','-lshell32','-luser32','-lgdi32','-lwinmm']
    else: cmd += ['-lm']
    return cmd

def populate(root:Path, stage:Path, cc:str, seed:Path)->tuple[Path,Path]:
    bindir=stage/'bin'; libdir=stage/'lib'/'slug'/LANG; shared=stage/'share'/'slug'/LANG
    (shared/'std').mkdir(parents=True, exist_ok=True)
    (shared/'docs').mkdir(parents=True, exist_ok=True)
    (shared/'examples').mkdir(parents=True, exist_ok=True)
    (shared/'tooling'/'vscode').mkdir(parents=True, exist_ok=True)
    libdir.mkdir(parents=True, exist_ok=True); bindir.mkdir(parents=True, exist_ok=True)
    exe=bindir/('slug.exe' if os.name=='nt' else 'slug')
    cmd=compile_command(cc,seed,exe,os.name=='nt')
    subprocess.run(cmd,check=True)
    expected_version=(root/'VERSION').read_text(encoding='utf-8').strip()
    expected_language=(root/'LANGUAGE_VERSION').read_text(encoding='utf-8').strip()
    got_version=subprocess.check_output([str(exe),'--version'],text=True).strip()
    got_language=subprocess.check_output([str(exe),'--language-version'],text=True).strip()
    if got_version!=expected_version or got_language!=expected_language:
        raise SystemExit(f'seed identity mismatch: compiler={got_version!r}/{got_language!r} expected={expected_version!r}/{expected_language!r}')
    shutil.copy2(root/'compiler'/'stage2'/'runtime_stage2.c',libdir/'runtime_stage2.c')
    for name in ('LANGUAGE_VERSION','CLI_CONTRACT_VERSION','VERSION','PUBLIC_CONTRACT.json','INSTALL_LAYOUT.json'):
        shutil.copy2(root/name,shared/name)
    shutil.copy2(root/'distribution'/'std'/'registry.json',shared/'std'/'registry.json')
    for name in ('LICENSE','SECURITY.md','README.md','CHANGELOG.md'):
        shutil.copy2(root/name,shared/name)
    shutil.copy2(root/'tooling'/'lsp'/'slug-lsp.js',shared/'tooling'/'slug-lsp.js')
    subprocess.run([sys.executable,str(root/'tools'/'build_vscode_vsix.py'),'--root',str(root),'--out',str(shared/'tooling'/'vscode'/'slug-language.vsix')],check=True,stdout=subprocess.DEVNULL)
    if os.name=='nt':
        launcher=bindir/'slug-lsp.cmd'
        launcher.write_text('@echo off\r\nnode "%~dp0..\\share\\slug\\1.0\\tooling\\slug-lsp.js" --slug "%~dp0slug.exe" %*\r\n',encoding='utf-8')
    else:
        launcher=bindir/'slug-lsp'
        launcher.write_text('#!/bin/sh\nD=$(CDPATH= cd "$(dirname "$0")" && pwd)\nexec node "$D/../share/slug/1.0/tooling/slug-lsp.js" --slug "$D/slug" "$@"\n',encoding='utf-8')
        launcher.chmod(0o755)
    for name in ('SLUG_V1_SPECIFICATION.md','SLUG_V1_COMPILER_ARCHITECTURE.md','SLUG_V1_STANDARD_MODULES.md','SLUG_PUBLIC_CLI_V1.md','SLUG_V1_INSTALL_AND_PROJECT_LAYOUT.md','SLUG_V1_LSP.md','SLUG_V1_VSCODE.md','SLUG_V1_SUPPORTED_PLATFORMS.md','SLUG_V1_RELEASE_PROCESS.md'):
        shutil.copy2(root/'docs'/name,shared/'docs'/name)
    for p in sorted((root/'examples').iterdir()):
        if p.is_file() and (p.suffix in {'.slg','.slgc'} or p.name=='README.md'):
            shutil.copy2(p,shared/'examples'/p.name)
    return exe,launcher

def commit(stage:Path,prefix:Path)->Path:
    sb=stage/'bin'; sl=stage/'lib'/'slug'/LANG; ss=stage/'share'/'slug'/LANG
    bindir=prefix/'bin'; libdir=prefix/'lib'/'slug'/LANG; shared=prefix/'share'/'slug'/LANG
    bindir.mkdir(parents=True,exist_ok=True);libdir.parent.mkdir(parents=True,exist_ok=True);shared.parent.mkdir(parents=True,exist_ok=True)
    # Never delete PREFIX itself. Replace only paths owned by this SLUG language-version install.
    shutil.rmtree(libdir,ignore_errors=True);shutil.rmtree(shared,ignore_errors=True)
    shutil.copytree(sl,libdir);shutil.copytree(ss,shared)
    for owned in (bindir/'slug',bindir/'slug.exe',bindir/'slug-lsp',bindir/'slug-lsp.cmd'):
        try:owned.unlink()
        except FileNotFoundError:pass
    exe_name='slug.exe' if os.name=='nt' else 'slug'; launcher_name='slug-lsp.cmd' if os.name=='nt' else 'slug-lsp'
    shutil.copy2(sb/exe_name,bindir/exe_name);shutil.copy2(sb/launcher_name,bindir/launcher_name)
    if os.name!='nt':(bindir/'slug-lsp').chmod(0o755);(bindir/'slug').chmod(0o755)
    return bindir/exe_name

def main()->int:
    ap=argparse.ArgumentParser(description='Build canonical SLUG 1.0 install tree')
    ap.add_argument('--prefix',required=True)
    ap.add_argument('--cc',default=os.environ.get('CC') or ('clang' if os.name=='nt' else 'cc'))
    ap.add_argument('--seed-c',default=None,help='generated compiler C; defaults to bootstrap/slug_seed.c')
    ns=ap.parse_args();root=Path(__file__).resolve().parents[1];prefix=Path(ns.prefix).resolve()
    seed=Path(ns.seed_c).resolve() if ns.seed_c else root/'bootstrap'/'slug_seed.c'
    with tempfile.TemporaryDirectory(prefix='slug-install-stage-') as td:
        stage=Path(td);populate(root,stage,ns.cc,seed);exe=commit(stage,prefix)
    print(exe);return 0
if __name__=='__main__':raise SystemExit(main())

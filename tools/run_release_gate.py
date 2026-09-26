#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def run(label:str,cmd:list[str],*,env:dict[str,str]|None=None)->None:
    print(f'\n=== {label} ===',flush=True);t=time.monotonic()
    e=os.environ.copy();
    if env:e.update(env)
    p=subprocess.run(cmd,cwd=ROOT,env=e)
    dt=time.monotonic()-t
    if p.returncode:raise SystemExit(f'RELEASE GATE FAIL: {label} rc={p.returncode} elapsed={dt:.2f}s')
    print(f'=== PASS {label} ({dt:.2f}s) ===',flush=True)

def main()->int:
    ap=argparse.ArgumentParser(description='Run the SLUG 1.0 release gate')
    ap.add_argument('--slug',type=Path,required=True,help='native compiler candidate')
    ap.add_argument('--prefix',type=Path,help='installed prefix for install/editor smoke')
    ap.add_argument('--quick',action='store_true',help='skip heavy rebuild/conformance/hardening/bootstrap stages')
    a=ap.parse_args(); slug=a.slug.resolve()
    if not slug.is_file():raise SystemExit(f'missing native compiler: {slug}')
    py=sys.executable
    run('release metadata',[py,'tools/release_metadata.py'])
    run('public contract',[py,'tools/verify_public_contract.py'])
    run('install layout contract',[py,'tools/verify_install_layout.py'])
    run('install safety',[py,'tests/run_v1_install_safety.py'])
    run('install command shape',[py,'tests/run_v1_install_command_shape.py'])
    run('CLI contract',[py,'tests/run_v1_cli_contract.py','--slug',str(slug)])
    run('project/dependencies',[py,'tests/run_v1_project_manifest.py','--slug',str(slug)])
    run('identifier migration',[py,'tests/run_v1_identifier_migration.py','--slug',str(slug)])
    run('exception control',[py,'tests/run_v1_exception_control_hardening.py','--slug',str(slug)])
    run('module linkage',[py,'tests/run_v1_module_linkage.py','--slug',str(slug)])
    run('tooling',[py,'tests/run_v1_tooling.py','--slug',str(slug)])
    run('LSP',[py,'tests/run_v1_lsp.py','--slug',str(slug)])
    run('VS Code package',[py,'tests/run_v1_vscode_extension.py'])
    run('adversarial corpus',[py,'tests/run_v1_adversarial.py','--slug',str(slug),'--cases','64'])
    runtime_env=None if a.prefix else {'SLUG_RUNTIME':str((ROOT/'compiler'/'stage2'/'runtime_stage2.c').resolve())}
    run('platform UTF-8',[py,'tests/run_v1_platform_utf8.py','--slug',str(slug)],env=runtime_env)
    run('public examples',[py,'tests/run_v1_public_examples.py','--slug',str(slug)],env=runtime_env)
    if a.prefix:
        run('installed layout',[py,'tests/run_v1_install_layout.py','--prefix',str(a.prefix.resolve())])
        run('installed VS Code smoke',[py,'tests/run_v1_vscode_extension.py','--prefix',str(a.prefix.resolve())])
    if not a.quick:
        b=ROOT/'build'/'v1';b.mkdir(parents=True,exist_ok=True)
        for name in ('expr','program','semantic'):
            out=b/(name+'_cli'+('.exe' if os.name=='nt' else ''))
            run(f'build {name} differential probe',[py,'slug.py','build',f'compiler/v1/{name}_cli.slg','-o',str(out)])
        run('lexer differential',[py,'tests/run_v1_lexer_differential.py'])
        run('expression differential',[py,'tests/run_v1_expr_differential.py'])
        run('program differential',[py,'tests/run_v1_program_differential.py'])
        run('semantic differential',[py,'tests/run_v1_semantic_differential.py'])
        run('audited conformance',[py,'tests/test_v1_audited_conformance.py'])
        run('native hardening',[py,'tests/run_v1_native_hardening.py'])
        if os.name=='nt':
            ps=shutil.which('pwsh') or shutil.which('powershell')
            if not ps: raise SystemExit('RELEASE GATE FAIL: PowerShell unavailable for Windows bootstrap convergence')
            run('bootstrap convergence',[ps,'-NoProfile','-ExecutionPolicy','Bypass','-File','bootstrap/verify_bootstrap.ps1'])
        else:
            run('bootstrap convergence',['bash','bootstrap/verify_bootstrap.sh'])
    print('\nSLUG RELEASE GATE PASS')
    return 0
if __name__=='__main__':raise SystemExit(main())

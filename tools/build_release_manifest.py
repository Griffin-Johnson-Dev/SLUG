#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, platform, shutil, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def version_line(cmd:list[str]):
    try:
        p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=10)
        return p.stdout.splitlines()[0].strip() if p.stdout else None
    except Exception:return None

def item(p:Path):return {'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)}

def main()->int:
    ap=argparse.ArgumentParser(description='Build sidecar manifest for an exact SLUG release archive')
    ap.add_argument('--archive',type=Path,required=True)
    ap.add_argument('--compiler-c',type=Path,default=ROOT/'bootstrap'/'slug_seed.c')
    ap.add_argument('--out',type=Path)
    a=ap.parse_args();archive=a.archive.resolve();compiler=a.compiler_c.resolve()
    if not archive.is_file():raise SystemExit(f'missing archive: {archive}')
    if not compiler.is_file():raise SystemExit(f'missing compiler C: {compiler}')
    seed=(ROOT/'bootstrap'/'slug_seed.c').resolve()
    out=(a.out or archive.with_name(archive.stem+'_RELEASE_MANIFEST.json')).resolve()
    data={
      'schema':1,
      'compiler_version':(ROOT/'VERSION').read_text().strip(),
      'language_version':(ROOT/'LANGUAGE_VERSION').read_text().strip(),
      'cli_contract':int((ROOT/'CLI_CONTRACT_VERSION').read_text().strip()),
      'source_archive':item(archive),
      'canonical_generated_c':item(compiler),
      'bootstrap_seed':item(seed),
      'host':{'platform':platform.platform(),'python':platform.python_version(),'node':version_line(['node','--version']) if shutil.which('node') else None},
      'toolchains':{
        'gcc':version_line(['gcc','--version']) if shutil.which('gcc') else None,
        'clang':version_line(['clang','--version']) if shutil.which('clang') else None,
        'clang_cl':version_line(['clang-cl','--version']) if shutil.which('clang-cl') else None,
      },
    }
    out.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(out)
    return 0
if __name__=='__main__':raise SystemExit(main())

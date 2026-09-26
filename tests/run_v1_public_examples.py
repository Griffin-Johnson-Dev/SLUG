#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={
    'collections.slg':'1\n2\n3\n',
    'functions.slg':'81\n',
    'hello.slg':'Hello, SLUG!\n',
    'rpn.slg':'14\n',
}

def main()->int:
    ap=argparse.ArgumentParser(description='Execute every public SLUG v1 example')
    ap.add_argument('--slug',type=Path,required=True)
    a=ap.parse_args(); slug=a.slug.resolve()
    if not slug.is_file(): raise SystemExit(f'missing compiler: {slug}')
    passed=0
    for name,expected in EXPECTED.items():
        src=ROOT/'examples'/name
        if not src.is_file(): raise SystemExit(f'FAIL missing public example: {name}')
        ck=subprocess.run([str(slug),'check',str(src)],cwd=ROOT,text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        if ck.returncode:
            raise SystemExit(f'FAIL {name} check rc={ck.returncode}: {ck.stderr!r}')
        p=subprocess.run([str(slug),'run',str(src)],cwd=ROOT,text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
        if p.returncode or p.stdout!=expected:
            raise SystemExit(f'FAIL {name} run: {p.returncode=} {p.stdout=!r} {p.stderr=!r} expected={expected!r}')
        passed+=1; print(f'PASS {name}')
    print(f'PUBLIC EXAMPLES PASS {passed}/{len(EXPECTED)}')
    return 0
if __name__=='__main__': raise SystemExit(main())

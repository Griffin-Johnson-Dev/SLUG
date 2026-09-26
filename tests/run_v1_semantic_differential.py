from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from sluglang.compiler import frontend

NATIVE = ROOT / 'build' / 'v1' / ('semantic_cli.exe' if os.name == 'nt' else 'semantic_cli')

VALID = [
    'a:=1',
    "er'bad'",
    ">'x.slg'",
    '~ab{rv}',
    '~ab@i{rv1}',
    '~ab[@i,@s]{rv1 @s2}',
    '~ab x=1 y=2{rv}',
    '~ab x[y]{rv}',
    '~ab x{?x{rvx}ee{rv0}}',
    'wl?1{bl}',
    'wl?1{cl;bl}',
    'fl3{bl}',
    'fli0$5{?i==2{cl}}',
    '~ab{wl?1{rv1}}',
    '~ab{fl3{?1{rv}}}',
    'wl?1{?1{bl}}',
    '~ab{wl?1{?1{cl}rv}}',
    '~ab[@i,@s]{wl?0{bl}rv1 @s2}',
    '~ab{tr{rv}ca{rv}fn{rv}}',
    '~ab@i{tr{rv1}ca{rv2}fn{a:=1}}',
    'wl?1{tr{bl}fn{cl}}',
    'fl3{tr{?1{bl}}ca{cl}fn{a:=1}}',
    '~ab{wl?1{tr{cl}ca{bl}fn{rv}}rv}',
    '~ab{tr{tr{rv}fn{a:=1}}ca{rv}fn{a:=2}}',
    "tr{er'x'}cae{coe}fn{co'fin'}",
    'tr{a:=1}fn{a=2}',
]

INVALID = [
    'rv',
    'rv1',
    'bl',
    'cl',
    '?1{bl}',
    '?1{rv}',
    '~ab{bl}',
    '~ab{cl}',
    '~ab@i{rv}',
    '~ab[@i,@s]{rv1}',
    '~ab x=1 y{rv}',
    '~ab x[x]{rv}',
    '~ab{~cd{rv}rv}',
    "~ab{>'x.slg';rv}",
    '~ab{?1{bl}rv}',
    'wl?1{rv}',
    "?1{>'x.slg'}",
    'fl3{~ab{rv}}',
    '~ab{wl?1{~cd{rv}}rv}',
    'tr{rv}fn{}',
    'tr{}ca{rv}',
    'tr{}fn{bl}',
    'tr{}ca{cl}',
    "tr{>'x.slg'}fn{}",
    "tr{}ca{>'x.slg'}",
    "tr{}fn{>'x.slg'}",
    'tr{~ab{rv}}fn{}',
    'tr{}ca{~ab{rv}}',
    'tr{}fn{~ab{rv}}',
    '~ab@i{tr{rv}fn{}}',
    '~ab@i{tr{}ca{rv}fn{}}',
]


def oracle_accepts(src: str) -> tuple[bool, str]:
    try:
        frontend(src)
        return True, ''
    except Exception as e:
        return False, str(e)


def native_accepts(src: str) -> tuple[bool, str, str]:
    p = subprocess.run([str(NATIVE), src], cwd=ROOT, text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=20)
    return p.returncode == 0, p.stdout.strip(), p.stderr.strip()


def main() -> int:
    if not NATIVE.exists():
        print(f'missing native probe: {NATIVE}', file=sys.stderr)
        return 2
    bad = []
    for src in VALID:
        oa, oe = oracle_accepts(src)
        na, no, ne = native_accepts(src)
        if not (oa and na):
            bad.append(('VALID', src, oa, na, oe, no, ne))
    for src in INVALID:
        oa, oe = oracle_accepts(src)
        na, no, ne = native_accepts(src)
        if oa or na:
            bad.append(('INVALID', src, oa, na, oe, no, ne))
    print(f'V1 structural semantic differential: valid={len(VALID)-(sum(1 for b in bad if b[0]=="VALID"))}/{len(VALID)}; rejects={len(INVALID)-(sum(1 for b in bad if b[0]=="INVALID"))}/{len(INVALID)}')
    if bad:
        print(f'failures={len(bad)}')
        for kind, src, oa, na, oe, no, ne in bad:
            print(f'\n{kind} {src!r}\n  oracle_accepts={oa} native_accepts={na}\n  oracle={oe!r}\n  stdout={no!r}\n  stderr={ne!r}')
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

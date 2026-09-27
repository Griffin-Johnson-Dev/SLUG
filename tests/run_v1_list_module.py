#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = str((ROOT / 'compiler' / 'stage2' / 'runtime_stage2.c').resolve())


def invoke(slug: Path, command: str, source: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix='slug-list-module-') as td0:
        td = Path(td0)
        src = td / 'main.slg'
        src.write_text(source, encoding='utf-8')
        env = os.environ.copy()
        env['SLUG_RUNTIME'] = RUNTIME
        return subprocess.run(
            [str(slug), command, str(src)],
            cwd=ROOT,
            env=env,
            text=True,
            encoding='utf-8',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )


def require_run(slug: Path, name: str, source: str, expected: str) -> None:
    p = invoke(slug, 'run', source)
    if p.returncode != 0 or p.stdout != expected or p.stderr:
        raise SystemExit(
            f'FAIL {name}: rc={p.returncode} stdout={p.stdout!r} stderr={p.stderr!r} expected={expected!r}'
        )
    print(f'PASS {name}')


def require_error(slug: Path, name: str, source: str, kind: str) -> None:
    p = invoke(slug, 'run', source)
    if p.returncode == 0 or f"kind='{kind}'" not in p.stderr:
        raise SystemExit(
            f'FAIL {name}: rc={p.returncode} stdout={p.stdout!r} stderr={p.stderr!r} expected kind={kind!r}'
        )
    print(f'PASS {name}')


def main() -> int:
    ap = argparse.ArgumentParser(description='SLUG v1 @std/list mutation contract')
    ap.add_argument('--slug', type=Path, required=True)
    a = ap.parse_args()
    slug = a.slug.resolve()
    if not slug.is_file():
        raise SystemExit(f'missing compiler: {slug}')

    require_run(
        slug,
        'mutation-indexing-capabilities',
        ">'@std/list':LI >'@std/sys':SY\n"
        "a:=[] LI.ap[a,1$] LI.ap[a,2$] LI.ap[a,2$] "
        "LI.ip[a,0$,0$] LI.ip[a,ln[a],3$] LI.ip[a,1$-,9$] "
        "co[a] co[LI.rm[a,2$]] co[a] co[LI.pp[a,2$-]] co[a] "
        "co[LI.pp[a]] co[a] "
        "co[SY.cp['@std/list.ap']] co[SY.cp['@std/list.ip']] "
        "co[SY.cp['@std/list.rm']] co[SY.cp['@std/list.pp']]",
        '[0,1,2,2,9,3]\ntrue\n[0,1,2,9,3]\n9\n[0,1,2,3]\n3\n[0,1,2]\ntrue\ntrue\ntrue\ntrue\n',
    )

    require_run(
        slug,
        'active-namespace-and-module-name-collision',
        ">'@std/list':LI >'@std/fs':FS\n"
        "a:=[1$] <:LI ap[a,2$] co[rm[a,1$]] <:. "
        "co[FS.fe['/definitely/not/a/slug/path']] co[a]",
        'true\nfalse\n[2]\n',
    )

    require_run(
        slug,
        'alias-mutation-and-first-match',
        ">\'@std/list\':LI\n"
        "a:=[1$,1$] b:=a LI.ap[b,2$] co[a] "
        "co[LI.rm[a,1$]] co[a] co[LI.rm[a,9$]] co[a]",
        '[1,1,2]\ntrue\n[1,2]\nfalse\n[1,2]\n',
    )

    require_error(slug, 'pop-empty', ">'@std/list':LI a:=[] LI.pp[a]", 'index')
    require_error(slug, 'pop-out-of-range', ">'@std/list':LI a:=[1$] LI.pp[a,1$]", 'index')
    require_error(slug, 'insert-out-of-range', ">'@std/list':LI a:=[1$] LI.ip[a,2$,9$]", 'index')
    require_error(slug, 'insert-noninteger', ">'@std/list':LI a:=[1$] LI.ip[a,1.5,9$]", 'type')
    require_error(slug, 'pop-noninteger', ">'@std/list':LI a:=[1$] LI.pp[a,0.5]", 'type')
    require_error(slug, 'append-nonlist', ">'@std/list':LI LI.ap[1$,2$]", 'type')

    print('LIST MODULE PASS 9/9')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

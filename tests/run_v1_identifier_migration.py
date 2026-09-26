#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, tempfile
from pathlib import Path


def run(slug: str, *args: str):
    return subprocess.run([slug, *args], text=True, capture_output=True)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--slug',required=True); ns=ap.parse_args()
    slug=str(Path(ns.slug).resolve()); passed=[]
    def need(ok: bool, name: str, detail=''):
        if not ok: raise AssertionError(f'{name}: {detail}')
        passed.append(name); print('PASS',name)
    with tempfile.TemporaryDirectory(prefix='slug-ident-') as td:
        td=Path(td)
        p=td/'names.slg'
        p.write_text("_1_:=7;_currentIndex_:=3;_Name_:=11;_name_:=12;co[_1_];co[_currentIndex_];co[_Name_];co[_name_]\n",encoding='utf-8')
        cp=run(slug,'run',str(p)); need(cp.returncode==0 and cp.stdout=='7\n3\n11\n12\n' and cp.stderr=='','native-new-identifiers',repr((cp.returncode,cp.stdout,cp.stderr)))

        q=td/'interp.slg'; q.write_text("_thing2_:=9;co['v={_thing2_}']\n",encoding='utf-8')
        cp=run(slug,'run',str(q)); need(cp.returncode==0 and cp.stdout=='v=9\n' and cp.stderr=='','interpolation-identifier',repr((cp.returncode,cp.stdout,cp.stderr)))

        cp=run(slug,'fmt',str(p)); need(cp.returncode==0 and '_currentIndex_' in cp.stdout and '_Name_' in cp.stdout,'fmt-preserves-new-spelling',repr((cp.returncode,cp.stdout,cp.stderr)))
        cp=run(slug,'crush',str(p)); crushed=p.with_suffix('.slgc'); ct=crushed.read_text(encoding='utf-8') if crushed.exists() else ''; need(cp.returncode==0 and '_currentIndex_' in ct and '_Name_' in ct,'crush-preserves-new-spelling',repr((cp.returncode,ct,cp.stderr)))

        bad=td/'legacy.slg'; bad.write_text('_n_e_x_t_:=1\n',encoding='utf-8')
        cp=run(slug,'check',str(bad)); need(cp.returncode==65,'common-legacy-spelling-rejected',repr((cp.returncode,cp.stdout,cp.stderr)))

        one=td/'numeric.slg'; one.write_text('_1_:=2;co[_1_]\n',encoding='utf-8')
        cp=run(slug,'check',str(one)); need(cp.returncode==0,'numeric-extended-name-check',repr((cp.returncode,cp.stdout,cp.stderr)))

        adj=td/'adjacent.slg'; adj.write_text('_left_:=1;_right_:=2;co[_left_];co[_right_]\n',encoding='utf-8')
        cp=run(slug,'run',str(adj)); need(cp.returncode==0 and cp.stdout=='1\n2\n','adjacent-name-boundaries',repr((cp.returncode,cp.stdout,cp.stderr)))

        mixed=td/'mixed.slg'; mixed.write_text('_a1B2_:=5;co[_a1B2_]\n',encoding='utf-8')
        cp=run(slug,'run',str(mixed)); need(cp.returncode==0 and cp.stdout=='5\n','mixed-alnum-case-name',repr((cp.returncode,cp.stdout,cp.stderr)))

    print(f'IDENTIFIER MIGRATION PASS {len(passed)}/8')
    return 0
if __name__=='__main__': raise SystemExit(main())

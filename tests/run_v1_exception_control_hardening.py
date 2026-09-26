#!/usr/bin/env python3
import argparse, subprocess, tempfile
from pathlib import Path

CASES = [
    ("return_try_no_finally", "~ab{tr{rv7}ca{rv8}}co[ab[]]", 0, "7\n"),
    ("return_finally", "~ab{tr{rv7}fn{co'f'}}co[ab[]]", 0, "f\n7\n"),
    ("catch_return_finally", "~ab{tr{er'x'}cae{rv8}fn{co'f'}}co[ab[]]", 0, "f\n8\n"),
    ("finally_return_supersedes_return", "~ab{tr{rv7}fn{rv9}}co[ab[]]", 0, "9\n"),
    ("finally_return_supersedes_error", "~ab{tr{er'x'}fn{rv9}}co[ab[]]", 0, "9\n"),
    ("nested_return_finally_order", "~ab{tr{tr{rv7}fn{co'i'}}fn{co'o'}}co[ab[]]", 0, "i\no\n7\n"),
    ("break_finally", "a:=0 wl?a<3{a=a1+ tr{bl}fn{co'f'}}co'd'", 0, "f\nd\n"),
    ("continue_finally", "a:=0 wl?a<2{a=a1+ tr{cl}fn{co'f'}}co'd'", 0, "f\nf\nd\n"),
    ("outer_try_inner_break", "a:=0 tr{wl?a<3{a=a1+ bl}co'i'}fn{co'f'}co'd'", 0, "i\nf\nd\n"),
    ("post_return_exception_frame_clean", "~ab{tr{rv7}ca{rv8}}ab[] tr{er'x'}ca{co'caught'}", 0, "caught\n"),
    ("callee_raise_caught_by_caller", "~ab{er'x'}~cd{tr{ab[]}cae{rv7}}co[cd[]]", 0, "7\n"),
    ("nested_callee_raise_caught_by_outer", "~ab{er'x'}~cd{ab[]}tr{cd[]}cae{co'caught'}", 0, "caught\n"),
]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--slug', required=True); ns=ap.parse_args()
    slug=str(Path(ns.slug).resolve())
    ok=0
    with tempfile.TemporaryDirectory(prefix='slug-exc-ctrl-') as td:
        td=Path(td)
        for name,src,rc,out in CASES:
            f=td/(name+'.slg'); f.write_text(src+'\n',encoding='utf-8')
            cp=subprocess.run([slug,'run',str(f)],text=True,capture_output=True)
            good=cp.returncode==rc and cp.stdout==out and cp.stderr==''
            if good:
                ok+=1; print('PASS',name)
            else:
                print('FAIL',name)
                print(' rc',cp.returncode,'expected',rc)
                print(' stdout',repr(cp.stdout),'expected',repr(out))
                print(' stderr',repr(cp.stderr))
    print(f'EXCEPTION CONTROL HARDENING {ok}/{len(CASES)}')
    raise SystemExit(0 if ok==len(CASES) else 1)

if __name__=='__main__': main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PYCLI = [sys.executable, str(ROOT / "slug.py")]
RUNTIME = str((ROOT / "compiler" / "stage2" / "runtime_stage2.c").resolve())


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SLUG_RUNTIME"] = RUNTIME
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
    )


def write_case(root: Path, files: dict[str, str]) -> None:
    for name, source in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source, encoding="utf-8")


# (name, files, command, expected stdout).  expected stdout=None means compile-time reject.
BASE_CASE_COUNT = 23

CASES: list[tuple[str, dict[str, str], str, str | None]] = [
    ("alias-call", {"lib.slg": "~tw x{rv x 2 *}\n", "main.slg": ">'lib.slg':m\nco[m.tw[20]]\n"}, "run", "40\n"),
    ("alias-call-statement", {"lib.slg": "+:x:=0\n~up{x=x 1 + rv}\n~gt{rv x}\n", "main.slg": ">'lib.slg':m\nm.up[]\nco[m.gt[]]\n"}, "run", "1\n"),
    ("alias-state", {"state.slg": "+:x:=1\n~nx{x=x 1 + rv x}\n~gt{rv x}\n", "main.slg": ">'state.slg':ST\nco[ST.x]\nco[ST.nx[]]\nST.x=5\nco[ST.gt[]]\n"}, "run", "1\n2\n5\n"),
    ("direct-state", {"state.slg": "+:x:=1\n~gt{rv x}\n", "main.slg": ">'state.slg'\nco[x]\nx=5\nco[gt[]]\n"}, "run", "1\n5\n"),
    ("alias-class", {"obj.slg": "#AB x{.v:=x ~gt{rv .v} ~~mk y{rv y 1 +}}\n", "main.slg": ">'obj.slg':MA\na:=MA.AB[5]\nco[a.gt[]]\nco[MA.AB.mk[7]]\n"}, "run", "5\n8\n"),
    ("alias-class-static-field", {"obj.slg": "#AB{..x:=4 ~~mk{rv ..x 1 +}}\n", "main.slg": ">'obj.slg':MA\nco[MA.AB.x]\nco[MA.AB.mk[]]\n"}, "run", "4\n5\n"),
    ("active-namespace", {"lib.slg": "~tw x{rv x 2 *}\n", "main.slg": ">'lib.slg':MA\n<:MA\nco[tw[3]]\n<:.\n"}, "run", "6\n"),
    ("active-namespace-state", {"state.slg": "+:x:=1\n~gt{rv x}\n", "main.slg": ">'state.slg':ST\n<:ST\nco[x]\nx=5\nco[x]\n<:.\nco[ST.gt[]]\n"}, "run", "1\n5\n5\n"),
    ("active-namespace-class", {"obj.slg": "#AB{..x:=4 ~~mk{rv ..x 1 +}}\n", "main.slg": ">'obj.slg':MA\n<:MA\nco[AB.x]\nco[AB.mk[]]\n<:.\n"}, "run", "4\n5\n"),
    ("active-namespace-whitespace", {"lib.slg": "~tw x{rv x 2 *}\n", "main.slg": ">'lib.slg':MA\n< : M A\nc o[t w[3]]\n< : .\n"}, "run", "6\n"),
    ("hard-punctuation-whitespace", {"state.slg": "+:x : = 1\n~gt{r v x}\n", "main.slg": ">'state.slg':ST\na : = S T.x\n? a = = 1 { c o[2] }\n"}, "run", "2\n"),
    ("alias-shapes", {"lib.slg": "~tw x{rv x 2 *}\n", "main.slg": ">'lib.slg':m\n>'lib.slg':MA\n>'lib.slg':_ma_\nco[m.tw[1]]\nco[MA.tw[2]]\nco[_ma_.tw[3]]\n"}, "run", "2\n4\n6\n"),
    ("nested-direct", {"base.slg": "~ad x{rv x 1 +}\n", "calc.slg": ">'base.slg'\n~tw x{rv ad[x] 2 *}\n", "main.slg": ">'calc.slg':m\nco[m.tw[20]]\n"}, "run", "42\n"),
    ("nested-alias", {"base.slg": "~ad x{rv x 1 +}\n", "calc.slg": ">'base.slg':b\n~tw x{rv b.ad[x] 2 *}\n", "main.slg": ">'calc.slg':m\nco[m.tw[20]]\n"}, "run", "42\n"),
    ("diamond-state", {"state.slg": "+:x:=1\n~nx{x=x 1 + rv x}\n", "left.slg": ">'state.slg':s\n~li{rv s.nx[]}\n", "right.slg": ">'state.slg':s\n~ri{rv s.nx[]}\n", "main.slg": ">'left.slg':LL\n>'right.slg':RR\n>'state.slg':ST\nco[LL.li[]]\nco[RR.ri[]]\nco[ST.x]\n"}, "run", "2\n3\n3\n"),
    ("direct-class-inheritance", {"base.slg": "#AB x{.v:=x ~gt{rv .v}}\n", "main.slg": ">'base.slg'\n#CD<AB x{^^[x]}\na:=CD[9]\nco[a.gt[]]\n"}, "run", "9\n"),
    ("private-alias-hidden", {"lib.slg": "-~pr x{rv x}\n", "main.slg": ">'lib.slg':m\nco[m.pr[1]]\n"}, "check", None),
    ("immutable-alias-write", {"lib.slg": "+:x::=1\n", "main.slg": ">'lib.slg':m\nm.x=2\n"}, "check", None),
    ("duplicate-alias", {"a.slg": "~aa{rv 1}\n", "b.slg": "~bb{rv 2}\n", "main.slg": ">'a.slg':m\n>'b.slg':m\n"}, "check", None),
    ("direct-call-collision", {"a.slg": "~tw x{rv x}\n", "b.slg": "~tw x{rv x 1 +}\n", "main.slg": ">'a.slg'\n>'b.slg'\nco[tw[1]]\n"}, "check", None),
    ("direct-var-collision", {"a.slg": "+:x:=1\n", "b.slg": "+:x:=2\n", "main.slg": ">'a.slg'\n>'b.slg'\nco[x]\n"}, "check", None),
    ("local-direct-collision", {"a.slg": "~tw x{rv x}\n", "main.slg": ">'a.slg'\n~tw x{rv x 1 +}\n"}, "check", None),
    ("cycle", {"a.slg": ">'b.slg'\n~aa{rv 1}\n", "b.slg": ">'a.slg'\n~bb{rv 2}\n", "main.slg": ">'a.slg'\n"}, "check", None),

    # Imported-parent semantic seed coverage. These prove that inheritance metadata
    # crossing a module boundary retains constructor contracts, private ownership,
    # and inherited instance-storage identity rather than only the public class name.
    ("import-parent-default-auto", {"base.slg": "#AB x=3{.v:=x ~gt{rv.v}}\n", "main.slg": ">'base.slg'\n#CD<AB{}\na:=CD[]\nco[a.gt[]]\n"}, "run", "3\n"),
    ("import-parent-default-explicit-xx", {"base.slg": "#AB x=3{.v:=x ~gt{rv.v}}\n", "main.slg": ">'base.slg'\n#CD<AB{^^[xx]}\na:=CD[]\nco[a.gt[]]\n"}, "run", "3\n"),
    ("import-parent-required-super", {"base.slg": "#AB x{.v:=x}\n", "main.slg": ">'base.slg'\n#CD<AB{}\n"}, "check", None),
    ("import-parent-super-order", {"base.slg": "#AB x{.v:=x}\n", "main.slg": ">'base.slg'\n#CD<AB x{.w:=1 ^^[x]}\n"}, "check", None),
    ("import-parent-double-super", {"base.slg": "#AB x{.v:=x}\n", "main.slg": ">'base.slg'\n#CD<AB x{^^[x] ^^[x]}\n"}, "check", None),
    ("import-parent-super-missing-arg", {"base.slg": "#AB x{.v:=x}\n", "main.slg": ">'base.slg'\n#CD<AB{^^[]}\n"}, "check", None),
    ("import-parent-super-too-many", {"base.slg": "#AB{.v:=1}\n", "main.slg": ">'base.slg'\n#CD<AB{^^[1]}\n"}, "check", None),
    ("import-parent-super-default-required", {"base.slg": "#AB x{.v:=x}\n", "main.slg": ">'base.slg'\n#CD<AB{^^[xx]}\n"}, "check", None),
    ("import-parent-public-field-redecl", {"base.slg": "#AB{.x:=1}\n", "main.slg": ">'base.slg'\n#CD<AB{.x:=2}\n"}, "check", None),
    ("import-parent-private-field-redecl", {"base.slg": "#AB{-.x:=1}\n", "main.slg": ">'base.slg'\n#CD<AB{.x:=2}\n"}, "check", None),
    ("import-parent-private-field-read", {"base.slg": "#AB{-.x:=1}\n", "main.slg": ">'base.slg'\n#CD<AB{~gt{rv.x}}\n"}, "check", None),
    ("import-parent-private-method-call", {"base.slg": "#AB{-~pr{rv1}}\n", "main.slg": ">'base.slg'\n#CD<AB{~gt{rv.pr[]}}\n"}, "check", None),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="SLUG v1 provider-aware module linkage differential")
    ap.add_argument("--slug", required=True, help="native compiler candidate")
    ap.add_argument("--group", choices=("all", "base", "inheritance"), default="all",
                    help="run the base linkage cases, the imported-inheritance extension, or both")
    ap.add_argument("--case", action="append", dest="cases",
                    help="run only the named case (repeatable); useful for resumable proof runs")
    ns = ap.parse_args()
    native = Path(ns.slug)
    if not native.is_absolute():
        native = (Path.cwd() / native).resolve()
    if not native.is_file():
        print(f"missing native compiler: {native}", file=sys.stderr)
        return 2

    selected = CASES if ns.group == "all" else (CASES[:BASE_CASE_COUNT] if ns.group == "base" else CASES[BASE_CASE_COUNT:])
    if ns.cases:
        wanted = set(ns.cases)
        known = {case[0] for case in selected}
        missing = sorted(wanted - known)
        if missing:
            print("unknown case(s): " + ", ".join(missing), file=sys.stderr)
            return 2
        selected = [case for case in selected if case[0] in wanted]
    failures: list[str] = []
    positives = negatives = 0
    with tempfile.TemporaryDirectory(prefix="slug-module-linkage-") as td0:
        root = Path(td0)
        for name, files, command, expected_out in selected:
            td = root / name
            td.mkdir()
            write_case(td, files)
            py = run(PYCLI + [command, "main.slg"], td)
            na = run([str(native), command, "main.slg"], td)

            if expected_out is None:
                negatives += 1
                ok = py.returncode != 0 and na.returncode == 65 and not py.stdout and not na.stdout
            else:
                positives += 1
                ok = (
                    py.returncode == 0
                    and na.returncode == 0
                    and py.stdout == expected_out
                    and na.stdout == expected_out
                    and py.stderr == ""
                    and na.stderr == ""
                )

            print(
                ("PASS" if ok else "FAIL"),
                name,
                "ref=", py.returncode, repr(py.stdout), repr(py.stderr[:180]),
                "native=", na.returncode, repr(na.stdout), repr(na.stderr[:180]),
            )
            if not ok:
                failures.append(name)

    print(f"MODULE LINKAGE[{ns.group}]: {len(selected)-len(failures)}/{len(selected)}; positive={positives}; negative={negatives}")
    if failures:
        print("FAILURES:", ", ".join(failures))
        return 1
    print("MODULE LINKAGE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

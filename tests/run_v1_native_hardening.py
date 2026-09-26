from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sluglang.compiler import emit_c


@dataclass(frozen=True)
class Case:
    name: str
    source: str
    expected_rc: int = 0


CASES = (
    Case("range_continue", "s:=0 fli0$5{?i==2{cl}s=si+} co[s]"),
    Case("cycle_equal", "a:=[nn] b:=[nn] a[0]=a b[0]=b co[a] co[?a==b]"),
    Case("unicode_slice", "s:='🐌é𐍈a' co[ln[s]] co[s[::1$-]]"),
    Case("numeric_edges", "co[18446744073709551615$] co[?9007199254740993$>9007199254740992.] co[7$- 3$ %]"),
    Case("exception_rethrow", "tr{tr{er'x'}cae{er}fn{co'i'}}cae{coe}fn{co'o'}"),
    Case("finally_supersede", "tr{er'x'}fn{er'y'}", 66),
    Case("interpolation_order", "a:=0 co['{a:=1}{a:=2}{a}']"),
    Case("snapshot_map_iteration", "m:=['a':1,'b':2] s:='' flkm{s=sk+ m['c']:=3} co[s] co[ln[m]]"),
)


def compiler() -> str | None:
    return shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")


def compile_native(cc: str, cfile: Path, exe: Path, *, opt: str, sanitize: bool = False) -> tuple[bool, str]:
    cmd = [cc, str(cfile), "-std=c11", opt]
    base = Path(cc).name.lower()
    if "clang" in base:
        # Generated C mirrors finite SLUG nesting.  Avoid inheriting Clang's default
        # 256 bracket limit as a language semantic ceiling.
        ctext = cfile.read_text(encoding="utf-8")
        depth = max(256, ctext.count("(") + ctext.count("[") + ctext.count("{") + 32)
        cmd.append(f"-fbracket-depth={depth}")
    if sanitize:
        cmd += ["-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    if os.name != "nt":
        cmd.append("-lm")
    else:
        cmd += ["-lws2_32", "-lshell32", "-luser32", "-lgdi32", "-lwinmm"]
    cmd += ["-o", str(exe)]
    p = subprocess.run(cmd, text=True, encoding='utf-8', errors='replace', capture_output=True)
    return p.returncode == 0, p.stdout + p.stderr


def run_native(exe: Path, *, sanitized: bool = False) -> tuple[int, bytes, bytes]:
    env = os.environ.copy()
    if sanitized:
        env["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
        env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    p = subprocess.run([str(exe)], capture_output=True, timeout=10, env=env)
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    cc = compiler()
    if cc is None:
        print("SKIP: no C compiler available")
        return 0

    failures: list[str] = []
    sanitizer_supported = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for case in CASES:
            cfile = root / f"{case.name}.c"
            cfile.write_text(emit_c(case.source), encoding="utf-8")

            results: dict[str, tuple[int, bytes, bytes]] = {}
            for opt in ("-O0", "-O3"):
                exe = root / (f"{case.name}_{opt[1:]}" + ('.exe' if os.name == 'nt' else ''))
                ok, diag = compile_native(cc, cfile, exe, opt=opt)
                if not ok:
                    failures.append(f"{case.name} {opt} compile failed:\n{diag}")
                    continue
                results[opt] = run_native(exe)
                if results[opt][0] != case.expected_rc:
                    failures.append(
                        f"{case.name} {opt} rc={results[opt][0]} expected={case.expected_rc}; stderr={results[opt][2]!r}"
                    )

            if "-O0" in results and "-O3" in results and results["-O0"] != results["-O3"]:
                failures.append(
                    f"{case.name} optimization differential:\n  O0={results['-O0']!r}\n  O3={results['-O3']!r}"
                )

            if sanitizer_supported:
                exe = root / (f"{case.name}_san" + ('.exe' if os.name == 'nt' else ''))
                ok, diag = compile_native(cc, cfile, exe, opt="-O3", sanitize=True)
                if not ok:
                    sanitizer_supported = False
                    print(f"SANITIZER SKIP after {case.name}: toolchain did not accept ASan/UBSan")
                    print(diag.strip())
                else:
                    got = run_native(exe, sanitized=True)
                    if got[0] != case.expected_rc:
                        failures.append(
                            f"{case.name} sanitizer rc={got[0]} expected={case.expected_rc}; stderr={got[2]!r}"
                        )
                    elif "-O3" in results and got != results["-O3"]:
                        failures.append(
                            f"{case.name} sanitizer behavioral differential:\n  O3={results['-O3']!r}\n  SAN={got!r}"
                        )

            if case.name not in "\n".join(failures):
                print(f"PASS {case.name}")

    if failures:
        print(f"FAILURES={len(failures)}", file=sys.stderr)
        for failure in failures:
            print("\n" + failure, file=sys.stderr)
        return 1

    print(f"PASS native hardening: {len(CASES)} cases; optimizer O0/O3 differential clean")
    if sanitizer_supported:
        print("PASS ASan+UBSan corpus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

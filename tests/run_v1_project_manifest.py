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


def run(cmd: list[str], cwd: Path, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SLUG_RUNTIME"] = RUNTIME
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def manifest(name: str = "demo", entry: str = "src/main.slg", deps: str = "{}") -> str:
    return f'{{"schema":1,"name":"{name}","entry":"{entry}","dependencies":{deps}}}\n'


def main() -> int:
    ap = argparse.ArgumentParser(description="SLUG v1 K9E project manifest/dependency differential")
    ap.add_argument("--slug", required=True, help="native compiler candidate")
    ns = ap.parse_args()
    native = Path(ns.slug).resolve()
    if not native.is_file():
        print(f"missing native compiler: {native}", file=sys.stderr)
        return 2

    failures: list[str] = []
    passed = total = 0

    def record(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
            print(f"PASS {name}")
        else:
            failures.append(name + (f": {detail}" if detail else ""))
            print(f"FAIL {name}: {detail}")

    with tempfile.TemporaryDirectory(prefix="slug-k9e-project-") as td0:
        base = Path(td0)

        # 1-3: upward discovery plus source-optional check/run/build.
        p = base / "discover"
        write(p, "slug.json", manifest(deps='{"math":"vendor/math"}'))
        write(p, "vendor/math/lib.slg", "~tw x{rv x 2 *}\n")
        write(p, "src/main.slg", ">'@dep/math/lib.slg':MA\nco[MA.tw[21]]\n")
        nested = p / "nested" / "deeper"; nested.mkdir(parents=True)
        py = run(PYCLI + ["check"], nested); na = run([str(native), "check"], nested)
        record("discover-check", py.returncode == 0 and na.returncode == 0 and not na.stdout,
               f"py={py.returncode} na={na.returncode} naerr={na.stderr!r}")
        py = run(PYCLI + ["run"], nested); na = run([str(native), "run"], nested)
        record("discover-run", py.returncode == 0 and na.returncode == 0 and py.stdout == "42\n" and na.stdout == "42\n",
               f"py={py.returncode}/{py.stdout!r} na={na.returncode}/{na.stdout!r} err={na.stderr!r}")
        cc = os.environ.get("CC") or ("clang" if os.name == "nt" else "cc")
        na = run([str(native), "build", "--cc", cc], nested, timeout=120)
        exe = p / "build" / ("demo.exe" if os.name == "nt" else "demo")
        ex = run([str(exe)], p) if na.returncode == 0 and exe.is_file() else None
        record("discover-build-default", na.returncode == 0 and ex is not None and ex.returncode == 0 and ex.stdout == "42\n",
               f"build={na.returncode} stderr={na.stderr!r} exe={exe.is_file()}")

        # 4: explicit source still receives discovered manifest context.
        py = run(PYCLI + ["check", "src/main.slg"], p); na = run([str(native), "check", "src/main.slg"], p)
        record("explicit-source-project-context", py.returncode == 0 and na.returncode == 0,
               f"py={py.returncode} na={na.returncode} err={na.stderr!r}")

        # 5: dependency modules retain ordinary importer-relative imports.
        p = base / "nesteddep"
        write(p, "slug.json", manifest(deps='{"math":"vendor/math"}'))
        write(p, "vendor/math/util.slg", "~ad x{rv x 1 +}\n")
        write(p, "vendor/math/lib.slg", ">'util.slg'\n~tw x{rv ad[x] 2 *}\n")
        write(p, "src/main.slg", ">'@dep/math/lib.slg':MA\nco[MA.tw[20]]\n")
        py = run(PYCLI + ["run"], p); na = run([str(native), "run"], p)
        record("dependency-relative-import", py.returncode == 0 and na.returncode == 0 and py.stdout == "42\n" and na.stdout == "42\n",
               f"py={py.returncode}/{py.stdout!r} na={na.returncode}/{na.stdout!r} err={na.stderr!r}")

        # 6: repeated @dep resolution must share one provider/state cell through a diamond.
        p = base / "diamond"
        write(p, "slug.json", manifest(deps='{"state":"vendor/state"}'))
        write(p, "vendor/state/state.slg", "+:x:=1\n~nx{x=x 1 + rv x}\n")
        write(p, "src/left.slg", ">'@dep/state/state.slg':ST\n~li{rv ST.nx[]}\n")
        write(p, "src/right.slg", ">'@dep/state/state.slg':ST\n~ri{rv ST.nx[]}\n")
        write(p, "src/main.slg", ">'left.slg':LL\n>'right.slg':RR\n>'@dep/state/state.slg':ST\nco[LL.li[]]\nco[RR.ri[]]\nco[ST.x]\n")
        py = run(PYCLI + ["run"], p); na = run([str(native), "run"], p)
        record("dependency-provider-identity", py.returncode == 0 and na.returncode == 0 and py.stdout == "2\n3\n3\n" and na.stdout == "2\n3\n3\n",
               f"py={py.returncode}/{py.stdout!r} na={na.returncode}/{na.stdout!r} err={na.stderr!r}")

        # 7: explicit absolute source discovers its own project even from an unrelated cwd.
        outside = base / "outside"; outside.mkdir()
        src_abs = (base / "discover" / "src" / "main.slg").resolve()
        py = run(PYCLI + ["check", str(src_abs)], outside); na = run([str(native), "check", str(src_abs)], outside)
        record("absolute-source-project-context", py.returncode == 0 and na.returncode == 0,
               f"py={py.returncode} na={na.returncode} err={na.stderr!r}")

        # 8: dependency modules may address another root-declared dependency.
        p = base / "crossdep"
        write(p, "slug.json", manifest(deps='{"math":"vendor/math","util":"vendor/util"}'))
        write(p, "vendor/util/base.slg", "~ad x{rv x 1 +}\n")
        write(p, "vendor/math/lib.slg", ">'@dep/util/base.slg':UT\n~tw x{rv UT.ad[x] 2 *}\n")
        write(p, "src/main.slg", ">'@dep/math/lib.slg':MA\nco[MA.tw[20]]\n")
        py = run(PYCLI + ["check"], p); na = run([str(native), "check"], p)
        record("root-flat-cross-dependency", py.returncode == 0 and na.returncode == 0,
               f"py={py.returncode} na={na.returncode} err={na.stderr!r}")

        # 9: project-mode run preserves the public `--` argument-forwarding rule.
        p = base / "runargs"
        write(p, "slug.json", manifest())
        write(p, "src/main.slg", ">'@std/sys':SY\nco[SY.av[]]\n")
        py = run(PYCLI + ["run", "--", "hello", "world"], p); na = run([str(native), "run", "--", "hello", "world"], p)
        record("project-run-arguments", py.returncode == 0 and na.returncode == 0 and "'hello'" in py.stdout and "'world'" in py.stdout and "'hello'" in na.stdout and "'world'" in na.stdout,
               f"py={py.returncode}/{py.stdout!r} na={na.returncode}/{na.stdout!r} err={na.stderr!r}")

        # Check-only rejection helpers.
        def reject(name: str, manifest_text: str | None, source: str = "co[1]\n", *, explicit: bool = False) -> None:
            p = base / ("reject-" + name); p.mkdir()
            write(p, "src/main.slg", source)
            if manifest_text is not None:
                write(p, "slug.json", manifest_text)
            args = ["check", "src/main.slg"] if explicit else ["check"]
            py = run(PYCLI + args, p); na = run([str(native), *args], p)
            record(name, py.returncode != 0 and na.returncode != 0,
                   f"py={py.returncode} na={na.returncode} pyerr={py.stderr!r} naerr={na.stderr!r}")

        # 7-18: strict schema, dependency contract, and deterministic path rules.
        reject("no-manifest-project-command", None)
        reject("dep-without-manifest", None, ">'@dep/math/lib.slg':MA\n", explicit=True)
        reject("unknown-field", '{"schema":1,"name":"demo","entry":"src/main.slg","extra":"x"}\n')
        reject("duplicate-field", '{"schema":1,"name":"demo","name":"other","entry":"src/main.slg"}\n')
        reject("wrong-schema", '{"schema":2,"name":"demo","entry":"src/main.slg"}\n')
        reject("invalid-name", '{"schema":1,"name":"Demo","entry":"src/main.slg"}\n')
        reject("parent-entry", '{"schema":1,"name":"demo","entry":"../main.slg"}\n')
        reject("dependency-object-required", '{"schema":1,"name":"demo","entry":"src/main.slg","dependencies":[]}\n')
        reject("parent-dependency-root", '{"schema":1,"name":"demo","entry":"src/main.slg","dependencies":{"math":"../math"}}\n')
        reject("unicode-escape-noncanonical", r'{"schema":1,"name":"de\u006do","entry":"src/main.slg"}' + "\n")
        reject("undeclared-dependency", manifest(), ">'@dep/math/lib.slg':MA\n")
        reject("dependency-exact-suffix", manifest(deps='{"math":"vendor/math"}'), ">'@dep/math/lib':MA\n")

        # 19: canonical escaped solidus remains accepted by both implementations.
        p = base / "escaped-solidus"
        write(p, "slug.json", '{"schema":1,"name":"demo","entry":"src\\/main.slg"}\n')
        write(p, "src/main.slg", "co[7]\n")
        py = run(PYCLI + ["check"], p); na = run([str(native), "check"], p)
        record("escaped-solidus", py.returncode == 0 and na.returncode == 0,
               f"py={py.returncode} na={na.returncode} err={na.stderr!r}")

    if failures:
        print(f"K9E PROJECT MANIFEST FAIL {passed}/{total}", file=sys.stderr)
        for failure in failures:
            print(" - " + failure, file=sys.stderr)
        return 1
    print(f"K9E PROJECT MANIFEST PASS {passed}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

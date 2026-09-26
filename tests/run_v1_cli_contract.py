#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(exe: Path, args: list[str], cwd: Path, env: dict[str, str] | None = None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run([str(exe), *args], cwd=cwd, env=e, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def need(cond: bool, label: str, detail: str = ""):
    if not cond:
        raise AssertionError(f"{label}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ns = ap.parse_args()
    root = Path.cwd().resolve()
    expected_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    expected_language = (root / "LANGUAGE_VERSION").read_text(encoding="utf-8").strip()
    exe = Path(ns.slug)
    if not exe.is_absolute():
        exe = (root / exe).resolve()
    need(exe.is_file(), "native compiler exists", str(exe))

    td = root / "build" / "k9c_cli_contract"
    shutil.rmtree(td, ignore_errors=True)
    td.mkdir(parents=True)
    simple = td / "simple.slg"
    simple.write_text("a:=1;co[a]\n", encoding="utf-8")
    args_src = td / "args.slg"
    args_src.write_text(">'@std/sys':SY\nco[SY.av[]]\n", encoding="utf-8")
    bad = td / "bad.slg"
    bad.write_text("if ? {\n", encoding="utf-8")
    boom = td / "boom.slg"
    boom.write_text("er 'boom'\n", encoding="utf-8")
    comments = td / "comments.slg"
    comments.write_text("## ordinary\n##! keep\na:=1;co[a]\n", encoding="utf-8")

    checks: list[str] = []
    def ok(name: str):
        checks.append(name)
        print(f"PASS {name}")

    p = run(exe, ["--version"], root)
    need(p.returncode == 0 and p.stdout.strip() == expected_version and not p.stderr, "version", repr((p.returncode,p.stdout,p.stderr))); ok("version")
    p = run(exe, ["--language-version"], root)
    need(p.returncode == 0 and p.stdout.strip() == expected_language and not p.stderr, "language version"); ok("language-version")
    p = run(exe, ["--help"], root)
    need(p.returncode == 0 and all(x in p.stdout for x in ("slug check", "slug build", "slug run", "slug fmt", "slug crush", "slug expand")) and not p.stderr, "help"); ok("help")

    p = run(exe, ["check"], root)
    need(p.returncode == 64 and "slug.json" in p.stderr and not p.stdout, "project discovery usage exit", repr((p.returncode,p.stdout,p.stderr))); ok("project-discovery-64")
    p = run(exe, ["check", str(simple)], root)
    need(p.returncode == 0 and not p.stdout and not p.stderr, "silent check"); ok("check-success-silent")
    p = run(exe, ["check", str(bad)], root)
    need(p.returncode == 65 and p.stderr and not p.stdout, "human source error"); ok("source-error-65")
    p = run(exe, ["check", str(bad), "--diagnostic-format", "json"], root)
    need(p.returncode == 65 and not p.stdout, "json source exit")
    lines = [x for x in p.stderr.splitlines() if x.strip()]
    need(len(lines) == 1, "json NDJSON count", repr(lines))
    obj = json.loads(lines[0])
    need(obj.get("schema") == 1 and obj.get("severity") == "error" and obj.get("kind") and obj.get("message") and obj.get("file") == str(bad), "json schema core", repr(obj)); ok("diagnostic-json-schema-1")
    p = run(exe, ["check", str(simple), "--diagnostic-format", "bogus"], root)
    need(p.returncode == 64, "bad diagnostic format"); ok("diagnostic-format-usage")

    out = td / ("simple.exe" if os.name == "nt" else "simple_bin")
    p = run(exe, ["build", str(simple), "-o", str(out)], root)
    need(p.returncode == 0 and not p.stdout and not p.stderr and out.is_file(), "build explicit"); ok("build-explicit-silent")
    p = subprocess.run([str(out.resolve())], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    need(p.returncode == 0 and p.stdout.strip() == "1", "built executable"); ok("built-executable-runs")

    keep = td / ("keep.exe" if os.name == "nt" else "keep")
    p = run(exe, ["build", str(simple), "-o", str(keep), "--keep-c"], root)
    need(p.returncode == 0 and keep.is_file() and Path(str(keep)+".c").is_file(), "keep-c"); ok("keep-c")
    missing = td / ("missing.exe" if os.name == "nt" else "missing")
    p = run(exe, ["build", str(simple), "-o", str(missing), "--cc", "__slug_no_such_cc__"], root)
    need(p.returncode == 69 and not missing.exists(), "host unavailable", repr((p.returncode,p.stderr))); ok("host-unavailable-69")
    p = run(exe, ["build", str(simple), "-o", str(simple)], root)
    need(p.returncode == 64, "build source overwrite"); ok("build-overwrite-safety")

    default_src = td / "default.slg"
    default_src.write_text("co[2]\n", encoding="utf-8")
    default_out = default_src.with_suffix(".exe" if os.name == "nt" else "")
    p = run(exe, ["build", str(default_src)], root)
    need(p.returncode == 0 and default_out.is_file(), "default build output", str(default_out)); ok("build-default-output")

    p = run(exe, ["run", str(args_src), "--", "hello", "world"], root)
    need(p.returncode == 0 and "'hello'" in p.stdout and "'world'" in p.stdout, "run arg forwarding", repr((p.returncode,p.stdout,p.stderr))); ok("run-argument-forwarding")
    p = run(exe, ["run", str(boom)], root)
    need(p.returncode == 66, "run forwards runtime 66", repr((p.returncode,p.stderr))); ok("run-exit-forwarding")
    p = run(exe, ["run", str(bad)], root)
    need(p.returncode == 65, "run preexecution source error"); ok("run-preexecution-65")

    before = simple.read_text(encoding="utf-8")
    p = run(exe, ["fmt", str(simple)], root)
    need(p.returncode == 0 and p.stdout.endswith("\n") and simple.read_text(encoding="utf-8") == before, "fmt stdout/no overwrite"); ok("fmt-stdout-safe")
    p = run(exe, ["fmt", str(simple), "--check"], root)
    need(p.returncode == 65, "fmt check noncanonical"); ok("fmt-check-65")
    p = run(exe, ["fmt", str(simple), "--write"], root)
    need(p.returncode == 0 and not p.stdout and not p.stderr, "fmt write");
    p2 = run(exe, ["fmt", str(simple), "--check"], root)
    need(p2.returncode == 0, "fmt canonical after write"); ok("fmt-write-and-check")
    p = run(exe, ["fmt", str(simple), "--write", "--check"], root)
    need(p.returncode == 64, "fmt mutually exclusive"); ok("fmt-mode-exclusion")
    p = run(exe, ["fmt", str(simple), "-o", str(simple)], root)
    need(p.returncode == 64, "fmt explicit overwrite requires write"); ok("fmt-overwrite-safety")

    comment_before = comments.read_text(encoding="utf-8")
    p = run(exe, ["crush", str(comments)], root)
    crushed = comments.with_suffix(".slgc")
    need(p.returncode == 0 and not p.stdout and not p.stderr and crushed.is_file() and comments.read_text(encoding="utf-8") == comment_before, "crush default")
    ct = crushed.read_text(encoding="utf-8")
    need("ordinary" not in ct and "##! keep" in ct, "crush comment policy", ct); ok("crush-default-preserved-comments")
    p = run(exe, ["expand", str(crushed)], root)
    need(p.returncode == 0 and p.stdout.endswith("\n") and "##! keep" in p.stdout and crushed.read_text(encoding="utf-8") == ct, "expand stdout safe"); ok("expand-stdout-safe")
    expanded = td / "expanded.slg"
    p = run(exe, ["expand", str(crushed), "-o", str(expanded)], root)
    need(p.returncode == 0 and expanded.is_file() and not p.stdout and not p.stderr, "expand output"); ok("expand-output")
    p = run(exe, ["expand", str(crushed), "-o", str(crushed)], root)
    need(p.returncode == 64, "expand overwrite safety"); ok("expand-overwrite-safety")

    print(f"CLI CONTRACT PASS {len(checks)}/{len(checks)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

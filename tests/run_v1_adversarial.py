#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SEED = 0x51A6_1A60
BASE = [
    "a:=1;co[a]\n",
    "~sq x {rv x x *};co[sq[9]]\n",
    "a:=[3,1,2];sl[a];fli x a {co[x]}\n",
    "if?1{co['ok']}ee{co['no']}\n",
    "tr{er'boom'}ca e {co[e.m]}fn{co['done']}\n",
    "'x{1 2 +}y'\n",
]
ALPHABET = "{}[]()?:;#~@!+-*/%^=<>$|'\\\"_abcXYZ019\n €"


def run(exe: Path, args: list[str], cwd: Path, src: str):
    return subprocess.run(
        [str(exe), *args], cwd=cwd, input=src, text=True,
        encoding="utf-8", errors="strict",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )


def mutate(rng: random.Random, s: str, idx: int) -> str:
    # Deterministic property corpus: every family exercises a different malformed-source shape.
    mode = idx % 6
    if not s:
        return "?"
    if mode == 0:  # delete one code point
        p = rng.randrange(len(s))
        return s[:p] + s[p+1:]
    if mode == 1:  # insert punctuation/unicode
        p = rng.randrange(len(s) + 1)
        return s[:p] + rng.choice(ALPHABET) + s[p:]
    if mode == 2:  # replace one code point
        p = rng.randrange(len(s))
        return s[:p] + rng.choice(ALPHABET) + s[p+1:]
    if mode == 3:  # truncate at arbitrary boundary
        return s[:rng.randrange(len(s) + 1)]
    if mode == 4:  # duplicate a short slice
        a = rng.randrange(len(s)); b = min(len(s), a + rng.randrange(1, 5))
        p = rng.randrange(len(s) + 1)
        return s[:p] + s[a:b] + s[p:]
    # delimiter/comment/string stress
    return s + rng.choice(["[", "{", "'", "#*", "##", "€", "\\"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic SLUG v1 malformed-source/adversarial gate")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--cases", type=int, default=64)
    ns = ap.parse_args()
    exe = Path(ns.slug)
    if not exe.is_absolute():
        exe = (ROOT / exe).resolve()
    if not exe.is_file():
        raise SystemExit(f"missing compiler: {exe}")

    rng = random.Random(SEED)
    corpus = []
    for i in range(ns.cases):
        src = BASE[i % len(BASE)]
        # Apply 1..3 deterministic mutations to broaden interactions.
        for j in range(1 + (i % 3)):
            src = mutate(rng, src, i + j)
        corpus.append(src)

    digest = hashlib.sha256("\0".join(corpus).encode("utf-8")).hexdigest()
    valid = invalid = located = unlocated = 0
    with tempfile.TemporaryDirectory(prefix="slug-adversarial-") as td0:
        td = Path(td0)
        logical = td / "mutant.slg"
        logical.write_text("sentinel\n", encoding="utf-8")
        original = logical.read_bytes()
        for i, src in enumerate(corpus):
            a = run(exe, ["tooling-check", str(logical), "--diagnostic-format", "json"], td, src)
            b = run(exe, ["tooling-check", str(logical), "--diagnostic-format", "json"], td, src)
            if (a.returncode, a.stdout, a.stderr) != (b.returncode, b.stdout, b.stderr):
                raise AssertionError(f"nondeterministic tooling-check case {i}")
            if a.returncode == 0:
                valid += 1
            elif a.returncode == 65:
                invalid += 1
            else:
                raise AssertionError(f"unexpected tooling-check rc={a.returncode} case {i}: {a.stderr!r}")

            la = run(exe, ["tooling-locate", str(logical)], td, src)
            lb = run(exe, ["tooling-locate", str(logical)], td, src)
            if (la.returncode, la.stdout, la.stderr) != (lb.returncode, lb.stdout, lb.stderr):
                raise AssertionError(f"nondeterministic tooling-locate case {i}")
            if la.returncode != 0:
                raise AssertionError(f"tooling-locate rc={la.returncode} case {i}: {la.stderr!r}")
            first = la.stdout.splitlines()[:1]
            found = bool(first and first[0] == "1")
            if found: located += 1
            else: unlocated += 1

            if logical.read_bytes() != original:
                raise AssertionError(f"tooling mutated logical source case {i}")
            debris = list(td.glob(".*.slug-lsp-*.slg")) + list(td.glob("*.slug-tmp"))
            if debris:
                raise AssertionError(f"tooling debris case {i}: {debris}")

    print(f"ADVERSARIAL PASS {len(corpus)}/{len(corpus)} seed={SEED} sha256={digest}")
    print(f"  checks: valid={valid} invalid={invalid}; locator: found={located} none={unlocated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

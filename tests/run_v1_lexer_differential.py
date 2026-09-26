from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sluglang.lexer import lex

NATIVE = ROOT / "build" / "v1" / ("lexer_cli.exe" if os.name == "nt" else "lexer_cli")
SOURCE = ROOT / "compiler" / "v1" / "lexer_cli.slg"

CASES = [
    "",
    "a:=1",
    "abcXYZ019",
    " \t\n\r\v\f\x1c\x1d\x1e\x1f a",
    "\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000a",
    "\ufeffa:=1",
    "a\r\nb\rc\nd",
    "## comment",
    "##! preserve",
    "a## tail\nb",
    "a : = 1 ## c i : = stays comment\nb : = 2",
    "#* outer *#a",
    "#*! keep #* nested *# tail *#a",
    "#* a\nb *#c",
    "''",
    "'plain'",
    r"'a\\n\\r\\t\\0\\\\\\\'\\\"\\{\\}'",
    r"'x{1 2 +}y'",
    r"'x{cv['s','{ok}']}y'",
    r"'x{1#* { ignored } *#2+}y'",
    "': = c i / / # # # * remains string'",
    "_x_ _Xx_ _next_",
    "_1_ _currentIndex_ _a1B2_",
    "_left__right_",
    "_a_b_c_",  # retired spelling shape now tokenizes as _a_, b, _c_
    ". .23 23. 23.4 123",
    "<:. ::= !== === <: := == != <= >= ++ -- ^^ ~- ~~ //",
    "< : . : : = ! = = = = = < : : = = = ! = < = > = + + - - ^ ^ ~ - ~ ~ / /",
    "<\n:\n. :\n:\n= !\n=\n= =\n=\n= <\n: :\n= =\n= !\n= <\n= >\n= +\n+ -\n- ^\n^ ~\n- ~\n~ /\n/",
    "{}[](),:;.#~@!?+-*/%^=<>$|`",
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
]

ERROR_CASES = [
    ('"x"', "double-quoted strings"),
    ("#* never", "unterminated block comment"),
    ("'never", "unterminated string"),
    ("'x{1'", "unterminated nested string in interpolation"),
    ("'x\ny'", "physical newline inside string"),
    ("_", "invalid extended identifier"),
    ("_a", "extended identifier"),
    ("_n_e_x_t_", "invalid extended identifier"),
    ("é", "unexpected character"),
    ("\ufeff\ufeffa", "unexpected character"),
]


def build_native() -> None:
    NATIVE.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "slug.py"), "build", str(SOURCE), "-o", str(NATIVE)]
    p = subprocess.run(cmd, cwd=ROOT, text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip() or "failed to build native lexer probe")


def oracle(src: str):
    return [
        (t.kind, t.text.encode("utf-8"), t.start, t.end, t.line, t.column, bool(t.preserve))
        for t in lex(src)
    ]


def _parse_hex_bytes(line: str) -> bytes:
    if not line.startswith("0x"):
        raise ValueError(f"expected byte display, got {line!r}")
    h = line[2:]
    return bytes.fromhex(h) if h else b""


def native(src: str):
    p = subprocess.run([str(NATIVE), src], cwd=ROOT, text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=10)
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip() or f"native lexer rc={p.returncode}")
    lines = p.stdout.splitlines()
    if len(lines) % 7:
        raise RuntimeError(f"native lexer emitted {len(lines)} lines, expected multiple of 7: {p.stdout!r}")
    out = []
    for i in range(0, len(lines), 7):
        kind = lines[i]
        text = _parse_hex_bytes(lines[i + 1])
        start, end, line, col = map(int, lines[i + 2:i + 6])
        raw_p = lines[i + 6]
        preserve = raw_p == "true" or (raw_p not in {"false", ""} and int(raw_p) != 0)
        out.append((kind, text, start, end, line, col, preserve))
    return out


def main() -> int:
    build_native()
    failures = []
    for i, src in enumerate(CASES, 1):
        try:
            want = oracle(src)
        except Exception as e:
            failures.append((i, src, "oracle unexpectedly failed", repr(e), ""))
            continue
        try:
            got = native(src)
        except Exception as e:
            failures.append((i, src, "native failed", repr(want), str(e)))
            continue
        if got != want:
            failures.append((i, src, "mismatch", repr(want), repr(got)))

    offset = len(CASES)
    for j, (src, needle) in enumerate(ERROR_CASES, 1):
        i = offset + j
        try:
            oracle(src)
        except Exception as oe:
            oracle_msg = str(oe)
        else:
            failures.append((i, src, "oracle accepted error case", needle, ""))
            continue
        p = subprocess.run([str(NATIVE), src], cwd=ROOT, text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=10)
        native_msg = (p.stdout + p.stderr).strip()
        if p.returncode == 0:
            failures.append((i, src, "native accepted error case", oracle_msg, native_msg))
        elif needle not in native_msg:
            failures.append((i, src, "native error mismatch", oracle_msg, native_msg))

    total = len(CASES) + len(ERROR_CASES)
    print(f"V1 lexer differential: {total-len(failures)}/{total} matched")
    if failures:
        for row in failures:
            print("\n#%d %r %s\n  oracle: %s\n  native: %s" % row)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

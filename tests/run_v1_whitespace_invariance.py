#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from sluglang.lexer import lex
from sluglang.parser import parse


def sig(source: str):
    """Semantic parser signature; source positions deliberately do not participate."""
    return parse(lex(source), source)


WS_TRANSPARENT_OPS = {'<:.', '::=', '!==', '===', '<:', ':=', '==', '!=', '<=', '>='}


def spaced_ops(source: str, sep: str) -> str:
    """Expand whitespace-transparent composite punctuation only.

    Repeated executable compounds such as ``++`` and ``//`` intentionally remain
    atomic when contiguous because their separated characters can already form valid
    SLUG 1.0 source with a different meaning. The transformation is token-driven, so
    strings/comments are never rewritten.
    """
    toks = [t for t in lex(source) if t.kind == 'OP' and t.text in WS_TRANSPARENT_OPS]
    out = []
    last = 0
    for t in toks:
        out.append(source[last:t.start])
        out.append(sep.join(t.text))
        last = t.end
    out.append(source[last:])
    return ''.join(out)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, encoding='utf-8', errors='strict', stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description='SLUG v1 whitespace-invariance regression gate')
    ap.add_argument('--slug', type=Path, help='optional native compiler candidate')
    a = ap.parse_args()

    # Dense programs exercise every whitespace-transparent structural/comparison
    # composite in real grammar positions. Compound executable operators are covered
    # separately by compatibility tests below.
    corpus = [
        "n:=ci'name? 'co'hello 'n+', from SLUG'+",
        "a:=1;b::=2;?a==1{co[a]}ee{co[b]}",
        "a:=1;?a!=2{co[a]}",
        "?1===1{co1}ee{co0}",
        "?1!==2{co1}",
        "?1<=2{co1};?2>=1{co2}",
    ]

    failures: list[str] = []
    checked = 0
    for src in corpus:
        try:
            want = sig(src)
        except Exception as e:
            failures.append(f'canonical parse failed: {src!r}: {e}')
            continue
        for sep_name, sep in [('space', ' '), ('tab', '\t'), ('newline', '\n')]:
            variant = spaced_ops(src, sep)
            try:
                got = sig(variant)
            except Exception as e:
                failures.append(f'{sep_name} variant failed: {variant!r}: {e}')
                continue
            checked += 1
            if got != want:
                failures.append(f'{sep_name} AST drift:\ncanonical={src!r}\nvariant={variant!r}\nwant={want!r}\ngot={got!r}')

    # The exact public bug report: builtin/reserved two-letter spellings may also have
    # whitespace because lowercase letters are deliberately atomic lexer tokens.
    dense = "n:=ci'name? 'co'hello 'n+', from SLUG'+"
    open_form = "n : = c i 'name? ' c o 'hello ' n + ', from SLUG' +"
    vertical = "n\n:\n=\nc\ni\n'name? '\nc\no\n'hello '\nn\n+\n', from SLUG'\n+"
    for label, src in [('open-form', open_form), ('vertical-form', vertical)]:
        try:
            checked += 1
            if sig(src) != sig(dense):
                failures.append(f'{label} does not match dense program')
        except Exception as e:
            failures.append(f'{label} failed: {e}')

    # Compatibility is stronger than blindly deleting whitespace. In 1.0.0, the
    # separated component punctuation below was already valid source. It must keep its
    # old meaning rather than being greedily fused into ++, --, ^^, ~-, ~~ or //.
    compatibility_pairs = [
        ("co[1 2 3 + +]", ['+', '+']),
        ("co[8 4 2 / /]", ['/', '/']),
        ("co[2 3 2 ^ ^]", ['^', '^']),
        ("co[8 4 2 - -]", ['-', '-']),
    ]
    for src, puncts in compatibility_pairs:
        try:
            toks = lex(src)
            checked += 1
            got_punc = [t.text for t in toks if t.kind == 'PUNC' and t.text in set(puncts)]
            if got_punc[-len(puncts):] != puncts:
                failures.append(f'separated operator compatibility lost: {src!r}: {got_punc!r}')
            sig(src)
        except Exception as e:
            failures.append(f'separated operator compatibility failed: {src!r}: {e}')

    # Conversely, exact contiguous compound operators remain exact tokens.
    for src, op in [("a:=1;a++", '++'), ("a:=1;a--", '--'), ("co[8 4//]", '//')]:
        try:
            toks = lex(src)
            checked += 1
            if op not in [t.text for t in toks if t.kind == 'OP']:
                failures.append(f'exact compound token lost: {src!r} expected {op}')
            sig(src)
        except Exception as e:
            failures.append(f'exact compound compatibility failed: {src!r}: {e}')

    # Source is never globally whitespace-stripped. Text inside strings stays byte-for-byte
    # lexical content, and line comments still end at their physical newline.
    string_src = "co[': = c i # # # * / /']"
    st = lex(string_src)
    checked += 1
    strings = [t.text for t in st if t.kind == 'STRING']
    if strings != ["': = c i # # # * / /'"]:
        failures.append(f'string boundary damaged: {strings!r}')

    comment_src = "a:=1## comment containing : = and c i\nb:=2"
    try:
        ts = lex(comment_src)
        checked += 1
        comments = [t for t in ts if t.kind == 'COMMENT']
        if len(comments) != 1 or 'b:=2' in comments[0].text:
            failures.append(f'line comment swallowed following code: {comments!r}')
        sig(comment_src)
    except Exception as e:
        failures.append(f'comment-safety parse failed: {e}')

    if a.slug:
        slug = a.slug.resolve()
        if not slug.is_file():
            failures.append(f'native compiler does not exist: {slug}')
        else:
            with tempfile.TemporaryDirectory(prefix='slug-whitespace-') as td:
                td = Path(td)
                for idx, src in enumerate((dense, open_form, vertical), 1):
                    p = td / f'case{idx}.slg'
                    p.write_text(src + '\n', encoding='utf-8', newline='\n')
                    q = run([str(slug), 'check', str(p)], cwd=ROOT, timeout=30)
                    checked += 1
                    if q.returncode:
                        failures.append(f'native check failed for case {idx}: {(q.stdout+q.stderr).strip()}')

                # Guard against the tempting but incorrect implementation of deleting
                # whitespace before lexing: comments/strings must retain their boundaries.
                for label, src in [('comment-safety', comment_src), ('string-safety', string_src)]:
                    safe = td / (label + '.slg')
                    safe.write_text(src + '\n', encoding='utf-8', newline='\n')
                    q = run([str(slug), 'check', str(safe)], cwd=ROOT, timeout=30)
                    checked += 1
                    if q.returncode:
                        failures.append(f'native {label} check failed: {(q.stdout+q.stderr).strip()}')

                # Native formatter/crusher/expander must accept the open spelling and
                # produce source that remains accepted by the same compiler.
                p = td / 'open.slg'
                p.write_text(open_form + '\n', encoding='utf-8', newline='\n')
                for cmd, suffix in [('fmt', '.fmt.slg'), ('crush', '.slgc')]:
                    out = td / ('out' + suffix)
                    q = run([str(slug), cmd, str(p), '-o', str(out)], cwd=ROOT, timeout=60)
                    checked += 1
                    if q.returncode:
                        failures.append(f'native {cmd} failed: {(q.stdout+q.stderr).strip()}')
                    elif not out.is_file():
                        failures.append(f'native {cmd} did not create {out}')
                    else:
                        z = run([str(slug), 'check', str(out)], cwd=ROOT, timeout=30)
                        checked += 1
                        if z.returncode:
                            failures.append(f'native {cmd} output does not re-check: {(z.stdout+z.stderr).strip()}')

    print(f'SLUG WHITESPACE INVARIANCE: {checked-len(failures)}/{checked} checks passed')
    if failures:
        for f in failures:
            print('FAIL:', f, file=sys.stderr)
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

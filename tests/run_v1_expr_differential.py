from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from sluglang import ast
from sluglang.lexer import lex
from sluglang.parser import Parser

NATIVE = ROOT / 'build' / 'v1' / ('expr_cli.exe' if __import__('os').name == 'nt' else 'expr_cli')

CASES = [
    # literals, names, decimal hard boundaries
    '0','1','9','10','123','10$','127$','255$','18446744073709551615$','.23','23.','23.4',
    "''", "'x'", "'ab'", 'nn', 'a', '_x_',
    # RPN and unary
    '12+','1 2 +','12+3+','12-','3 -','12*','12/','12%','23^','2 3 - ^',
    "'a' 'b' +", '1 2 + 3 *', '1 2 3 * +',
    # casts
    '@i1','@i|1|','@i8|127$|','@u8|255$|','@u64|18446744073709551615$|',
    '@f64|1.5|', "@s|'abc'|", '@b|0|', '@i|1 2 +|',
    "ty[a]", "cv['i','5']", "@ty[a]b", "t:=ty[a]", "@|t|b",
    # collections
    '[]','[1]','[1,2]','@[1,2]', '[:]', '[1:2]', "['a':1,'b':2]", '@[:]', '@[1:2]',
    '[[1,2],[3,4]]', "['x':[1,2]]",
    # index/slice chains
    'a[0]','[1,2][0]', "'ab'[1]", 'a[0][1]', 'a[:]', 'a[1:]', 'a[:2]',
    'a[1:2]', 'a[::1]', 'a[1::2]', 'a[:2:1]', 'a[1:2:3]', 'a[::1 -]',
    # builtin calls / explicit / forced / ambiguity-sensitive
    'co1','co[1]','!co1','!co[1]','ln[1]','ln[[]]','in1[1]','in[1,[1]]',
    "iv[1,[1:1]]", 'sl[[3,1,2]]',"by['x']",'ci[]','ci[1]','!ci1',
    'in11','in12','co10','co[12+]','ln[1]1+','co in1[1]',
    # assignment expressions and contracts
    'a:=1','a::=1','a:=b:=3','a@i:=1','_x_@u8:=255$','ab:=1','a@i b@u8:=1',
    'a:=@i|1 2 +|','a:=b::=3',
    'a[0]:=1', "m['x']:='v'", 'a[0][1]:=2',
    # Boolean/comparison precedence
    '?1','?!0','?1<2','?1==1','?1!=2','?1<=2','?2>=1','?1+0','?1/0',
    '?1+0/1','?1/0+1','?[1/0]+1','?1==1+0==1','?a:=1','?in1[1]',
    # members / methods (class-aware contexts are supplied by source prefix in program tests;
    # current/self members do not require a declaration)
    '.x','a.x','a.sm[]','a.x.y',
    # composition
    'a[0]1+','[1,2][0]3+','ln[[1,2]]1+','@i|ln[[1,2]]|','7 2 //',
]

INVALID_CASES = [
    # removed hexadecimal source and old root capabilities
    'A$', 'F$', '7F$', 'FF$', '@u64|FFFFFFFFFFFFFFFF$|',
    'av[]', 'pf[]', 'tm[]',
    # nonexistent float widths
    '@f16|1.0|', '@f32|1.0|', '@f128|1.0|',
]


def typevec(types):
    return '[' + ','.join('_' if x is None else x for x in types) + ']'


def fp(x: ast.Expr) -> str:
    if isinstance(x, ast.Literal):
        return f'L({x.kind}:{x.raw})'
    if isinstance(x, ast.Var):
        return f'V({x.name})'
    if isinstance(x, ast.ExtendedName):
        return f'X({x.name})'
    if isinstance(x, ast.DefaultArg):
        return 'D'
    if isinstance(x, ast.Binary):
        return f'B({x.op},{fp(x.left)},{fp(x.right)})'
    if isinstance(x, ast.Unary):
        return f'U({x.op},{fp(x.value)})'
    if isinstance(x, ast.Compare):
        return f'C({x.op},{fp(x.left)},{fp(x.right)})'
    if isinstance(x, ast.LogicBinary):
        return f'G({x.op},{fp(x.left)},{fp(x.right)})'
    if isinstance(x, ast.BoolExpr):
        return f'Q({fp(x.value)})'
    if isinstance(x, ast.LogicNot):
        return f'N({fp(x.value)})'
    if isinstance(x, ast.Cast):
        return f'T({x.type_code},{fp(x.value)})'
    if isinstance(x, ast.DynamicCast):
        return f'DT({fp(x.type_expr)},{fp(x.value)})'
    if isinstance(x, ast.Call):
        return f"F({x.name},[{','.join(fp(a) for a in x.args)}])"
    if isinstance(x, ast.ClassCall):
        return f"CC({x.name},[{','.join(fp(a) for a in x.args)}])"
    if isinstance(x, ast.MemberExpr):
        base = '_' if x.base is None else fp(x.base)
        cls = '_' if x.class_name is None else x.class_name
        return f"MB({x.name},{base},{cls},{'S' if x.static else 'I'})"
    if isinstance(x, ast.MethodCall):
        recv = '_' if x.receiver is None else fp(x.receiver)
        cls = '_' if x.class_name is None else x.class_name
        return f"MC({x.name},[{','.join(fp(a) for a in x.args)}],{recv},{cls},{'S' if x.static else 'I'},{'U' if x.super_call else 'N'})"
    if isinstance(x, ast.CallableInvoke):
        return f"I({fp(x.callee)},[{','.join(fp(a) for a in x.args)}])"
    if isinstance(x, ast.ListLiteral):
        return ('Z' if x.frozen else 'A') + '[' + ','.join(fp(a) for a in x.items) + ']'
    if isinstance(x, ast.MapLiteral):
        return ('Y' if x.frozen else 'M') + '[' + ','.join(f'{fp(k)}:{fp(v)}' for k,v in x.entries) + ']'
    if isinstance(x, ast.IndexExpr):
        return f'J({fp(x.base)},{fp(x.index)})'
    if isinstance(x, ast.SliceExpr):
        part = lambda y: '_' if y is None else fp(y)
        return f'S({fp(x.base)},{part(x.start)},{part(x.stop)},{part(x.step)})'
    if isinstance(x, ast.SetIndexExpr):
        return f'SI({fp(x.target)},{fp(x.value)})'
    if isinstance(x, ast.SetMemberExpr):
        return f"SM({fp(x.target)},{fp(x.value)},{'I' if x.immutable else 'M'})"
    if isinstance(x, ast.AssignExpr):
        targets = []
        for n in x.targets:
            if len(n) == 1 and 'a' <= n <= 'z':
                targets.append(f'V({n})')
            else:
                targets.append(f'X({n})')
        return f"E({x.op},[{','.join(targets)}],{typevec(x.target_types)},{fp(x.value)})"
    raise TypeError(f'unsupported expression fingerprint: {type(x).__name__}: {x!r}')


def oracle(src: str) -> str:
    tokens = lex(src)
    p = Parser(tokens, src)
    complete = [c for c in p.expr_candidates(0) if tokens[c.end].kind == 'EOF']
    if not complete:
        raise RuntimeError('oracle incomplete')
    score = min(c.score for c in complete)
    best = p._dedupe_expr(c for c in complete if c.score == score)
    if len(best) != 1:
        raise RuntimeError(f'oracle ambiguous cheapest: {len(best)}')
    return fp(best[0].expr)


def native(src: str) -> str:
    p = subprocess.run([str(NATIVE), src], cwd=ROOT, text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=10)
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip() or f'native rc={p.returncode}')
    return p.stdout.strip()


def main() -> int:
    if not NATIVE.exists():
        print(f'missing native probe: {NATIVE}', file=sys.stderr)
        return 2
    bad = []
    valid = 0
    for i, src in enumerate(CASES, 1):
        try:
            want = oracle(src)
        except Exception as e:
            bad.append((i, src, 'ORACLE-ERROR', str(e), ''))
            continue
        valid += 1
        try:
            got = native(src)
        except Exception as e:
            bad.append((i, src, 'NATIVE-ERROR', want, str(e)))
            continue
        if got != want:
            bad.append((i, src, 'MISMATCH', want, got))
    mismatched = len([b for b in bad if b[2] != 'ORACLE-ERROR'])
    reject_bad = []
    for src in INVALID_CASES:
        oracle_rejected = False
        try:
            oracle(src)
        except Exception:
            oracle_rejected = True
        p = subprocess.run([str(NATIVE), src], cwd=ROOT, text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=10)
        native_rejected = p.returncode != 0
        if not (oracle_rejected and native_rejected):
            reject_bad.append((src, oracle_rejected, native_rejected, p.stdout.strip(), p.stderr.strip()))
    print(f'V1 expression differential: {valid-mismatched}/{valid} matched; corpus={len(CASES)}; rejects={len(INVALID_CASES)-len(reject_bad)}/{len(INVALID_CASES)}')
    if bad or reject_bad:
        print(f'failures={len(bad)+len(reject_bad)}')
        for row in bad:
            print('\n#%d %r %s\n  oracle: %s\n  native: %s' % row)
        for src, orej, nrej, out, err in reject_bad:
            print(f'\nREJECT {src!r}\n  oracle_rejected={orej} native_rejected={nrej}\n  stdout={out!r}\n  stderr={err!r}')
        return 1
    print('PASS')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

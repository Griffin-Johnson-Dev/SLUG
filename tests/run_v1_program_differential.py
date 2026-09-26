from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))
if str(ROOT / 'tests') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tests'))

from sluglang import ast
from sluglang.lexer import lex
from sluglang.parser import parse
from run_v1_expr_differential import fp, typevec

NATIVE = ROOT / 'build' / 'v1' / ('program_cli.exe' if __import__('os').name == 'nt' else 'program_cli')

CASES = [
    # definitions / nearest assignment / contracts
    'a:=1', 'a::=1', '_x_:=1', 'a@i:=1', '_x_@u8:=255$',
    'a=2', '_x_=3', 'a:=1;a=2', 'a:=b:=3',
    # mutation
    'a++', 'a--', '_x_++', '_x_--', 'a:=1;a++;a--',
    # indexed writes: '=' statement-only, ':=' value-producing expression
    'a[0]=9', 'a[0][1]=2', "m['name']:='slug'", 'a[0]:=a', 'a[0][1]:=2',
    # effectful expression statements
    'co[1]', "co['x']", 'co[1 2 +]', 'ci[]', "ci['name?']",
    'a:=ci[]', 'a:=@i\'123\'', "a:=@f'1.25'", 'a:=@ty[b]c',
    # return / raise
    'rv', 'rv 1', 'rv a', 'rv a b', 'rv 1 2 +', "er'bad'", "er 'bad'",
    # control-transfer tokens (parser-only; semantic loop/function legality is later)
    'bl', 'cl',
    # comments / imports
    '##! hi', "#* plain *#", ">'x.slg'", ">'lib/a.slg':AB", ">'x.slg':_mod_",
    # statement boundaries and mixed programs
    'a:=1;b=2', 'a:=1;b=2;co[a]', 'a:=1;;;b=2;;co[b]',
    "##! p\na:=1\nco[a]", ">'x.slg';a:=1;co[a]",
    'a:=1\na++\nco[a]',
    # expression ambiguity exercised as statements
    'co[in1[1]]', 'co[ln[[1,2]]1+]', 'a:=in1[1]',
    "a:=cv['i','123']", "a:=ty[1]", "a:=@|ty[1]|'12'",
    # conditionals / chained tails / nested blocks / while (prefer dense spellings)
    '?1{co1}', 'if?1{co1}', '?0{co1}ee{co2}',
    'if?0{co1}ei?1{co2}ee{co3}', 'if?0{co1}ei?0{co2}ei?1{co3}',
    '?1{a:=1;coa}', '?1{?0{co1}ee{co2}}',
    'a:=1? a==1 {coa}ee{co0}', 'if?[1==1]+[2>1]{co1}',
    'wl?0{co1}', 'wl?1{bl}', 'a:=3;wl?a>0{a--;?a==1{bl}}',
    'wl?1{?0{cl}ee{bl}}', '~ab x{?x{rvx}ee{rv0}};ab1',
    # fl repeat / foreach / range / iterable slices (dense spellings first)
    'fl3{co1}', 'fl?1{co1}', 'fl10${a:=1}', 'a:=0;fl3{a++};coa',
    'fli0$5{coi}', 'fli0$5{?i==2{cl}coi}',
    'a:=[1,2,3];flia{coi}', "s:='abc';flcs{coc}",
    'a:=[1,2,3,4,5];flia1$4{coi}',
    'a:=[1,2,3,4,5];flia0$5$2{coi}',
    'fl_i_0$5{co_i_}', 'fl2{fl3{co1}}',
    'a:=[1,2,3];flia{?i==2{bl}}',
    # try / catch / finally exception structure
    "tr{er'bad'}cae{coe}fn{co'fin'}", "tr{er'x'}ca{co1}",
    "tr{er'x'}fn{co'fin'}", "tr{}ca{}", "tr{}ca_e_{}fn{}",
    "tr{tr{er'x'}fn{co'i'}}cae{coe}fn{co'o'}",
    "~ab{tr{rv10$}fn{co'fin'}};ab", "fl3{tr{bl}fn{co'f'}}",
    "wl?1{tr{cl}fn{co'g'}}",
    # named function declarations / prepass / nested body sequencing
    '~ab x{rvx}', '~ab@i x@i y@i {rvxy+}', '~ad x=1 y=2 {rvxy+}',
    '~sp[@i,@s]x {rvx @sx}', '~va[x] {rvln[x]}', '~vb x[y] {rvxln[y]+}',
    '-~ab x{rvx}', '~~ab x{rvx}', '~np{rv}', '~mr x{rvx x1+}',
    '~aa x{rvaa[x]}', '~aa x{rvbb[x]}~bb x{rvx}',
    '~ad x=1 y=2 {rvxy+};coad', '~ab x=@i\'12\' {rvx}',
    # denser/default/forward/variadic function coverage
    '~ad x=1 y=2{rvxy+};coad3', '~ab x y{rvxy+};coab12',
    '~ab@i x@i=1{rvx};coab', 'coab1;~ab x{rvx}', '~np{rv};np',
    '~ad x=1 y=2{rvxy+};ad[xx,2]', '~ad x=1 y=2{rvxy+};ad[1,xx]',
    '~va[x]{rvln[x]};va[1,2,3]', '~vb x[y]{rvxln[y]+};vb[1,2,3]',
    "~ab _long_='x'{rv_long_};ab['y']", '~ab x=@i\'12\'{rvx};coab',
    '~ab[@i,@s]x{rvx @sx};ab[1]', '-~ab x{rvx};ab[1]',
    '~~ab x{rvx};ab[1]', '~ab x{a:=x;a++;rv a};ab[1]',
    # minimal classes: empty bodies + constructor signatures + class/hex ambiguity
    '#AB{}', '#ABx{}', '-#ABx{}', '#AB x=1{}',
    '#ABx{};a:=AB10$', '#ABx{};a:=AB[10$]', '#AB x=1{};a:=AB',
    '#ABx{};a:=AB1;coa.x', '#AB{};a:=AB[];a.sm[]', '#AB{};a:=AB[];coa.x.y',
]

INVALID_CASES = [
    # removed v0.x lexical forms
    'a:=A$',
    'a:=FF$',
    '//! legacy comment',
    '/* legacy block comment */',
    # Variadics require explicit argument packs and must never regain dense inference.
    '~va[x]{rvln[x]};cova',
    '~va[x]{rvln[x]};co[va]',
    '~va[x]{rvln[x]};va1',
    '~vb x[y]{rvxln[y]+};vb1',
    # orphan / malformed control tails must not become standalone statements
    'ei?1{co1}',
    'ee{co1}',
    'wl1{co1}',
    'if1{co1}',
    # malformed loop forms
    'fl{co1}',
    'fli0$5$1$2$3{coi}',
    # malformed/orphan exception structures
    "tr{co1}",
    "cae{co1}",
    "fn{co1}",
    "trco1",
    "tr{}cae",
    "tr{}fn",
    "tr{}caAB{}",
    'a[:]=1', 'a[0]::=1', 'ab[0]=1',
    # malformed minimal-class forms
    '#AB[x]{}', '#A{}', '#AB@i x{}', '#ABx{};a:=AB',
]



def name_fp(n: str) -> str:
    return f'V({n})' if len(n) == 1 and 'a' <= n <= 'z' else f'X({n})'


def stmt_fp(x: ast.Stmt) -> str:
    if isinstance(x, ast.CommentStmt):
        return f'K({x.text})'
    if isinstance(x, ast.ImportStmt):
        return f"P({x.path},{'_' if x.alias is None else x.alias})"
    if isinstance(x, ast.BreakStmt):
        return 'BR'
    if isinstance(x, ast.ContinueStmt):
        return 'CT'
    if isinstance(x, ast.ReturnStmt):
        return 'R[' + ','.join(fp(v) for v in x.values) + ']'
    if isinstance(x, ast.RaiseStmt):
        return f'H({fp(x.value)})'
    if isinstance(x, ast.AssignStmt):
        targets = '[' + ','.join(name_fp(n) for n in x.targets) + ']'
        types = typevec(x.target_types)
        return f'W({targets},{types},{fp(x.value)})'
    if isinstance(x, ast.MutateStmt):
        return f'U({x.op},{fp(x.target)})'
    if isinstance(x, ast.SetIndexStmt):
        return f'WI({fp(x.target)},{fp(x.value)})'
    if isinstance(x, ast.ExprStmt):
        return f'E({fp(x.expr)})'
    if isinstance(x, ast.IfStmt):
        elifs = '[' + ','.join(
            '(' + fp(c) + ',[' + ','.join(stmt_fp(s) for s in b) + '])'
            for c, b in x.elifs
        ) + ']'
        eb = '_' if x.else_body is None else '[' + ','.join(stmt_fp(s) for s in x.else_body) + ']'
        body = '[' + ','.join(stmt_fp(s) for s in x.body) + ']'
        return f'IF({fp(x.condition)},{body},{elifs},{eb})'
    if isinstance(x, ast.WhileStmt):
        body = '[' + ','.join(stmt_fp(s) for s in x.body) + ']'
        return f'WL({fp(x.condition)},{body})'
    if isinstance(x, ast.TryStmt):
        body = '[' + ','.join(stmt_fp(s) for s in x.body) + ']'
        cname = '_' if x.catch_name is None else x.catch_name
        cb = '_' if x.catch_body is None else '[' + ','.join(stmt_fp(s) for s in x.catch_body) + ']'
        fb = '_' if x.finally_body is None else '[' + ','.join(stmt_fp(s) for s in x.finally_body) + ']'
        return f'TR({body},{cname},{cb},{fb})'
    if isinstance(x, ast.ForStmt):
        def ef(v):
            return '_' if v is None else fp(v)
        var = '_' if x.var is None else x.var
        body = '[' + ','.join(stmt_fp(s) for s in x.body) + ']'
        return f'FL({x.kind},{var},{ef(x.source)},{ef(x.start)},{ef(x.stop)},{ef(x.step)},{body})'
    if isinstance(x, ast.ClassDecl):
        params = '[' + ','.join(
            'P(' + p.name + ':' + ('_' if p.type_code is None else p.type_code) + ':'
            + ('_' if p.default is None else fp(p.default)) + ')'
            for p in x.params
        ) + ']'
        body = '[' + ','.join(stmt_fp(s) for s in x.body) + ']'
        return f"CL({x.name},{'P' if x.private else 'U'},{params},{body})"
    if isinstance(x, ast.FunctionDecl):
        ret = '_' if x.return_types is None else '[' + ','.join(x.return_types) + ']'
        params = '[' + ','.join(
            'P(' + p.name + ':' + ('_' if p.type_code is None else p.type_code) + ':'
            + ('_' if p.default is None else fp(p.default)) + ')'
            for p in x.params
        ) + ']'
        var = '_' if x.variadic is None else x.variadic
        body = '[' + ','.join(stmt_fp(s) for s in x.body) + ']'
        return f"FN({x.name},{'S' if x.static else 'I'},{'P' if x.private else 'U'},{ret},{params},{var},{body})"
    raise TypeError(f'unsupported statement fingerprint: {type(x).__name__}: {x!r}')


def oracle(src: str) -> str:
    p = parse(lex(src), src)
    return '[' + ','.join(stmt_fp(x) for x in p.statements) + ']'


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
    print(f'V1 program differential: {valid-mismatched}/{valid} matched; valid-corpus={len(CASES)}; rejects={len(INVALID_CASES)-len(reject_bad)}/{len(INVALID_CASES)}')
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

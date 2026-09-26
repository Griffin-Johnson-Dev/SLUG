from __future__ import annotations

from dataclasses import dataclass, fields
import gc
import heapq
import itertools
import math
import sys
from typing import Iterable

from . import ast
from .diagnostics import AmbiguityError, ParseError, Span
from .symbols import CallableSig, ClassSig, MethodSig, Symbols
from .tokens import Token


@dataclass(frozen=True, slots=True)
class ExprCand:
    expr: ast.Expr
    end: int
    score: int = 0


@dataclass(frozen=True, slots=True)
class StmtCand:
    stmt: ast.Stmt
    end: int
    score: int = 0


@dataclass(frozen=True, slots=True)
class SeqCand:
    statements: tuple[ast.Stmt, ...]
    end: int
    score: int = 0


_BINARY = {"+", "-", "*", "/", "//", "%", "^"}
_RESERVED_PAIRS = {"rv", "lb", "if", "ei", "ee", "fl", "wl", "bl", "cl", "tr", "ca", "fn", "er", "nn"}


class Parser:
    def __init__(self, tokens: list[Token], source: str = "", symbols: Symbols | None = None, modules: dict[str, Symbols] | None = None):
        self.tokens = tokens
        self.source = source
        self.symbols = Symbols.core()
        if symbols is not None:
            self.symbols.callables.update(symbols.callables)
            self.symbols.classes.update(symbols.classes)
            self.symbols.variables.update(symbols.variables)
            self.symbols.interfaces.update(symbols.interfaces)
        self.modules = dict(modules or {})
        self.method_sigs: dict[str, list[MethodSig]] = {}
        for syms in (self.symbols, *self.modules.values()):
            for cls in syms.classes.values():
                for method in cls.methods:
                    self.method_sigs.setdefault(method.name, []).append(method)
            for interface in syms.interfaces.values():
                for method in interface.methods:
                    self.method_sigs.setdefault(method.name, []).append(method)
        self._expr_cache: dict[int, tuple[ExprCand, ...]] = {}
        self._seq_cache: dict[tuple[int, str | None], tuple[SeqCand, ...]] = {}
        self._fp_cache: dict[int, tuple[ast.Node, object]] = {}
        # Active namespaces are compile-time lexical context.  They are derived from
        # hard `<:` directives before ambiguity exploration, so expression memoization
        # can remain keyed only by token position: every position has exactly one
        # lexically active namespace regardless of which AST candidate reaches it.
        self._namespace_at: list[str | None] = [None] * len(tokens)
        self._namespace_tail_dots: set[int] = set()
        self._prepass_namespaces()
        self._prepass_symbols()


    def _module_alias_at(self, pos: int) -> tuple[str, int] | None:
        """Parse exactly one legal module-alias atom.

        Module aliases intentionally share SLUG's dense symbol shapes: one lowercase
        letter, one two-uppercase symbol, or an extended identifier.  Exactly two
        lowercase letters are *not* an alias atom; those remain callable spelling.
        """
        if self._is_lower(pos):
            return self._text(pos), pos + 1
        if self.tokens[pos].kind == "EXT":
            return self._text(pos), pos + 1
        if self._is_upper(pos) and self._is_upper(pos + 1):
            return self._text(pos) + self._text(pos + 1), pos + 2
        return None

    def _namespace_selector_at(self, pos: int) -> tuple[str | None, int] | None:
        if self._text(pos) == "<:.":
            return None, pos + 1
        if self._text(pos) != "<:":
            return None
        alias = self._module_alias_at(pos + 1)
        if alias is None:
            return None
        return alias

    def _prepass_namespaces(self) -> None:
        """Assign a lexical active namespace to every token position.

        `<:` is a hard compile-time directive, and every executable `{}` already
        creates lexical scope in SLUG.  Therefore namespace context can be computed
        purely from the token stream: entering a block inherits the current namespace;
        leaving it restores the previous one.  This avoids making the ambiguity parser
        probabilistically carry namespace state.
        """
        current: str | None = None
        stack: list[str | None] = []
        i = 0
        n = len(self.tokens)
        while i < n:
            self._namespace_at[i] = current
            text = self._text(i)
            if text == "{":
                stack.append(current)
                i += 1
                continue
            if text == "}":
                current = stack.pop() if stack else None
                i += 1
                continue
            selector = self._namespace_selector_at(i)
            if selector is not None:
                alias, end = selector
                # Selector tokens themselves live in the preceding context; source
                # immediately after the selector lives in the newly selected context.
                for j in range(i + 1, min(end, n)):
                    self._namespace_at[j] = current
                current = alias
                if alias is not None and self._text(end) == ".":
                    # `<:MA.ma` means select MA, then immediately resolve `.ma` from
                    # MA.  This one dot is not current-instance member syntax.
                    self._namespace_tail_dots.add(end)
                i = end
                continue
            i += 1

    def _active_namespace(self, pos: int) -> str | None:
        if 0 <= pos < len(self._namespace_at):
            return self._namespace_at[pos]
        return None

    def _active_module_symbols(self, pos: int) -> tuple[str, Symbols] | None:
        alias = self._active_namespace(pos)
        if alias is None:
            return None
        symbols = self.modules.get(alias)
        if symbols is None:
            return None
        return alias, symbols

    def _resolved_callable(self, pos: int, name: str) -> tuple[CallableSig | None, str | None]:
        active = self._active_module_symbols(pos)
        root = self.symbols.callables.get(name)
        if active is not None:
            alias, symbols = active
            scoped = symbols.callables.get(name)
            if scoped is not None and root is not None:
                raise AmbiguityError(
                    f"bare callable {name} exists in active namespace {alias} and root; qualify it or use ` root escape",
                    span=self._span(self.tokens[pos]),
                )
            if scoped is not None:
                return scoped, alias
        return root, None

    def _resolved_class(self, pos: int, name: str) -> tuple[ClassSig | None, str | None]:
        active = self._active_module_symbols(pos)
        root = self.symbols.classes.get(name)
        if active is not None:
            alias, symbols = active
            scoped = symbols.classes.get(name)
            if scoped is not None and root is not None:
                raise AmbiguityError(
                    f"bare class {name} exists in active namespace {alias} and root; qualify it or use ` root escape",
                    span=self._span(self.tokens[pos]),
                )
            if scoped is not None:
                return scoped, alias
        return root, None

    def _interface_ref_at(self, pos: int) -> tuple[str, int] | None:
        """Parse one interface reference used after ':' in class/trait headers.

        Local/direct imports use ``IF``. Aliased modules use ``MA.IF`` (or any legal
        alias atom), and an active namespace lets the imported interface be written
        bare while preserving its provider alias in the AST for linking.
        """
        alias_atom = self._module_alias_at(pos)
        if alias_atom is not None:
            alias, end = alias_atom
            if self._text(end) == "." and self._is_upper(end + 1) and self._is_upper(end + 2):
                name = self._text(end + 1) + self._text(end + 2)
                symbols = self.modules.get(alias)
                if symbols is not None and name in symbols.interfaces:
                    return f"{alias}.{name}", end + 3
                return None
        if self._is_upper(pos) and self._is_upper(pos + 1):
            name = self._text(pos) + self._text(pos + 1)
            active = self._active_module_symbols(pos)
            if active is not None and name in active[1].interfaces:
                return f"{active[0]}.{name}", pos + 2
            return name, pos + 2
        return None

    def _prepass_symbols(self) -> None:
        i = 0
        while i < len(self.tokens) - 1:
            if self._text(i) == "-" and self._text(i + 1) in {"#", "~", "~~"}:
                i += 1
            if self._text(i) == "#" and self._text(i + 1) != "?" and self._is_upper(i + 1) and self._is_upper(i + 2):
                name = self._text(i + 1) + self._text(i + 2)
                min_a, max_a = self._rough_class_arity(i + 3)
                self.symbols.classes[name] = ClassSig(name, min_a, max_a)
                i += 3
                continue
            if self._text(i) in {"~", "~~"}:
                j = i + 1
                if self._is_lower(j) and self._is_lower(j + 1):
                    name = self._text(j) + self._text(j + 1)
                    header_pos = j + 2
                    header_pos = self._rough_skip_return_annotation(header_pos)
                    min_a, max_a = self._rough_function_arity(header_pos)
                    sig = CallableSig(name, min_a, max_a, None, False)
                    self.symbols.callables[name] = sig
                    self.method_sigs.setdefault(name, []).append(MethodSig(name, min_a, max_a, self._text(i) == "~~", False))
                    i = j + 2
                    continue
            i += 1

    def _rough_skip_return_annotation(self, pos: int) -> int:
        if self._text(pos) == "@":
            return self._skip_type_code(pos)
        if self._text(pos) == "[" and self._text(pos + 1) == "@":
            i = pos + 1
            while self._text(i) == "@":
                i = self._skip_type_code(i)
                if self._text(i) == ",":
                    i += 1
                    continue
                break
            if self._text(i) == "]":
                return i + 1
        return pos

    def _rough_skip_default(self, pos: int) -> int:
        """Skip the bootstrap subset permitted in parameter defaults.

        Defaults in v0.0.8 are intentionally kept to a single compact expression atom
        (literals, null, casted atom, list/map literal, or a single variable). The full
        expression parser still builds the real AST later; this prepass only needs arity.
        """
        i = pos
        if self._text(i) == "@" and self._text(i + 1) != "[":
            i = self._skip_type_code(i)
            return self._rough_skip_default(i)
        if self.tokens[i].kind in {"STRING", "FLOAT", "EXT"}:
            return i + 1
        if self._pair(i) == "nn":
            return i + 2
        terminated = self._scan_decimal_terminated(i)
        if terminated:
            return terminated[1]
        if self.tokens[i].kind == "DIGIT":
            while self.tokens[i].kind == "DIGIT":
                i += 1
            return i
        if self._is_lower(i):
            return i + 1
        if self._text(i) in {"[", "@"} and (self._text(i) == "[" or self._text(i + 1) == "["):
            # Conservative balanced-bracket skip for literal defaults.
            if self._text(i) == "@":
                i += 1
            depth = 0
            while i < len(self.tokens):
                if self._text(i) == "[": depth += 1
                elif self._text(i) == "]":
                    depth -= 1
                    if depth == 0: return i + 1
                i += 1
        return pos

    def _rough_function_arity(self, pos: int) -> tuple[int, int | None]:
        required = 0
        total = 0
        i = pos
        saw_default = False
        while i < len(self.tokens):
            if self._text(i) == "{":
                return required, total
            # trailing [x] means variadic capture; inferred calls are disabled later.
            if self._text(i) == "[" and (self._is_lower(i + 1) or self.tokens[i + 1].kind == "EXT") and self._text(i + 2) == "]":
                return required, None
            if not (self._is_lower(i) or self.tokens[i].kind == "EXT"):
                i += 1
                continue
            total += 1
            i += 1
            if self._text(i) == "@":
                i = self._skip_type_code(i)
            if self._text(i) == "=":
                saw_default = True
                j = self._rough_skip_default(i + 1)
                if j == i + 1:
                    # If the prepass cannot prove the default extent, conservatively
                    # stop at this parameter. The full declaration parser diagnoses it.
                    return required, total
                i = j
            else:
                if saw_default:
                    # Required-after-default is rejected by declaration semantics; keep
                    # parsing deterministic by treating it as required here.
                    required += 1
                else:
                    required += 1
        return required, total

    def _rough_class_arity(self, pos: int) -> tuple[int, int]:
        """Conservative constructor arity scan, including defaulted parameters."""
        required = 0
        total = 0
        i = pos
        saw_default = False
        # Skip an optional inheritance header if the caller starts before it.
        if self._text(i) == "<" and self._is_upper(i + 1) and self._is_upper(i + 2):
            i += 3
        while i < len(self.tokens):
            if self._text(i) == "{":
                break
            if not (self._is_lower(i) or self.tokens[i].kind == "EXT"):
                i += 1
                continue
            total += 1
            i += 1
            if self._text(i) == "@":
                i = self._skip_type_code(i)
            if self._text(i) == "=":
                saw_default = True
                j = self._rough_skip_default(i + 1)
                i = j if j > i + 1 else i + 1
            else:
                required += 1
                if saw_default:
                    # Full semantics rejects required-after-default; preserving the
                    # required count keeps prepass call parsing deterministic.
                    pass
        return required, total

    def parse(self) -> ast.Program:
        # Cyclic-GC scheduling is handled by the module-level parse() wrapper.  Doing
        # it here is subtly wrong: while this method is executing, `self` still keeps
        # the entire candidate graph reachable, so an explicit gc.collect() can only
        # traverse that graph, not reclaim it.
        paths = self._parse_seq(0, stop=None)
        complete = [p for p in paths if self.tokens[p.end].kind == "EOF"]
        if not complete:
            tok = self.tokens[0] if self.tokens else Token("EOF", "", 0, 0, 1, 1)
            raise ParseError("source does not form a complete SLUG program", span=self._span(tok))
        best_score = min(p.score for p in complete)
        best = self._dedupe_seq([p for p in complete if p.score == best_score])
        if len(best) > 1:
            raise AmbiguityError(
                f"program has {len(best)} equally preferred parses; add the smallest explicit disambiguator",
                span=self._span(self.tokens[0]),
            )
        return ast.Program(best[0].statements)

    def _parse_seq(self, pos: int, stop: str | None) -> tuple[SeqCand, ...]:
        """Parse a statement sequence without recursing once per statement.

        Sequence parsing is a forward DAG: every statement candidate advances to a later
        token position.  Older bootstrap revisions expressed that DAG with Python
        recursion, which made an otherwise ordinary ~1000-statement source file hit the
        host recursion limit.  The explicit post-order work stack below preserves the
        same candidate ordering, memoization and scoring while making flat program size
        independent of Python's call-stack depth. Candidate search is not truncated by
        a fixed beam: all semantically non-dominated paths remain available.
        """
        root = (pos, stop)
        cached = self._seq_cache.get(root)
        if cached is not None:
            return cached

        pending: dict[tuple[int, str | None], tuple[tuple[StmtCand, ...], tuple[tuple[int, str | None], ...]]] = {}
        stack: list[tuple[int, str | None]] = [root]

        while stack:
            key = stack[-1]
            if key in self._seq_cache:
                stack.pop()
                continue

            cur, cur_stop = key
            # Explicit boundaries are syntax, not statements.  Preserve cache entries
            # for the original position so callers that land on the same boundary do
            # not have to normalize it repeatedly.
            norm = cur
            while self._text(norm) == ";":
                norm += 1
            if norm != cur:
                dep = (norm, cur_stop)
                cached_dep = self._seq_cache.get(dep)
                if cached_dep is not None:
                    self._seq_cache[key] = cached_dep
                    stack.pop()
                else:
                    stack.append(dep)
                continue

            if cur_stop is not None and self._text(norm) == cur_stop:
                self._seq_cache[key] = (SeqCand((), norm, 0),)
                stack.pop()
                continue
            if self.tokens[norm].kind == "EOF":
                self._seq_cache[key] = (SeqCand((), norm, 0),) if cur_stop is None else ()
                stack.pop()
                continue

            frame = pending.get(key)
            if frame is None:
                stmts = self._stmt_candidates(norm)
                deps: list[tuple[int, str | None]] = []
                filtered: list[StmtCand] = []
                for sc in stmts:
                    next_pos = sc.end
                    # A semicolon, when present, is a hard boundary consumed by the
                    # sequence parser.
                    if self._text(next_pos) == ";":
                        next_pos += 1
                    # A non-advancing candidate would form a cycle in the sequence DAG
                    # and can never contribute to a complete parse.
                    if next_pos <= norm:
                        continue
                    filtered.append(sc)
                    deps.append((next_pos, cur_stop))
                frame = (tuple(filtered), tuple(deps))
                pending[key] = frame

            stmts, deps = frame
            missing = next((dep for dep in deps if dep not in self._seq_cache), None)
            if missing is not None:
                stack.append(missing)
                continue

            # Each dependency cache is itself score-ranked. Merge the cross-branch
            # products lazily rather than materializing every statement-candidate x
            # rest-path combination at once. Unlike the historical beam, this drains
            # the heap completely, so there is no arbitrary parse-count cutoff.
            heap: list[tuple[int, int, StmtCand, tuple[SeqCand, ...], int]] = []
            serial = itertools.count()
            for sc, dep in zip(stmts, deps):
                rests = self._seq_cache.get(dep, ())
                if rests:
                    r0 = rests[0]
                    heapq.heappush(heap, (sc.score + r0.score, next(serial), sc, rests, 0))

            # Rest candidates are already deduplicated inside their dependency cache.
            # Pairing the first-statement fingerprint with the exact cached rest path
            # is therefore a compact semantic sequence identity; rebuilding a full
            # N-statement fingerprint here made long torture programs quadratic.
            chosen: dict[tuple[object, int], SeqCand] = {}
            while heap:
                score, _ord, sc, rests, ri = heapq.heappop(heap)
                rest = rests[ri]
                cand = SeqCand((sc.stmt,) + rest.statements, rest.end, score)
                ckey = (self._fp(sc.stmt), id(rest))
                if ckey not in chosen:
                    chosen[ckey] = cand
                ni = ri + 1
                if ni < len(rests):
                    nr = rests[ni]
                    heapq.heappush(heap, (sc.score + nr.score, next(serial), sc, rests, ni))
            ranked = sorted(chosen.values(), key=lambda x: (x.score, -x.end))
            self._seq_cache[key] = tuple(ranked)
            pending.pop(key, None)
            stack.pop()

        return self._seq_cache[root]

    def _stmt_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        tok = self.tokens[pos]
        if tok.kind == "COMMENT":
            return (StmtCand(ast.CommentStmt(tok.text, tok.preserve), pos + 1, 0),)

        # Compile-time module import. `>'path'` imports public names directly;
        # `>'path':m`, `:'MA'`-style two-uppercase aliases (without quotes), and
        # extended aliases bind the module behind a namespace symbol. Two lowercase
        # letters are never consumed as one alias because that spelling is callable.
        if self._text(pos) == ">" and self.tokens[pos + 1].kind == "STRING":
            path = self._decode_static_string(self._text(pos + 1), purpose="import path")
            end = pos + 2
            alias = None
            if self._text(end) == ":":
                found = self._module_alias_at(end + 1)
                if found is not None:
                    alias, end = found
            return (StmtCand(ast.ImportStmt(path, alias), end, 0),)

        # `<:alias` selects an imported module as the active lexical namespace.
        # `<:.` restores the current/default module. The selector consumes exactly one
        # namespace atom; a following dot is ordinary immediate traversal, so
        # `<:MA.ma` means "select MA; use MA.ma" rather than selecting `MA.ma`.
        selector = self._namespace_selector_at(pos)
        if selector is not None:
            alias, end = selector
            if alias is not None and alias not in self.modules:
                raise ParseError(f"unknown module namespace {alias}", span=self._span(tok))
            return (StmtCand(ast.NamespaceStmt(alias), end, 0),)

        # Structured exceptions are statement forms.
        if self._pair(pos) == "tr":
            return self._try_candidates(pos)
        if self._pair(pos) == "er":
            return self._raise_candidates(pos)

        if self._text(pos) == "+" and self._text(pos + 1) == ":":
            target = self._target_list(pos + 2)
            if target is not None and len(target[0]) == 1 and self._text(target[2]) in {":=", "::="}:
                name = target[0][0]; type_code = target[1][0]; op_pos = target[2]
                out: list[StmtCand] = []
                for e in self.expr_candidates(op_pos + 1):
                    out.append(StmtCand(ast.ExportDecl(name, self._text(op_pos), e.expr, type_code), e.end, e.score))
                return tuple(self._dedupe_stmt(out))

        private = False
        dpos = pos
        if self._text(dpos) == "-" and self._text(dpos + 1) in {"#", "~", "~~", "."}:
            private = True
            dpos += 1

        if self._text(dpos) == "#":
            c = self._parse_interface_decl(dpos, private) if self._text(dpos + 1) == "?" else self._parse_class_decl(dpos, private)
            return (StmtCand(c[0], c[1], 0),) if c else ()
        if self._text(dpos) == "~-":
            c = self._parse_destructor_decl(dpos)
            return (StmtCand(c[0], c[1], 0),) if c else ()
        if self._text(dpos) in {"~", "~~"}:
            c = self._parse_function_decl(dpos, private)
            return (StmtCand(c[0], c[1], 0),) if c else ()

        # Private field declarations are statement forms because privacy is declaration
        # metadata, not part of the value-yielding assignment expression.
        if private and self._text(dpos) == ".":
            out = []
            for target_cand in self._member_target_candidates(dpos):
                op = self._text(target_cand.end)
                if op not in {":=", "::="}:
                    continue
                for e in self.expr_candidates(target_cand.end + 1):
                    out.append(StmtCand(ast.SetMemberStmt(target_cand.expr, e.expr, True, op == "::=", True), e.end, target_cand.score + e.score))
            return tuple(self._dedupe_stmt(out))

        # Explicit super-constructor call. It is constructor-only semantically.
        if self._text(pos) == "^^" and self._text(pos + 1) == "[":
            out = []
            for args, end, score in self._parse_arg_pack(pos + 1, allow_default=True):
                out.append(StmtCand(ast.SuperInitStmt(tuple(args)), end, score))
            return tuple(self._dedupe_stmt(out))

        # Control flow. These pairs are reserved in statement position.
        if self._pair(pos) == "if" or self._text(pos) == "?":
            return self._if_candidates(pos)
        if self._pair(pos) == "wl":
            return self._while_candidates(pos)
        if self._pair(pos) == "fl":
            return self._for_candidates(pos)
        if self._pair(pos) == "bl":
            return (StmtCand(ast.BreakStmt(), pos + 2, 0),)
        if self._pair(pos) == "cl":
            return (StmtCand(ast.ContinueStmt(), pos + 2, 0),)

        # return
        if self._pair(pos) == "rv":
            return self._return_candidates(pos)

        module_writes: list[StmtCand] = []
        # Direct-imported public variables retain their provider origin in VarSig so
        # they cannot be confused with an ordinary lexical variable of the same spelling.
        if self.tokens[pos].kind in {"LOWER", "EXT"}:
            direct_sig = self.symbols.variables.get(self._text(pos))
            if direct_sig is not None and direct_sig.origin is not None and self._text(pos + 1) == "=":
                for rhs in self.expr_candidates(pos + 2):
                    module_writes.append(StmtCand(ast.ModuleVarAssignStmt(direct_sig.origin, direct_sig.name, rhs.expr, "direct"), rhs.end, rhs.score))
        active_mod = self._active_module_symbols(pos)
        if active_mod is not None and self.tokens[pos].kind in {"LOWER", "EXT"}:
            alias, syms = active_mod
            n = self._text(pos)
            if n in syms.variables and self._text(pos + 1) == "=":
                for rhs in self.expr_candidates(pos + 2):
                    module_writes.append(StmtCand(ast.ModuleVarAssignStmt(alias, n, rhs.expr, "namespace-bare"), rhs.end, rhs.score))
        for cand in tuple(self._module_atoms(pos)) + tuple(self._active_namespace_dot_atoms(pos)):
            if isinstance(cand.expr, ast.ModuleVar) and self._text(cand.end) == "=":
                for rhs in self.expr_candidates(cand.end + 1):
                    module_writes.append(StmtCand(ast.ModuleVarAssignStmt(cand.expr.alias, cand.expr.name, rhs.expr, cand.expr.mode), rhs.end, cand.score + rhs.score))
        if module_writes:
            return tuple(self._dedupe_stmt(module_writes))

        # Indexed '=' assignment is statement-only. Unlike lexical '=', it requires
        # the indexed element/key to already exist; `:=` is the create/update + yield
        # form and is parsed as an expression below.
        indexed = []
        for target_cand in self._index_target_candidates(pos):
            if self._text(target_cand.end) == "=":
                for e in self.expr_candidates(target_cand.end + 1):
                    indexed.append(StmtCand(ast.SetIndexStmt(target_cand.expr, e.expr), e.end, target_cand.score + e.score))
        if indexed:
            return tuple(self._dedupe_stmt(indexed))

        member_updates = []
        for target_cand in self._member_target_candidates(pos):
            op = self._text(target_cand.end)
            if op == "=":
                for e in self.expr_candidates(target_cand.end + 1):
                    member_updates.append(StmtCand(ast.SetMemberStmt(target_cand.expr, e.expr, False, False, False), e.end, target_cand.score + e.score))
        if member_updates:
            return tuple(self._dedupe_stmt(member_updates))

        # Plain '=' assignment is statement-only. Multiple lowercase/extended targets
        # are allowed, and '=' creates locally only when no nearer binding exists.
        target = self._target_list(pos)
        if target and self._text(target[2]) == "=":
            names, target_types, op_pos = target
            out = []
            for e in self.expr_candidates(op_pos + 1):
                out.append(StmtCand(ast.AssignStmt(tuple(names), e.expr, tuple(target_types)), e.end, e.score))
            return tuple(self._dedupe_stmt(out))

        # Postfix mutation statement.
        mutation_targets: list[tuple[ast.Expr, int]] = []
        one = self._single_target_expr(pos)
        if one is not None:
            mutation_targets.append(one)
        mutation_targets.extend((c.expr, c.end) for c in self._member_target_candidates(pos))
        for target_expr, end in mutation_targets:
            if self._text(end) in {"++", "--"}:
                return (StmtCand(ast.MutateStmt(target_expr, self._text(end)), end + 1, 0),)

        # Only expressions with observable effects are useful as standalone statements.
        # This is also an important SLUG disambiguator: `coa` should not degrade into
        # three no-op variable statements `c`, `o`, `a`; the valid statement is co(a).
        effectful = (ast.AssignExpr, ast.SetIndexExpr, ast.SetMemberExpr, ast.Call, ast.ClassCall, ast.ModuleCall, ast.ModuleClassCall, ast.ModuleClassMethodCall, ast.MethodCall, ast.CallableInvoke)
        out = [
            StmtCand(ast.ExprStmt(e.expr), e.end, e.score)
            for e in self.expr_candidates(pos)
            if isinstance(e.expr, effectful)
        ]
        return tuple(self._dedupe_stmt(out))

    def _return_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        start = pos + 2
        if self._text(start) in {";", "}", ""} or self.tokens[start].kind == "EOF":
            return (StmtCand(ast.ReturnStmt(()), start, 0),)

        # Iterative worklist: return arity is limited only by real resources, not a
        # historical parser counter or Python recursion depth.
        out: list[StmtCand] = []
        work: list[tuple[int, tuple[ast.Expr, ...], int]] = [(start, (), 0)]
        seen: set[tuple[int, tuple[object, ...]]] = set()
        while work:
            p, vals, score = work.pop()
            key = (p, tuple(self._fp(v) for v in vals))
            if key in seen:
                continue
            seen.add(key)
            if vals:
                out.append(StmtCand(ast.ReturnStmt(vals), p, score))
            if self._text(p) in {";", "}"} or self.tokens[p].kind == "EOF":
                continue
            choices = [e for e in self.expr_candidates(p) if e.end != p]
            for e in reversed(choices):
                work.append((e.end, vals + (e.expr,), score + e.score))
        return tuple(self._dedupe_stmt(out))

    def _raise_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        if self._pair(pos) != "er":
            return ()
        out: list[StmtCand] = []
        after = pos + 2
        if self._text(after) in {";", "}"} or self.tokens[after].kind == "EOF":
            out.append(StmtCand(ast.RaiseStmt(None), after, 0))
        for e in self.expr_candidates(after):
            out.append(StmtCand(ast.RaiseStmt(e.expr), e.end, e.score))
        return tuple(self._dedupe_stmt(out))

    def _try_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        if self._pair(pos) != "tr" or self._text(pos + 2) != "{":
            return ()
        out: list[StmtCand] = []
        for body, end, bscore in self._block_candidates(pos + 2):
            p = end
            catch_name: str | None = None
            catch_options: list[tuple[str | None, tuple[ast.Stmt, ...] | None, int, int]] = []
            if self._pair(p) == "ca":
                q = p + 2
                name = None
                if self._text(q) != "{" and (self._is_lower(q) or self.tokens[q].kind == "EXT"):
                    name = self._text(q)
                    q += 1
                if self._text(q) == "{":
                    for cb, ce, cs in self._block_candidates(q):
                        catch_options.append((name, cb, ce, cs))
            # A try may omit catch when it has finally.
            catch_options.append((None, None, p, 0))

            for cname, cbody, after_catch, cscore in catch_options:
                fbody = None
                final_end = after_catch
                fscore = 0
                if self._pair(after_catch) == "fn" and self._text(after_catch + 2) == "{":
                    for fb, fe, fs in self._block_candidates(after_catch + 2):
                        out.append(StmtCand(ast.TryStmt(body, cname, cbody, fb), fe, bscore + cscore + fs))
                    continue
                if cbody is not None:
                    out.append(StmtCand(ast.TryStmt(body, cname, cbody, None), final_end, bscore + cscore + fscore))
        return tuple(self._dedupe_stmt(out))

    def _lambda_candidates(self, pos: int) -> tuple[ExprCand, ...]:
        if self._pair(pos) != "lb":
            return ()
        i = pos + 2
        return_types: tuple[str, ...] | None = None
        if self._text(i) == "@":
            rt, j = self._parse_type_code(i)
            if rt is None:
                return ()
            return_types = (rt,)
            i = j
        elif self._text(i) == "[" and self._text(i + 1) == "@":
            rts: list[str] = []
            j = i + 1
            while self._text(j) == "@":
                rt, j2 = self._parse_type_code(j)
                if rt is None:
                    return ()
                rts.append(rt); j = j2
                if self._text(j) == ",":
                    j += 1; continue
                break
            if self._text(j) != "]":
                return ()
            return_types = tuple(rts); i = j + 1
        params, i = self._parse_simple_params(i)
        variadic = None
        if self._text(i) == "[" and (self._is_lower(i + 1) or self.tokens[i + 1].kind == "EXT") and self._text(i + 2) == "]":
            variadic = self._text(i + 1); i += 3
        if self._text(i) != "{":
            return ()
        out: list[ExprCand] = []
        for body, end, score in self._block_candidates(i):
            out.append(ExprCand(ast.LambdaExpr(tuple(params), body, return_types, variadic), end, score))
        return tuple(self._dedupe_expr(out))

    def _logic_candidates(self, qpos: int) -> tuple[ExprCand, ...]:
        """Parse SLUG logic/comparison mode beginning at `?`.

        `+` and `/` are Boolean AND/OR once complete Boolean atoms exist. Arithmetic
        RPN with those same glyphs remains legal inside comparison operands; candidate
        scoring prefers the Boolean boundary whenever both readings are complete.
        """
        if self._text(qpos) != "?":
            return ()
        start = qpos + 1
        comparators = {"==", "!=", "<", ">", "<=", ">=", "===", "!=="}
        p_cache: dict[int, tuple[ExprCand, ...]] = {}
        a_cache: dict[int, tuple[ExprCand, ...]] = {}
        o_cache: dict[int, tuple[ExprCand, ...]] = {}

        def separator_penalty(cands: tuple[ExprCand, ...] | list[ExprCand], cand: ExprCand) -> int:
            cuts = [x.end for x in cands if self._text(x.end) in {"+", "/"}]
            if cuts and cand.end > min(cuts):
                return 12
            return 0

        def primary(pos: int) -> tuple[ExprCand, ...]:
            if pos in p_cache:
                return p_cache[pos]
            out: list[ExprCand] = []

            # [] groups Boolean expressions in logic mode.
            if self._text(pos) == "[":
                for inner in parse_or(pos + 1):
                    if self._text(inner.end) == "]":
                        out.append(ExprCand(inner.expr, inner.end + 1, inner.score))

            # !f[...] is lexically callable-value invocation before ! is considered NOT.
            explicit_invoke = False
            if self._text(pos) == "!":
                callee = self._single_target_expr(pos + 1)
                explicit_invoke = bool(callee and self._text(callee[1]) == "[")
                if not explicit_invoke:
                    for inner in primary(pos + 1):
                        out.append(ExprCand(ast.LogicNot(inner.expr), inner.end, inner.score))

            values = self.expr_candidates(pos)

            # Comparisons are Boolean atoms. Arithmetic operators may live inside either
            # operand; surrounding syntax and RPN validity decide how far each operand runs.
            for left in values:
                op = self._text(left.end)
                if op not in comparators:
                    continue
                rights = self.expr_candidates(left.end + 1)
                for right in rights:
                    pen = separator_penalty(rights, right)
                    out.append(ExprCand(ast.Compare(op, left.expr, right.expr), right.end, left.score + right.score + pen))

            # Plain truthiness is also a Boolean atom. If a complete value ends before
            # + or /, crossing that point as arithmetic is legal only as a lower-priority
            # interpretation; Boolean mode owns the operator by default.
            for value in values:
                if self._text(value.end) in comparators:
                    continue
                # When the lexical form starts !f[...], only callable-invocation
                # interpretations may use that initial ! as an atom.
                if explicit_invoke:
                    root = value.expr
                    def has_invoke(e: ast.Expr) -> bool:
                        if isinstance(e, ast.CallableInvoke):
                            return True
                        if isinstance(e, ast.Cast): return has_invoke(e.value)
                        if isinstance(e, ast.DynamicCast): return has_invoke(e.type_expr) or has_invoke(e.value)
                        if isinstance(e, ast.Unary): return has_invoke(e.value)
                        if isinstance(e, ast.Binary): return has_invoke(e.left) or has_invoke(e.right)
                        return False
                    if not has_invoke(root):
                        continue
                out.append(ExprCand(value.expr, value.end, value.score + separator_penalty(values, value)))

            p_cache[pos] = tuple(self._dedupe_expr(out))
            return p_cache[pos]

        def parse_and(pos: int) -> tuple[ExprCand, ...]:
            if pos in a_cache:
                return a_cache[pos]
            out: list[ExprCand] = []
            for first in primary(pos):
                out.append(first)
                if self._text(first.end) == "+":
                    for rest in parse_and(first.end + 1):
                        out.append(ExprCand(ast.LogicBinary("and", first.expr, rest.expr), rest.end, first.score + rest.score))
            a_cache[pos] = tuple(self._dedupe_expr(out))
            return a_cache[pos]

        def parse_or(pos: int) -> tuple[ExprCand, ...]:
            if pos in o_cache:
                return o_cache[pos]
            out: list[ExprCand] = []
            for first in parse_and(pos):
                out.append(first)
                if self._text(first.end) == "/":
                    for rest in parse_or(first.end + 1):
                        out.append(ExprCand(ast.LogicBinary("or", first.expr, rest.expr), rest.end, first.score + rest.score))
            o_cache[pos] = tuple(self._dedupe_expr(out))
            return o_cache[pos]

        return tuple(
            self._dedupe_expr(
                ExprCand(ast.BoolExpr(c.expr), c.end, c.score) for c in parse_or(start)
            )
        )

    def _block_candidates(self, brace_pos: int) -> list[tuple[tuple[ast.Stmt, ...], int, int]]:
        if self._text(brace_pos) != "{":
            return []
        out: list[tuple[tuple[ast.Stmt, ...], int, int]] = []
        for path in self._parse_seq(brace_pos + 1, stop="}"):
            if self._text(path.end) == "}":
                out.append((path.statements, path.end + 1, path.score))
        return out

    def _if_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        qpos = pos + 2 if self._pair(pos) == "if" else pos
        if self._text(qpos) != "?":
            return ()
        out: list[StmtCand] = []

        def tails(p: int) -> list[tuple[tuple[tuple[ast.Expr, tuple[ast.Stmt, ...]], ...], tuple[ast.Stmt, ...] | None, int, int]]:
            # returns (elifs, else_body, end, score)
            if self._pair(p) == "ei":
                q = p + 2
                if self._text(q) != "?":
                    return []
                result = []
                for cond in self._logic_candidates(q):
                    if self._text(cond.end) != "{":
                        continue
                    for body, end, bscore in self._block_candidates(cond.end):
                        for more, eb, final, tscore in tails(end):
                            result.append((((cond.expr, body),) + more, eb, final, cond.score + bscore + tscore))
                return result
            if self._pair(p) == "ee" and self._text(p + 2) == "{":
                return [((), body, end, score) for body, end, score in self._block_candidates(p + 2)]
            return [((), None, p, 0)]

        for cond in self._logic_candidates(qpos):
            if self._text(cond.end) != "{":
                continue
            for body, end, bscore in self._block_candidates(cond.end):
                for elifs, eb, final, tscore in tails(end):
                    out.append(StmtCand(ast.IfStmt(cond.expr, body, elifs, eb), final, cond.score + bscore + tscore))
        return tuple(self._dedupe_stmt(out))

    def _while_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        qpos = pos + 2
        if self._text(qpos) != "?":
            return ()
        out: list[StmtCand] = []
        for cond in self._logic_candidates(qpos):
            if self._text(cond.end) != "{":
                continue
            for body, end, bscore in self._block_candidates(cond.end):
                out.append(StmtCand(ast.WhileStmt(cond.expr, body), end, cond.score + bscore))
        return tuple(self._dedupe_stmt(out))

    def _for_candidates(self, pos: int) -> tuple[StmtCand, ...]:
        start = pos + 2
        out: list[StmtCand] = []

        def add(kind: str, var: str | None, source: ast.Expr | None, begin: ast.Expr | None,
                stop: ast.Expr | None, step: ast.Expr | None, brace: int, score: int) -> None:
            if self._text(brace) != "{":
                return
            for body, end, bscore in self._block_candidates(brace):
                out.append(StmtCand(ast.ForStmt(kind, var, source, begin, stop, step, body), end, score + bscore))

        # fl n {...}: repeat n times, no exposed counter.
        for count in self.expr_candidates(start):
            if self._text(count.end) == "{":
                add("repeat", None, None, count.expr, None, None, count.end, count.score)

        # Remaining forms begin with an explicit loop-variable target.
        target = self._single_target_expr(start)
        if target is not None and isinstance(target[0], (ast.Var, ast.ExtendedName)):
            var = target[0].name
            p = target[1]
            for vals, end, score in self._consume_n_exprs(p, 1):
                if self._text(end) == "{":
                    add("foreach", var, vals[0], None, None, None, end, score)
            for vals, end, score in self._consume_n_exprs(p, 2):
                if self._text(end) == "{":
                    add("range", var, None, vals[0], vals[1], None, end, score)
            for vals, end, score in self._consume_n_exprs(p, 3):
                if self._text(end) == "{":
                    add("slice", var, vals[0], vals[1], vals[2], None, end, score)
            for vals, end, score in self._consume_n_exprs(p, 4):
                if self._text(end) == "{":
                    add("slice_step", var, vals[0], vals[1], vals[2], vals[3], end, score)

        return tuple(self._dedupe_stmt(out))

    def _parse_interface_decl(self, pos: int, private: bool) -> tuple[ast.InterfaceDecl, int] | None:
        if self._text(pos) != "#" or self._text(pos + 1) != "?": return None
        if not (self._is_upper(pos + 2) and self._is_upper(pos + 3)): return None
        name = self._text(pos + 2) + self._text(pos + 3); i = pos + 4
        parents: list[str] = []
        while self._text(i) == ":":
            ref = self._interface_ref_at(i + 1)
            if ref is None:
                break
            parents.append(ref[0]); i = ref[1]
        if self._text(i) != "{": return None
        paths = self._parse_seq(i + 1, stop="}")
        if not paths: return None
        score = min(x.score for x in paths); best = self._dedupe_seq([x for x in paths if x.score == score])
        if len(best) != 1: return None
        methods: list[ast.FunctionDecl] = []
        for child in best[0].statements:
            if isinstance(child, ast.CommentStmt): continue
            if not isinstance(child, ast.FunctionDecl): return None
            methods.append(child)
        return ast.InterfaceDecl(name, tuple(methods), private, tuple(parents)), best[0].end + 1

    def _parse_class_decl(self, pos: int, private: bool) -> tuple[ast.ClassDecl, int] | None:
        if not (self._is_upper(pos + 1) and self._is_upper(pos + 2)):
            return None
        name = self._text(pos + 1) + self._text(pos + 2)
        i = pos + 3
        parent = None
        if self._text(i) == "<" and self._is_upper(i + 1) and self._is_upper(i + 2):
            parent = self._text(i + 1) + self._text(i + 2)
            i += 3
        interfaces: list[str] = []
        while self._text(i) == ":":
            ref = self._interface_ref_at(i + 1)
            if ref is None:
                break
            interfaces.append(ref[0]); i = ref[1]
        params, i = self._parse_simple_params(i)
        if self._text(i) != "{":
            return None
        body_paths = self._parse_seq(i + 1, stop="}")
        if not body_paths:
            return None
        best_score = min(p.score for p in body_paths)
        best = self._dedupe_seq([p for p in body_paths if p.score == best_score])
        if len(best) != 1:
            return None
        close = best[0].end
        return ast.ClassDecl(name, tuple(params), best[0].statements, private, parent, tuple(interfaces)), close + 1

    def _parse_function_decl(self, pos: int, private: bool) -> tuple[ast.FunctionDecl, int] | None:
        head = self._text(pos)
        static = head == "~~"
        if head not in {"~", "~~"}:
            return None
        i = pos + 1
        if self._text(i) == "-":  # destructor is not a normal named callable yet
            return None
        if not (self._is_lower(i) and self._is_lower(i + 1)):
            return None
        name = self._text(i) + self._text(i + 1)
        i += 2

        # Optional return contract: @i or [@i,@f,@s].
        return_types = None
        if self._text(i) == "@":
            type_code, i2 = self._parse_type_code(i)
            if type_code:
                return_types = (type_code,)
                i = i2
        elif self._text(i) == "[" and self._text(i + 1) == "@":
            j = i + 1
            rts: list[str] = []
            while self._text(j) == "@":
                tc, j2 = self._parse_type_code(j)
                if not tc:
                    return None
                rts.append(tc); j = j2
                if self._text(j) == ",":
                    j += 1
                    continue
                break
            if not rts or self._text(j) != "]":
                return None
            return_types = tuple(rts)
            i = j + 1

        params, i = self._parse_simple_params(i)
        variadic = None
        if self._text(i) == "[" and (self._is_lower(i + 1) or self.tokens[i + 1].kind == "EXT") and self._text(i + 2) == "]":
            variadic = self._text(i + 1)
            i += 3
        if self._text(i) != "{":
            return None
        body_paths = self._parse_seq(i + 1, stop="}")
        if not body_paths:
            return None
        best_score = min(p.score for p in body_paths)
        best = self._dedupe_seq([p for p in body_paths if p.score == best_score])
        if len(best) != 1:
            return None
        close = best[0].end
        return ast.FunctionDecl(name, tuple(params), best[0].statements, static, private, return_types, variadic), close + 1

    def _parse_destructor_decl(self, pos: int) -> tuple[ast.DestructorDecl, int] | None:
        if self._text(pos) != "~-" or self._text(pos + 1) != "{":
            return None
        body_paths = self._parse_seq(pos + 2, stop="}")
        if not body_paths:
            return None
        best_score = min(p.score for p in body_paths)
        best = self._dedupe_seq([p for p in body_paths if p.score == best_score])
        if len(best) != 1:
            return None
        close = best[0].end
        return ast.DestructorDecl(best[0].statements), close + 1

    def _parse_simple_params(self, pos: int) -> tuple[list[ast.Param], int]:
        params: list[ast.Param] = []
        i = pos
        while self._text(i) != "{" and self.tokens[i].kind != "EOF":
            if not (self._is_lower(i) or self.tokens[i].kind == "EXT"):
                break
            name = self._text(i)
            i += 1
            type_code = None
            default = None
            if self._text(i) == "@":
                type_code, i = self._parse_type_code(i)
            if self._text(i) == "=":
                # Bootstrap header defaults are deliberately restricted to an expression
                # with a unique shortest parse; this already covers literals and casts.
                cands = self.expr_candidates(i + 1)
                if not cands:
                    break
                shortest_end = min(c.end for c in cands)
                choices = [c for c in cands if c.end == shortest_end]
                best = min(choices, key=lambda c: c.score)
                default = best.expr
                i = best.end
            params.append(ast.Param(name, type_code, default))
        return params, i

    def expr_candidates(self, pos: int) -> tuple[ExprCand, ...]:
        if pos in self._expr_cache:
            return self._expr_cache[pos]
        # Prevent direct recursive cache loops.
        self._expr_cache[pos] = ()
        out = self._rpn_candidates(pos)
        out = tuple(self._dedupe_expr(out))
        self._expr_cache[pos] = out
        return out

    def _rpn_candidates(self, start: int) -> list[ExprCand]:
        # Assignment expressions are prefix structures and yield their RHS value.
        target = self._target_list(start)
        assignment_out: list[ExprCand] = []

        # Member :=/::= is value-yielding, like lexical/indexed definition.
        for target_cand in self._member_target_candidates(start):
            op = self._text(target_cand.end)
            if op in {":=", "::="}:
                for rhs in self.expr_candidates(target_cand.end + 1):
                    # Receiver-field assignment (a.x:=...) can lexically overlap an
                    # already-complete value followed by a current-field assignment
                    # (a .x:=...). Keep it available, but make the implicit statement
                    # boundary cheaper when both survive.
                    receiver_penalty = 8 if target_cand.expr.base is not None else 0
                    assignment_out.append(ExprCand(ast.SetMemberExpr(target_cand.expr, rhs.expr, op == "::="), rhs.end, target_cand.score + rhs.score + receiver_penalty))

        # Indexed := is a value-yielding create/update operation. Slice assignment and
        # indexed ::= are deliberately not part of v0.0.7.
        for target_cand in self._index_target_candidates(start):
            if self._text(target_cand.end) == ":=":
                for rhs in self.expr_candidates(target_cand.end + 1):
                    assignment_out.append(ExprCand(ast.SetIndexExpr(target_cand.expr, rhs.expr), rhs.end, target_cand.score + rhs.score))

        if target and self._text(target[2]) in {":=", "::="}:
            names, target_types, op_pos = target
            for rhs in self.expr_candidates(op_pos + 1):
                # A multi-target assignment expression is valid, but when the same
                # character stream can instead finish a preceding expression and
                # begin a new assignment, prefer that statement boundary.  Single-
                # target nested assignments (a:=b:=3) remain zero-cost.
                target_penalty = max(0, len(names) - 1) * 3
                assignment_out.append(ExprCand(ast.AssignExpr(tuple(names), self._text(op_pos), rhs.expr, tuple(target_types)), rhs.end, rhs.score + target_penalty))

        # Explore lower-cost interpretations first.  A simple LIFO walk starves
        # short, sensible parses when a highly implicit stream has thousands of
        # legal nested-assignment/call continuations.  The priority queue makes the
        # parser constraint-directed: cheap variable/RPN boundaries are discovered
        # before expensive inferred/nested alternatives, while forced longer parses
        # are still reachable when the short ones cannot complete the surrounding
        # program.
        serial = itertools.count()
        states: list[tuple[int, int, int, tuple[ast.Expr, ...], bool]] = []

        def push(pos: int, stack: tuple[ast.Expr, ...], score: int, consumed: bool) -> None:
            heapq.heappush(states, (score, pos, next(serial), stack, consumed))

        push(start, (), 0, False)
        out: list[ExprCand] = assignment_out[:]
        seen: set[tuple[int, tuple[ast.Expr, ...], int]] = set()
        while states:
            score, pos, _, stack, consumed = heapq.heappop(states)
            key = (pos, stack, score)
            if key in seen:
                continue
            seen.add(key)
            if consumed and len(stack) == 1:
                out.append(ExprCand(stack[0], pos, score))

            text = self._text(pos)
            if text in {";", "}", "]", ",", ":", ""} or self.tokens[pos].kind in {"EOF", "COMMENT"}:
                continue

            # RPN operators. A '-' immediately followed by a declaration introducer
            # is the private-declaration prefix, not arithmetic; once the current RPN
            # stack already has its value this is a provable statement boundary.
            if text == "-" and self._text(pos + 1) in {"#", "~", "~~", "."}:
                continue
            if text in _BINARY and stack:
                # `-` is both unary negation and binary subtraction.  Do not decide
                # greedily from the current stack depth: a continuation can make only
                # one interpretation viable.  Example: `23-^` must be able to mean
                # `2 (3 neg) ^`, while `23-` naturally resolves to binary subtraction.
                if text == "-":
                    push(pos + 1, stack[:-1] + (ast.Unary("-", stack[-1]),), score, True)
                if len(stack) >= 2:
                    expr = ast.Binary(text, stack[-2], stack[-1])
                    push(pos + 1, stack[:-2] + (expr,), score, True)
                continue

            atoms = self._atom_candidates(pos)
            for a in atoms:
                # `:=`/`::=` are first-class expressions, but a later assignment
                # should not be swallowed into an already-complete RPN value merely
                # because assignments themselves yield values.
                embed_penalty = 8 if stack and isinstance(a.expr, (ast.AssignExpr, ast.SetIndexExpr, ast.SetMemberExpr)) else 0
                push(a.end, stack + (a.expr,), score + a.score + embed_penalty, True)
        return out

    def _atom_candidates(self, pos: int) -> tuple[ExprCand, ...]:
        t = self.tokens[pos]
        out: list[ExprCand] = []

        # Backtick is a one-shot root/default-namespace escape. It changes only the
        # resolution of the immediately following name; arguments still parse in the
        # active namespace. This avoids the ambiguity `.name` would have with member
        # traversal and does not mutate the lexical namespace selected by `<:XX`.
        if self._text(pos) == "`":
            return self._root_atom_candidates(pos + 1)

        # assignment expression as an atom (for nesting inside calls/returns/etc.)
        for target_cand in self._member_target_candidates(pos):
            op = self._text(target_cand.end)
            if op in {":=", "::="}:
                for rhs in self.expr_candidates(target_cand.end + 1):
                    receiver_penalty = 8 if target_cand.expr.base is not None else 0
                    out.append(ExprCand(ast.SetMemberExpr(target_cand.expr, rhs.expr, op == "::="), rhs.end, target_cand.score + rhs.score + receiver_penalty))

        for target_cand in self._index_target_candidates(pos):
            if self._text(target_cand.end) == ":=":
                for rhs in self.expr_candidates(target_cand.end + 1):
                    out.append(ExprCand(ast.SetIndexExpr(target_cand.expr, rhs.expr), rhs.end, target_cand.score + rhs.score))

        target = self._target_list(pos)
        if target and self._text(target[2]) in {":=", "::="}:
            names, target_types, op_pos = target
            for rhs in self.expr_candidates(op_pos + 1):
                target_penalty = max(0, len(names) - 1) * 3
                out.append(ExprCand(ast.AssignExpr(tuple(names), self._text(op_pos), rhs.expr, tuple(target_types)), rhs.end, rhs.score + target_penalty))

        # Module alias traversal is symbol-directed and therefore wins over ordinary
        # object-member/class traversal when the left spelling is a known import alias.
        out.extend(self._module_atoms(pos))

        # The dot immediately after `<:MA` is a namespace-tail operator, not current-
        # instance member syntax. Elsewhere `.x` / `..x` retain their OOP meaning.
        ns_dot = self._active_namespace_dot_atoms(pos)
        if ns_dot:
            out.extend(ns_dot)
        else:
            out.extend(self._current_member_atoms(pos))

        # `^^.ab[...]` directly names the parent implementation. `^^[...]` is handled
        # as a constructor statement rather than a value expression.
        if self._text(pos) == "^^" and self._text(pos + 1) == ".":
            out.extend(self._super_method_atoms(pos))

        # `AB.x` / `AB.ab[...]` static traversal does not construct AB. With an
        # active namespace, an exported AB is resolved there first. A module alias
        # spelled AB also owns `AB.` outright, so it cannot simultaneously be read as
        # the current module's class traversal at the same token position.
        if self._is_upper(pos) and self._is_upper(pos + 1) and self._text(pos + 2) == ".":
            pair = self._text(pos) + self._text(pos + 1)
            active = self._active_module_symbols(pos)
            if active is not None and pair in active[1].classes:
                out.extend(self._module_member_atoms(active[0], pos, True))
            elif pair not in self.modules:
                out.extend(self._class_member_atoms(pos))

        if t.kind == "STRING":
            out.append(ExprCand(self._parse_string_expr(t.text, pos), pos + 1, 0))
        elif t.kind == "FLOAT":
            raw = t.text
            value = float(raw if not raw.startswith(".") else "0" + raw)
            if not math.isfinite(value):
                raise ParseError("float literal is outside finite f64 range", span=self._span(t))
            out.append(ExprCand(ast.Literal("float", value, raw), pos + 1, 0))
        elif t.kind == "EXT":
            if not (t.text in self.modules and self._text(pos + 1) == "."):
                active_var = self._active_module_symbols(pos)
                direct_sig = self.symbols.variables.get(t.text)
                if active_var is not None and t.text in active_var[1].variables:
                    out.append(ExprCand(ast.ModuleVar(active_var[0], t.text, "namespace-bare"), pos + 1, 0))
                elif direct_sig is not None and direct_sig.origin is not None:
                    out.append(ExprCand(ast.ModuleVar(direct_sig.origin, t.text, "direct"), pos + 1, 0))
                else:
                    out.append(ExprCand(ast.ExtendedName(t.text), pos + 1, 0))

        # Decimal integer candidates. `$` is a zero-value lexical terminator; it
        # never changes base or value. Candidate digit runs remain splittable so RPN
        # can prove a shorter partition (for example `52/` -> `5 2 /`).
        terminated = self._scan_decimal_terminated(pos)
        if terminated:
            raw_digits, end = terminated
            value = int(raw_digits, 10)
            if value <= 0xFFFFFFFFFFFFFFFF:
                out.append(ExprCand(ast.Literal("int", value, raw_digits + "$"), end, 0))
            # `$` is an explicit integer boundary. Once present, the preceding digit
            # run is one atom and must not also explode into every shorter prefix.
            # Besides honoring the source-level disambiguator, this keeps very wide
            # decimal values linear rather than creating a combinatorial RPN search.
        elif t.kind == "DIGIT":
            j = pos
            digits = ""
            runs: list[tuple[str, int]] = []
            while self.tokens[j].kind == "DIGIT":
                digits += self._text(j)
                j += 1
                runs.append((digits, j))
            total = len(runs)
            for idx, (raw_digits, end_digits) in enumerate(runs):
                value = int(raw_digits, 10)
                if value > 0xFFFFFFFFFFFFFFFF:
                    continue
                penalty = total - idx - 1
                out.append(ExprCand(ast.Literal("int", value, raw_digits), end_digits, penalty))

        # nn is hard null literal.
        if self._pair(pos) == "nn":
            out.append(ExprCand(ast.Literal("null", None, "nn"), pos + 2, 0))

        # `lb...{...}` is the first-class lambda introducer. It is recognized before
        # the ordinary one-character `l`,`b` variable partition.
        lambda_cands = self._lambda_candidates(pos) if self._pair(pos) == "lb" else ()
        out.extend(lambda_cands)

        # One-character variables are lowercase only. A known two-letter callable
        # immediately followed by `[` is explicit call syntax, so that spelling wins
        # lexically over the otherwise cheaper a,b variable partition.
        _call_name = self._text(pos) + self._text(pos + 1) if t.kind == "LOWER" and self._is_lower(pos + 1) else None
        _call_sig, _call_alias = self._resolved_callable(pos, _call_name) if _call_name is not None else (None, None)
        explicit_named_pack = bool(_call_sig is not None and self._text(pos + 2) == "[")
        _alias_here = self._module_alias_at(pos)
        module_alias_here = bool(_alias_here and _alias_here[0] in self.modules and self._text(_alias_here[1]) == ".")
        # A known fixed zero-argument callable is itself a complete value.  Its exact
        # two-letter spelling therefore wins over splitting the same bytes into two
        # one-letter variables.  Without this rule `f:=mk` could degrade into
        # `f:=m` followed by a stray `k`, defeating the language rule that a known
        # zero-arity callable invokes bare.  A programmer who truly wants adjacent
        # variables named m and k can provide a real structural boundary.
        zero_callable_here = False
        if t.kind == "LOWER" and self._is_lower(pos + 1):
            _zn = self._text(pos) + self._text(pos + 1)
            _zs, _za = self._resolved_callable(pos, _zn)
            zero_callable_here = bool(_zs and _zs.dense_infer and _zs.min_arity == 0 and _zs.max_arity == 0 and _zn not in _RESERVED_PAIRS)
        if t.kind == "LOWER" and self._pair(pos) != "nn" and not explicit_named_pack and not lambda_cands and not module_alias_here and not zero_callable_here:
            active_var = self._active_module_symbols(pos)
            direct_sig = self.symbols.variables.get(t.text)
            if active_var is not None and t.text in active_var[1].variables:
                out.append(ExprCand(ast.ModuleVar(active_var[0], t.text, "namespace-bare"), pos + 1, 0))
            elif direct_sig is not None and direct_sig.origin is not None:
                out.append(ExprCand(ast.ModuleVar(direct_sig.origin, t.text, "direct"), pos + 1, 0))
            else:
                out.append(ExprCand(ast.Var(t.text), pos + 1, 0))

        # Cast.  The compact form keeps SLUG's normal context-sensitive endpoint:
        #     @iA$       @svalue
        # A pipe immediately after the type is an explicit hard operand boundary:
        #     @i8|7F$|   @s|[1,2,3]|   @i8|@u8|7F$||
        # Bare |...| is intentionally not a general grouping construct.
        if self._text(pos) == "@":
            type_code, after = self._parse_type_code(pos)
            if type_code:
                if self._text(after) == "|":
                    for v in self.expr_candidates(after + 1):
                        if self._text(v.end) == "|":
                            out.append(ExprCand(ast.Cast(type_code, v.expr, True), v.end + 1, v.score))
                else:
                    inner = self.expr_candidates(after)
                    if inner:
                        # Prefer the earliest complete operand that ends immediately before
                        # a new assignment statement. Assignments themselves yield values,
                        # so blindly choosing the farthest candidate can absorb an arbitrary
                        # number of later statements into the cast. Keep a penalized farthest
                        # fallback for cases where later RPN syntax proves the apparent
                        # boundary was actually inside the operand.
                        boundary = []
                        for v in inner:
                            target = self._target_list(v.end)
                            if v.end > after and target and self._text(target[2]) in {"=", ":=", "::="}:
                                boundary.append(v)
                        if boundary:
                            first_end = min(v.end for v in boundary)
                            for v in boundary:
                                if v.end == first_end:
                                    out.append(ExprCand(ast.Cast(type_code, v.expr), v.end, v.score))
                            farthest = max(v.end for v in inner)
                            if farthest != first_end:
                                for v in inner:
                                    if v.end == farthest:
                                        out.append(ExprCand(ast.Cast(type_code, v.expr), v.end, v.score + 32))
                        else:
                            farthest = max(v.end for v in inner)
                            for v in inner:
                                if v.end == farthest:
                                    out.append(ExprCand(ast.Cast(type_code, v.expr), v.end, v.score))

        # Dynamic cast. A runtime type token can come directly from ty[...] or from
        # an explicitly grouped type expression: @ty[a]b / @|t|b. Static @i/@s/etc.
        # remain on the separate path above so dynamic typing cannot perturb their
        # historical ambiguity rules. Bare @t value is intentionally not accepted: a
        # one-letter descriptor variable is too easy to confuse with ordinary dense
        # source; use @|t|value instead.
        if self._text(pos) == "@" and not self._parse_type_code(pos)[0]:
            type_cands = []
            if self._text(pos + 1) == "|":
                for tc in self.expr_candidates(pos + 2):
                    if self._text(tc.end) == "|":
                        type_cands.append((tc, tc.end + 1, True))
            else:
                for tc in self.expr_candidates(pos + 1):
                    if isinstance(tc.expr, ast.Call) and tc.expr.name == "ty":
                        type_cands.append((tc, tc.end, False))
            for tc, after_type, grouped_type in type_cands:
                vals = self.expr_candidates(after_type)
                if vals:
                    farthest = max(v.end for v in vals)
                    for v in vals:
                        if v.end == farthest:
                            out.append(ExprCand(ast.DynamicCast(tc.expr, v.expr, grouped_type), v.end, tc.score + v.score))

        # Boolean/comparison expression. `?` enters logic mode and yields a real
        # Boolean value, so it can appear in assignments, returns, lists, etc.
        if self._text(pos) == "?":
            out.extend(self._logic_candidates(pos))

        # List/map literals. Standalone ':' inside brackets selects map grammar; the
        # same ':' after an indexable is handled by postfix slicing below.
        if self._text(pos) == "@" and self._text(pos + 1) == "[":
            out.extend(self._parse_list(pos + 1, frozen=True))
            out.extend(self._parse_map(pos + 1, frozen=True))
        elif self._text(pos) == "[":
            out.extend(self._parse_list(pos, frozen=False))
            out.extend(self._parse_map(pos, frozen=False))

        # Explicit callable value invocation !f[...].
        if self._text(pos) == "!":
            callee = self._single_target_expr(pos + 1)
            if callee and self._text(callee[1]) == "[":
                # Callable values carry their parameter/default contract at runtime.
                # `xx` is therefore meaningful here too; the invoked closure validates
                # whether that position actually has a default.
                for args, end, score in self._parse_arg_pack(callee[1], allow_default=True):
                    out.append(ExprCand(ast.CallableInvoke(callee[0], tuple(args)), end, score))
            # !ab forces named callable.
            if self._is_lower(pos + 1) and self._is_lower(pos + 2):
                name = self._text(pos + 1) + self._text(pos + 2)
                sig, active_alias = self._resolved_callable(pos + 1, name)
                if sig:
                    q = pos + 3
                    if self._text(q) == "[":
                        # `!ab[...]` is the forced-named-call analogue of ordinary
                        # `ab[...]`: the brackets are an argument pack, not a list
                        # literal passed as one inferred argument.
                        for args, end, score in self._parse_arg_pack(q, allow_default=True):
                            if sig.max_arity is None:
                                ok = len(args) >= sig.min_arity
                            else:
                                ok = sig.min_arity <= len(args) <= sig.max_arity
                            if ok:
                                if active_alias is None:
                                    ex = ast.Call(name, tuple(args), "forced")
                                else:
                                    ex = ast.ModuleCall(active_alias, name, tuple(args), "namespace-forced")
                                out.append(ExprCand(ex, end, score))
                    else:
                        out.extend(self._call_candidates(name, sig, q, forced=True, alias=active_alias))

        # Inferred named callable. Variable interpretation is preferred by score.
        if self._is_lower(pos) and self._is_lower(pos + 1):
            name = self._text(pos) + self._text(pos + 1)
            sig, active_alias = self._resolved_callable(pos, name)
            if sig and name not in _RESERVED_PAIRS:
                # `ab[...]` is explicit argument-pack syntax.  Once `[` immediately
                # follows a known callable name, do not also reinterpret that same
                # bracket group as a list literal consumed by inferred-arity calling.
                # A literal list argument remains expressible as `ab[[...]]`.
                if self._text(pos + 2) == "[":
                    for args, end, score in self._parse_arg_pack(pos + 2, allow_default=True):
                        if sig.max_arity is None:
                            if len(args) >= sig.min_arity:
                                ex = ast.Call(name, tuple(args), "pack") if active_alias is None else ast.ModuleCall(active_alias, name, tuple(args), "namespace-pack")
                                out.append(ExprCand(ex, end, 4 + score))
                        elif sig.min_arity <= len(args) <= sig.max_arity:
                            ex = ast.Call(name, tuple(args), "pack") if active_alias is None else ast.ModuleCall(active_alias, name, tuple(args), "namespace-pack")
                            out.append(ExprCand(ex, end, 4 + score))
                elif sig.dense_infer:
                    out.extend(self._call_candidates(name, sig, pos + 2, forced=False, alias=active_alias))

        # Known class call. This intentionally outranks a full ABA$ hex fallback.
        if self._is_upper(pos) and self._is_upper(pos + 1) and self._text(pos + 2) != ".":
            name = self._text(pos) + self._text(pos + 1)
            sig, active_alias = self._resolved_class(pos, name)
            if sig:
                if self._text(pos + 2) == "[":
                    for args, end, score in self._parse_arg_pack(pos + 2, allow_default=True):
                        max_a = sig.max_arity if sig.max_arity is not None else len(args)
                        if sig.min_arity <= len(args) <= max_a:
                            ex = ast.ClassCall(name, tuple(args)) if active_alias is None else ast.ModuleClassCall(active_alias, name, tuple(args), "namespace-pack")
                            out.append(ExprCand(ex, end, score))
                else:
                    out.extend(self._class_call_candidates(name, sig, pos + 2, alias=active_alias))

        # Index/slice and member traversal are postfix syntax. Whitespace cannot alter
        # a.x, a.ab[...], a[0].x, etc.
        expanded: list[ExprCand] = []
        for cand in list(out):
            if self._text(cand.end) == ".":
                # Member traversal binds to the immediately preceding value. A bare
                # candidate ending just before `.` would otherwise let `x:=a.sp[]`
                # split into `x:=a` followed by a current-instance `.sp[]` statement,
                # or attach `.sp[]` to the assignment expression itself. Assignment
                # is deliberately lower precedence than postfix traversal.
                if isinstance(cand.expr, (ast.AssignExpr, ast.SetIndexExpr, ast.SetMemberExpr)):
                    continue
                chains = self._postfix_chain(cand.expr, cand.end, cand.score)
                if chains:
                    # Dot traversal normally binds to the value on its left. However a
                    # single/extended field beginning at the same dot can also be a new
                    # current-object RPN atom (`.x.y+` => `.x .y +`) or the next field
                    # assignment (`.x:=x.y:=y`). Preserve that split candidate with a
                    # small cost so postfix wins whenever both complete the same grammar.
                    # An explicit two-letter method pack is hard postfix syntax: `a.sp[]`
                    # cannot degrade into `a` followed by current `.sp[]`.
                    p = cand.end + 1
                    meth = self._method_name_at(p)
                    explicit_method = bool(meth and self._text(meth[1]) == "[")
                    member_boundary = any(
                        self._text(t.end) in {"=", ":=", "::="}
                        for t in self._member_target_candidates(cand.end)
                    )
                    if not explicit_method:
                        expanded.append(ExprCand(cand.expr, cand.end, cand.score + (0 if member_boundary else 1)))
                    expanded.extend(chains)
                    continue
            expanded.append(cand)
            expanded.extend(self._postfix_chain(cand.expr, cand.end, cand.score))
        return tuple(self._dedupe_expr(expanded))

    def _root_atom_candidates(self, pos: int) -> tuple[ExprCand, ...]:
        """Resolve exactly one expression name against this unit's root symbols.

        The returned AST records the escape so format/crush/expand round-trips remain
        correct even while a namespace with a shadowing symbol is active.
        """
        out: list[ExprCand] = []
        t = self.tokens[pos]

        if t.kind == "EXT":
            out.append(ExprCand(ast.ExtendedName(t.text, True), pos + 1, 0))
            return tuple(out)

        if t.kind == "LOWER":
            # A known root callable owns its two-letter spelling exactly as it does in
            # the ordinary namespace-aware path. Otherwise backtick may name a normal
            # one-character root variable.
            if self._is_lower(pos + 1):
                name = self._text(pos) + self._text(pos + 1)
                sig = self.symbols.callables.get(name)
                if sig is not None and name not in _RESERVED_PAIRS:
                    q = pos + 2
                    if self._text(q) == "[":
                        for args, end, score in self._parse_arg_pack(q, allow_default=True):
                            ok = len(args) >= sig.min_arity if sig.max_arity is None else sig.min_arity <= len(args) <= sig.max_arity
                            if ok:
                                out.append(ExprCand(ast.Call(name, tuple(args), "pack", True), end, 4 + score))
                    elif sig.dense_infer:
                        out.extend(self._call_candidates(name, sig, q, forced=False, alias=None, root=True))
                    return tuple(self._dedupe_expr(out))
            out.append(ExprCand(ast.Var(t.text, True), pos + 1, 0))
            return tuple(out)

        if self._is_upper(pos) and self._is_upper(pos + 1):
            name = self._text(pos) + self._text(pos + 1)
            sig = self.symbols.classes.get(name)
            if sig is not None:
                q = pos + 2
                if self._text(q) == "[":
                    for args, end, score in self._parse_arg_pack(q, allow_default=True):
                        max_a = sig.max_arity if sig.max_arity is not None else len(args)
                        if sig.min_arity <= len(args) <= max_a:
                            out.append(ExprCand(ast.ClassCall(name, tuple(args), True), end, score))
                else:
                    out.extend(self._class_call_candidates(name, sig, q, alias=None, root=True))
                return tuple(self._dedupe_expr(out))

        # Forced root named call: `!ab[...] / `!ab...
        if self._text(pos) == "!" and self._is_lower(pos + 1) and self._is_lower(pos + 2):
            name = self._text(pos + 1) + self._text(pos + 2)
            sig = self.symbols.callables.get(name)
            if sig is not None:
                q = pos + 3
                if self._text(q) == "[":
                    for args, end, score in self._parse_arg_pack(q, allow_default=True):
                        ok = len(args) >= sig.min_arity if sig.max_arity is None else sig.min_arity <= len(args) <= sig.max_arity
                        if ok:
                            out.append(ExprCand(ast.Call(name, tuple(args), "forced", True), end, score))
                else:
                    out.extend(self._call_candidates(name, sig, q, forced=True, alias=None, root=True))
                return tuple(self._dedupe_expr(out))

        return ()

    def _call_candidates(self, name: str, sig: CallableSig, pos: int, forced: bool, alias: str | None = None, root: bool = False) -> list[ExprCand]:
        # Variadic named calls require explicit [] so there is a hard endpoint for the
        # unlimited argument list. `va[...]` is therefore accepted above, while bare
        # `va...` is never inferred.
        if sig.max_arity is None:
            return []
        max_arity = sig.max_arity
        counts = list(range(max_arity, sig.min_arity - 1, -1))
        out: list[ExprCand] = []
        for count in counts:
            for args, end, score in self._consume_n_call_args(pos, count):
                # Defaulted parameters are omitted unless surrounding syntax proves an
                # additional argument belongs to this call. This preserves statement
                # boundaries: `coadcoA$` with ad/0..2 prefers ad(); co(A$), while
                # `adA$` at EOF must consume A$ because the leftover literal cannot
                # form a statement.
                penalty = (count - sig.min_arity) * 3
                if alias is None:
                    ex = ast.Call(name, tuple(args), "forced" if forced else "inferred", root)
                else:
                    ex = ast.ModuleCall(alias, name, tuple(args), "namespace-forced" if forced else "namespace-inferred")
                out.append(ExprCand(ex, end, (0 if forced else 4) + score + penalty))
        return out

    def _consume_n_call_args(self, pos: int, count: int) -> list[tuple[list[ast.Expr], int, int]]:
        # Dynamic-programming frontier avoids both the old 96-candidate truncation and
        # recursion proportional to call arity.
        states: list[tuple[list[ast.Expr], int, int]] = [([], pos, 0)]
        for _ in range(count):
            nxt: list[tuple[list[ast.Expr], int, int]] = []
            dedup: dict[tuple[int, tuple[object, ...]], tuple[list[ast.Expr], int, int]] = {}
            for args, p, score in states:
                choices = list(self.expr_candidates(p))
                if self._pair(p) == "xx":
                    choices.insert(0, ExprCand(ast.DefaultArg(), p + 2, 0))
                for first in choices:
                    nested_penalty = 0
                    if isinstance(first.expr, (ast.AssignExpr, ast.SetIndexExpr)):
                        nested_penalty = 12
                    elif isinstance(first.expr, ast.Call) and first.expr.name in {"co", "ci"}:
                        nested_penalty = 12
                    row = (args + [first.expr], first.end, score + first.score + nested_penalty)
                    key = (first.end, tuple(self._fp(x) for x in row[0]))
                    prior = dedup.get(key)
                    if prior is None or row[2] < prior[2]:
                        dedup[key] = row
            states = list(dedup.values())
            if not states:
                break
        return states if count else [([], pos, 0)]

    def _class_call_candidates(self, name: str, sig: ClassSig, pos: int, alias: str | None = None, root: bool = False) -> list[ExprCand]:
        max_arity = sig.max_arity if sig.max_arity is not None else sig.min_arity
        out: list[ExprCand] = []
        for count in range(max_arity, sig.min_arity - 1, -1):
            for args, end, score in self._consume_n_call_args(pos, count):
                penalty = (count - sig.min_arity) * 3
                ex = ast.ClassCall(name, tuple(args), root) if alias is None else ast.ModuleClassCall(alias, name, tuple(args), "namespace-inferred")
                out.append(ExprCand(ex, end, score + penalty))
        return out

    def _consume_n_exprs(self, pos: int, count: int) -> list[tuple[list[ast.Expr], int, int]]:
        states: list[tuple[list[ast.Expr], int, int]] = [([], pos, 0)]
        for _ in range(count):
            nxt: dict[tuple[int, tuple[object, ...]], tuple[list[ast.Expr], int, int]] = {}
            for items, p, score in states:
                for first in self.expr_candidates(p):
                    row = (items + [first.expr], first.end, score + first.score)
                    key = (first.end, tuple(self._fp(x) for x in row[0]))
                    prior = nxt.get(key)
                    if prior is None or row[2] < prior[2]:
                        nxt[key] = row
            states = list(nxt.values())
            if not states:
                break
        return states if count else [([], pos, 0)]

    def _parse_list(self, bracket_pos: int, frozen: bool) -> tuple[ExprCand, ...]:
        if self._text(bracket_pos) != "[":
            return ()
        if self._text(bracket_pos + 1) == "]":
            return (ExprCand(ast.ListLiteral((), frozen), bracket_pos + 2, 0),)
        out: list[ExprCand] = []
        work: list[tuple[int, tuple[ast.Expr, ...], int]] = [(bracket_pos + 1, (), 0)]
        seen: set[tuple[int, tuple[object, ...]]] = set()
        while work:
            p, items, score = work.pop()
            key=(p, tuple(self._fp(x) for x in items))
            if key in seen: continue
            seen.add(key)
            for e in self.expr_candidates(p):
                if self._text(e.end) == "]":
                    out.append(ExprCand(ast.ListLiteral(items + (e.expr,), frozen), e.end + 1, score + e.score))
                elif self._text(e.end) == ",":
                    work.append((e.end + 1, items + (e.expr,), score + e.score))
        return tuple(self._dedupe_expr(out))

    def _parse_map(self, bracket_pos: int, frozen: bool) -> tuple[ExprCand, ...]:
        if self._text(bracket_pos) != "[":
            return ()
        if self._text(bracket_pos + 1) == ":" and self._text(bracket_pos + 2) == "]":
            return (ExprCand(ast.MapLiteral((), frozen), bracket_pos + 3, 0),)
        out: list[ExprCand] = []
        work: list[tuple[int, tuple[tuple[ast.Expr, ast.Expr], ...], int]]=[(bracket_pos+1,(),0)]
        seen:set[tuple[int, tuple[object,...]]]=set()
        while work:
            p, entries, score = work.pop()
            key=(p, tuple((self._fp(k),self._fp(v)) for k,v in entries))
            if key in seen: continue
            seen.add(key)
            for key_c in self.expr_candidates(p):
                if self._text(key_c.end) != ":": continue
                for value in self.expr_candidates(key_c.end + 1):
                    pair=(key_c.expr,value.expr)
                    subtotal=score+key_c.score+value.score
                    if self._text(value.end)=="]":
                        out.append(ExprCand(ast.MapLiteral(entries+(pair,),frozen),value.end+1,subtotal))
                    elif self._text(value.end)==",":
                        work.append((value.end+1,entries+(pair,),subtotal))
        return tuple(self._dedupe_expr(out))

    def _member_name_at(self, pos: int) -> tuple[str, int] | None:
        if self.tokens[pos].kind == "EXT":
            return self._text(pos), pos + 1
        if self._is_lower(pos):
            return self._text(pos), pos + 1
        return None

    def _method_name_at(self, pos: int) -> tuple[str, int] | None:
        if self._is_lower(pos) and self._is_lower(pos + 1):
            return self._text(pos) + self._text(pos + 1), pos + 2
        return None

    def _module_member_atoms(self, alias: str, p: int, namespace_mode: bool = False) -> list[ExprCand]:
        """Parse a public member from one known module alias.

        `p` points at the first member token, after either `alias.` or the special
        immediate dot following `<:alias`.  When namespace_mode is true the AST keeps
        the originating alias for linking but the formatter may omit that redundant
        qualification because the active namespace already proves it.
        """
        symbols = self.modules.get(alias)
        if symbols is None:
            return []
        out: list[ExprCand] = []

        if self._is_lower(p) and self._is_lower(p + 1):
            name = self._text(p) + self._text(p + 1)
            sig = symbols.callables.get(name)
            if sig is not None:
                q = p + 2
                if self._text(q) == "[":
                    for args, end, score in self._parse_arg_pack(q, allow_default=True):
                        if sig.max_arity is None:
                            ok = len(args) >= sig.min_arity
                        else:
                            ok = sig.min_arity <= len(args) <= sig.max_arity
                        if ok:
                            mode = "namespace-pack" if namespace_mode else "pack"
                            out.append(ExprCand(ast.ModuleCall(alias, name, tuple(args), mode), end, score))
                elif sig.max_arity is not None:
                    for count in range(sig.max_arity, sig.min_arity - 1, -1):
                        for args, end, score in self._consume_n_call_args(q, count):
                            mode = "namespace-inferred" if namespace_mode else "inferred"
                            out.append(ExprCand(ast.ModuleCall(alias, name, tuple(args), mode), end, score + (count - sig.min_arity) * 3))

        mem = self._member_name_at(p)
        if mem and mem[0] in symbols.variables:
            mode = "namespace-member" if namespace_mode else "member"
            out.append(ExprCand(ast.ModuleVar(alias, mem[0], mode), mem[1], 4))

        if self._is_upper(p) and self._is_upper(p + 1):
            name = self._text(p) + self._text(p + 1)
            sig = symbols.classes.get(name)
            if sig is not None:
                q = p + 2
                # Module -> class -> public static member/method. Static methods keep
                # the same hard explicit-pack rule as ordinary `AB.mk[...]` today.
                if self._text(q) == ".":
                    mp = q + 1
                    meth = self._method_name_at(mp)
                    if meth and self._text(meth[1]) == "[":
                        for args, end, score in self._parse_arg_pack(meth[1], allow_default=True):
                            mode = "namespace-pack" if namespace_mode else "pack"
                            out.append(ExprCand(ast.ModuleClassMethodCall(alias, name, meth[0], tuple(args), mode), end, score))
                        return out
                    if meth:
                        msig = sig.method(meth[0], True)
                        if msig is not None and msig.max_arity is not None:
                            for count in range(msig.max_arity, msig.min_arity - 1, -1):
                                for args, end, score in self._consume_n_call_args(meth[1], count):
                                    mode = "namespace-inferred" if namespace_mode else "inferred"
                                    out.append(ExprCand(ast.ModuleClassMethodCall(alias, name, meth[0], tuple(args), mode), end, score + (count-msig.min_arity)*3 + 1))
                    mem = self._member_name_at(mp)
                    if mem:
                        mode = "namespace-member" if namespace_mode else "member"
                        out.append(ExprCand(ast.ModuleClassMember(alias, name, mem[0], mode), mem[1], 0))
                        return out
                if self._text(q) == "[":
                    for args, end, score in self._parse_arg_pack(q, allow_default=True):
                        max_a = sig.max_arity if sig.max_arity is not None else len(args)
                        if sig.min_arity <= len(args) <= max_a:
                            mode = "namespace-pack" if namespace_mode else "pack"
                            out.append(ExprCand(ast.ModuleClassCall(alias, name, tuple(args), mode), end, score))
                else:
                    max_a = sig.max_arity if sig.max_arity is not None else sig.min_arity
                    for count in range(max_a, sig.min_arity - 1, -1):
                        for args, end, score in self._consume_n_call_args(q, count):
                            mode = "namespace-inferred" if namespace_mode else "inferred"
                            out.append(ExprCand(ast.ModuleClassCall(alias, name, tuple(args), mode), end, score + (count - sig.min_arity) * 3))
        return out

    def _module_atoms(self, pos: int) -> list[ExprCand]:
        found = self._module_alias_at(pos)
        if found is None:
            return []
        alias, after_alias = found
        if alias not in self.modules or self._text(after_alias) != ".":
            return []
        return self._module_member_atoms(alias, after_alias + 1, False)

    def _active_namespace_dot_atoms(self, pos: int) -> list[ExprCand]:
        if pos not in self._namespace_tail_dots or self._text(pos) != ".":
            return []
        alias = self._active_namespace(pos)
        if alias is None:
            return []
        return self._module_member_atoms(alias, pos + 1, True)

    def _inferred_method_candidates(self, name: str, pos: int, build) -> list[ExprCand]:
        out: list[ExprCand] = []
        shapes = sorted({(m.min_arity, m.max_arity) for m in self.method_sigs.get(name, ()) if m.max_arity is not None})
        for min_a, max_a in shapes:
            assert max_a is not None
            for count in range(max_a, min_a - 1, -1):
                for args, end, score in self._consume_n_call_args(pos, count):
                    # A known method whose arity fits is a stronger parse than
                    # splitting its first letter into a field plus adjacent values.
                    out.append(ExprCand(build(tuple(args)), end, score + (count - min_a) * 3 - 1))
        return out

    def _current_member_atoms(self, pos: int) -> list[ExprCand]:
        if self._text(pos) != ".":
            return []
        static = self._text(pos + 1) == "."
        p = pos + (2 if static else 1)
        out: list[ExprCand] = []
        meth = self._method_name_at(p)
        if meth and self._text(meth[1]) == "[":
            # Explicit two-letter method + argument pack is a hard postfix form.
            # Do not also reinterpret its first letter as a field; whitespace is
            # meaningless and `..gt[]` must mean the method call, not `.g` + `t`.
            for args, end, score in self._parse_arg_pack(meth[1], allow_default=True):
                out.append(ExprCand(ast.MethodCall(meth[0], tuple(args), None, None, static, False), end, score))
            return out
        if meth:
            out.extend(self._inferred_method_candidates(meth[0], meth[1], lambda args: ast.MethodCall(meth[0], args, None, None, static, False)))
        mem = self._member_name_at(p)
        if mem:
            out.append(ExprCand(ast.MemberExpr(mem[0], None, None, static), mem[1], 0))
        return out

    def _class_member_atoms(self, pos: int) -> list[ExprCand]:
        if not (self._is_upper(pos) and self._is_upper(pos + 1) and self._text(pos + 2) == "."):
            return []
        cls = self._text(pos) + self._text(pos + 1)
        p = pos + 3
        out: list[ExprCand] = []
        meth = self._method_name_at(p)
        if meth and self._text(meth[1]) == "[":
            for args, end, score in self._parse_arg_pack(meth[1], allow_default=True):
                out.append(ExprCand(ast.MethodCall(meth[0], tuple(args), None, cls, True, False), end, score))
            return out
        if meth:
            out.extend(self._inferred_method_candidates(meth[0], meth[1], lambda args: ast.MethodCall(meth[0], args, None, cls, True, False)))
        mem = self._member_name_at(p)
        if mem:
            out.append(ExprCand(ast.MemberExpr(mem[0], None, cls, True), mem[1], 0))
        return out

    def _super_method_atoms(self, pos: int) -> list[ExprCand]:
        if self._text(pos) != "^^" or self._text(pos + 1) != ".":
            return []
        p = pos + 2
        meth = self._method_name_at(p)
        if not meth:
            return []
        out: list[ExprCand] = []
        if self._text(meth[1]) == "[":
            for args, end, score in self._parse_arg_pack(meth[1], allow_default=True):
                out.append(ExprCand(ast.MethodCall(meth[0], tuple(args), None, None, False, True), end, score))
            return out
        out.extend(self._inferred_method_candidates(meth[0], meth[1], lambda args: ast.MethodCall(meth[0], args, None, None, False, True)))
        return out

    def _member_suffix(self, base: ast.Expr, dot_pos: int, score: int = 0) -> list[ExprCand]:
        if self._text(dot_pos) != ".":
            return []
        p = dot_pos + 1
        out: list[ExprCand] = []
        meth = self._method_name_at(p)
        if meth and self._text(meth[1]) == "[":
            for args, end, extra in self._parse_arg_pack(meth[1], allow_default=True):
                out.append(ExprCand(ast.MethodCall(meth[0], tuple(args), base, None, False, False), end, score + extra))
            return out
        if meth:
            out.extend(self._inferred_method_candidates(meth[0], meth[1], lambda args: ast.MethodCall(meth[0], args, base, None, False, False)))
        mem = self._member_name_at(p)
        if mem:
            out.append(ExprCand(ast.MemberExpr(mem[0], base, None, False), mem[1], score))
        return out

    def _postfix_chain(self, base: ast.Expr, pos: int, score: int = 0) -> list[ExprCand]:
        direct: list[ExprCand] = []
        if self._text(pos) == "[":
            direct.extend(self._parse_access_suffix(base, pos, score))
        if self._text(pos) == ".":
            direct.extend(self._member_suffix(base, pos, score))
        out = list(direct)
        for cand in direct:
            out.extend(self._postfix_chain(cand.expr, cand.end, cand.score))
        return self._dedupe_expr(out)

    def _access_chain(self, base: ast.Expr, pos: int, score: int = 0) -> list[ExprCand]:
        """Return one-or-more postfix index/slice continuations for *base*."""
        if self._text(pos) != "[":
            return []
        direct = self._parse_access_suffix(base, pos, score)
        out = list(direct)
        for cand in direct:
            out.extend(self._postfix_chain(cand.expr, cand.end, cand.score))
        return self._dedupe_expr(out)

    def _parse_access_suffix(self, base: ast.Expr, bracket_pos: int, score: int = 0) -> list[ExprCand]:
        if self._text(bracket_pos) != "[":
            return []
        p = bracket_pos + 1
        out: list[ExprCand] = []

        def finish_slice(start_expr: ast.Expr | None, after_colon: int, subtotal: int) -> None:
            # x[a:] / x[:]
            if self._text(after_colon) == "]":
                out.append(ExprCand(ast.SliceExpr(base, start_expr, None, None), after_colon + 1, subtotal))
                return
            # x[a::step] / x[::step]
            if self._text(after_colon) == ":":
                parse_step(start_expr, None, after_colon + 1, subtotal)
                return
            for stop_c in self.expr_candidates(after_colon):
                if self._text(stop_c.end) == "]":
                    out.append(ExprCand(ast.SliceExpr(base, start_expr, stop_c.expr, None), stop_c.end + 1, subtotal + stop_c.score))
                elif self._text(stop_c.end) == ":":
                    parse_step(start_expr, stop_c.expr, stop_c.end + 1, subtotal + stop_c.score)

        def parse_step(start_expr: ast.Expr | None, stop_expr: ast.Expr | None, step_pos: int, subtotal: int) -> None:
            if self._text(step_pos) == "]":
                out.append(ExprCand(ast.SliceExpr(base, start_expr, stop_expr, None), step_pos + 1, subtotal))
                return
            for step_c in self.expr_candidates(step_pos):
                if self._text(step_c.end) == "]":
                    out.append(ExprCand(ast.SliceExpr(base, start_expr, stop_expr, step_c.expr), step_c.end + 1, subtotal + step_c.score))

        # omitted start
        if self._text(p) == ":":
            finish_slice(None, p + 1, score)
            return out

        # index or explicit-start slice
        for first in self.expr_candidates(p):
            if self._text(first.end) == "]":
                out.append(ExprCand(ast.IndexExpr(base, first.expr), first.end + 1, score + first.score))
            elif self._text(first.end) == ":":
                finish_slice(first.expr, first.end + 1, score + first.score)
        return out

    def _member_target_candidates(self, pos: int) -> tuple[ExprCand, ...]:
        out: list[ExprCand] = []
        # Current .x / ..x. Only single-char or extended names are fields.
        if self._text(pos) == ".":
            static = self._text(pos + 1) == "."
            p = pos + (2 if static else 1)
            mem = self._member_name_at(p)
            if mem:
                out.append(ExprCand(ast.MemberExpr(mem[0], None, None, static), mem[1], 0))
        # AB.x static target.
        if self._is_upper(pos) and self._is_upper(pos + 1) and self._text(pos + 2) == ".":
            mem = self._member_name_at(pos + 3)
            if mem:
                out.append(ExprCand(ast.MemberExpr(mem[0], None, self._text(pos)+self._text(pos+1), True), mem[1], 0))
        # a.x / _obj_.x and nested object fields. Start from an assignable lexical root.
        base = self._single_target_expr(pos)
        if base is not None and self._text(base[1]) == ".":
            for c in self._member_suffix(base[0], base[1], 0):
                if isinstance(c.expr, ast.MemberExpr):
                    out.append(c)
        return tuple(self._dedupe_expr(out))

    def _index_target_candidates(self, pos: int) -> tuple[ExprCand, ...]:
        base = self._single_target_expr(pos)
        if base is None or self._text(base[1]) != "[":
            return ()
        cands = self._access_chain(base[0], base[1], 0)
        return tuple(c for c in cands if isinstance(c.expr, ast.IndexExpr))

    def _parse_arg_pack(self, bracket_pos: int, allow_default: bool = False) -> list[tuple[list[ast.Expr], int, int]]:
        if self._text(bracket_pos) != "[": return []
        if self._text(bracket_pos + 1) == "]": return [([], bracket_pos + 2, 0)]
        out: list[tuple[list[ast.Expr], int, int]]=[]
        work:list[tuple[int,list[ast.Expr],int]]=[(bracket_pos+1,[],0)]
        seen:set[tuple[int,tuple[object,...]]]=set()
        while work:
            p,items,score=work.pop()
            key=(p,tuple(self._fp(x) for x in items))
            if key in seen: continue
            seen.add(key)
            choices=list(self.expr_candidates(p))
            if allow_default and self._pair(p)=="xx": choices.insert(0,ExprCand(ast.DefaultArg(),p+2,0))
            for e in choices:
                row=items+[e.expr]
                if self._text(e.end)=="]": out.append((row,e.end+1,score+e.score))
                elif self._text(e.end)==",": work.append((e.end+1,row,score+e.score))
        return out

    def _target_list(self, pos: int) -> tuple[list[str], list[str | None], int] | None:
        """Parse lexical assignment targets plus optional binding contracts.

        Contracts are suffixes on individual binding names, e.g. ``a@i8:=7F$`` or
        ``a@ib@u8:=...``.  The annotation is unambiguous here because this routine
        only succeeds when the entire target run is followed by an assignment
        operator.  Two-lowercase callable spelling remains untouched elsewhere.
        """
        names: list[str] = []
        types: list[str | None] = []
        i = pos
        while self._is_lower(i) or self.tokens[i].kind == "EXT":
            names.append(self._text(i))
            i += 1
            type_code = None
            if self._text(i) == "@":
                type_code, end = self._parse_type_code(i)
                if type_code is None:
                    return None
                i = end
            types.append(type_code)
        if names and self._text(i) in {"=", ":=", "::="}:
            return names, types, i
        return None

    def _single_target_expr(self, pos: int) -> tuple[ast.Expr, int] | None:
        if self._is_lower(pos):
            return ast.Var(self._text(pos)), pos + 1
        if self.tokens[pos].kind == "EXT":
            return ast.ExtendedName(self._text(pos)), pos + 1
        return None

    def _scan_decimal_terminated(self, pos: int) -> tuple[str, int] | None:
        i = pos
        pieces: list[str] = []
        while i < len(self.tokens) and self.tokens[i].kind == "DIGIT":
            pieces.append(self.tokens[i].text)
            i += 1
        if pieces and self._text(i) == "$":
            return "".join(pieces), i + 1
        return None

    def _parse_type_code(self, at_pos: int) -> tuple[str | None, int]:
        if self._text(at_pos) != "@" or not self._is_lower(at_pos + 1):
            return None, at_pos
        base = self._text(at_pos + 1)
        if base not in {"i", "u", "f", "s", "b"}:
            return None, at_pos

        # Whitespace is not a delimiter.  Consume the *whole contiguous digit run* as
        # a width only when that complete run is a valid width.  Thus ungrouped
        # ``@i87F$`` is plain ``@i(87F$)`` rather than a guessed i8 cast.  The explicit
        # form ``@i8|7F$|`` puts `|` after the 8, making the width unambiguous.
        widths = {
            "i": {"8", "16", "32", "64"},
            "u": {"8", "16", "32", "64"},
            "f": {"64"},
            "s": set(),
            "b": set(),
        }
        start = at_pos + 2
        i = start
        digits: list[str] = []
        while self.tokens[i].kind == "DIGIT":
            digits.append(self._text(i)); i += 1
        width = "".join(digits)
        if width and width in widths[base]:
            return base + width, i
        return base, start

    def _skip_type_code(self, at_pos: int) -> int:
        _, end = self._parse_type_code(at_pos)
        return end

    @staticmethod
    def _decode_string_body(body: str) -> str:
        out: list[str] = []
        i = 0
        escapes = {
            "n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\",
            "'": "'", '"': '"', "{": "{", "}": "}",
        }
        while i < len(body):
            if body[i] != "\\":
                out.append(body[i]); i += 1; continue
            if i + 1 >= len(body):
                raise ParseError("trailing backslash in string literal")
            c = body[i + 1]
            if c not in escapes:
                raise ParseError(f"unknown string escape \\{c}")
            out.append(escapes[c])
            i += 2
        return "".join(out)

    @classmethod
    def _decode_string(cls, raw: str) -> str:
        return cls._decode_string_body(raw[1:-1])

    @classmethod
    def _decode_static_string(cls, raw: str, *, purpose: str = "compile-time string") -> str:
        """Decode a string that must not contain interpolation.

        Imports and other compile-time identifiers have to be available before normal
        expression evaluation, so accepting ``{expr}`` there would make module identity
        depend on runtime state. Escaped braces remain ordinary literal characters.
        """
        body = raw[1:-1]
        i = 0
        while i < len(body):
            if body[i] == "\\":
                i += 2
                continue
            if body[i] in "{}":
                raise ParseError(f"{purpose} cannot contain interpolation; escape literal braces")
            i += 1
        return cls._decode_string_body(body)

    @staticmethod
    def _matching_interp_brace(body: str, start: int) -> int:
        """Return the matching ``}`` for ``body[start] == '{'``.

        The outer lexer has already validated the same structure.  Repeating the
        small scanner here lets the parser split literal/interpolation segments
        without losing nested lambda blocks, nested strings, or nested block comments.
        """
        depth = 1
        i = start + 1
        n = len(body)
        while i < n:
            c = body[i]
            if c == "'":
                i += 1
                while i < n:
                    if body[i] == "\\":
                        i += 2; continue
                    if body[i] == "'":
                        i += 1; break
                    i += 1
                continue
            if body.startswith("#*", i):
                cd = 1; i += 2
                while i < n and cd:
                    if body.startswith("#*", i): cd += 1; i += 2; continue
                    if body.startswith("*#", i): cd -= 1; i += 2; continue
                    i += 1
                continue
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: return i
            i += 1
        raise ParseError("unterminated string interpolation")

    def _parse_interpolation_expr(self, source: str, outer_pos: int) -> ast.Expr:
        if not source.strip():
            raise ParseError("empty string interpolation", span=self._span(self.tokens[outer_pos]))
        # Local import avoids making the low-level token module dependency cyclic.
        from .lexer import lex
        tokens = lex(source)
        inner = Parser(tokens, source, self.symbols, self.modules)
        # An interpolation inherits the lexical namespace active at the containing
        # string.  Namespace directives themselves are statements and therefore are
        # not meaningful inside a one-expression interpolation.
        active = self._namespace_at[outer_pos] if outer_pos < len(self._namespace_at) else None
        inner._namespace_at = [active] * len(tokens)
        choices = [c for c in inner.expr_candidates(0) if inner.tokens[c.end].kind == "EOF"]
        if not choices:
            raise ParseError("string interpolation does not form one complete SLUG expression", span=self._span(self.tokens[outer_pos]))
        score = min(c.score for c in choices)
        best = inner._dedupe_expr(c for c in choices if c.score == score)
        if len(best) != 1:
            raise AmbiguityError(
                f"string interpolation has {len(best)} equally preferred parses; add an explicit disambiguator",
                span=self._span(self.tokens[outer_pos]),
            )
        return best[0].expr

    def _parse_string_expr(self, raw: str, outer_pos: int) -> ast.Expr:
        body = raw[1:-1]
        parts: list[str | ast.Expr] = []
        literal_start = 0
        i = 0
        saw_interpolation = False
        while i < len(body):
            if body[i] == "\\":
                if i + 1 >= len(body):
                    raise ParseError("trailing backslash in string literal", span=self._span(self.tokens[outer_pos]))
                i += 2
                continue
            if body[i] == "}":
                raise ParseError("literal '}' in a formatted string must be escaped as \\}", span=self._span(self.tokens[outer_pos]))
            if body[i] != "{":
                i += 1
                continue
            saw_interpolation = True
            if i > literal_start:
                parts.append(self._decode_string_body(body[literal_start:i]))
            end = self._matching_interp_brace(body, i)
            inner_source = body[i + 1:end]
            parts.append(self._parse_interpolation_expr(inner_source, outer_pos))
            i = end + 1
            literal_start = i
        if not saw_interpolation:
            return ast.Literal("string", self._decode_string_body(body), raw)
        if literal_start < len(body):
            parts.append(self._decode_string_body(body[literal_start:]))
        return ast.FormattedString(tuple(parts))

    def _pair(self, pos: int) -> str:
        if self._is_lower(pos) and self._is_lower(pos + 1):
            return self._text(pos) + self._text(pos + 1)
        return ""

    def _text(self, pos: int) -> str:
        if pos < 0 or pos >= len(self.tokens):
            return ""
        return self.tokens[pos].text

    def _is_lower(self, pos: int) -> bool:
        return 0 <= pos < len(self.tokens) and self.tokens[pos].kind == "LOWER"

    def _is_upper(self, pos: int) -> bool:
        return 0 <= pos < len(self.tokens) and self.tokens[pos].kind == "UPPER"

    def _fp(self, value):
        """Cheap cached structural fingerprint for immutable AST nodes.

        Dataclass-generated __hash__ recursively re-hashes the entire subtree every
        time a sequence candidate is deduplicated. On the ambiguity gauntlet that can
        mean tens of millions of repeated child hashes. Fingerprint each AST object
        once, then reuse the compact tuple.
        """
        if isinstance(value, ast.Node):
            oid=id(value)
            cached=self._fp_cache.get(oid)
            if cached is not None and cached[0] is value:return cached[1]
            fp=(type(value).__name__,)+tuple((f.name,self._fp(getattr(value,f.name))) for f in fields(value))
            self._fp_cache[oid]=(value,fp)
            return fp
        if isinstance(value, tuple):return tuple(self._fp(x) for x in value)
        if isinstance(value, list):return tuple(self._fp(x) for x in value)
        return value

    def _dedupe_expr(self, items: Iterable[ExprCand]) -> list[ExprCand]:
        best: dict[tuple[object, int], ExprCand] = {}
        for x in items:
            key = (self._fp(x.expr), x.end)
            if key not in best or x.score < best[key].score:
                best[key] = x
        return sorted(best.values(), key=lambda x: (x.end, x.score))

    def _dedupe_stmt(self, items: Iterable[StmtCand]) -> list[StmtCand]:
        best: dict[tuple[object, int], StmtCand] = {}
        for x in items:
            key = (self._fp(x.stmt), x.end)
            if key not in best or x.score < best[key].score:
                best[key] = x
        return sorted(best.values(), key=lambda x: (x.end, x.score))

    def _dedupe_seq(self, items: Iterable[SeqCand]) -> list[SeqCand]:
        best: dict[tuple[tuple[object, ...], int], SeqCand] = {}
        for x in items:
            key = (tuple(self._fp(st) for st in x.statements), x.end)
            if key not in best or x.score < best[key].score:
                best[key] = x
        return sorted(best.values(), key=lambda x: (x.end, x.score))

    @staticmethod
    def _span(tok: Token) -> Span:
        return Span(tok.start, tok.end, tok.line, tok.column)


def parse(tokens: list[Token], source: str = "", symbols: Symbols | None = None, modules: dict[str, Symbols] | None = None) -> ast.Program:
    """Parse one complete source unit with predictable cyclic-GC behavior.

    Ambiguity exploration creates self-recursive local helper closures.  On large SLUG
    programs Python's automatic cyclic collector can otherwise fire mid-search and turn
    a few-second parse into a very long pause.  Disable cyclic collection only for the
    search, release the Parser (and therefore its candidate caches), then collect after
    it is genuinely unreachable.  Reference-counted objects are still reclaimed
    normally while GC is disabled.
    """
    gc_was_enabled = gc.isenabled()
    old_recursion = sys.getrecursionlimit()
    needed_recursion = max(old_recursion, 4096 + len(tokens) * 64)
    if needed_recursion != old_recursion:
        sys.setrecursionlimit(needed_recursion)
    if gc_was_enabled:
        gc.disable()
    parser = Parser(tokens, source, symbols, modules)
    try:
        result = parser.parse()
    finally:
        # Drop the parser before collecting; collecting from Parser.parse() itself
        # merely scans the still-live candidate graph and cannot reclaim it.
        del parser
        if gc_was_enabled:
            gc.enable()
            gc.collect()
        if needed_recursion != old_recursion:
            sys.setrecursionlimit(old_recursion)
    return result

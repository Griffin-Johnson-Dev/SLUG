from __future__ import annotations

"""Optimizer-oriented CFG/SSA MIR for SLUG.

v0.1.5 retains and extends v0.1.4, which lowers the typed v0.1.3 HIR into explicit basic blocks and SSA binding
versions.  The HIR remains the semantic/type fact boundary; MIR is deliberately
less source-shaped and is the surface consumed by optimization passes.

Control-flow lowering is AST-aware through the checked program retained by HIR.
That is intentional: the v0.1.3 textual HIR used compact structured markers and
cannot by itself distinguish loop-header re-evaluation from straight-line
execution.  Optimizers therefore never need to understand parser ambiguity, but
CFG construction still has access to the checked structured program that created
those HIR facts.
"""

from dataclasses import dataclass, field
from typing import Iterable

from . import ast
from .builtins import is_builtin
from .ir import IRModule, TypeFact, join_types, lower_ir


@dataclass(frozen=True, slots=True)
class MIRInstr:
    result: str | None
    op: str
    args: tuple[str, ...] = ()
    type: TypeFact = TypeFact()
    detail: str | None = None
    source_id: int | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class MIRPhi:
    result: str
    binding: str
    incoming: tuple[tuple[str, str], ...]
    type: TypeFact = TypeFact()


@dataclass(frozen=True, slots=True)
class MIRTerminator:
    op: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MIRBlock:
    label: str
    phis: tuple[MIRPhi, ...]
    instructions: tuple[MIRInstr, ...]
    terminator: MIRTerminator


@dataclass(frozen=True, slots=True)
class MIRFunction:
    name: str
    params: tuple[tuple[str, str, TypeFact], ...]
    returns: tuple[TypeFact, ...] | None
    blocks: tuple[MIRBlock, ...]


@dataclass(frozen=True, slots=True)
class MIRModule:
    top: MIRFunction
    functions: tuple[MIRFunction, ...]


@dataclass(slots=True)
class _Binding:
    value: str
    type: TypeFact = TypeFact()
    depth: int = 0
    parent: "_Binding | None" = None


@dataclass(slots=True)
class _PhiBuild:
    result: str
    binding: str
    incoming: list[tuple[str, str]]
    type: TypeFact


@dataclass(slots=True)
class _BlockBuild:
    label: str
    phis: list[_PhiBuild] = field(default_factory=list)
    instructions: list[MIRInstr] = field(default_factory=list)
    terminator: MIRTerminator | None = None


@dataclass(slots=True)
class _LoopContext:
    header: str
    exit: str
    phi_by_name: dict[str, _PhiBuild]
    scope_depth: int
    continues: list[tuple[str, dict[str, _Binding]]] = field(default_factory=list)
    breaks: list[tuple[str, dict[str, _Binding]]] = field(default_factory=list)


class _FunctionBuilder:
    def __init__(self, module_builder: "_MIRBuilder", name: str, params: tuple[tuple[str, TypeFact], ...], returns: tuple[TypeFact, ...] | None):
        self.mb = module_builder
        self.name = name
        self.returns = returns
        self.value_counter = 0
        self.block_counter = 0
        self.blocks: list[_BlockBuild] = []
        self.by_label: dict[str, _BlockBuild] = {}
        self.current = self._new_block("entry", exact=True)
        self.params: list[tuple[str, str, TypeFact]] = []
        self.env: dict[str, _Binding] = {}
        self.loops: list[_LoopContext] = []
        self.scope_depth = 0
        for pname, ptype in params:
            value = self._value("p")
            self.params.append((pname, value, ptype))
            self.env[pname] = _Binding(value, ptype, 0, None)

    def _value(self, prefix: str = "t") -> str:
        self.value_counter += 1
        return f"%{prefix}{self.value_counter}"

    def _new_block(self, hint: str, *, exact: bool = False) -> _BlockBuild:
        if exact:
            label = hint
        else:
            self.block_counter += 1
            label = f"{hint}.{self.block_counter}"
        b = _BlockBuild(label)
        self.blocks.append(b)
        self.by_label[label] = b
        return b

    def _switch(self, block: _BlockBuild) -> None:
        self.current = block

    def _emit(self, op: str, args: tuple[str, ...] = (), type: TypeFact = TypeFact(), detail: str | None = None, source: ast.Node | None = None, result: bool = True) -> str | None:
        r = self._value() if result else None
        self.current.instructions.append(MIRInstr(r, op, args, type, detail, id(source) if source is not None else None))
        return r

    def _terminate(self, op: str, *args: str) -> None:
        if self.current.terminator is None:
            self.current.terminator = MIRTerminator(op, tuple(args))

    @staticmethod
    def _copy_env(env: dict[str, _Binding]) -> dict[str, _Binding]:
        return {k: _Binding(v.value, v.type, v.depth, v.parent) for k, v in env.items()}

    @staticmethod
    def _env_at_depth(env: dict[str, _Binding], depth: int) -> dict[str, _Binding]:
        out: dict[str, _Binding] = {}
        for name, binding in env.items():
            cur: _Binding | None = binding
            while cur is not None and cur.depth > depth:
                cur = cur.parent
            if cur is not None and cur.depth <= depth:
                out[name] = _Binding(cur.value, cur.type, cur.depth, cur.parent)
        return out

    def _type(self, node: ast.Expr) -> TypeFact:
        return self.mb.hir.expr_types.get(id(node), TypeFact())

    def _undef(self, name: str) -> _Binding:
        return _Binding(f"@undef:{name}", TypeFact(), self.scope_depth, None)

    def _merge_env(self, block: _BlockBuild, incoming: list[tuple[str, dict[str, _Binding]]]) -> dict[str, _Binding]:
        if not incoming:
            return {}
        names: set[str] = set()
        for _, env in incoming:
            names.update(env)
        merged: dict[str, _Binding] = {}
        for name in sorted(names):
            vals = [(pred, env.get(name, self._undef(name))) for pred, env in incoming]
            first = vals[0][1]
            if all(v.value == first.value for _, v in vals[1:]):
                merged[name] = _Binding(first.value, first.type, first.depth, first.parent)
                continue
            typ = first.type
            for _, v in vals[1:]:
                typ = self.mb.join_typefacts(typ, v.type)
            r = self._value("v")
            phi = _PhiBuild(r, name, [(p, v.value) for p, v in vals], typ)
            block.phis.append(phi)
            depth = first.depth
            parent = first.parent
            merged[name] = _Binding(r, typ, depth, parent)
        return merged

    def _bind(self, name: str, value: str, typ: TypeFact, detail: str | None, source: ast.Node, env: dict[str, _Binding], *, define: bool) -> str:
        r = self._emit("bind", (value,), typ, f"{name}" + (f" {detail}" if detail else ""), source)
        assert r is not None
        prior = env.get(name)
        if define:
            if prior is not None and prior.depth == self.scope_depth:
                depth, parent = prior.depth, prior.parent
            else:
                depth, parent = self.scope_depth, prior
        else:
            # Nearest-scope `=` updates the visible cell. An unresolved name here is
            # module/capture state from outside the MIR function.
            if prior is not None:
                depth, parent = prior.depth, prior.parent
            else:
                depth, parent = -1, None
        env[name] = _Binding(r, typ, depth, parent)
        return r

    def _clobber_env(self, env: dict[str, _Binding], reason: str) -> None:
        # Until interprocedural effect summaries exist, an arbitrary user/closure/
        # method/constructor call may mutate module state or a captured lexical cell.
        # Give every visible binding a fresh unknown SSA version rather than carrying
        # a stale constant across that effect boundary.
        for name in sorted(tuple(env)):
            old = env[name]
            r = self._emit("clobber", (name, old.value), old.type, reason)
            assert r is not None
            env[name] = _Binding(r, old.type, old.depth, old.parent)

    def expr(self, e: ast.Expr, env: dict[str, _Binding]) -> str:
        typ = self._type(e)
        if isinstance(e, ast.Literal):
            r = self._emit("const", (repr(e.value),), typ, e.kind, e)
            assert r is not None
            return r
        if isinstance(e, ast.FormattedString):
            vals: list[str] = []
            for part in e.parts:
                if isinstance(part, str):
                    r0 = self._emit("const", (repr(part),), TypeFact("s"), "string")
                    assert r0 is not None
                    vals.append(r0)
                else:
                    x = self.expr(part, env)
                    r0 = self._emit("cast", (x,), TypeFact("s"), "s", part)
                    assert r0 is not None
                    vals.append(r0)
            r = self._emit("format.string", tuple(vals), TypeFact("s"), None, e)
            assert r is not None
            return r
        if isinstance(e, (ast.Var, ast.ExtendedName)):
            b = env.get(e.name)
            if b is not None:
                return b.value
            r = self._emit("load", (e.name,), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.Cast):
            x = self.expr(e.value, env)
            r = self._emit("cast", (x,), typ, e.type_code, e)
            assert r is not None
            return r
        if isinstance(e, ast.DynamicCast):
            tc = self.expr(e.type_expr, env)
            x = self.expr(e.value, env)
            r = self._emit("dynamic.cast", (tc, x), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.Unary):
            x = self.expr(e.value, env)
            r = self._emit("unary." + e.op, (x,), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.Binary):
            a = self.expr(e.left, env)
            b = self.expr(e.right, env)
            r = self._emit("binary." + e.op, (a, b), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.BoolExpr):
            x = self.expr(e.value, env)
            r = self._emit("truthy", (x,), TypeFact("b"), None, e)
            assert r is not None
            return r
        if isinstance(e, ast.LogicNot):
            x = self.expr(e.value, env)
            r = self._emit("logic.not", (x,), TypeFact("b"), None, e)
            assert r is not None
            return r
        if isinstance(e, ast.Compare):
            a = self.expr(e.left, env)
            b = self.expr(e.right, env)
            r = self._emit("cmp." + e.op, (a, b), TypeFact("b"), None, e)
            assert r is not None
            return r
        if isinstance(e, ast.LogicBinary):
            # Short-circuiting is represented as real CFG so a RHS assignment/call is
            # not accidentally made unconditional by optimization lowering.
            left = self.expr(e.left, env)
            left_bool = self._emit("truthy", (left,), TypeFact("b"), None, e.left)
            assert left_bool is not None
            pre_env = self._copy_env(env)
            rhs = self._new_block("logic.rhs")
            short = self._new_block("logic.short")
            merge = self._new_block("logic.merge")
            pred = self.current.label
            if e.op == "and":
                self._terminate("branch", left_bool, rhs.label, short.label)
                short_value = "@bool:false"
            else:
                self._terminate("branch", left_bool, short.label, rhs.label)
                short_value = "@bool:true"

            self._switch(short)
            short_env = self._copy_env(pre_env)
            self._terminate("jump", merge.label)
            short_pred = short.label

            self._switch(rhs)
            rhs_env = self._copy_env(pre_env)
            rv = self.expr(e.right, rhs_env)
            rb = self._emit("truthy", (rv,), TypeFact("b"), None, e.right)
            assert rb is not None
            rhs_pred = self.current.label
            if self.current.terminator is None:
                self._terminate("jump", merge.label)

            self._switch(merge)
            merged = self._merge_env(merge, [(short_pred, short_env), (rhs_pred, rhs_env)])
            env.clear(); env.update(merged)
            result = self._value("v")
            merge.phis.insert(0, _PhiBuild(result, "<logic>", [(short_pred, short_value), (rhs_pred, rb)], TypeFact("b")))
            return result
        if isinstance(e, ast.AssignExpr):
            value = self.expr(e.value, env)
            contracts = self.mb.hir.assignment_contracts.get(id(e), (None,) * len(e.targets))
            out_value = value
            for i, name in enumerate(e.targets):
                c = contracts[i] if i < len(contracts) else None
                bt = TypeFact.from_code(c) if c else self._type(e.value)
                detail = ("immutable" if e.op == "::=" else "mutable") + (f" @{c}" if c else "")
                out_value = self._bind(name, value, bt, detail, e, env, define=True)
            return out_value
        if isinstance(e, ast.ListLiteral):
            args = tuple(self.expr(x, env) for x in e.items)
            r = self._emit("list", args, TypeFact("list"), "frozen" if e.frozen else None, e)
            assert r is not None
            return r
        if isinstance(e, ast.MapLiteral):
            args: list[str] = []
            for k, v in e.entries:
                args.extend((self.expr(k, env), self.expr(v, env)))
            r = self._emit("map", tuple(args), TypeFact("map"), "frozen" if e.frozen else None, e)
            assert r is not None
            return r
        if isinstance(e, ast.IndexExpr):
            a = self.expr(e.base, env); b = self.expr(e.index, env)
            r = self._emit("index", (a, b), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.SliceExpr):
            vals = [self.expr(e.base, env)]
            for x in (e.start, e.stop, e.step):
                vals.append(self.expr(x, env) if x is not None else "@null")
            r = self._emit("slice", tuple(vals), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.SetIndexExpr):
            a = self.expr(e.target.base, env); b = self.expr(e.target.index, env); v = self.expr(e.value, env)
            r = self._emit("setindex", (a, b, v), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.Call):
            args = tuple("@default" if isinstance(a, ast.DefaultArg) else self.expr(a, env) for a in e.args)
            r = self._emit("call", (e.name,) + args, typ, None, e)
            assert r is not None
            user_defined = any(isinstance(st, ast.FunctionDecl) and st.name == e.name for st in self.mb.program.statements)
            if user_defined or not is_builtin(e.name):
                self._clobber_env(env, f"call {e.name}")
            return r
        if isinstance(e, ast.ClassCall):
            args = tuple(self.expr(a, env) for a in e.args)
            r = self._emit("new", (e.name,) + args, typ, None, e)
            assert r is not None
            self._clobber_env(env, f"new {e.name}")
            return r
        if isinstance(e, ast.CallableInvoke):
            c = self.expr(e.callee, env); args = tuple(self.expr(a, env) for a in e.args)
            r = self._emit("invoke", (c,) + args, typ, None, e)
            assert r is not None
            self._clobber_env(env, "callable invoke")
            return r
        if isinstance(e, ast.LambdaExpr):
            lname = self.mb.lower_lambda(e)
            r = self._emit("lambda", (lname,), TypeFact("callable"), None, e)
            assert r is not None
            return r
        if isinstance(e, ast.MemberExpr):
            base = self.expr(e.base, env) if e.base is not None else (e.class_name or ("@static" if e.static else "@self"))
            r = self._emit("member", (base, e.name), typ, None, e)
            assert r is not None
            return r
        if isinstance(e, ast.MethodCall):
            base = self.expr(e.receiver, env) if e.receiver is not None else (e.class_name or ("@super" if e.super_call else "@self"))
            args = tuple(self.expr(a, env) for a in e.args)
            r = self._emit("method", (base, e.name) + args, typ, None, e)
            assert r is not None
            self._clobber_env(env, f"method {e.name}")
            return r
        if isinstance(e, ast.SetMemberExpr):
            value = self.expr(e.value, env)
            r = self._emit("setmember", (e.target.name, value), typ, "immutable" if e.immutable else None, e)
            assert r is not None
            return r
        if isinstance(e, ast.DefaultArg):
            return "@default"
        r = self._emit("dynamic", (), typ, type(e).__name__, e)
        assert r is not None
        return r

    def _lower_if(self, s: ast.IfStmt, env: dict[str, _Binding]) -> None:
        # Every brace body is a lexical child scope. `:=` therefore shadows a
        # same-named outer binding, while nearest-scope `=` still updates it.
        # Export only bindings visible at the parent depth into the CFG merge.
        parent_depth = self.scope_depth
        merge = self._new_block("if.merge")
        incoming: list[tuple[str, dict[str, _Binding]]] = []
        cases = [(s.condition, s.body), *list(s.elifs)]
        fall_env = self._copy_env(env)

        for index, (cond, body) in enumerate(cases):
            cond_env = self._copy_env(fall_env)
            cv = self.expr(cond, cond_env)
            cond_pred = self.current.label
            then = self._new_block("if.then")
            is_last = index + 1 == len(cases)
            if not is_last or s.else_body is not None:
                false_block = self._new_block("if.next")
            else:
                false_block = merge
            self._terminate("branch", cv, then.label, false_block.label)

            self._switch(then)
            then_env = self._copy_env(cond_env)
            self.scope_depth = parent_depth + 1
            try:
                self.stmts(body, then_env)
            finally:
                self.scope_depth = parent_depth
            if self.current.terminator is None:
                pred = self.current.label
                self._terminate("jump", merge.label)
                incoming.append((pred, self._env_at_depth(then_env, parent_depth)))

            fall_env = self._copy_env(cond_env)
            if false_block is merge:
                incoming.append((cond_pred, self._copy_env(fall_env)))
                break
            self._switch(false_block)

        if s.else_body is not None:
            else_env = self._copy_env(fall_env)
            self.scope_depth = parent_depth + 1
            try:
                self.stmts(s.else_body, else_env)
            finally:
                self.scope_depth = parent_depth
            if self.current.terminator is None:
                pred = self.current.label
                self._terminate("jump", merge.label)
                incoming.append((pred, self._env_at_depth(else_env, parent_depth)))

        self._switch(merge)
        env.clear(); env.update(self._merge_env(merge, incoming))

    def _assigned_names(self, nodes: Iterable[ast.Node] | ast.Node) -> set[str]:
        out: set[str] = set()
        def walk(x: object) -> None:
            if isinstance(x, ast.AssignExpr):
                out.update(x.targets); walk(x.value); return
            if isinstance(x, ast.AssignStmt):
                out.update(x.targets); walk(x.value); return
            if isinstance(x, ast.MutateStmt) and isinstance(x.target, (ast.Var, ast.ExtendedName)):
                out.add(x.target.name); return
            if isinstance(x, ast.ForStmt) and x.var:
                out.add(x.var)
            if isinstance(x, ast.Node):
                for fname in x.__dataclass_fields__:
                    walk(getattr(x, fname))
            elif isinstance(x, (tuple, list)):
                for y in x: walk(y)
        walk(nodes)
        return out

    def _prepare_loop_header(self, env: dict[str, _Binding], assigned: set[str], hint: str) -> tuple[_BlockBuild, dict[str, _Binding], dict[str, _PhiBuild], str]:
        pre_label = self.current.label
        header = self._new_block(hint)
        self._terminate("jump", header.label)
        henv = self._copy_env(env)
        phis: dict[str, _PhiBuild] = {}
        for name in sorted(assigned):
            initial = henv.get(name, self._undef(name))
            r = self._value("v")
            phi = _PhiBuild(r, name, [(pre_label, initial.value)], initial.type)
            header.phis.append(phi); phis[name] = phi; henv[name] = _Binding(r, initial.type, initial.depth, initial.parent)
        self._switch(header)
        return header, henv, phis, pre_label

    def _finish_loop(self, env: dict[str, _Binding], header: _BlockBuild, henv: dict[str, _Binding], phis: dict[str, _PhiBuild], exit_block: _BlockBuild, false_pred: str, false_env: dict[str, _Binding], ctx: _LoopContext, normal_backedge: tuple[str, dict[str, _Binding]] | None) -> None:
        backs = list(ctx.continues)
        if normal_backedge is not None:
            backs.append(normal_backedge)
        for pred, benv in backs:
            for name, phi in phis.items():
                b = benv.get(name, self._undef(name))
                phi.incoming.append((pred, b.value))
                phi.type = self.mb.join_typefacts(phi.type, b.type)
        incoming = [(false_pred, false_env)] + ctx.breaks
        self._switch(exit_block)
        env.clear(); env.update(self._merge_env(exit_block, incoming))

    def _lower_while(self, s: ast.WhileStmt, env: dict[str, _Binding]) -> None:
        loop_depth = self.scope_depth
        assigned = self._assigned_names((s.condition, s.body))
        header, henv, phis, _ = self._prepare_loop_header(env, assigned, "while.header")
        cv = self.expr(s.condition, henv)
        false_pred = self.current.label
        false_env = self._copy_env(henv)
        body = self._new_block("while.body"); exit_block = self._new_block("while.exit")
        self._terminate("branch", cv, body.label, exit_block.label)
        ctx = _LoopContext(header.label, exit_block.label, phis, loop_depth)
        self.loops.append(ctx)
        self._switch(body); benv = self._copy_env(henv)
        self.scope_depth = loop_depth + 1
        try:
            self.stmts(s.body, benv)
        finally:
            self.scope_depth = loop_depth
        normal: tuple[str, dict[str, _Binding]] | None = None
        if self.current.terminator is None:
            pred = self.current.label
            self._terminate("jump", header.label)
            normal = (pred, self._env_at_depth(benv, loop_depth))
        self.loops.pop()
        self._finish_loop(env, header, henv, phis, exit_block, false_pred, false_env, ctx, normal)

    def _lower_for(self, s: ast.ForStmt, env: dict[str, _Binding]) -> None:
        loop_depth = self.scope_depth
        setup: list[str] = []
        for x in (s.source, s.start, s.stop, s.step):
            setup.append(self.expr(x, env) if x is not None else "@none")
        iterator = self._emit("iter.init." + s.kind, tuple(setup), TypeFact("object"), s.var, s)
        assert iterator is not None
        assigned = self._assigned_names(s.body)
        if s.var: assigned.add(s.var)
        header, henv, phis, _ = self._prepare_loop_header(env, assigned, "for.header")
        has = self._emit("iter.has", (iterator,), TypeFact("b"), s.kind, s)
        assert has is not None
        false_pred = self.current.label; false_env = self._copy_env(henv)
        body = self._new_block("for.body"); exit_block = self._new_block("for.exit")
        self._terminate("branch", has, body.label, exit_block.label)
        ctx = _LoopContext(header.label, exit_block.label, phis, loop_depth); self.loops.append(ctx)
        self._switch(body); benv = self._copy_env(henv)
        self.scope_depth = loop_depth + 1
        try:
            if s.var:
                item = self._emit("iter.value", (iterator,), TypeFact(), s.kind, s)
                assert item is not None
                self._bind(s.var, item, TypeFact(), "loop", s, benv, define=True)
            self.stmts(s.body, benv)
        finally:
            self.scope_depth = loop_depth
        normal = None
        if self.current.terminator is None:
            self._emit("iter.step", (iterator,), TypeFact(), s.kind, s, result=False)
            pred = self.current.label
            self._terminate("jump", header.label)
            normal = (pred, self._env_at_depth(benv, loop_depth))
        self.loops.pop()
        self._finish_loop(env, header, henv, phis, exit_block, false_pred, false_env, ctx, normal)

    def stmt(self, s: ast.Stmt, env: dict[str, _Binding]) -> None:
        if isinstance(s, (ast.CommentStmt, ast.ImportStmt, ast.NamespaceStmt, ast.FunctionDecl, ast.ClassDecl, ast.InterfaceDecl, ast.DestructorDecl)):
            return
        if isinstance(s, ast.ExprStmt):
            self.expr(s.expr, env); return
        if isinstance(s, ast.AssignStmt):
            value = self.expr(s.value, env)
            contracts = self.mb.hir.assignment_contracts.get(id(s), (None,) * len(s.targets))
            for i, name in enumerate(s.targets):
                c = contracts[i] if i < len(contracts) else None
                bt = TypeFact.from_code(c) if c else self._type(s.value)
                self._bind(name, value, bt, (f"@{c}" if c else "nearest"), s, env, define=False)
            return
        if isinstance(s, ast.MutateStmt):
            if isinstance(s.target, (ast.Var, ast.ExtendedName)):
                old = env.get(s.target.name)
                if old is None:
                    value = self._emit("load", (s.target.name,), TypeFact(), None, s.target)
                    assert value is not None
                    old = _Binding(value, TypeFact())
                r = self._emit("mutate." + s.op, (old.value,), old.type, s.target.name, s)
                assert r is not None
                env[s.target.name] = _Binding(r, old.type, old.depth, old.parent)
            else:
                self._emit("mutate." + s.op, (), TypeFact(), type(s.target).__name__, s, result=False)
            return
        if isinstance(s, ast.SetIndexStmt):
            a = self.expr(s.target.base, env); b = self.expr(s.target.index, env); v = self.expr(s.value, env)
            self._emit("setindex", (a, b, v), TypeFact(), None, s, result=False); return
        if isinstance(s, ast.SetMemberStmt):
            v = self.expr(s.value, env)
            self._emit("setmember", (s.target.name, v), TypeFact(), "define" if s.define else "update", s, result=False); return
        if isinstance(s, ast.SuperInitStmt):
            args = tuple(self.expr(a, env) for a in s.args)
            self._emit("super.init", args, TypeFact(), None, s, result=False); return
        if isinstance(s, ast.ReturnStmt):
            vals = tuple(self.expr(v, env) for v in s.values)
            self._terminate("return", *vals); return
        if isinstance(s, ast.RaiseStmt):
            if s.value is None: self._terminate("reraise")
            else: self._terminate("raise", self.expr(s.value, env))
            return
        if isinstance(s, ast.BreakStmt):
            if not self.loops:
                self._terminate("unreachable"); return
            ctx = self.loops[-1]; pred = self.current.label
            ctx.breaks.append((pred, self._env_at_depth(env, ctx.scope_depth))); self._terminate("jump", ctx.exit); return
        if isinstance(s, ast.ContinueStmt):
            if not self.loops:
                self._terminate("unreachable"); return
            ctx = self.loops[-1]; pred = self.current.label
            ctx.continues.append((pred, self._env_at_depth(env, ctx.scope_depth))); self._terminate("jump", ctx.header); return
        if isinstance(s, ast.IfStmt):
            self._lower_if(s, env); return
        if isinstance(s, ast.WhileStmt):
            self._lower_while(s, env); return
        if isinstance(s, ast.ForStmt):
            self._lower_for(s, env); return
        if isinstance(s, ast.TryStmt):
            # Exception/finally edges remain a conservative optimization barrier in
            # v0.1.4. The protected region may also call code that mutates module or
            # captured bindings, so invalidate every visible binding rather than only
            # syntactically assigned names.
            self._emit("barrier.try", (), TypeFact(), f"catch={s.catch_body is not None} finally={s.finally_body is not None}", s, result=False)
            self._clobber_env(env, "try region")
            return
        self._emit("barrier.stmt", (), TypeFact(), type(s).__name__, s, result=False)

    def stmts(self, stmts: Iterable[ast.Stmt], env: dict[str, _Binding] | None = None) -> None:
        env = self.env if env is None else env
        for s in stmts:
            if self.current.terminator is not None:
                break
            self.stmt(s, env)

    def finish(self) -> MIRFunction:
        if self.current.terminator is None:
            self.current.terminator = MIRTerminator("return")
        frozen: list[MIRBlock] = []
        for b in self.blocks:
            term = b.terminator or MIRTerminator("unreachable")
            phis = tuple(MIRPhi(p.result, p.binding, tuple(p.incoming), p.type) for p in b.phis)
            frozen.append(MIRBlock(b.label, phis, tuple(b.instructions), term))
        return MIRFunction(self.name, tuple(self.params), self.returns, tuple(frozen))


class _MIRBuilder:
    def __init__(self, hir: IRModule):
        if hir.program is None:
            raise ValueError("HIR does not retain its checked program")
        self.hir = hir
        self.program = hir.program
        self.class_parents: dict[str, str | None] = {
            s.name: s.parent for s in self.program.statements if isinstance(s, ast.ClassDecl)
        }
        self.functions: list[MIRFunction] = []
        self.lambda_counter = 0

    def join_typefacts(self, a: TypeFact, b: TypeFact) -> TypeFact:
        if a == b:
            return a
        if a.kind == b.kind == "object" and a.class_name and b.class_name:
            chain: list[str] = []
            seen: set[str] = set()
            cur: str | None = a.class_name
            while cur is not None and cur not in seen:
                seen.add(cur); chain.append(cur); cur = self.class_parents.get(cur)
            ancestors_b: set[str] = set()
            seen.clear(); cur = b.class_name
            while cur is not None and cur not in seen:
                seen.add(cur); ancestors_b.add(cur); cur = self.class_parents.get(cur)
            for name in chain:
                if name in ancestors_b:
                    return TypeFact("object", class_name=name)
            return TypeFact()
        return join_types(a, b)

    @staticmethod
    def _params(fn: ast.FunctionDecl, owner: str | None = None) -> tuple[tuple[str, TypeFact], ...]:
        out: list[tuple[str, TypeFact]] = []
        if owner is not None and not fn.static:
            out.append(("self", TypeFact("object", class_name=owner)))
        out.extend((p.name, TypeFact.from_code(p.type_code)) for p in fn.params)
        if fn.variadic:
            out.append((fn.variadic, TypeFact("list")))
        return tuple(out)

    def _lower_body(self, name: str, body: Iterable[ast.Stmt], params: tuple[tuple[str, TypeFact], ...], returns: tuple[TypeFact, ...] | None) -> MIRFunction:
        fb = _FunctionBuilder(self, name, params, returns)
        fb.stmts(body)
        return fb.finish()

    def lower_lambda(self, node: ast.LambdaExpr) -> str:
        self.lambda_counter += 1
        name = f"<lambda:{self.lambda_counter}>"
        params = [(p.name, TypeFact.from_code(p.type_code)) for p in node.params]
        if node.variadic: params.append((node.variadic, TypeFact("list")))
        returns = None if node.return_types is None else tuple(TypeFact.from_code(x) for x in node.return_types)
        self.functions.append(self._lower_body(name, node.body, tuple(params), returns))
        return name

    def build(self) -> MIRModule:
        top_body = tuple(s for s in self.program.statements if not isinstance(s, (ast.FunctionDecl, ast.ClassDecl, ast.InterfaceDecl)))
        top = self._lower_body("<module>", top_body, (), None)
        named: list[MIRFunction] = []
        for s in self.program.statements:
            if isinstance(s, ast.FunctionDecl):
                returns = None if s.return_types is None else tuple(TypeFact.from_code(x) for x in s.return_types)
                named.append(self._lower_body(s.name, s.body, self._params(s), returns))
            elif isinstance(s, ast.ClassDecl):
                ctor_params = (("self", TypeFact("object", class_name=s.name)),) + tuple((p.name, TypeFact.from_code(p.type_code)) for p in s.params)
                ctor_body = tuple(x for x in s.body if not isinstance(x, (ast.FunctionDecl, ast.DestructorDecl)))
                named.append(self._lower_body(f"{s.name}.<init>", ctor_body, ctor_params, (TypeFact("object", class_name=s.name),)))
                for child in s.body:
                    if isinstance(child, ast.FunctionDecl):
                        returns = None if child.return_types is None else tuple(TypeFact.from_code(x) for x in child.return_types)
                        named.append(self._lower_body(f"{s.name}.{child.name}", child.body, self._params(child, s.name), returns))
                    elif isinstance(child, ast.DestructorDecl):
                        named.append(self._lower_body(f"{s.name}.<destroy>", child.body, (("self", TypeFact("object", class_name=s.name)),), ()))
        # Lambda functions are discovered while lowering top/named/class bodies. Keep
        # them after declarations for stable textual identity, matching HIR ordering.
        return MIRModule(top, tuple(named + self.functions))


def lower_mir(hir: IRModule | ast.Program) -> MIRModule:
    if isinstance(hir, ast.Program):
        hir = lower_ir(hir)
    return _MIRBuilder(hir).build()


def format_mir(module: MIRModule) -> str:
    def fmt_fn(fn: MIRFunction) -> list[str]:
        params = ", ".join(f"{name}={value}:{typ.code}" for name, value, typ in fn.params)
        returns = "?" if fn.returns is None else ",".join(t.code for t in fn.returns)
        out = [f"fn {fn.name}({params}) -> {returns}"]
        for block in fn.blocks:
            out.append(block.label + ":")
            for p in block.phis:
                inc = ", ".join(f"{pred}:{value}" for pred, value in p.incoming)
                typ = f" :{p.type.code}" if p.type.kind != "any" else ""
                out.append(f"  {p.result} = phi {p.binding} [{inc}]{typ}")
            for i in block.instructions:
                lhs = f"{i.result} = " if i.result else ""
                args = " ".join(i.args)
                typ = f" :{i.type.code}" if i.type.kind != "any" else ""
                detail = f" ; {i.detail}" if i.detail else ""
                out.append(f"  {lhs}{i.op}{(' ' + args) if args else ''}{typ}{detail}")
            targs = " ".join(block.terminator.args)
            out.append(f"  -> {block.terminator.op}{(' ' + targs) if targs else ''}")
        return out
    lines = fmt_fn(module.top)
    for fn in module.functions:
        lines += [""] + fmt_fn(fn)
    return "\n".join(lines) + "\n"

from __future__ import annotations

"""Typed high-level IR for the SLUG bootstrap.

v0.1.3 intentionally introduces an HIR before the optimizer.  It preserves SLUG's
structured control constructs while assigning stable temporary values and carrying
static type/contract facts.  The C backend consumes the same semantic contract map,
so this is already part of compilation rather than a debug-only pretty printer.

The optimizer milestone can lower this HIR into a CFG/SSA MIR without having to teach
optimization passes about the ambiguity parser or source grammar.
"""

from dataclasses import dataclass, field
from typing import Iterable

from . import ast
from .builtins import builtin
from .semantics import analyze_details


@dataclass(frozen=True, slots=True)
class TypeFact:
    kind: str = "any"       # any/null/i/u/f/s/b/list/map/object/callable/error
    width: int | None = None
    class_name: str | None = None

    @property
    def code(self) -> str:
        if self.kind == "object" and self.class_name:
            return f"class:{self.class_name}"
        if self.kind in {"i", "u", "f"} and self.width:
            return f"{self.kind}{self.width}"
        return self.kind

    @classmethod
    def from_code(cls, code: str | None) -> "TypeFact":
        if not code:
            return cls()
        if code.startswith("class:"):
            return cls("object", class_name=code[6:])
        if code in {"null", "list", "map", "callable", "error", "any", "integer", "bytes", "socket", "file", "surface", "window", "audio", "device"}:
            return cls(code)
        if code[0:1] in {"i", "u", "f"}:
            suffix = code[1:]
            return cls(code[0], int(suffix) if suffix.isdigit() else None)
        if code in {"s", "b"}:
            return cls(code)
        return cls()


def join_types(a: TypeFact, b: TypeFact) -> TypeFact:
    if a == b:
        return a
    # `any` means unknown/top, not an empty fact. Narrowing unknown with one concrete
    # predecessor would be unsound at a CFG merge.
    if a.kind == "any" or b.kind == "any": return TypeFact()
    numeric = {"i", "u", "f", "b", "integer"}
    if a.kind in numeric and b.kind in numeric:
        if "f" in {a.kind, b.kind}: return TypeFact("f")
        if a.kind == b.kind and a.width == b.width: return a
        if "u" in {a.kind,b.kind} and "i" in {a.kind,b.kind}: return TypeFact("integer")
        return TypeFact("i")
    return TypeFact()


@dataclass(frozen=True, slots=True)
class IRInstr:
    result: str | None
    op: str
    args: tuple[str, ...] = ()
    type: TypeFact = TypeFact()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class IRBlock:
    label: str
    instructions: tuple[IRInstr, ...]


@dataclass(frozen=True, slots=True)
class IRFunction:
    name: str
    params: tuple[tuple[str, TypeFact], ...]
    returns: tuple[TypeFact, ...] | None
    blocks: tuple[IRBlock, ...]


@dataclass(slots=True)
class IRModule:
    top: IRFunction
    functions: tuple[IRFunction, ...]
    # Node-id keyed facts are intentionally excluded from textual IR identity. They let
    # downstream lowering enforce contracts without mutating the immutable AST.
    assignment_contracts: dict[int, tuple[str | None, ...]] = field(default_factory=dict, repr=False)
    expr_types: dict[int, TypeFact] = field(default_factory=dict, repr=False)
    # Checked structured program retained for CFG construction. Kept last so the
    # v0.1.3 positional IRModule(top, functions, contracts, types) shape remains valid.
    program: ast.Program | None = field(default=None, repr=False, compare=False)


class _Builder:
    def __init__(self, program: ast.Program, contracts: dict[int, tuple[str | None, ...]], semantic_expr_types: dict[int, str | None] | None = None):
        self.program = program
        self.contracts = contracts
        self.semantic_expr_types = semantic_expr_types or {}
        self.counter = 0
        self.expr_types: dict[int, TypeFact] = {}
        self.functions = {s.name: s for s in program.statements if isinstance(s, ast.FunctionDecl)}
        self.classes = {s.name: s for s in program.statements if isinstance(s, ast.ClassDecl)}
        self.extra_functions: list[IRFunction] = []
        self.lambda_counter = 0

    def _method_decl(self, class_name: str, name: str, static: bool) -> ast.FunctionDecl | None:
        seen: set[str] = set()
        cur: str | None = class_name
        while cur is not None and cur not in seen:
            seen.add(cur)
            cls = self.classes.get(cur)
            if cls is None:
                return None
            for child in cls.body:
                if isinstance(child, ast.FunctionDecl) and child.name == name and child.static == static:
                    return child
            cur = cls.parent
        return None

    def temp(self) -> str:
        self.counter += 1
        return f"%{self.counter}"

    def type_of(self, e: ast.Expr, env: dict[str, TypeFact]) -> TypeFact:
        cached = self.expr_types.get(id(e))
        if cached is not None:
            return cached
        if id(e) in self.semantic_expr_types:
            semantic = self.semantic_expr_types[id(e)]
            t = TypeFact.from_code(semantic)
            self.expr_types[id(e)] = t
            return t
        t = TypeFact()
        if isinstance(e, ast.Literal):
            if e.kind == "int": t = TypeFact("u") if int(e.value) > 0x7FFFFFFFFFFFFFFF else TypeFact("i")
            else: t = {"float": TypeFact("f"), "string": TypeFact("s"), "null": TypeFact("null")}.get(e.kind, TypeFact())
        elif isinstance(e, ast.FormattedString): t = TypeFact("s")
        elif isinstance(e, (ast.Var, ast.ExtendedName, ast.ModuleVar)):
            t = env.get(e.name, TypeFact())
        elif isinstance(e, ast.Cast): t = TypeFact.from_code(e.type_code)
        elif isinstance(e, ast.DynamicCast): t = TypeFact()
        elif isinstance(e, ast.ClassCall): t = TypeFact("object", class_name=e.name)
        elif isinstance(e, ast.LambdaExpr): t = TypeFact("callable")
        elif isinstance(e, (ast.BoolExpr, ast.Compare, ast.LogicNot, ast.LogicBinary)): t = TypeFact("b")
        elif isinstance(e, ast.ListLiteral): t = TypeFact("list")
        elif isinstance(e, ast.MapLiteral): t = TypeFact("map")
        elif isinstance(e, ast.AssignExpr):
            cs = self.contracts.get(id(e), ())
            t = TypeFact.from_code(cs[0]) if len(cs) == 1 and cs[0] else self.type_of(e.value, env)
        elif isinstance(e, ast.Unary):
            inner = self.type_of(e.value, env)
            if e.op == "-" and inner.kind in {"i", "u", "b"}: t = TypeFact("i")
            else: t = inner
        elif isinstance(e, ast.Binary):
            a, b = self.type_of(e.left, env), self.type_of(e.right, env)
            if e.op == "+" and (a.kind == "s" or b.kind == "s"): t = TypeFact("s")
            elif e.op == "/": t = TypeFact("f")
            elif a.kind in {"i","u","f","b"} and b.kind in {"i","u","f","b"}:
                # Fixed widths are binding/cast constraints, not arithmetic result
                # widths. Preserve only sound carrier facts for optimizer decisions.
                if "f" in {a.kind,b.kind}: t = TypeFact("f")
                elif a.kind == "u" and b.kind == "u": t = TypeFact("u")
                elif "u" in {a.kind,b.kind} and "i" in {a.kind,b.kind}: t = TypeFact("integer")
                else: t = TypeFact("i")
        elif isinstance(e, ast.SliceExpr):
            bt = self.type_of(e.base, env); t = TypeFact("s") if bt.kind == "s" else (TypeFact("list") if bt.kind == "list" else TypeFact())
        elif isinstance(e, ast.IndexExpr):
            bt = self.type_of(e.base, env); t = TypeFact("s") if bt.kind == "s" else TypeFact()
        elif isinstance(e, ast.SetIndexExpr): t = self.type_of(e.value, env)
        elif isinstance(e, ast.SetMemberExpr): t = self.type_of(e.value, env)
        elif isinstance(e, ast.Call):
            fn = self.functions.get(e.name)
            if fn is not None:
                if fn.return_types and len(fn.return_types) == 1: t = TypeFact.from_code(fn.return_types[0])
            else:
                spec = builtin(e.name)
                if spec is not None and spec.return_kind is not None:
                    t = TypeFact.from_code(spec.return_kind)
        elif isinstance(e, ast.MethodCall):
            owner: str | None = e.class_name
            static = e.static if e.class_name is not None else False
            if owner is None and e.receiver is not None:
                rt = self.type_of(e.receiver, env)
                if rt.kind == "object": owner = rt.class_name
            if owner is not None:
                fn = self._method_decl(owner, e.name, static)
                if fn is not None and fn.return_types is not None and len(fn.return_types) == 1:
                    t = TypeFact.from_code(fn.return_types[0])
        self.expr_types[id(e)] = t
        return t

    def expr(self, e: ast.Expr, env: dict[str, TypeFact], out: list[IRInstr]) -> str:
        # HIR operands deliberately use nested temporary IDs, making evaluation order
        # explicit for the future optimizer while preserving structured statements.
        if isinstance(e, ast.Literal):
            r=self.temp(); t=self.type_of(e,env); out.append(IRInstr(r,"const",(repr(e.value),),t,e.kind)); return r
        if isinstance(e, ast.FormattedString):
            xs: list[str] = []
            for part in e.parts:
                if isinstance(part, str):
                    r0=self.temp();out.append(IRInstr(r0,"const",(repr(part),),TypeFact("s"),"string"));xs.append(r0)
                else:
                    x=self.expr(part,env,out);r0=self.temp();out.append(IRInstr(r0,"cast",(x,),TypeFact("s"),"s"));xs.append(r0)
            r=self.temp();out.append(IRInstr(r,"format.string",tuple(xs),TypeFact("s")));return r
        if isinstance(e,(ast.Var,ast.ExtendedName,ast.ModuleVar)):
            r=self.temp(); t=self.type_of(e,env); out.append(IRInstr(r,"load",(e.name,),t)); return r
        if isinstance(e,ast.Cast):
            x=self.expr(e.value,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"cast",(x,),t,e.type_code));return r
        if isinstance(e,ast.DynamicCast):
            tc=self.expr(e.type_expr,env,out);x=self.expr(e.value,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"dynamic.cast",(tc,x),t));return r
        if isinstance(e,ast.Unary):
            x=self.expr(e.value,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"unary."+e.op,(x,),t));return r
        if isinstance(e,ast.Binary):
            a=self.expr(e.left,env,out);b=self.expr(e.right,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"binary."+e.op,(a,b),t));return r
        if isinstance(e,(ast.BoolExpr,ast.LogicNot)):
            inner=e.value;r0=self.expr(inner,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"bool",(r0,),t,type(e).__name__));return r
        if isinstance(e,ast.Compare):
            a=self.expr(e.left,env,out);b=self.expr(e.right,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"cmp."+e.op,(a,b),t));return r
        if isinstance(e,ast.LogicBinary):
            a=self.expr(e.left,env,out);b=self.expr(e.right,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"logic."+e.op,(a,b),t));return r
        if isinstance(e,ast.AssignExpr):
            x=self.expr(e.value,env,out);cs=self.contracts.get(id(e),(None,)*len(e.targets))
            for i,n in enumerate(e.targets):
                c=cs[i] if i<len(cs) else None;env[n]=TypeFact.from_code(c) if c else self.type_of(e.value,env)
                out.append(IRInstr(None,"bind",(n,x),env[n],("immutable" if e.op=="::=" else "mutable") + ((" @"+c) if c else "")))
            return x
        if isinstance(e,ast.ListLiteral):
            xs=tuple(self.expr(x,env,out) for x in e.items);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"list",xs,t,"frozen" if e.frozen else None));return r
        if isinstance(e,ast.MapLiteral):
            xs=[]
            for k,v in e.entries:xs.extend((self.expr(k,env,out),self.expr(v,env,out)))
            r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"map",tuple(xs),t,"frozen" if e.frozen else None));return r
        if isinstance(e,ast.IndexExpr):
            a=self.expr(e.base,env,out);b=self.expr(e.index,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"index",(a,b),t));return r
        if isinstance(e,ast.SliceExpr):
            vals=[self.expr(e.base,env,out)]
            for x in (e.start,e.stop,e.step): vals.append(self.expr(x,env,out) if x is not None else "_")
            r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"slice",tuple(vals),t));return r
        if isinstance(e,ast.SetIndexExpr):
            a=self.expr(e.target.base,env,out);b=self.expr(e.target.index,env,out);v=self.expr(e.value,env,out);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"setindex",(a,b,v),t));return r
        if isinstance(e,ast.Call):
            args=tuple(self.expr(a,env,out) if not isinstance(a,ast.DefaultArg) else "xx" for a in e.args);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"call",(e.name,)+args,t));return r
        if isinstance(e,ast.ClassCall):
            args=tuple(self.expr(a,env,out) for a in e.args);r=self.temp();t=self.type_of(e,env);out.append(IRInstr(r,"new",(e.name,)+args,t));return r
        if isinstance(e,ast.CallableInvoke):
            c=self.expr(e.callee,env,out);args=tuple(self.expr(a,env,out) for a in e.args);r=self.temp();out.append(IRInstr(r,"invoke",(c,)+args,TypeFact()));return r
        if isinstance(e,ast.LambdaExpr):
            self.lambda_counter += 1
            lname=f"<lambda:{self.lambda_counter}>"
            r=self.temp()
            lenv=dict(env)
            for p in e.params: lenv[p.name]=TypeFact.from_code(p.type_code)
            if e.variadic: lenv[e.variadic]=TypeFact("list")
            body:list[IRInstr]=[]; self.stmts(e.body,lenv,body)
            returns=None if e.return_types is None else tuple(TypeFact.from_code(x) for x in e.return_types)
            params=tuple((p.name,TypeFact.from_code(p.type_code)) for p in e.params)
            self.extra_functions.append(IRFunction(lname,params,returns,(IRBlock("entry",tuple(body)),)))
            out.append(IRInstr(r,"lambda",(lname,),TypeFact("callable"),f"params={len(e.params)}"));return r
        if isinstance(e,ast.MemberExpr):
            base=self.expr(e.base,env,out) if e.base is not None else (e.class_name or ("static" if e.static else "self"));r=self.temp();out.append(IRInstr(r,"member",(base,e.name),TypeFact()));return r
        if isinstance(e,ast.MethodCall):
            base=self.expr(e.receiver,env,out) if e.receiver is not None else (e.class_name or ("super" if e.super_call else "self"));args=tuple(self.expr(a,env,out) for a in e.args);r=self.temp();out.append(IRInstr(r,"method",(base,e.name)+args,self.type_of(e,env)));return r
        if isinstance(e,ast.SetMemberExpr):
            v=self.expr(e.value,env,out);r=self.temp();out.append(IRInstr(r,"setmember",(e.target.name,v),self.type_of(e,env)));return r
        if isinstance(e,ast.DefaultArg): return "xx"
        r=self.temp();out.append(IRInstr(r,"dynamic",(),TypeFact(),type(e).__name__));return r

    def stmts(self, stmts: Iterable[ast.Stmt], env: dict[str, TypeFact], out: list[IRInstr]) -> None:
        for s in stmts:
            if isinstance(s,(ast.CommentStmt,ast.ImportStmt,ast.NamespaceStmt,ast.FunctionDecl,ast.ClassDecl,ast.InterfaceDecl,ast.DestructorDecl)): continue
            if isinstance(s,ast.ExprStmt): self.expr(s.expr,env,out); continue
            if isinstance(s,ast.AssignStmt):
                x=self.expr(s.value,env,out);cs=self.contracts.get(id(s),(None,)*len(s.targets))
                for i,n in enumerate(s.targets):
                    c=cs[i] if i<len(cs) else None;env[n]=TypeFact.from_code(c) if c else self.type_of(s.value,env);out.append(IRInstr(None,"store",(n,x),env[n],("@"+c) if c else None))
                continue
            if isinstance(s,ast.MutateStmt): out.append(IRInstr(None,"mutate",(s.op,),TypeFact(),type(s.target).__name__));continue
            if isinstance(s,ast.ReturnStmt):
                vals=tuple(self.expr(v,env,out) for v in s.values);out.append(IRInstr(None,"return",vals));continue
            if isinstance(s,ast.RaiseStmt): out.append(IRInstr(None,"reraise" if s.value is None else "raise",() if s.value is None else (self.expr(s.value,env,out),)));continue
            if isinstance(s,ast.IfStmt):
                c=self.expr(s.condition,env,out);out.append(IRInstr(None,"if.begin",(c,)));self.stmts(s.body,dict(env),out)
                for ec,eb in s.elifs: q=self.expr(ec,env,out);out.append(IRInstr(None,"elif",(q,)));self.stmts(eb,dict(env),out)
                if s.else_body is not None: out.append(IRInstr(None,"else"));self.stmts(s.else_body,dict(env),out)
                out.append(IRInstr(None,"if.end"));continue
            if isinstance(s,ast.WhileStmt):
                c=self.expr(s.condition,env,out);out.append(IRInstr(None,"while.begin",(c,)));self.stmts(s.body,dict(env),out);out.append(IRInstr(None,"while.end"));continue
            if isinstance(s,ast.ForStmt):
                args=[]
                for e in (s.source,s.start,s.stop,s.step): args.append(self.expr(e,env,out) if e is not None else "_")
                out.append(IRInstr(None,"for."+s.kind,tuple(args),TypeFact(),s.var));child=dict(env)
                if s.var: child[s.var]=TypeFact()
                self.stmts(s.body,child,out);out.append(IRInstr(None,"for.end"));continue
            if isinstance(s,ast.TryStmt):
                out.append(IRInstr(None,"try.begin"));self.stmts(s.body,dict(env),out)
                if s.catch_body is not None: out.append(IRInstr(None,"catch",(),TypeFact("error"),s.catch_name));self.stmts(s.catch_body,dict(env),out)
                if s.finally_body is not None: out.append(IRInstr(None,"finally"));self.stmts(s.finally_body,dict(env),out)
                out.append(IRInstr(None,"try.end"));continue
            out.append(IRInstr(None,"stmt",(),TypeFact(),type(s).__name__))

    def function(self, fn: ast.FunctionDecl, name: str | None = None, owner: str | None = None) -> IRFunction:
        env={p.name:TypeFact.from_code(p.type_code) for p in fn.params}
        params=list((p.name,TypeFact.from_code(p.type_code)) for p in fn.params)
        if owner is not None and not fn.static:
            env["self"]=TypeFact("object",class_name=owner)
            params.insert(0,("self",TypeFact("object",class_name=owner)))
        if fn.variadic: env[fn.variadic]=TypeFact("list")
        ins:list[IRInstr]=[];self.stmts(fn.body,env,ins)
        returns=None if fn.return_types is None else tuple(TypeFact.from_code(x) for x in fn.return_types)
        return IRFunction(name or fn.name,tuple(params),returns,(IRBlock("entry",tuple(ins)),))

    def class_functions(self, cls: ast.ClassDecl) -> list[IRFunction]:
        out:list[IRFunction]=[]
        # Constructor/body is represented explicitly so later escape/devirtualization
        # passes can reason about allocations and initialization without reconstructing
        # class semantics from source AST.
        ctor_env={p.name:TypeFact.from_code(p.type_code) for p in cls.params}
        ctor_env["self"]=TypeFact("object",class_name=cls.name)
        ctor_params=[("self",TypeFact("object",class_name=cls.name))]+[(p.name,TypeFact.from_code(p.type_code)) for p in cls.params]
        ctor_body=[x for x in cls.body if not isinstance(x,(ast.FunctionDecl,ast.DestructorDecl))]
        ctor_ins:list[IRInstr]=[];self.stmts(ctor_body,ctor_env,ctor_ins)
        out.append(IRFunction(f"{cls.name}.<init>",tuple(ctor_params),(TypeFact("object",class_name=cls.name),),(IRBlock("entry",tuple(ctor_ins)),)))
        for child in cls.body:
            if isinstance(child,ast.FunctionDecl):
                out.append(self.function(child,f"{cls.name}.{child.name}",cls.name))
            elif isinstance(child,ast.DestructorDecl):
                denv={"self":TypeFact("object",class_name=cls.name)}; dins:list[IRInstr]=[];self.stmts(child.body,denv,dins)
                out.append(IRFunction(f"{cls.name}.<destroy>",(("self",TypeFact("object",class_name=cls.name)),),(),(IRBlock("entry",tuple(dins)),)))
        return out

    def build(self) -> IRModule:
        env:dict[str,TypeFact]={};ins:list[IRInstr]=[]
        self.stmts((s for s in self.program.statements if not isinstance(s,(ast.FunctionDecl,ast.ClassDecl))),env,ins)
        top=IRFunction("<module>",(),None,(IRBlock("entry",tuple(ins)),))
        fns=[self.function(s) for s in self.program.statements if isinstance(s,ast.FunctionDecl)]
        for cls in (s for s in self.program.statements if isinstance(s,ast.ClassDecl)):
            fns.extend(self.class_functions(cls))
        # Lambda bodies are discovered while lowering the top/functions/classes.
        fns.extend(self.extra_functions)
        return IRModule(top,tuple(fns),dict(self.contracts),dict(self.expr_types),self.program)


def lower_ir(program: ast.Program) -> IRModule:
    checked=analyze_details(program)
    return _Builder(checked.program,checked.assignment_contracts,checked.expr_type_codes).build()


def format_ir(module: IRModule) -> str:
    def fmt_fn(fn: IRFunction) -> list[str]:
        params=", ".join(f"{n}:{t.code}" for n,t in fn.params)
        returns="?" if fn.returns is None else ",".join(t.code for t in fn.returns)
        out=[f"fn {fn.name}({params}) -> {returns}"]
        for block in fn.blocks:
            out.append(block.label+":")
            for i in block.instructions:
                lhs=(i.result+" = ") if i.result else ""
                args=" ".join(i.args)
                typ=(" :"+i.type.code) if i.type.kind!="any" else ""
                detail=(" ; "+i.detail) if i.detail else ""
                out.append(f"  {lhs}{i.op}{(' '+args) if args else ''}{typ}{detail}")
        return out
    lines=fmt_fn(module.top)
    for fn in module.functions: lines += [""] + fmt_fn(fn)
    return "\n".join(lines)+"\n"

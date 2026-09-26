from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import sys
from contextlib import contextmanager
from dataclasses import fields, replace
from pathlib import Path

from . import ast
from .codegen_c import generate_c
from .diagnostics import SemanticError
from .lexer import lex
from .parser import Parser, parse
from .semantics import analyze
from .ir import lower_ir, format_ir
from .mir import lower_mir, format_mir
from .optimizer import optimize_mir
from .symbols import CallableSig, ClassSig, InterfaceSig, MethodSig, Symbols, VarSig
from .builtins import builtin, internal_module_exports, standard_module_exports
from .project import ProjectManifest, project_for_source


@contextmanager
def _source_recursion_budget(token_count: int):
    """Scale the host recursion allowance with source structure, not a language cap.

    Several legacy frontend visitors are still recursive over genuinely nested syntax.
    A fixed Python recursion limit would therefore become an accidental SLUG grammar
    limit.  Until those visitors are completely iterative, derive the temporary host
    allowance from the input size and restore the process setting afterwards.
    """
    old = sys.getrecursionlimit()
    needed = max(old, 4096 + token_count * 64)
    if needed != old:
        sys.setrecursionlimit(needed)
    try:
        yield
    finally:
        if needed != old:
            sys.setrecursionlimit(old)


def _frontend_from_tokens(tokens, source: str):
    program = parse(tokens, source)
    return analyze(program)


def _ast_node_count(root: object) -> int:
    """Count AST/dataclass structure iteratively for a downstream host-stack budget.

    Module linking can combine trees whose individual sources were parsed under their
    own source-scaled recursion envelopes.  Once linked, later recursive visitors must
    not fall back to Python's process default merely because the root file itself was
    shallow.  This is a host implementation allowance, not a SLUG semantic ceiling.
    """
    total = 0
    stack: list[object] = [root]
    while stack:
        value = stack.pop()
        if isinstance(value, ast.Node):
            total += 1
            for f in fields(value):
                stack.append(getattr(value, f.name))
        elif isinstance(value, (tuple, list)):
            stack.extend(value)
    return total


@contextmanager
def _program_recursion_budget(program: ast.Program):
    # Recursive visitor depth is bounded by AST structural depth and therefore by the
    # number of nodes.  Use a generous multiplier for visitors that interpose helper
    # frames, restoring the interpreter setting immediately afterwards.
    with _source_recursion_budget(max(1, _ast_node_count(program) * 4)):
        yield


def frontend(source: str):
    tokens = lex(source)
    with _source_recursion_budget(len(tokens)):
        return _frontend_from_tokens(tokens, source)


def emit_c(source: str) -> str:
    tokens = lex(source)
    # Keep the source-scaled recursion envelope active through analysis, IR/MIR and C
    # generation; otherwise a deep but legal AST could parse successfully and then hit
    # Python's default guard in a later visitor.
    with _source_recursion_budget(len(tokens)):
        return generate_c(_frontend_from_tokens(tokens, source))


def emit_ir(source: str) -> str:
    tokens = lex(source)
    with _source_recursion_budget(len(tokens)):
        return format_ir(lower_ir(_frontend_from_tokens(tokens, source)))


def emit_mir(source: str, *, optimized: bool = False) -> str:
    tokens = lex(source)
    with _source_recursion_budget(len(tokens)):
        mir = lower_mir(lower_ir(_frontend_from_tokens(tokens, source)))
        if optimized:
            mir = optimize_mir(mir).module
        return format_mir(mir)


def _function_sig(fn: ast.FunctionDecl) -> CallableSig:
    required = sum(1 for p in fn.params if p.default is None)
    max_a = None if fn.variadic else len(fn.params)
    returns = None if fn.return_types is None else len(fn.return_types)
    return CallableSig(fn.name, required, max_a, returns, False)


def _method_sig(fn: ast.FunctionDecl) -> MethodSig:
    required = sum(1 for p in fn.params if p.default is None)
    max_a = None if fn.variadic else len(fn.params)
    return MethodSig(fn.name, required, max_a, fn.static, fn.private)


def _class_sig(cls: ast.ClassDecl) -> ClassSig:
    required = sum(1 for p in cls.params if p.default is None)
    methods = tuple(_method_sig(x) for x in cls.body if isinstance(x, ast.FunctionDecl) and not x.private)
    static_fields: list[str] = []
    for x in cls.body:
        if isinstance(x, ast.ExprStmt) and isinstance(x.expr, ast.SetMemberExpr):
            target = x.expr.target
            if target.static and target.base is None and target.class_name is None:
                static_fields.append(target.name)
        elif isinstance(x, ast.SetMemberStmt) and x.define:
            target = x.target
            if target.static and target.base is None and target.class_name is None and not x.private:
                static_fields.append(target.name)
    return ClassSig(cls.name, required, len(cls.params), methods, tuple(static_fields))


def _public_symbols(program: ast.Program) -> Symbols:
    """Extract parser/linker-visible public metadata from one source module.

    Exported class/interface signatures include locally inherited public methods.  The
    linked semantic pass remains authoritative, but flattening these shapes here is
    necessary for dense inferred calls such as ``MA.CH.goA$`` when ``go`` is declared
    only on CH's local parent.  Child declarations override inherited signatures by
    (static,name), matching runtime dispatch.
    """
    out = Symbols()
    classes = {s.name: s for s in program.statements if isinstance(s, ast.ClassDecl)}
    interfaces = {s.name: s for s in program.statements if isinstance(s, ast.InterfaceDecl)}

    iface_cache: dict[str, tuple[MethodSig, ...]] = {}
    def iface_methods(name: str, trail: set[str] | None = None) -> tuple[MethodSig, ...]:
        if name in iface_cache:
            return iface_cache[name]
        node = interfaces.get(name)
        if node is None:
            return ()
        trail = set() if trail is None else set(trail)
        if name in trail:
            return ()  # semantic analysis reports the actual inheritance cycle
        trail.add(name)
        merged: dict[tuple[bool, str], MethodSig] = {}
        for parent in node.parents:
            if parent in interfaces:
                for sig in iface_methods(parent, trail):
                    merged[(sig.static, sig.name)] = sig
        for fn in node.methods:
            sig = _method_sig(fn)
            if not sig.private:
                merged[(sig.static, sig.name)] = sig
        result = tuple(merged[k] for k in sorted(merged, key=lambda x: (x[0], x[1])))
        iface_cache[name] = result
        return result

    class_cache: dict[str, ClassSig] = {}
    def class_sig(name: str, trail: set[str] | None = None) -> ClassSig:
        if name in class_cache:
            return class_cache[name]
        node = classes[name]
        trail = set() if trail is None else set(trail)
        if name in trail:
            return _class_sig(node)  # semantic analysis reports the actual cycle
        trail.add(name)
        inherited_methods: dict[tuple[bool, str], MethodSig] = {}
        inherited_fields: set[str] = set()
        if node.parent in classes:
            parent = class_sig(node.parent, trail)
            inherited_methods.update(((m.static, m.name), m) for m in parent.methods)
            inherited_fields.update(parent.static_fields)
        for interface in node.interfaces:
            if interface in interfaces:
                for sig in iface_methods(interface):
                    inherited_methods.setdefault((sig.static, sig.name), sig)
        own = _class_sig(node)
        for sig in own.methods:
            inherited_methods[(sig.static, sig.name)] = sig
        inherited_fields.update(own.static_fields)
        result = ClassSig(
            own.name, own.min_arity, own.max_arity,
            tuple(inherited_methods[k] for k in sorted(inherited_methods, key=lambda x: (x[0], x[1]))),
            tuple(sorted(inherited_fields)),
        )
        class_cache[name] = result
        return result

    for s in program.statements:
        if isinstance(s, ast.FunctionDecl) and not s.private:
            out.callables[s.name] = _function_sig(s)
        elif isinstance(s, ast.ClassDecl) and not s.private:
            out.classes[s.name] = class_sig(s.name)
        elif isinstance(s, ast.ExportDecl):
            out.variables[s.name] = VarSig(s.name, s.type_code, s.op == "::=")
        elif isinstance(s, ast.InterfaceDecl) and not s.private:
            out.interfaces[s.name] = InterfaceSig(s.name, iface_methods(s.name))
    return out


def _decode_import_string(raw: str) -> str:
    return Parser._decode_static_string(raw, purpose="import path")


def _scan_imports(source: str) -> list[ast.ImportStmt]:
    tokens = lex(source)
    out: list[ast.ImportStmt] = []
    depth = 0
    i = 0
    while i < len(tokens) - 1:
        t = tokens[i].text
        if t == "{":
            depth += 1; i += 1; continue
        if t == "}":
            depth = max(0, depth - 1); i += 1; continue
        if depth == 0 and t == ">" and tokens[i + 1].kind == "STRING":
            path = _decode_import_string(tokens[i + 1].text)
            j = i + 2; alias = None
            if tokens[j].text == ":":
                if tokens[j + 1].kind in {"LOWER", "EXT"}:
                    alias = tokens[j + 1].text; j += 2
                elif tokens[j + 1].kind == "UPPER" and tokens[j + 2].kind == "UPPER":
                    alias = tokens[j + 1].text + tokens[j + 2].text; j += 3
            out.append(ast.ImportStmt(path, alias)); i = j; continue
        i += 1
    return out


def _resolve_import_path(base: Path, spec: str) -> Path:
    p = Path(spec)
    if not p.is_absolute():
        p = base.parent / p
    candidates = [p]
    if not p.suffix:
        candidates.append(p.with_suffix(".slg"))
    for c in candidates:
        if c.is_file():
            return c.resolve()
    raise FileNotFoundError(f"SLUG import {spec!r} not found relative to {base}")


def _transform_expr(e: ast.Expr, fmap: dict[str, str], cmap: dict[str, str], alias_maps: dict[str, tuple[dict[str,str],dict[str,str],dict[str,tuple[str,bool]]]] | None = None, vmap: dict[str,str] | None = None) -> ast.Expr:
    alias_maps = alias_maps or {}
    vmap = vmap or {}
    if isinstance(e, (ast.Literal, ast.DefaultArg)):
        return e
    if isinstance(e, ast.FormattedString):
        return ast.FormattedString(tuple(part if isinstance(part, str) else _transform_expr(part,fmap,cmap,alias_maps,vmap) for part in e.parts))
    if isinstance(e, ast.Var):
        return ast.Var(vmap.get(e.name,e.name), e.root)
    if isinstance(e, ast.ExtendedName):
        return ast.ExtendedName(vmap.get(e.name,e.name), e.root)
    if isinstance(e, ast.Call):
        return ast.Call(fmap.get(e.name,e.name), tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args), e.mode, e.root)
    if isinstance(e, ast.ClassCall):
        return ast.ClassCall(cmap.get(e.name,e.name), tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args), e.root)
    if isinstance(e, ast.ModuleCall):
        maps=alias_maps.get(e.alias)
        if maps is None or e.name not in maps[0]: raise SemanticError(f"unknown imported callable {e.alias}.{e.name}")
        return ast.Call(maps[0][e.name], tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args), "pack")
    if isinstance(e, ast.ModuleVar):
        maps=alias_maps.get(e.alias)
        if maps is None or e.name not in maps[2]:
            raise SemanticError(f"unknown imported variable {e.alias}.{e.name}")
        return ast.Var(maps[2][e.name][0])
    if isinstance(e, ast.ModuleClassCall):
        maps=alias_maps.get(e.alias)
        if maps is None or e.name not in maps[1]: raise SemanticError(f"unknown imported class {e.alias}.{e.name}")
        return ast.ClassCall(maps[1][e.name], tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args))
    if isinstance(e, ast.ModuleClassMember):
        maps=alias_maps.get(e.alias)
        if maps is None or e.class_name not in maps[1]: raise SemanticError(f"unknown imported class {e.alias}.{e.class_name}")
        return ast.MemberExpr(e.name, None, maps[1][e.class_name], True)
    if isinstance(e, ast.ModuleClassMethodCall):
        maps=alias_maps.get(e.alias)
        if maps is None or e.class_name not in maps[1]: raise SemanticError(f"unknown imported class {e.alias}.{e.class_name}")
        return ast.MethodCall(e.name, tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args), None, maps[1][e.class_name], True, False)
    if isinstance(e, ast.CallableInvoke):
        return ast.CallableInvoke(_transform_expr(e.callee,fmap,cmap,alias_maps,vmap), tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args))
    if isinstance(e, ast.LambdaExpr):
        ps=tuple(ast.Param(vmap.get(p.name,p.name),p.type_code,_transform_expr(p.default,fmap,cmap,alias_maps,vmap) if p.default is not None else None) for p in e.params)
        return ast.LambdaExpr(ps, tuple(_transform_stmt(s,fmap,cmap,alias_maps,True,vmap) for s in e.body), e.return_types, vmap.get(e.variadic,e.variadic) if e.variadic else None)
    if isinstance(e, ast.Cast): return ast.Cast(e.type_code,_transform_expr(e.value,fmap,cmap,alias_maps,vmap),e.grouped)
    if isinstance(e, ast.DynamicCast): return ast.DynamicCast(_transform_expr(e.type_expr,fmap,cmap,alias_maps,vmap),_transform_expr(e.value,fmap,cmap,alias_maps,vmap),e.grouped_type)
    if isinstance(e, ast.Unary): return ast.Unary(e.op,_transform_expr(e.value,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.Binary): return ast.Binary(e.op,_transform_expr(e.left,fmap,cmap,alias_maps,vmap),_transform_expr(e.right,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.AssignExpr): return ast.AssignExpr(tuple(vmap.get(n,n) for n in e.targets),e.op,_transform_expr(e.value,fmap,cmap,alias_maps,vmap),e.target_types)
    if isinstance(e, ast.BoolExpr): return ast.BoolExpr(_transform_expr(e.value,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.Compare): return ast.Compare(e.op,_transform_expr(e.left,fmap,cmap,alias_maps,vmap),_transform_expr(e.right,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.LogicNot): return ast.LogicNot(_transform_expr(e.value,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.LogicBinary): return ast.LogicBinary(e.op,_transform_expr(e.left,fmap,cmap,alias_maps,vmap),_transform_expr(e.right,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.ListLiteral): return ast.ListLiteral(tuple(_transform_expr(x,fmap,cmap,alias_maps,vmap) for x in e.items),e.frozen)
    if isinstance(e, ast.MapLiteral): return ast.MapLiteral(tuple((_transform_expr(k,fmap,cmap,alias_maps,vmap),_transform_expr(v,fmap,cmap,alias_maps,vmap)) for k,v in e.entries),e.frozen)
    if isinstance(e, ast.IndexExpr): return ast.IndexExpr(_transform_expr(e.base,fmap,cmap,alias_maps,vmap),_transform_expr(e.index,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.SliceExpr):
        f=lambda x:_transform_expr(x,fmap,cmap,alias_maps,vmap) if x is not None else None
        return ast.SliceExpr(_transform_expr(e.base,fmap,cmap,alias_maps,vmap),f(e.start),f(e.stop),f(e.step))
    if isinstance(e, ast.SetIndexExpr): return ast.SetIndexExpr(_transform_expr(e.target,fmap,cmap,alias_maps,vmap),_transform_expr(e.value,fmap,cmap,alias_maps,vmap))
    if isinstance(e, ast.MemberExpr): return ast.MemberExpr(e.name,_transform_expr(e.base,fmap,cmap,alias_maps,vmap) if e.base is not None else None,cmap.get(e.class_name,e.class_name) if e.class_name else None,e.static)
    if isinstance(e, ast.MethodCall): return ast.MethodCall(e.name,tuple(_transform_expr(a,fmap,cmap,alias_maps,vmap) for a in e.args),_transform_expr(e.receiver,fmap,cmap,alias_maps,vmap) if e.receiver is not None else None,cmap.get(e.class_name,e.class_name) if e.class_name else None,e.static,e.super_call)
    if isinstance(e, ast.SetMemberExpr): return ast.SetMemberExpr(_transform_expr(e.target,fmap,cmap,alias_maps,vmap),_transform_expr(e.value,fmap,cmap,alias_maps,vmap),e.immutable)
    return e


def _transform_stmt(s: ast.Stmt, fmap: dict[str,str], cmap: dict[str,str], alias_maps: dict[str, tuple[dict[str,str],dict[str,str],dict[str,tuple[str,bool]]]] | None = None, rename_decls: bool = True, vmap: dict[str,str] | None = None) -> ast.Stmt:
    alias_maps = alias_maps or {}
    vmap = vmap or {}
    te=lambda e:_transform_expr(e,fmap,cmap,alias_maps,vmap)

    def type_ref(name: str) -> str:
        if "." in name:
            alias, member = name.split(".", 1)
            maps = alias_maps.get(alias)
            if maps is None or member not in maps[1]:
                raise SemanticError(f"unknown imported type {name}")
            return maps[1][member]
        return cmap.get(name, name)
    if isinstance(s, ast.CommentStmt): return s
    if isinstance(s, ast.ImportStmt): return s
    if isinstance(s, ast.NamespaceStmt): return s
    if isinstance(s, ast.InterfaceDecl):
        methods=tuple(_transform_stmt(x,fmap,cmap,alias_maps,False,vmap) for x in s.methods)
        return ast.InterfaceDecl(cmap.get(s.name,s.name) if rename_decls else s.name, methods, s.private, tuple(type_ref(x) for x in s.parents))
    if isinstance(s, ast.ExportDecl):
        target=vmap.get(s.name,s.name)
        return ast.ExprStmt(ast.AssignExpr((target,),s.op,te(s.value),(s.type_code,)))
    if isinstance(s, ast.ModuleVarAssignStmt):
        maps=alias_maps.get(s.alias)
        if maps is None or s.name not in maps[2]:
            raise SemanticError(f"unknown imported variable {s.alias}.{s.name}")
        target,immutable=maps[2][s.name]
        if immutable:
            raise SemanticError(f"cannot assign to immutable imported binding {s.name!r}")
        return ast.AssignStmt((target,),te(s.value))
    if isinstance(s, ast.ExprStmt): return ast.ExprStmt(te(s.expr))
    if isinstance(s, ast.AssignStmt): return ast.AssignStmt(tuple(vmap.get(n,n) for n in s.targets),te(s.value),s.target_types)
    if isinstance(s, ast.MutateStmt): return ast.MutateStmt(te(s.target),s.op)
    if isinstance(s, ast.SetIndexStmt): return ast.SetIndexStmt(te(s.target),te(s.value))
    if isinstance(s, ast.SetMemberStmt): return ast.SetMemberStmt(te(s.target),te(s.value),s.define,s.immutable,s.private)
    if isinstance(s, ast.SuperInitStmt): return ast.SuperInitStmt(tuple(te(a) for a in s.args))
    if isinstance(s, ast.DestructorDecl): return ast.DestructorDecl(tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.body))
    if isinstance(s, ast.ReturnStmt): return ast.ReturnStmt(tuple(te(v) for v in s.values))
    if isinstance(s, ast.RaiseStmt): return ast.RaiseStmt(None if s.value is None else te(s.value))
    if isinstance(s, ast.TryStmt):
        return ast.TryStmt(tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.body),vmap.get(s.catch_name,s.catch_name) if s.catch_name else None,tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.catch_body) if s.catch_body is not None else None,tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.finally_body) if s.finally_body is not None else None)
    if isinstance(s, ast.FunctionDecl):
        ps=tuple(ast.Param(vmap.get(p.name,p.name),p.type_code,te(p.default) if p.default is not None else None) for p in s.params)
        return ast.FunctionDecl(fmap.get(s.name,s.name) if rename_decls else s.name,ps,tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.body),s.static,s.private,s.return_types,vmap.get(s.variadic,s.variadic) if s.variadic else None)
    if isinstance(s, ast.ClassDecl):
        ps=tuple(ast.Param(vmap.get(p.name,p.name),p.type_code,te(p.default) if p.default is not None else None) for p in s.params)
        # Class names are module-namespaced, but method names are members, not module
        # declarations.  Preserve method spellings even when a top-level function has
        # the same two-letter name; method bodies still rewrite references to module
        # globals/functions through fmap/vmap.
        body=tuple(_transform_stmt(x,fmap,cmap,alias_maps,False,vmap) for x in s.body)
        return ast.ClassDecl(cmap.get(s.name,s.name) if rename_decls else s.name,ps,body,s.private,cmap.get(s.parent,s.parent) if s.parent else None,tuple(type_ref(x) for x in s.interfaces))
    if isinstance(s, ast.IfStmt): return ast.IfStmt(te(s.condition),tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.body),tuple((te(c),tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in b)) for c,b in s.elifs),tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.else_body) if s.else_body is not None else None)
    if isinstance(s, ast.WhileStmt): return ast.WhileStmt(te(s.condition),tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.body))
    if isinstance(s, ast.ForStmt):
        f=lambda x:te(x) if x is not None else None
        return ast.ForStmt(s.kind,vmap.get(s.var,s.var) if s.var else None,f(s.source),f(s.start),f(s.stop),f(s.step),tuple(_transform_stmt(x,fmap,cmap,alias_maps,rename_decls,vmap) for x in s.body))
    return s


def _lexical_names(node: object, out: set[str] | None = None) -> set[str]:
    out = out if out is not None else set()
    if isinstance(node, (ast.Var, ast.ExtendedName)):
        out.add(node.name)
    elif isinstance(node, ast.AssignExpr):
        out.update(node.targets)
        _lexical_names(node.value,out)
        return out
    elif isinstance(node, ast.AssignStmt):
        out.update(node.targets)
        _lexical_names(node.value,out)
        return out
    elif isinstance(node, ast.ExportDecl):
        out.add(node.name)
        _lexical_names(node.value,out)
        return out
    elif isinstance(node, ast.FunctionDecl):
        out.update(p.name for p in node.params)
        if node.variadic: out.add(node.variadic)
    elif isinstance(node, ast.ClassDecl):
        out.update(p.name for p in node.params)
    elif isinstance(node, ast.LambdaExpr):
        out.update(p.name for p in node.params)
        if node.variadic: out.add(node.variadic)
    elif isinstance(node, ast.TryStmt) and node.catch_name:
        out.add(node.catch_name)
    elif isinstance(node, ast.ForStmt) and node.var:
        out.add(node.var)
    if isinstance(node, ast.Node):
        for f in fields(node):
            _lexical_names(getattr(node,f.name),out)
    elif isinstance(node,(tuple,list)):
        for x in node:_lexical_names(x,out)
    elif isinstance(node,dict):
        for x in node.values():_lexical_names(x,out)
    return out


def _declared_lexical_names(node: object, out: set[str] | None = None) -> set[str]:
    """Names introduced by lexical declarations, excluding ordinary references.

    Direct imports currently occupy a bare parser symbol for the whole module.  Until
    the parser carries full lexical shadow state, rejecting a declaration with the same
    spelling is safer than silently writing one cell and reading the imported one.
    """
    out = out if out is not None else set()
    if isinstance(node, ast.AssignExpr):
        if node.op in {":=", "::="}:
            out.update(node.targets)
        _declared_lexical_names(node.value, out)
        return out
    if isinstance(node, ast.ExportDecl):
        out.add(node.name)
        _declared_lexical_names(node.value, out)
        return out
    if isinstance(node, ast.FunctionDecl):
        out.update(p.name for p in node.params)
        if node.variadic:
            out.add(node.variadic)
    elif isinstance(node, ast.ClassDecl):
        out.update(p.name for p in node.params)
    elif isinstance(node, ast.LambdaExpr):
        out.update(p.name for p in node.params)
        if node.variadic:
            out.add(node.variadic)
    elif isinstance(node, ast.TryStmt) and node.catch_name:
        out.add(node.catch_name)
    elif isinstance(node, ast.ForStmt) and node.var:
        out.add(node.var)
    if isinstance(node, ast.Node):
        for f in fields(node):
            _declared_lexical_names(getattr(node, f.name), out)
    elif isinstance(node, (tuple, list)):
        for value in node:
            _declared_lexical_names(value, out)
    elif isinstance(node, dict):
        for value in node.values():
            _declared_lexical_names(value, out)
    return out


def _namespace_program(program: ast.Program, prefix: str) -> tuple[ast.Program, dict[str,str], dict[str,str], dict[str,str]]:
    funcs={s.name for s in program.statements if isinstance(s,ast.FunctionDecl)}
    types={s.name for s in program.statements if isinstance(s,(ast.ClassDecl,ast.InterfaceDecl))}
    fmap={n:f"{prefix}f_{n}" for n in funcs}
    cmap={n:f"{prefix}c_{n}" for n in types}
    # Imported modules get a private lexical namespace as well. Renaming every
    # lexical binding/reference (not member names) preserves ordinary shadowing
    # while making module-owned executable state safe to link into one C unit.
    vmap={n:f"{prefix}v_{n}" for n in _lexical_names(program)}
    out=[]
    for st in program.statements:
        if isinstance(st, ast.ImportStmt):
            continue
        out.append(_transform_stmt(st,fmap,cmap,{},True,vmap))
    return ast.Program(tuple(out)), fmap, cmap, vmap


def _standard_import_unit(imp: ast.ImportStmt):
    exports_map = standard_module_exports(imp.path)
    internal = False
    if exports_map is None:
        exports_map = internal_module_exports(imp.path)
        internal = exports_map is not None
    if exports_map is None:
        return None
    if imp.alias is None:
        label = "internal module" if internal else "standard module"
        raise SemanticError(f"{label} {imp.path} must be imported with an alias")
    syms = Symbols()
    for public_name, internal_name in exports_map.items():
        spec = builtin(internal_name)
        assert spec is not None
        syms.callables[public_name] = CallableSig(public_name, spec.min_arity, spec.max_arity, 1, True, False)
    # A stable synthetic identity that never participates in filesystem lookup.
    ident = Path(("/__slug_internal__" if internal else "/__slug_std__") + (imp.path.removeprefix("@internal") if internal else imp.path.removeprefix("@std")))
    return ident, ast.Program(()), syms, exports_map, {}, {}


class ModuleResolver:
    """Resolve a SLUG module graph into one deterministic linked AST.

    v0.1 gives every imported module a stable private namespace and emits each
    canonical path exactly once.  This matters now that modules may own executable
    top-level state: diamond imports must share one state cell, not clone a module.
    """
    def __init__(self, project: ProjectManifest | None = None):
        self.project = project
        self.counter=0
        self._stack:list[Path]=[]
        self._prefixes:dict[Path,str]={}
        self._units:dict[Path,tuple[ast.Program,Symbols,dict[str,str],dict[str,str],dict[str,str],tuple[Path,...]]]={}
        self._order:list[Path]=[]

    def _prefix_for(self,path:Path)->str:
        path=path.resolve()
        if path not in self._prefixes:
            self.counter+=1
            self._prefixes[path]=f"__slugm{self.counter}_"
        return self._prefixes[path]

    @staticmethod
    def _direct_origin(path: Path) -> str:
        # Parser-internal namespace key. It can never be written in SLUG source.
        return "\0direct:" + str(path.resolve())

    @staticmethod
    def _seed_from_children(
        children: list[tuple[ast.ImportStmt, Path, ast.Program, Symbols, dict[str,str], dict[str,str], dict[str,str]]]
    ) -> tuple[Symbols, dict[str, Symbols], set[str]]:
        seed = Symbols()
        modules: dict[str, Symbols] = {}
        direct_names: set[str] = set()
        alias_names: set[str] = set()
        core_names = set(Symbols.core().callables)
        for imp, cp, _prog, exports, _fm, _cm, _vm in children:
            if imp.alias is None:
                origin = ModuleResolver._direct_origin(cp)
                modules[origin] = exports
                for n, sig in exports.callables.items():
                    if n in direct_names or n in core_names:
                        raise SemanticError(f"direct import collision for callable {n}")
                    direct_names.add(n)
                    seed.callables[n] = sig
                for n, sig in exports.classes.items():
                    if n in direct_names:
                        raise SemanticError(f"direct import collision for class {n}")
                    direct_names.add(n)
                    seed.classes[n] = sig
                for n, sig in exports.variables.items():
                    if n in direct_names or n in core_names:
                        raise SemanticError(f"direct import collision for variable {n}")
                    direct_names.add(n)
                    seed.variables[n] = VarSig(n, sig.type_code, sig.immutable, origin)
                for n, sig in exports.interfaces.items():
                    if n in direct_names:
                        raise SemanticError(f"direct import collision for interface {n}")
                    direct_names.add(n)
                    seed.interfaces[n] = InterfaceSig(n, sig.methods)
            else:
                if imp.alias in alias_names:
                    raise SemanticError(f"duplicate module alias {imp.alias}")
                alias_names.add(imp.alias)
                modules[imp.alias] = exports
        return seed, modules, direct_names

    def _compile_unit(self,path:Path)->tuple[ast.Program,Symbols,dict[str,str],dict[str,str],dict[str,str],tuple[Path,...]]:
        path=path.resolve()
        cached=self._units.get(path)
        if cached is not None:return cached
        if path in self._stack:
            chain=" -> ".join(str(x) for x in self._stack+[path]);raise SemanticError(f"module import cycle: {chain}")
        self._stack.append(path)
        try:
            source=path.read_text(encoding="utf-8")
            children=[]
            for imp in _scan_imports(source):
                std = _standard_import_unit(imp)
                if std is not None:
                    cp, prog, exports, fm, cm, vm = std
                else:
                    if imp.path.startswith("@dep/"):
                        if self.project is None:
                            raise SemanticError("dependency import requires a discovered slug.json project manifest")
                        cp = self.project.resolve_dependency(imp.path)
                    else:
                        cp=_resolve_import_path(path,imp.path)
                    prog,exports,fm,cm,vm,_deps=self._compile_unit(cp)
                children.append((imp,cp,prog,exports,fm,cm,vm))
            seed,modules,direct_names=self._seed_from_children(children)
            tokens=lex(source)
            with _source_recursion_budget(len(tokens)):
                raw=parse(tokens,source,seed,modules)
            own_names={s.name for s in raw.statements if isinstance(s,(ast.FunctionDecl,ast.ClassDecl,ast.InterfaceDecl,ast.ExportDecl))}
            declared = _declared_lexical_names(raw)
            for n in direct_names:
                if n in own_names or n in declared:
                    raise SemanticError(f"imported symbol {n} collides with local declaration")

            direct_fmap:dict[str,str]={};direct_cmap:dict[str,str]={};alias_maps={}
            deps=[]
            for imp,cp,_prog,exports,fm,cm,vm in children:
                deps.append(cp)
                exported_f={n:fm[n] for n in exports.callables if n in fm}
                # cmap namespaces both classes and interfaces.
                exported_c={n:cm[n] for n in (*exports.classes, *exports.interfaces) if n in cm}
                exported_v={n:(vm[n],sig.immutable) for n,sig in exports.variables.items() if n in vm}
                key=imp.alias if imp.alias is not None else self._direct_origin(cp)
                alias_maps[key]=(exported_f,exported_c,exported_v)
                if imp.alias is None:
                    direct_fmap.update(exported_f);direct_cmap.update(exported_c)

            current=[]
            for st in raw.statements:
                if isinstance(st,ast.ImportStmt):continue
                current.append(_transform_stmt(st,direct_fmap,direct_cmap,alias_maps,False))
            nsprog,fmap,cmap,vmap=_namespace_program(ast.Program(tuple(current)),self._prefix_for(path))
            exports=_public_symbols(raw)
            unit=(nsprog,exports,fmap,cmap,vmap,tuple(deps))
            self._units[path]=unit
            self._order.append(path)  # children are appended first: topological init order
            return unit
        finally:
            self._stack.pop()

    def _root_context(self,path:Path)->tuple[str,ast.Program,Symbols,dict[str,Symbols],list[tuple[ast.ImportStmt,Path,ast.Program,Symbols,dict[str,str],dict[str,str],dict[str,str]]]]:
        path=path.resolve();source=path.read_text(encoding="utf-8")
        children=[]
        for imp in _scan_imports(source):
            std = _standard_import_unit(imp)
            if std is not None:
                cp, prog, exports, fm, cm, vm = std
            else:
                if imp.path.startswith("@dep/"):
                    if self.project is None:
                        raise SemanticError("dependency import requires a discovered slug.json project manifest")
                    cp = self.project.resolve_dependency(imp.path)
                else:
                    cp=_resolve_import_path(path,imp.path)
                prog,exports,fm,cm,vm,_deps=self._compile_unit(cp)
            children.append((imp,cp,prog,exports,fm,cm,vm))
        seed,modules,direct_names=self._seed_from_children(children)
        tokens=lex(source)
        with _source_recursion_budget(len(tokens)):
            raw=parse(tokens,source,seed,modules)
        own_names={s.name for s in raw.statements if isinstance(s,(ast.FunctionDecl,ast.ClassDecl,ast.InterfaceDecl,ast.ExportDecl))}
        declared = _declared_lexical_names(raw)
        for n in direct_names:
            if n in own_names or n in declared:
                raise SemanticError(f"imported symbol {n} collides with local declaration")
        return source,raw,seed,modules,children

    def parse_context(self,path:str|Path)->tuple[str,ast.Program,Symbols,dict[str,Symbols]]:
        if self.project is None:
            self.project = project_for_source(path)
        source,raw,seed,modules,_=self._root_context(Path(path).resolve())
        return source,raw,seed,modules

    def load(self,path:str|Path)->ast.Program:
        if self.project is None:
            self.project = project_for_source(path)
        root=Path(path).resolve()
        source,raw,_seed,_modules,children=self._root_context(root)
        direct_fmap:dict[str,str]={};direct_cmap:dict[str,str]={};alias_maps={}
        for imp,cp,_prog,exports,fm,cm,vm in children:
            exported_f={n:fm[n] for n in exports.callables if n in fm}
            exported_c={n:cm[n] for n in (*exports.classes, *exports.interfaces) if n in cm}
            exported_v={n:(vm[n],sig.immutable) for n,sig in exports.variables.items() if n in vm}
            key=imp.alias if imp.alias is not None else self._direct_origin(cp)
            alias_maps[key]=(exported_f,exported_c,exported_v)
            if imp.alias is None:
                direct_fmap.update(exported_f);direct_cmap.update(exported_c)
        current=[]
        for st in raw.statements:
            if isinstance(st,ast.ImportStmt):continue
            current.append(_transform_stmt(st,direct_fmap,direct_cmap,alias_maps,False))

        linked_prefix=[]
        seen:set[Path]=set()
        for mp in self._order:
            if mp==root or mp in seen:continue
            seen.add(mp)
            linked_prefix.extend(self._units[mp][0].statements)
        linked=ast.Program(tuple(linked_prefix+current))
        with _program_recursion_budget(linked):
            return analyze(linked)


def parse_file(path: str|Path) -> tuple[str,ast.Program,Symbols,dict[str,Symbols]]:
    return ModuleResolver().parse_context(path)


def frontend_file(path: str|Path) -> ast.Program:
    return ModuleResolver().load(path)


def emit_c_file(path: str|Path) -> str:
    program = frontend_file(path)
    with _program_recursion_budget(program):
        return generate_c(program)


def emit_ir_file(path: str|Path) -> str:
    program = frontend_file(path)
    with _program_recursion_budget(program):
        return format_ir(lower_ir(program))


def emit_mir_file(path: str|Path, *, optimized: bool = False) -> str:
    program = frontend_file(path)
    with _program_recursion_budget(program):
        mir = lower_mir(lower_ir(program))
        if optimized:
            mir = optimize_mir(mir).module
        return format_mir(mir)


def find_cc(preferred: str | None = None) -> str:
    if preferred:
        found = shutil.which(preferred)
        if found:
            return found
        candidate = Path(preferred)
        if candidate.is_file():
            return str(candidate)
        raise FileNotFoundError(f"C compiler {preferred!r} not found")

    for name in ("clang", "gcc", "cc", "cl"):
        found = shutil.which(name)
        if found:
            return found

    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles"),os.environ.get("ProgramFiles(x86)"),]
        for root in roots:
            if not root: continue
            for rel in (Path("LLVM/bin/clang.exe"), Path("LLVM/bin/clang-cl.exe")):
                candidate = Path(root) / rel
                if candidate.is_file(): return str(candidate)
    raise FileNotFoundError("no C compiler found (tried clang, gcc, cc, cl and standard LLVM paths)")


def _compiler_command(compiler: str, cpath: Path, exe: Path, bracket_depth: int | None = None) -> list[str]:
    # Normalize both native and foreign-style separators.  Besides making the driver
    # friendlier to explicit Windows compiler paths, this keeps platform-policy tests
    # meaningful when they run on a POSIX host.
    base = str(compiler).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base in {"cl", "cl.exe", "clang-cl", "clang-cl.exe"}:
        cmd = [compiler, "/nologo", "/utf-8", str(cpath), "/O2", f"/Fe:{exe}"]
        if bracket_depth is not None and base in {"clang-cl", "clang-cl.exe"}:
            cmd.append(f"/clang:-fbracket-depth={bracket_depth}")
        if os.name == "nt": cmd += ["/link", "ws2_32.lib", "shell32.lib", "user32.lib", "gdi32.lib", "winmm.lib"]
        return cmd
    cmd = [compiler, str(cpath), "-std=c11", "-O2"]
    if bracket_depth is not None and base in {"clang", "clang.exe"}:
        cmd.append(f"-fbracket-depth={bracket_depth}")
    if os.name != "nt": cmd.append("-lm")
    else: cmd += ["-lws2_32", "-lshell32", "-luser32", "-lgdi32", "-lwinmm"]
    cmd += ["-o", str(exe)]
    return cmd


def _build_ctext(ctext:str, output:str|Path, cc:str|None=None, keep_c:str|Path|None=None)->Path:
    output=Path(output);compiler=find_cc(cc)
    with tempfile.TemporaryDirectory(prefix="slug-build-") as td:
        cpath=Path(td)/"program.c";cpath.write_text(ctext,encoding="utf-8")
        if keep_c:Path(keep_c).write_text(ctext,encoding="utf-8")
        output.parent.mkdir(parents=True,exist_ok=True)
        # Clang's default bracket-depth=256 is a frontend default, not a SLUG
        # semantic limit.  Generated C can mirror finite source nesting, so derive an
        # upper bound from this translation unit instead of replacing 256 with another
        # fixed language ceiling.
        bracket_depth = max(256, ctext.count("(") + ctext.count("[") + ctext.count("{") + 32)
        proc=subprocess.run(_compiler_command(compiler,cpath,output,bracket_depth),text=True,encoding="utf-8",errors="replace",capture_output=True)
        if proc.returncode!=0:raise RuntimeError(f"C compiler failed:\n{proc.stdout}{proc.stderr}")
    return output


def build(source: str, output: str | Path, cc: str | None = None, keep_c: str | Path | None = None) -> Path:
    return _build_ctext(emit_c(source),output,cc,keep_c)


def build_file(path:str|Path, output:str|Path, cc:str|None=None, keep_c:str|Path|None=None)->Path:
    return _build_ctext(emit_c_file(path),output,cc,keep_c)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Node:
    pass


@dataclass(frozen=True, slots=True)
class Program(Node):
    statements: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class Expr(Node):
    pass


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    kind: str
    value: Any
    raw: str


@dataclass(frozen=True, slots=True)
class FormattedString(Expr):
    """Audited-v1 formatted string.

    ``parts`` contains decoded literal text chunks and ordinary SLUG expressions in
    source order.  Literal chunks are strings; expression chunks are :class:`Expr`
    nodes.  Keeping interpolation as real AST (rather than lowering it in the parser
    to a chain of ``+`` operations) preserves the language's explicit ``@s``
    conversion semantics, left-to-right evaluation order, and one-allocation native
    lowering opportunity.
    """

    parts: tuple[str | Expr, ...]


@dataclass(frozen=True, slots=True)
class Var(Expr):
    name: str
    root: bool = False


@dataclass(frozen=True, slots=True)
class ExtendedName(Expr):
    name: str
    root: bool = False


@dataclass(frozen=True, slots=True)
class Call(Expr):
    name: str
    args: tuple[Expr, ...]
    mode: str = "inferred"  # inferred / pack / forced
    root: bool = False       # one-shot ` escape from an active namespace


@dataclass(frozen=True, slots=True)
class ClassCall(Expr):
    name: str
    args: tuple[Expr, ...]
    root: bool = False


@dataclass(frozen=True, slots=True)
class ModuleCall(Expr):
    alias: str
    name: str
    args: tuple[Expr, ...]
    mode: str = "inferred"


@dataclass(frozen=True, slots=True)
class ModuleVar(Expr):
    alias: str
    name: str
    mode: str = "member"


@dataclass(frozen=True, slots=True)
class ModuleClassCall(Expr):
    alias: str
    name: str
    args: tuple[Expr, ...]
    mode: str = "inferred"


@dataclass(frozen=True, slots=True)
class ModuleClassMember(Expr):
    alias: str
    class_name: str
    name: str
    mode: str = "inferred"


@dataclass(frozen=True, slots=True)
class ModuleClassMethodCall(Expr):
    alias: str
    class_name: str
    name: str
    args: tuple[Expr, ...]
    mode: str = "pack"


@dataclass(frozen=True, slots=True)
class CallableInvoke(Expr):
    callee: Expr
    args: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class LambdaExpr(Expr):
    params: tuple[Param, ...]
    body: tuple[Stmt, ...]
    return_types: tuple[str, ...] | None = None
    variadic: str | None = None


@dataclass(frozen=True, slots=True)
class DefaultArg(Expr):
    """Named-call placeholder `xx`: use this parameter's declared default."""
    pass


@dataclass(frozen=True, slots=True)
class Cast(Expr):
    type_code: str
    value: Expr
    grouped: bool = False


@dataclass(frozen=True, slots=True)
class DynamicCast(Expr):
    type_expr: Expr
    value: Expr
    grouped_type: bool = False


@dataclass(frozen=True, slots=True)
class Unary(Expr):
    op: str
    value: Expr


@dataclass(frozen=True, slots=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class AssignExpr(Expr):
    targets: tuple[str, ...]
    op: str  # := or ::=
    value: Expr
    # Optional binding contracts aligned with targets. None means adaptive/unconstrained.
    # Contracts are part of the binding, not merely a one-shot cast.
    target_types: tuple[str | None, ...] = ()


@dataclass(frozen=True, slots=True)
class BoolExpr(Expr):
    value: Expr


@dataclass(frozen=True, slots=True)
class Compare(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class LogicNot(Expr):
    value: Expr


@dataclass(frozen=True, slots=True)
class LogicBinary(Expr):
    op: str  # and / or
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class ListLiteral(Expr):
    items: tuple[Expr, ...]
    frozen: bool = False


@dataclass(frozen=True, slots=True)
class MapLiteral(Expr):
    entries: tuple[tuple[Expr, Expr], ...]
    frozen: bool = False


@dataclass(frozen=True, slots=True)
class IndexExpr(Expr):
    base: Expr
    index: Expr


@dataclass(frozen=True, slots=True)
class SliceExpr(Expr):
    base: Expr
    start: Expr | None = None
    stop: Expr | None = None
    step: Expr | None = None


@dataclass(frozen=True, slots=True)
class SetIndexExpr(Expr):
    target: IndexExpr
    value: Expr


@dataclass(frozen=True, slots=True)
class MemberExpr(Expr):
    """Object/class/current member reference.

    base is set for ``a.x`` style instance traversal.  class_name is set for
    ``AB.x`` static traversal.  With neither present, ``static`` selects
    current-instance ``.x`` vs current-class ``..x``.
    """
    name: str
    base: Expr | None = None
    class_name: str | None = None
    static: bool = False


@dataclass(frozen=True, slots=True)
class MethodCall(Expr):
    name: str
    args: tuple[Expr, ...]
    receiver: Expr | None = None
    class_name: str | None = None
    static: bool = False
    super_call: bool = False


@dataclass(frozen=True, slots=True)
class SetMemberExpr(Expr):
    target: MemberExpr
    value: Expr
    immutable: bool = False


@dataclass(frozen=True, slots=True)
class Stmt(Node):
    pass


@dataclass(frozen=True, slots=True)
class CommentStmt(Stmt):
    text: str
    preserve: bool = False


@dataclass(frozen=True, slots=True)
class ExprStmt(Stmt):
    expr: Expr


@dataclass(frozen=True, slots=True)
class AssignStmt(Stmt):
    targets: tuple[str, ...]
    value: Expr
    # Present only so the parser can diagnose illegal `a@i=...` precisely; binding
    # contracts are introduced with := / ::= rather than nearest-scope `=`.
    target_types: tuple[str | None, ...] = ()


@dataclass(frozen=True, slots=True)
class MutateStmt(Stmt):
    target: Expr
    op: str


@dataclass(frozen=True, slots=True)
class SetIndexStmt(Stmt):
    target: IndexExpr
    value: Expr


@dataclass(frozen=True, slots=True)
class SetMemberStmt(Stmt):
    target: MemberExpr
    value: Expr
    define: bool = False
    immutable: bool = False
    private: bool = False


@dataclass(frozen=True, slots=True)
class SuperInitStmt(Stmt):
    args: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class DestructorDecl(Stmt):
    body: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class ModuleVarAssignStmt(Stmt):
    alias: str
    name: str
    value: Expr
    mode: str = "member"


@dataclass(frozen=True, slots=True)
class ExportDecl(Stmt):
    name: str
    op: str
    value: Expr
    type_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReturnStmt(Stmt):
    values: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class Param(Node):
    name: str
    type_code: str | None = None
    default: Expr | None = None


@dataclass(frozen=True, slots=True)
class FunctionDecl(Stmt):
    name: str
    params: tuple[Param, ...]
    body: tuple[Stmt, ...]
    static: bool = False
    private: bool = False
    return_types: tuple[str, ...] | None = None
    variadic: str | None = None


@dataclass(frozen=True, slots=True)
class InterfaceDecl(Stmt):
    name: str
    methods: tuple[FunctionDecl, ...]
    private: bool = False
    parents: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassDecl(Stmt):
    name: str
    params: tuple[Param, ...]
    body: tuple[Stmt, ...]
    private: bool = False
    parent: str | None = None
    interfaces: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IfStmt(Stmt):
    condition: Expr
    body: tuple[Stmt, ...]
    elifs: tuple[tuple[Expr, tuple[Stmt, ...]], ...] = ()
    else_body: tuple[Stmt, ...] | None = None


@dataclass(frozen=True, slots=True)
class WhileStmt(Stmt):
    condition: Expr
    body: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class ForStmt(Stmt):
    kind: str  # repeat / foreach / range / slice / slice_step
    var: str | None
    source: Expr | None
    start: Expr | None
    stop: Expr | None
    step: Expr | None
    body: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class BreakStmt(Stmt):
    pass


@dataclass(frozen=True, slots=True)
class ContinueStmt(Stmt):
    pass


@dataclass(frozen=True, slots=True)
class RaiseStmt(Stmt):
    value: Expr | None = None


@dataclass(frozen=True, slots=True)
class TryStmt(Stmt):
    body: tuple[Stmt, ...]
    catch_name: str | None = None
    catch_body: tuple[Stmt, ...] | None = None
    finally_body: tuple[Stmt, ...] | None = None


@dataclass(frozen=True, slots=True)
class ImportStmt(Stmt):
    path: str
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class NamespaceStmt(Stmt):
    """Compile-time active-namespace selection.

    ``alias is None`` means restore the current/default module namespace (``<:.``).
    The statement has no runtime value or emitted instruction.
    """
    alias: str | None = None

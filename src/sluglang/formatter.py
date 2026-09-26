from __future__ import annotations

from . import ast


def _string_body(value: str, quote: str = "'") -> str:
    """Encode literal string text for the audited-v1 single-quoted syntax."""
    body = value.replace("\\", "\\\\")
    body = body.replace("\0", "\\0").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    body = body.replace("{", "\\{").replace("}", "\\}")
    body = body.replace(quote, "\\" + quote)
    return body


def _string_literal(value: str, quote: str = "'") -> str:
    # Single-quoted v1 source. Braces are escaped because unescaped braces are
    # interpolation delimiters.
    return quote + _string_body(value, quote) + quote


def _logic_expr(e: ast.Expr, compact: bool = False, parent_prec: int = 0) -> str:
    sep = "" if compact else " "
    if isinstance(e, ast.LogicBinary):
        prec = 2 if e.op == "and" else 1
        op = "+" if e.op == "and" else "/"
        text = _logic_expr(e.left, compact, prec) + sep + op + sep + _logic_expr(e.right, compact, prec)
        if prec < parent_prec:
            return "[" + text + "]"
        return text
    if isinstance(e, ast.LogicNot):
        text = "!" + _logic_expr(e.value, compact, 3)
        if 3 < parent_prec:
            return "[" + text + "]"
        return text
    if isinstance(e, ast.Compare):
        return expr(e.left, compact) + sep + e.op + sep + expr(e.right, compact)
    return expr(e, compact)


def expr(e: ast.Expr, compact: bool = False) -> str:
    sep = "" if compact else " "
    if isinstance(e, ast.Literal):
        if e.kind == "string":
            return _string_literal(e.value)
        if e.kind == "null":
            return "nn"
        if e.kind == "float":
            raw = e.raw
            if raw.startswith("0."):
                raw = raw[1:]
            if raw.endswith(".0"):
                raw = raw[:-1]
            return raw
        if e.kind == "int":
            return str(int(e.value))
    if isinstance(e, ast.FormattedString):
        pieces: list[str] = ["'"]
        for part in e.parts:
            if isinstance(part, str):
                pieces.append(_string_body(part))
            else:
                pieces.extend(("{", expr(part, compact), "}"))
        pieces.append("'")
        return "".join(pieces)
    if isinstance(e, ast.Var):
        return ("`" if e.root else "") + e.name
    if isinstance(e, ast.ExtendedName):
        return ("`" if e.root else "") + e.name
    if isinstance(e, ast.DefaultArg):
        return "xx"
    if isinstance(e, ast.BoolExpr):
        return "?" + _logic_expr(e.value, compact)
    if isinstance(e, ast.Compare):
        return _logic_expr(e, compact)
    if isinstance(e, ast.LogicNot):
        return _logic_expr(e, compact)
    if isinstance(e, ast.LogicBinary):
        return _logic_expr(e, compact)
    if isinstance(e, ast.Cast):
        if e.grouped:
            return f"@{e.type_code}|" + expr(e.value, compact) + "|"
        return f"@{e.type_code}" + sep + expr(e.value, compact)
    if isinstance(e, ast.DynamicCast):
        t = expr(e.type_expr, compact)
        if e.grouped_type:
            return "@|" + t + "|" + sep + expr(e.value, compact)
        return "@" + t + sep + expr(e.value, compact)
    if isinstance(e, ast.Unary):
        return expr(e.value, compact) + sep + e.op
    if isinstance(e, ast.Binary):
        left = expr(e.left, compact)
        right = expr(e.right, compact)
        # Whitespace is never a lexical boundary. When two decimal integer literals
        # are adjacent in RPN output, insert v1's zero-value `$` terminator so their
        # digits cannot merge/repartition.
        if (
            isinstance(e.left, ast.Literal) and e.left.kind == "int"
            and isinstance(e.right, ast.Literal) and e.right.kind == "int"
            and left and left[-1].isdigit() and right and right[0].isdigit()
        ):
            left += "$"
        if compact:
            return f"{left}{right}{e.op}"
        return f"{left} {right} {e.op}"
    if isinstance(e, ast.AssignExpr):
        types = e.target_types if e.target_types else (None,) * len(e.targets)
        head = "".join(n + (("@" + t) if t else "") for n, t in zip(e.targets, types))
        return f"{head}{e.op if compact else ' ' + e.op + ' '}{expr(e.value, compact)}"
    if isinstance(e, ast.Call):
        comma = "," if compact else ", "
        head = ("`" if e.root else "") + e.name
        if e.mode == "pack":
            return head + "[" + comma.join(expr(a, compact) for a in e.args) + "]"
        if e.mode == "forced":
            if not e.args:
                return ("`" if e.root else "") + "!" + e.name
            return ("`" if e.root else "") + "!" + e.name + sep + _expr_sequence(e.args, compact)
        if not e.args:
            return head
        if any(isinstance(a, (ast.AssignExpr, ast.SetIndexExpr, ast.ListLiteral, ast.MapLiteral, ast.DefaultArg)) for a in e.args):
            return head + "[" + comma.join(expr(a, compact) for a in e.args) + "]"
        return head + sep + _expr_sequence(e.args, compact)
    if isinstance(e, ast.ClassCall):
        head = ("`" if e.root else "") + e.name
        return head + (sep if e.args else "") + sep.join(expr(a, compact) for a in e.args)
    if isinstance(e, ast.ModuleVar):
        if e.mode in {"direct", "namespace-bare"}:
            return e.name
        if e.mode.startswith("namespace-"):
            return e.name
        return e.alias + "." + e.name
    if isinstance(e, ast.ModuleCall):
        comma = "," if compact else ", "
        ns = e.mode.startswith("namespace-")
        mode = e.mode[len("namespace-"):] if ns else e.mode
        head = e.name if ns else e.alias + "." + e.name
        if mode == "pack":
            return head + "[" + comma.join(expr(a, compact) for a in e.args) + "]"
        if mode == "forced":
            return "!" + e.name + ((sep + _expr_sequence(e.args, compact)) if e.args else "")
        return head + (sep if e.args else "") + _expr_sequence(e.args, compact)
    if isinstance(e, ast.ModuleClassCall):
        comma = "," if compact else ", "
        ns = e.mode.startswith("namespace-")
        mode = e.mode[len("namespace-"):] if ns else e.mode
        head = e.name if ns else e.alias + "." + e.name
        if mode == "pack":
            return head + "[" + comma.join(expr(a, compact) for a in e.args) + "]"
        return head + (sep if e.args else "") + _expr_sequence(e.args, compact)
    if isinstance(e, ast.ModuleClassMember):
        head = e.class_name if e.mode.startswith("namespace-") else e.alias + "." + e.class_name
        return head + "." + e.name
    if isinstance(e, ast.ModuleClassMethodCall):
        comma = "," if compact else ", "
        ns = e.mode.startswith("namespace-")
        head = e.class_name if ns else e.alias + "." + e.class_name
        return head + "." + e.name + "[" + comma.join(expr(a, compact) for a in e.args) + "]"
    if isinstance(e, ast.CallableInvoke):
        comma = "," if compact else ", "
        return "!" + expr(e.callee, compact) + "[" + comma.join(expr(a, compact) for a in e.args) + "]"
    if isinstance(e, ast.LambdaExpr):
        head = "lb"
        if e.return_types:
            if len(e.return_types) == 1:
                head += "@" + e.return_types[0]
            else:
                head += "[" + ",".join("@" + x for x in e.return_types) + "]"
        head += "".join(_param(p) for p in e.params)
        if e.variadic:
            head += "[" + e.variadic + "]"
        body = _compact_body(e.body)
        return head + "{" + body + "}"
    if isinstance(e, ast.ListLiteral):
        comma = "," if compact else ", "
        return ("@" if e.frozen else "") + "[" + comma.join(expr(i, compact) for i in e.items) + "]"
    if isinstance(e, ast.MapLiteral):
        comma = "," if compact else ", "
        colon = ":" if compact else ": "
        if not e.entries:
            return ("@" if e.frozen else "") + "[:]"
        body = comma.join(expr(k, compact) + colon + expr(v, compact) for k, v in e.entries)
        return ("@" if e.frozen else "") + "[" + body + "]"
    if isinstance(e, ast.IndexExpr):
        return expr(e.base, compact) + "[" + expr(e.index, compact) + "]"
    if isinstance(e, ast.SliceExpr):
        a = "" if e.start is None else expr(e.start, compact)
        b = "" if e.stop is None else expr(e.stop, compact)
        if e.step is None:
            return expr(e.base, compact) + "[" + a + ":" + b + "]"
        c = expr(e.step, compact)
        return expr(e.base, compact) + "[" + a + ":" + b + ":" + c + "]"
    if isinstance(e, ast.SetIndexExpr):
        return expr(e.target, compact) + (":=" if compact else " := ") + expr(e.value, compact)
    if isinstance(e, ast.MemberExpr):
        if e.class_name is not None:
            return e.class_name + "." + e.name
        if e.base is not None:
            return expr(e.base, compact) + "." + e.name
        return (".." if e.static else ".") + e.name
    if isinstance(e, ast.MethodCall):
        comma = "," if compact else ", "
        args = "[" + comma.join(expr(a, compact) for a in e.args) + "]"
        if e.super_call:
            return "^^." + e.name + args
        if e.class_name is not None:
            return e.class_name + "." + e.name + args
        if e.receiver is not None:
            return expr(e.receiver, compact) + "." + e.name + args
        return (".." if e.static else ".") + e.name + args
    if isinstance(e, ast.SetMemberExpr):
        op = "::=" if e.immutable else ":="
        return expr(e.target, compact) + (op if compact else " " + op + " ") + expr(e.value, compact)
    raise TypeError(f"no formatter for {type(e).__name__}")


def _expr_sequence(values: list[ast.Expr] | tuple[ast.Expr, ...], compact: bool) -> str:
    """Concatenate expressions without relying on whitespace as a delimiter.

    Adjacent digit-ending/start expressions need a real lexical boundary because SLUG
    ignores whitespace. `$` is the integer terminator, so `0,5` in a multi-expression
    header must become `0$5`, not `05`.
    """
    pieces = [expr(v, compact) for v in values]
    for i in range(len(pieces) - 1):
        if pieces[i] and pieces[i][-1].isdigit() and pieces[i + 1] and pieces[i + 1][0].isdigit():
            pieces[i] += "$"
    return ("" if compact else " " ).join(pieces)


def _param(p: ast.Param) -> str:
    out = p.name
    if p.type_code:
        out += "@" + p.type_code
    if p.default is not None:
        out += "=" + expr(p.default, True)
    return out



def _compact_body(body: tuple[ast.Stmt, ...] | list[ast.Stmt]) -> str:
    """Render a compact nested body without letting preserved line comments eat code.

    Semicolons are sufficient boundaries for ordinary SLUG statements, but ``//!`` is
    lexically a physical-line comment. A nested formatter must therefore emit a real
    newline after every preserved comment instead of merely appending ``;``. Using the
    same rule for preserved block comments is harmless and keeps the policy uniform.
    """
    parts: list[str] = []
    for stmt in body:
        text = compact_stmt(stmt)
        if not text:
            continue
        if isinstance(stmt, ast.CommentStmt) and stmt.preserve:
            if parts and not parts[-1].endswith("\n"):
                parts.append("\n")
            parts.append(text)
            parts.append("\n")
        else:
            parts.append(text)
            parts.append(";")
    if parts and parts[-1] == ";":
        parts.pop()
    return "".join(parts)

def compact_stmt(s: ast.Stmt) -> str:
    if isinstance(s, ast.CommentStmt):
        return s.text if s.preserve else ""
    if isinstance(s, ast.ExprStmt):
        return expr(s.expr, True)
    if isinstance(s, ast.AssignStmt):
        types = s.target_types if s.target_types else (None,) * len(s.targets)
        head = "".join(n + (("@" + t) if t else "") for n, t in zip(s.targets, types))
        return head + "=" + expr(s.value, True)
    if isinstance(s, ast.MutateStmt):
        return expr(s.target, True) + s.op
    if isinstance(s, ast.SetIndexStmt):
        return expr(s.target, True) + "=" + expr(s.value, True)
    if isinstance(s, ast.SetMemberStmt):
        prefix = "-" if s.private else ""
        op = "::=" if s.immutable else (":=" if s.define else "=")
        return prefix + expr(s.target, True) + op + expr(s.value, True)
    if isinstance(s, ast.SuperInitStmt):
        return "^^[" + ",".join(expr(a, True) for a in s.args) + "]"
    if isinstance(s, ast.DestructorDecl):
        return "~-{" + _compact_body(s.body) + "}"
    if isinstance(s, ast.ReturnStmt):
        return "rv" + "".join(expr(v, True) for v in s.values)
    if isinstance(s, ast.IfStmt):
        def body_text(body):
            return "{" + _compact_body(body) + "}"
        head = ("if" if s.elifs or s.else_body is not None else "") + expr(s.condition, True) + body_text(s.body)
        for cond, body in s.elifs:
            head += "ei" + expr(cond, True) + body_text(body)
        if s.else_body is not None:
            head += "ee" + body_text(s.else_body)
        return head
    if isinstance(s, ast.WhileStmt):
        body = "{" + _compact_body(s.body) + "}"
        return "wl" + expr(s.condition, True) + body
    if isinstance(s, ast.ForStmt):
        body = "{" + _compact_body(s.body) + "}"
        if s.kind == "repeat":
            return "fl" + expr(s.start, True) + body
        if s.kind == "foreach":
            return "fl" + s.var + expr(s.source, True) + body
        if s.kind == "range":
            return "fl" + s.var + _expr_sequence((s.start, s.stop), True) + body
        if s.kind == "slice":
            return "fl" + s.var + _expr_sequence((s.source, s.start, s.stop), True) + body
        if s.kind == "slice_step":
            return "fl" + s.var + _expr_sequence((s.source, s.start, s.stop, s.step), True) + body
        raise TypeError(f"unknown for kind {s.kind}")
    if isinstance(s, ast.BreakStmt):
        return "bl"
    if isinstance(s, ast.ContinueStmt):
        return "cl"
    if isinstance(s, ast.RaiseStmt):
        return "er" if s.value is None else "er" + expr(s.value, True)
    if isinstance(s, ast.TryStmt):
        body = "{" + _compact_body(s.body) + "}"
        out = "tr" + body
        if s.catch_body is not None:
            cb = "{" + _compact_body(s.catch_body) + "}"
            out += "ca" + (s.catch_name or "") + cb
        if s.finally_body is not None:
            fb = "{" + _compact_body(s.finally_body) + "}"
            out += "fn" + fb
        return out
    if isinstance(s, ast.ImportStmt):
        return ">" + _string_literal(s.path) + ((":" + s.alias) if s.alias else "")
    if isinstance(s, ast.NamespaceStmt):
        return "<:." if s.alias is None else "<:" + s.alias
    if isinstance(s, ast.ModuleVarAssignStmt):
        head = s.name if s.mode in {"direct", "namespace-bare"} or s.mode.startswith("namespace-") else s.alias + "." + s.name
        return head + "=" + expr(s.value, True)
    if isinstance(s, ast.ExportDecl):
        return "+:" + s.name + (("@" + s.type_code) if s.type_code else "") + s.op + expr(s.value, True)
    if isinstance(s, ast.InterfaceDecl):
        prefix = ("-" if s.private else "") + "#?" + s.name + "".join(":" + parent for parent in s.parents)
        return prefix + "{" + _compact_body(s.methods) + "}"
    if isinstance(s, ast.FunctionDecl):
        prefix = ("-" if s.private else "") + ("~~" if s.static else "~") + s.name
        if s.return_types:
            if len(s.return_types) == 1:
                prefix += "@" + s.return_types[0]
            else:
                prefix += "[" + ",".join("@" + x for x in s.return_types) + "]"
        head = prefix + "".join(_param(p) for p in s.params)
        if s.variadic:
            head += "[" + s.variadic + "]"
        return head + "{" + _compact_body(s.body) + "}"
    if isinstance(s, ast.ClassDecl):
        prefix = ("-" if s.private else "") + "#" + s.name
        if s.parent:
            prefix += "<" + s.parent
        prefix += "".join(":" + it for it in s.interfaces)
        return prefix + "".join(_param(p) for p in s.params) + "{" + _compact_body(s.body) + "}"
    raise TypeError(f"no compact formatter for {type(s).__name__}")


def compact_program(program: ast.Program, with_semicolons: bool = True) -> str:
    parts: list[str] = []
    for s in program.statements:
        text = compact_stmt(s)
        if not text:
            continue
        if isinstance(s, ast.CommentStmt) and s.preserve:
            if parts and not parts[-1].endswith("\n"):
                parts.append("\n")
            parts.append(text)
            parts.append("\n")
        else:
            parts.append(text)
            if with_semicolons:
                parts.append(";")
    out = "".join(parts)
    if with_semicolons:
        out = out.rstrip(";")
    return out


def pretty_program(program: ast.Program, indent: str = "    ") -> str:
    lines: list[str] = []

    def emit_stmt(s: ast.Stmt, depth: int) -> None:
        pad = indent * depth
        if isinstance(s, ast.CommentStmt):
            for line in s.text.splitlines():
                lines.append(pad + line)
            return
        if isinstance(s, ast.FunctionDecl):
            head = ("-" if s.private else "") + ("~~" if s.static else "~") + s.name
            if s.return_types:
                if len(s.return_types) == 1:
                    head += "@" + s.return_types[0]
                else:
                    head += "[" + ",".join("@" + x for x in s.return_types) + "]"
            if s.params:
                head += " " + " ".join(_param(p) for p in s.params)
            if s.variadic:
                head += " [" + s.variadic + "]"
            lines.append(pad + head + " {")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            return
        if isinstance(s, ast.InterfaceDecl):
            head = ("-" if s.private else "") + "#?" + s.name + "".join(":" + parent for parent in s.parents)
            lines.append(pad + head + " {")
            for child in s.methods:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            return
        if isinstance(s, ast.ExportDecl):
            lines.append(pad + "+:" + s.name + (("@" + s.type_code) if s.type_code else "") + " " + s.op + " " + expr(s.value, False) + ";")
            return
        if isinstance(s, ast.ModuleVarAssignStmt):
            lines.append(pad + compact_stmt(s) + ";")
            return
        if isinstance(s, ast.ClassDecl):
            head = ("-" if s.private else "") + "#" + s.name
            if s.parent:
                head += "<" + s.parent
            head += "".join(":" + it for it in s.interfaces)
            if s.params:
                head += " " + " ".join(_param(p) for p in s.params)
            lines.append(pad + head + " {")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            return
        if isinstance(s, ast.IfStmt):
            prefix = "if " if s.elifs or s.else_body is not None else ""
            lines.append(pad + prefix + expr(s.condition, False) + " {")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            for cond, body in s.elifs:
                lines.append(pad + "ei " + expr(cond, False) + " {")
                for child in body:
                    emit_stmt(child, depth + 1)
                lines.append(pad + "}")
            if s.else_body is not None:
                lines.append(pad + "ee {")
                for child in s.else_body:
                    emit_stmt(child, depth + 1)
                lines.append(pad + "}")
            return
        if isinstance(s, ast.WhileStmt):
            lines.append(pad + "wl " + expr(s.condition, False) + " {")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            return
        if isinstance(s, ast.ForStmt):
            if s.kind == "repeat":
                head = "fl " + expr(s.start, False)
            elif s.kind == "foreach":
                head = "fl " + s.var + " " + expr(s.source, False)
            elif s.kind == "range":
                head = "fl " + s.var + " " + _expr_sequence((s.start, s.stop), False)
            elif s.kind == "slice":
                head = "fl " + s.var + " " + _expr_sequence((s.source, s.start, s.stop), False)
            else:
                head = "fl " + s.var + " " + _expr_sequence((s.source, s.start, s.stop, s.step), False)
            lines.append(pad + head + " {")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            return
        if isinstance(s, ast.BreakStmt):
            lines.append(pad + "bl")
            return
        if isinstance(s, ast.ContinueStmt):
            lines.append(pad + "cl")
            return
        if isinstance(s, ast.RaiseStmt):
            lines.append(pad + ("er;" if s.value is None else "er " + expr(s.value, False) + ";"))
            return
        if isinstance(s, ast.TryStmt):
            lines.append(pad + "tr {")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            if s.catch_body is not None:
                lines.append(pad + "ca" + ((" " + s.catch_name) if s.catch_name else "") + " {")
                for child in s.catch_body:
                    emit_stmt(child, depth + 1)
                lines.append(pad + "}")
            if s.finally_body is not None:
                lines.append(pad + "fn {")
                for child in s.finally_body:
                    emit_stmt(child, depth + 1)
                lines.append(pad + "}")
            return
        if isinstance(s, ast.ImportStmt):
            lines.append(pad + ">" + _string_literal(s.path) + ((":" + s.alias) if s.alias else ""))
            return
        if isinstance(s, ast.NamespaceStmt):
            lines.append(pad + ("<:." if s.alias is None else "<:" + s.alias))
            return
        if isinstance(s, ast.ExprStmt):
            lines.append(pad + expr(s.expr, False) + ";")
            return
        if isinstance(s, ast.AssignStmt):
            types = s.target_types if s.target_types else (None,) * len(s.targets)
            head = "".join(n + (("@" + t) if t else "") for n, t in zip(s.targets, types))
            lines.append(pad + head + " = " + expr(s.value, False) + ";")
            return
        if isinstance(s, ast.MutateStmt):
            lines.append(pad + expr(s.target, False) + s.op + ";")
            return
        if isinstance(s, ast.SetIndexStmt):
            lines.append(pad + expr(s.target, False) + " = " + expr(s.value, False) + ";")
            return
        if isinstance(s, ast.SetMemberStmt):
            op = "::=" if s.immutable else (":=" if s.define else "=")
            lines.append(pad + ("-" if s.private else "") + expr(s.target, False) + " " + op + " " + expr(s.value, False) + ";")
            return
        if isinstance(s, ast.SuperInitStmt):
            lines.append(pad + "^^[" + ", ".join(expr(a, False) for a in s.args) + "];")
            return
        if isinstance(s, ast.DestructorDecl):
            lines.append(pad + "~-{")
            for child in s.body:
                emit_stmt(child, depth + 1)
            lines.append(pad + "}")
            return
        if isinstance(s, ast.ReturnStmt):
            if s.values:
                lines.append(pad + "rv " + " ".join(expr(v, False) for v in s.values) + ";")
            else:
                lines.append(pad + "rv;")
            return
        lines.append(pad + compact_stmt(s))

    for st in program.statements:
        emit_stmt(st, 0)
    return "\n".join(lines) + ("\n" if lines else "")


def semantic_key(program: ast.Program) -> ast.Program:
    """Return an AST key containing semantic structure, not source spelling.

    Literal `raw` text is deliberately normalized away so equivalent spellings such as
    `0.5`/`.5`, `3$`/`3`, and other crusher shortenings compare equal. Comments are
    source metadata and are likewise excluded from executable semantics.
    """
    def ne(e: ast.Expr) -> ast.Expr:
        if isinstance(e, ast.Literal):
            return ast.Literal(e.kind, e.value, "")
        if isinstance(e, ast.FormattedString):
            return ast.FormattedString(tuple(part if isinstance(part, str) else ne(part) for part in e.parts))
        if isinstance(e, (ast.Var, ast.ExtendedName, ast.DefaultArg, ast.ModuleVar)):
            return e
        if isinstance(e, ast.Call):
            return ast.Call(e.name, tuple(ne(a) for a in e.args), "inferred", e.root)
        if isinstance(e, ast.ClassCall):
            return ast.ClassCall(e.name, tuple(ne(a) for a in e.args), e.root)
        if isinstance(e, ast.ModuleCall):
            return ast.ModuleCall(e.alias, e.name, tuple(ne(a) for a in e.args), "inferred")
        if isinstance(e, ast.ModuleClassCall):
            return ast.ModuleClassCall(e.alias, e.name, tuple(ne(a) for a in e.args), "inferred")
        if isinstance(e, ast.ModuleClassMember):
            return ast.ModuleClassMember(e.alias, e.class_name, e.name, "inferred")
        if isinstance(e, ast.ModuleClassMethodCall):
            return ast.ModuleClassMethodCall(e.alias, e.class_name, e.name, tuple(ne(a) for a in e.args), "pack")
        if isinstance(e, ast.CallableInvoke):
            return ast.CallableInvoke(ne(e.callee), tuple(ne(a) for a in e.args))
        if isinstance(e, ast.LambdaExpr):
            return ast.LambdaExpr(tuple(ast.Param(p.name, p.type_code, ne(p.default) if p.default is not None else None) for p in e.params), tuple(ns(x) for x in e.body if not isinstance(x, ast.CommentStmt)), e.return_types, e.variadic)
        if isinstance(e, ast.Cast):
            # Explicit cast grouping is source disambiguation, not runtime semantics.
            return ast.Cast(e.type_code, ne(e.value), False)
        if isinstance(e, ast.DynamicCast):
            return ast.DynamicCast(ne(e.type_expr), ne(e.value), False)
        if isinstance(e, ast.Unary):
            return ast.Unary(e.op, ne(e.value))
        if isinstance(e, ast.Binary):
            return ast.Binary(e.op, ne(e.left), ne(e.right))
        if isinstance(e, ast.AssignExpr):
            return ast.AssignExpr(e.targets, e.op, ne(e.value), e.target_types)
        if isinstance(e, ast.BoolExpr):
            return ast.BoolExpr(ne(e.value))
        if isinstance(e, ast.Compare):
            return ast.Compare(e.op, ne(e.left), ne(e.right))
        if isinstance(e, ast.LogicNot):
            return ast.LogicNot(ne(e.value))
        if isinstance(e, ast.LogicBinary):
            return ast.LogicBinary(e.op, ne(e.left), ne(e.right))
        if isinstance(e, ast.ListLiteral):
            return ast.ListLiteral(tuple(ne(i) for i in e.items), e.frozen)
        if isinstance(e, ast.MapLiteral):
            return ast.MapLiteral(tuple((ne(k), ne(v)) for k, v in e.entries), e.frozen)
        if isinstance(e, ast.IndexExpr):
            return ast.IndexExpr(ne(e.base), ne(e.index))
        if isinstance(e, ast.SliceExpr):
            return ast.SliceExpr(ne(e.base), ne(e.start) if e.start is not None else None, ne(e.stop) if e.stop is not None else None, ne(e.step) if e.step is not None else None)
        if isinstance(e, ast.SetIndexExpr):
            return ast.SetIndexExpr(ne(e.target), ne(e.value))
        if isinstance(e, ast.MemberExpr):
            return ast.MemberExpr(e.name, ne(e.base) if e.base is not None else None, e.class_name, e.static)
        if isinstance(e, ast.MethodCall):
            return ast.MethodCall(e.name, tuple(ne(a) for a in e.args), ne(e.receiver) if e.receiver is not None else None, e.class_name, e.static, e.super_call)
        if isinstance(e, ast.SetMemberExpr):
            return ast.SetMemberExpr(ne(e.target), ne(e.value), e.immutable)
        return e

    def np(p: ast.Param) -> ast.Param:
        return ast.Param(p.name, p.type_code, ne(p.default) if p.default is not None else None)

    def ns(s: ast.Stmt) -> ast.Stmt | None:
        if isinstance(s, ast.CommentStmt):
            return None
        if isinstance(s, ast.ExprStmt):
            return ast.ExprStmt(ne(s.expr))
        if isinstance(s, ast.AssignStmt):
            return ast.AssignStmt(s.targets, ne(s.value), s.target_types)
        if isinstance(s, ast.MutateStmt):
            return ast.MutateStmt(ne(s.target), s.op)
        if isinstance(s, ast.SetIndexStmt):
            return ast.SetIndexStmt(ne(s.target), ne(s.value))
        if isinstance(s, ast.SetMemberStmt):
            return ast.SetMemberStmt(ne(s.target), ne(s.value), s.define, s.immutable, s.private)
        if isinstance(s, ast.SuperInitStmt):
            return ast.SuperInitStmt(tuple(ne(a) for a in s.args))
        if isinstance(s, ast.DestructorDecl):
            return ast.DestructorDecl(tuple(x for x in (ns(c) for c in s.body) if x is not None))
        if isinstance(s, ast.ReturnStmt):
            return ast.ReturnStmt(tuple(ne(v) for v in s.values))
        if isinstance(s, ast.FunctionDecl):
            return ast.FunctionDecl(
                s.name, tuple(np(p) for p in s.params),
                tuple(x for x in (ns(c) for c in s.body) if x is not None),
                s.static, s.private, s.return_types, s.variadic,
            )
        if isinstance(s, ast.ClassDecl):
            return ast.ClassDecl(
                s.name, tuple(np(p) for p in s.params),
                tuple(x for x in (ns(c) for c in s.body) if x is not None),
                s.private, s.parent, s.interfaces,
            )
        if isinstance(s, ast.IfStmt):
            body = tuple(x for x in (ns(c) for c in s.body) if x is not None)
            elifs = tuple((ne(c), tuple(x for x in (ns(v) for v in b) if x is not None)) for c,b in s.elifs)
            eb = None if s.else_body is None else tuple(x for x in (ns(c) for c in s.else_body) if x is not None)
            return ast.IfStmt(ne(s.condition), body, elifs, eb)
        if isinstance(s, ast.WhileStmt):
            return ast.WhileStmt(ne(s.condition), tuple(x for x in (ns(c) for c in s.body) if x is not None))
        if isinstance(s, ast.ForStmt):
            return ast.ForStmt(
                s.kind, s.var,
                ne(s.source) if s.source is not None else None,
                ne(s.start) if s.start is not None else None,
                ne(s.stop) if s.stop is not None else None,
                ne(s.step) if s.step is not None else None,
                tuple(x for x in (ns(c) for c in s.body) if x is not None),
            )
        if isinstance(s, (ast.BreakStmt, ast.ContinueStmt)):
            return s
        if isinstance(s, ast.RaiseStmt):
            return ast.RaiseStmt(None if s.value is None else ne(s.value))
        if isinstance(s, ast.TryStmt):
            body = tuple(x for x in (ns(c) for c in s.body) if x is not None)
            cb = None if s.catch_body is None else tuple(x for x in (ns(c) for c in s.catch_body) if x is not None)
            fb = None if s.finally_body is None else tuple(x for x in (ns(c) for c in s.finally_body) if x is not None)
            return ast.TryStmt(body, s.catch_name, cb, fb)
        if isinstance(s, ast.ImportStmt):
            return s
        if isinstance(s, ast.NamespaceStmt):
            return s
        if isinstance(s, ast.ModuleVarAssignStmt):
            return ast.ModuleVarAssignStmt(s.alias, s.name, ne(s.value), s.mode)
        if isinstance(s, ast.ExportDecl):
            return ast.ExportDecl(s.name, s.op, ne(s.value), s.type_code)
        if isinstance(s, ast.InterfaceDecl):
            return ast.InterfaceDecl(s.name, tuple(ns(m) for m in s.methods), s.private, s.parents)
        return s

    return ast.Program(tuple(x for x in (ns(s) for s in program.statements) if x is not None))

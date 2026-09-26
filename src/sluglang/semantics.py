from __future__ import annotations

from dataclasses import dataclass, field

from . import ast
from .builtins import builtin
from .diagnostics import SemanticError


@dataclass(slots=True)
class Binding:
    name: str
    immutable: bool = False
    inferred: str | None = None
    # Explicit binding contract (`a@i8:=...`).  Unlike inferred, this survives later
    # assignments and is enforced at every write boundary.
    contract: str | None = None


@dataclass(slots=True)
class Scope:
    parent: "Scope | None" = None
    bindings: dict[str, Binding] = field(default_factory=dict)

    def nearest(self, name: str) -> Binding | None:
        s: Scope | None = self
        while s:
            if name in s.bindings:
                return s.bindings[name]
            s = s.parent
        return None


@dataclass(slots=True)
class FieldInfo:
    owner: str
    name: str
    static: bool
    private: bool
    immutable: bool


@dataclass(slots=True)
class ClassInfo:
    decl: ast.ClassDecl
    fields: dict[tuple[bool, str], FieldInfo] = field(default_factory=dict)
    methods: dict[tuple[bool, str], ast.FunctionDecl] = field(default_factory=dict)
    destructor: ast.DestructorDecl | None = None

    @property
    def required_arity(self) -> int:
        return sum(1 for p in self.decl.params if p.default is None)

    @property
    def max_arity(self) -> int:
        return len(self.decl.params)


def _method_contract_key(fn: ast.FunctionDecl) -> tuple[object, ...]:
    return (
        fn.static,
        fn.name,
        tuple(p.type_code for p in fn.params),
        tuple(p.default is not None for p in fn.params),
        fn.variadic is not None,
        fn.return_types,
    )


def _has_trait_default(fn: ast.FunctionDecl) -> bool:
    return any(not isinstance(x, ast.CommentStmt) for x in fn.body)


def materialize_traits(program: ast.Program) -> ast.Program:
    """Validate interface/trait contracts and inject unambiguous default methods."""
    interfaces = {s.name: s for s in program.statements if isinstance(s, ast.InterfaceDecl)}
    classes = {s.name: s for s in program.statements if isinstance(s, ast.ClassDecl)}
    if len(interfaces) != sum(isinstance(s, ast.InterfaceDecl) for s in program.statements):
        raise SemanticError("duplicate interface declaration")
    overlap = set(interfaces) & set(classes)
    if overlap:
        raise SemanticError(f"type name {sorted(overlap)[0]} is both a class and an interface")

    for name, it in interfaces.items():
        seen: set[tuple[bool, str]] = set()
        for fn in it.methods:
            if fn.private:
                raise SemanticError(f"interface method {name}.{fn.name} cannot be private")
            key = (fn.static, fn.name)
            if key in seen:
                raise SemanticError(f"duplicate interface method {name}.{fn.name}")
            seen.add(key)
        for parent in it.parents:
            if parent not in interfaces:
                raise SemanticError(f"unknown parent interface {parent} for {name}")

    visiting: set[str] = set()
    done: set[str] = set()

    def check_cycle(name: str) -> None:
        if name in done:
            return
        if name in visiting:
            raise SemanticError(f"interface inheritance cycle involving {name}")
        visiting.add(name)
        for parent in interfaces[name].parents:
            check_cycle(parent)
        visiting.remove(name)
        done.add(name)

    for name in interfaces:
        check_cycle(name)

    cache: dict[str, dict[tuple[bool, str], tuple[ast.FunctionDecl, tuple[ast.FunctionDecl, ...]]]] = {}

    def resolved(name: str) -> dict[tuple[bool, str], tuple[ast.FunctionDecl, tuple[ast.FunctionDecl, ...]]]:
        if name in cache:
            return cache[name]
        out: dict[tuple[bool, str], tuple[ast.FunctionDecl, tuple[ast.FunctionDecl, ...]]] = {}
        for parent in interfaces[name].parents:
            for key, (req, defaults) in resolved(parent).items():
                if key in out and _method_contract_key(out[key][0]) != _method_contract_key(req):
                    raise SemanticError(f"conflicting inherited interface signatures for {name}.{key[1]}")
                if key in out:
                    old_req, old_defaults = out[key]
                    out[key] = (old_req, old_defaults + defaults)
                else:
                    out[key] = (req, defaults)
        for fn in interfaces[name].methods:
            key = (fn.static, fn.name)
            prior = out.get(key)
            if prior is not None and _method_contract_key(prior[0]) != _method_contract_key(fn):
                raise SemanticError(f"interface {name}.{fn.name} changes inherited method signature")
            defaults = (fn,) if _has_trait_default(fn) else ()
            if defaults:
                out[key] = (fn, defaults)
            elif prior is not None:
                out[key] = (fn, prior[1])
            else:
                out[key] = (fn, ())
        cache[name] = out
        return out

    for name in interfaces:
        resolved(name)

    def class_method(
        class_name: str,
        key: tuple[bool, str],
        class_map: dict[str, ast.ClassDecl],
    ) -> ast.FunctionDecl | None:
        seen: set[str] = set()
        cur: str | None = class_name
        while cur and cur not in seen:
            seen.add(cur)
            cls = class_map.get(cur)
            if cls is None:
                return None
            for child in cls.body:
                if isinstance(child, ast.FunctionDecl) and (child.static, child.name) == key:
                    return child
            cur = cls.parent
        return None

    materialized = dict(classes)
    order: list[str] = []
    seen_cls: set[str] = set()

    def visit_cls(name: str) -> None:
        if name in seen_cls:
            return
        cls = classes[name]
        if cls.parent in classes:
            visit_cls(cls.parent)
        seen_cls.add(name)
        order.append(name)

    for name in classes:
        visit_cls(name)

    for name in order:
        cls = materialized[name]
        merged: dict[tuple[bool, str], tuple[ast.FunctionDecl, list[ast.FunctionDecl]]] = {}
        for it_name in cls.interfaces:
            if it_name not in interfaces:
                raise SemanticError(f"unknown interface {it_name} for class {name}")
            for key, (req, defaults) in resolved(it_name).items():
                if key in merged and _method_contract_key(merged[key][0]) != _method_contract_key(req):
                    raise SemanticError(f"class {name} inherits conflicting interface signatures for {key[1]}")
                if key in merged:
                    merged[key][1].extend(defaults)
                else:
                    merged[key] = (req, list(defaults))
        additions: list[ast.FunctionDecl] = []
        for key, (req, defaults) in merged.items():
            found = class_method(name, key, materialized)
            if found is not None:
                if found.private:
                    raise SemanticError(f"private method {name}.{found.name} cannot satisfy an interface")
                if _method_contract_key(found) != _method_contract_key(req):
                    raise SemanticError(f"method {name}.{found.name} does not match interface signature")
                continue
            unique_defaults: list[ast.FunctionDecl] = []
            seen_defaults: set[tuple[object, ...]] = set()
            for default in defaults:
                sig = (
                    default.name,
                    default.static,
                    default.params,
                    default.body,
                    default.return_types,
                    default.variadic,
                )
                if sig not in seen_defaults:
                    seen_defaults.add(sig)
                    unique_defaults.append(default)
            if len(unique_defaults) > 1:
                raise SemanticError(f"ambiguous trait defaults for {name}.{req.name}; override it explicitly")
            if not unique_defaults:
                raise SemanticError(f"class {name} does not implement interface method {req.name}")
            default = unique_defaults[0]
            additions.append(
                ast.FunctionDecl(
                    default.name,
                    default.params,
                    default.body,
                    default.static,
                    False,
                    default.return_types,
                    default.variadic,
                )
            )
        if additions:
            cls = ast.ClassDecl(cls.name, cls.params, cls.body + tuple(additions), cls.private, cls.parent, cls.interfaces)
            materialized[name] = cls

    if not any(materialized.get(name) is not classes[name] for name in classes):
        return program
    return ast.Program(
        tuple(materialized.get(stmt.name, stmt) if isinstance(stmt, ast.ClassDecl) else stmt for stmt in program.statements)
    )


class Analyzer:
    def __init__(self) -> None:
        self.root = Scope()
        self.loop_depth = 0
        self.function_depth = 0
        self.class_depth = 0
        self.current_return_types: tuple[str, ...] | None = None
        self.functions: dict[str, ast.FunctionDecl] = {}
        self.classes: dict[str, ClassInfo] = {}
        self.current_class: str | None = None
        self.current_static_method = False
        self.in_constructor = False
        self.in_destructor = False
        self.catch_depth = 0
        # Effective contracts at assignment sites are consumed by the typed IR/C backend.
        self.assignment_contracts: dict[int, tuple[str | None, ...]] = {}
        # Strongest sound type fact at each expression site after local flow joins.
        self.expr_type_codes: dict[int, str | None] = {}

    def analyze(self, program: ast.Program) -> ast.Program:
        self.functions = {s.name: s for s in program.statements if isinstance(s, ast.FunctionDecl)}
        self._collect_classes(program)
        self._validate_class_graph()
        self._stmts(program.statements, self.root)
        return program

    # ---------- class metadata ----------

    def _collect_classes(self, program: ast.Program) -> None:
        for s in program.statements:
            if isinstance(s, ast.ClassDecl):
                if s.name in self.classes:
                    raise SemanticError(f"duplicate class {s.name}")
                self.classes[s.name] = ClassInfo(s)
        for name, ci in self.classes.items():
            for child in ci.decl.body:
                if isinstance(child, ast.FunctionDecl):
                    key = (child.static, child.name)
                    if key in ci.methods:
                        raise SemanticError(f"duplicate method {name}.{child.name}")
                    ci.methods[key] = child
                elif isinstance(child, ast.DestructorDecl):
                    if ci.destructor is not None:
                        raise SemanticError(f"class {name} has more than one destructor")
                    ci.destructor = child
                else:
                    d = self._field_decl_from_stmt(child)
                    if d is not None:
                        target, immutable, private = d
                        if target.base is not None or target.class_name is not None:
                            raise SemanticError("class field declarations must use .x or ..x")
                        key = (target.static, target.name)
                        if key in ci.fields:
                            raise SemanticError(f"duplicate field {name}.{target.name}")
                        ci.fields[key] = FieldInfo(name, target.name, target.static, private, immutable)

    def _validate_class_graph(self) -> None:
        for name, ci in self.classes.items():
            parent = ci.decl.parent
            if parent is not None and parent not in self.classes:
                raise SemanticError(f"unknown parent class {parent} for {name}")
            # constructor parameter order
            saw_default = False
            for p in ci.decl.params:
                if p.default is not None:
                    saw_default = True
                elif saw_default:
                    raise SemanticError(f"required constructor parameter cannot follow a default in {name}")
        for name in self.classes:
            seen: set[str] = set()
            cur: str | None = name
            while cur is not None:
                if cur in seen:
                    raise SemanticError(f"inheritance cycle involving {cur}")
                seen.add(cur)
                cur = self.classes[cur].decl.parent

        # Instance fields are inherited storage; redeclaring one in a child would create
        # the shadowing ambiguity SLUG deliberately forbids. Static fields are per-class
        # and may shadow.
        for name, ci in self.classes.items():
            if ci.decl.parent is None:
                continue
            for (static, field_name), _ in ci.fields.items():
                if static:
                    continue
                inherited = self._lookup_field(ci.decl.parent, field_name, False)
                if inherited is not None:
                    raise SemanticError(f"instance field {name}.{field_name} redeclares inherited field {inherited.owner}.{field_name}")

    @staticmethod
    def _field_decl_from_stmt(stmt: ast.Stmt) -> tuple[ast.MemberExpr, bool, bool] | None:
        if isinstance(stmt, ast.ExprStmt) and isinstance(stmt.expr, ast.SetMemberExpr):
            return stmt.expr.target, stmt.expr.immutable, False
        if isinstance(stmt, ast.SetMemberStmt) and stmt.define:
            return stmt.target, stmt.immutable, stmt.private
        return None

    def _lookup_field(self, class_name: str, name: str, static: bool) -> FieldInfo | None:
        cur: str | None = class_name
        while cur is not None:
            ci = self.classes.get(cur)
            if ci is None:
                return None
            found = ci.fields.get((static, name))
            if found is not None:
                return found
            # static state is class-specific; AB.x does not silently search a parent.
            if static:
                return None
            cur = ci.decl.parent
        return None

    def _lookup_method(self, class_name: str, name: str, static: bool) -> tuple[str, ast.FunctionDecl] | None:
        cur: str | None = class_name
        while cur is not None:
            ci = self.classes.get(cur)
            if ci is None:
                return None
            fn = ci.methods.get((static, name))
            if fn is not None:
                return cur, fn
            cur = ci.decl.parent
        return None

    def _check_private(self, owner: str, private: bool, what: str) -> None:
        if private and self.current_class != owner:
            raise SemanticError(f"cannot access private {what} of class {owner}")

    # ---------- flow-sensitive binding facts ----------

    @staticmethod
    def _binding_snapshot(scope: Scope) -> dict[int, Binding]:
        out: dict[int, Binding] = {}
        cur: Scope | None = scope
        while cur is not None:
            for binding in cur.bindings.values():
                out[id(binding)] = binding
            cur = cur.parent
        return out

    @staticmethod
    def _snapshot_values(snapshot: dict[int, Binding]) -> dict[int, str | None]:
        return {key: binding.inferred for key, binding in snapshot.items()}

    @staticmethod
    def _restore_snapshot(snapshot: dict[int, Binding], values: dict[int, str | None]) -> None:
        for key, binding in snapshot.items():
            binding.inferred = values[key]

    def _common_class(self, names: list[str]) -> str | None:
        if not names:
            return None
        chains: list[list[str]] = []
        for name in names:
            chain: list[str] = []
            cur: str | None = name
            seen: set[str] = set()
            while cur is not None and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                info = self.classes.get(cur)
                cur = info.decl.parent if info is not None else None
            chains.append(chain)
        for candidate in chains[0]:
            if all(candidate in chain for chain in chains[1:]):
                return candidate
        return None

    def _join_inferred(self, values: list[str | None]) -> str | None:
        if not values:
            return None
        if all(value == values[0] for value in values):
            return values[0]
        if any(value is None for value in values):
            return None
        assert all(value is not None for value in values)
        concrete = [value for value in values if value is not None]
        bases = [self._contract_base(value) for value in concrete]
        if all(base in {"i", "u", "integer"} for base in bases):
            return "integer"
        if all(value.startswith("class:") for value in concrete):
            common = self._common_class([value[6:] for value in concrete])
            return "class:" + common if common else None
        return None

    def _merge_flow_paths(
        self,
        snapshot: dict[int, Binding],
        paths: list[dict[int, str | None]],
    ) -> None:
        for key, binding in snapshot.items():
            if binding.contract is not None:
                binding.inferred = binding.contract
                continue
            binding.inferred = self._join_inferred([path[key] for path in paths])

    # ---------- statements ----------

    def _stmts(self, stmts: tuple[ast.Stmt, ...], scope: Scope) -> None:
        for stmt in stmts:
            self._stmt(stmt, scope)

    def _stmt(self, stmt: ast.Stmt, scope: Scope) -> None:
        if isinstance(stmt, ast.CommentStmt):
            return
        if isinstance(stmt, ast.InterfaceDecl):
            if scope is not self.root:
                raise SemanticError("interfaces are only valid at module scope")
            return
        if isinstance(stmt, ast.ExportDecl):
            if scope is not self.root:
                raise SemanticError("exports are only valid at module scope")
            if stmt.name in scope.bindings:
                raise SemanticError(f"duplicate module binding {stmt.name!r}")
            self._expr(stmt.value, scope)
            inferred = self._infer_expr_type(stmt.value, scope)
            if stmt.type_code is not None:
                self._check_contract_expr(stmt.type_code, stmt.value, scope, f"export {stmt.name}")
            contract = stmt.type_code
            scope.bindings[stmt.name] = Binding(stmt.name, stmt.op == "::=", contract or inferred, contract)
            self.assignment_contracts[id(stmt)] = (contract,)
            return
        if isinstance(stmt, ast.ModuleVarAssignStmt):
            # Imported module writes are validated during linking against the provider's
            # public symbol table. Semantic analysis still validates the RHS locally.
            self._expr(stmt.value, scope)
            return
        if isinstance(stmt, ast.ExprStmt):
            self._expr(stmt.expr, scope)
            return
        if isinstance(stmt, ast.AssignStmt):
            if stmt.target_types and any(t is not None for t in stmt.target_types):
                raise SemanticError("binding type contracts are introduced with := or ::=, not nearest-scope =")
            self._expr(stmt.value, scope)
            inferred = self._infer_expr_type(stmt.value, scope)
            effective: list[str | None] = []
            for name in stmt.targets:
                b = scope.nearest(name)
                if b and b.immutable:
                    raise SemanticError(f"cannot assign to immutable binding {name!r}")
                if b is None:
                    scope.bindings[name] = Binding(name, False, inferred, None)
                    effective.append(None)
                else:
                    if b.contract is None:
                        b.inferred = inferred
                    else:
                        b.inferred = b.contract
                    effective.append(b.contract)
            for name, contract in zip(stmt.targets, effective):
                if contract is not None:
                    self._check_contract_expr(contract, stmt.value, scope, f"binding {name}")
            self.assignment_contracts[id(stmt)] = tuple(effective)
            return
        if isinstance(stmt, ast.MutateStmt):
            if isinstance(stmt.target, (ast.Var, ast.ExtendedName)):
                b = scope.nearest(stmt.target.name)
                if b is None:
                    raise SemanticError(f"cannot {stmt.op} undefined binding {stmt.target.name!r}")
                if b.immutable:
                    raise SemanticError(f"cannot mutate immutable binding {stmt.target.name!r}")
            else:
                self._member_access(stmt.target, scope, writing=True)
            return
        if isinstance(stmt, ast.SetIndexStmt):
            self._expr(stmt.target.base, scope)
            self._expr(stmt.target.index, scope)
            self._expr(stmt.value, scope)
            return
        if isinstance(stmt, ast.SetMemberStmt):
            self._member_access(stmt.target, scope, writing=True, defining=stmt.define, immutable=stmt.immutable)
            self._expr(stmt.value, scope)
            return
        if isinstance(stmt, ast.SuperInitStmt):
            if not self.in_constructor or self.current_class is None:
                raise SemanticError("^^[...] is only valid in a class constructor body")
            parent = self.classes[self.current_class].decl.parent
            if parent is None:
                raise SemanticError(f"class {self.current_class} has no parent constructor")
            self._check_call_args(self.classes[parent].decl.params, None, stmt.args, parent)
            for i, a in enumerate(stmt.args):
                if not isinstance(a, ast.DefaultArg):
                    self._expr(a, scope)
                    if i < len(self.classes[parent].decl.params) and self.classes[parent].decl.params[i].type_code:
                        self._check_contract_expr(self.classes[parent].decl.params[i].type_code, a, scope, f"argument {i+1} of {parent}")
            return
        if isinstance(stmt, ast.DestructorDecl):
            if self.current_class is None:
                raise SemanticError("destructor used outside class")
            saved_ctor, saved_dtor = self.in_constructor, self.in_destructor
            saved_loop = self.loop_depth
            self.in_constructor = False
            self.in_destructor = True
            self.loop_depth = 0
            try:
                self._stmts(stmt.body, Scope(scope))
            finally:
                self.in_constructor, self.in_destructor = saved_ctor, saved_dtor
                self.loop_depth = saved_loop
            return
        if isinstance(stmt, ast.ReturnStmt):
            if self.function_depth <= 0 and not self.in_constructor and not self.in_destructor:
                raise SemanticError("return used outside a function/class body")
            if self.function_depth > 0 and self.current_return_types is not None and len(stmt.values) != len(self.current_return_types):
                raise SemanticError(
                    f"return provides {len(stmt.values)} value(s), but function contract requires {len(self.current_return_types)}"
                )
            for i, v in enumerate(stmt.values):
                self._expr(v, scope)
                if self.function_depth > 0 and self.current_return_types is not None:
                    self._check_contract_expr(self.current_return_types[i], v, scope, f"return value {i+1}")
            return
        if isinstance(stmt, ast.RaiseStmt):
            if stmt.value is None:
                if self.catch_depth <= 0:
                    raise SemanticError("bare er is only valid inside catch")
            else:
                self._expr(stmt.value, scope)
            return
        if isinstance(stmt, ast.TryStmt):
            snapshot = self._binding_snapshot(scope)
            entry = self._snapshot_values(snapshot)
            self._restore_snapshot(snapshot, entry)
            self._stmts(stmt.body, Scope(scope))
            paths = [self._snapshot_values(snapshot)]
            if stmt.catch_body is not None:
                # An exception may occur after any prefix of the try body. Without
                # effect-path splitting, the only sound catch-entry fact for a mutable
                # uncontracted binding is unknown. Contracts remain exact.
                catch_entry = dict(entry)
                for key, binding in snapshot.items():
                    if binding.contract is None:
                        catch_entry[key] = None
                self._restore_snapshot(snapshot, catch_entry)
                catch_scope = Scope(scope)
                if stmt.catch_name is not None:
                    catch_scope.bindings[stmt.catch_name] = Binding(stmt.catch_name, False, "error", "error")
                self.catch_depth += 1
                try:
                    self._stmts(stmt.catch_body, catch_scope)
                finally:
                    self.catch_depth -= 1
                paths.append(self._snapshot_values(snapshot))
            self._merge_flow_paths(snapshot, paths)
            if stmt.finally_body is not None:
                self._stmts(stmt.finally_body, Scope(scope))
            return
        if isinstance(stmt, ast.ImportStmt):
            if scope is not self.root:
                raise SemanticError("imports are only valid at module scope")
            return
        if isinstance(stmt, ast.NamespaceStmt):
            # Namespace selection is compile-time lexical lookup context. The parser
            # has already resolved affected calls/classes into module-qualified AST.
            return
        if isinstance(stmt, ast.FunctionDecl):
            # Named functions are module declarations or class methods. Nested named
            # declarations previously parsed but were not entered in any callable table,
            # creating a dangerous accept-but-unusable surface. Lambdas are the explicit
            # lexical/nested callable mechanism.
            if self.function_depth > 0 or (self.current_class is None and scope is not self.root):
                raise SemanticError("named functions are only valid at module scope or directly in a class body")
            self._analyze_function(stmt, scope, as_method=self.current_class is not None)
            return
        if isinstance(stmt, ast.ClassDecl):
            if scope is not self.root:
                raise SemanticError("classes are only valid at module scope")
            self._analyze_class(stmt, scope)
            return
        if isinstance(stmt, ast.IfStmt):
            # Conditions are evaluated in sequence on the false path. Preserve those
            # effects, but analyze each body from the exact state at its branch edge.
            self._expr(stmt.condition, scope)
            snapshot = self._binding_snapshot(scope)
            fallthrough = self._snapshot_values(snapshot)
            paths: list[dict[int, str | None]] = []

            self._restore_snapshot(snapshot, fallthrough)
            self._stmts(stmt.body, Scope(scope))
            paths.append(self._snapshot_values(snapshot))

            for cond, body in stmt.elifs:
                self._restore_snapshot(snapshot, fallthrough)
                self._expr(cond, scope)
                fallthrough = self._snapshot_values(snapshot)
                self._restore_snapshot(snapshot, fallthrough)
                self._stmts(body, Scope(scope))
                paths.append(self._snapshot_values(snapshot))

            self._restore_snapshot(snapshot, fallthrough)
            if stmt.else_body is not None:
                self._stmts(stmt.else_body, Scope(scope))
                paths.append(self._snapshot_values(snapshot))
            else:
                paths.append(dict(fallthrough))
            self._merge_flow_paths(snapshot, paths)
            return
        if isinstance(stmt, ast.WhileStmt):
            snapshot = self._binding_snapshot(scope)
            entry = self._snapshot_values(snapshot)
            header = dict(entry)
            exits: list[dict[int, str | None]] = []
            self.loop_depth += 1
            try:
                while True:
                    self._restore_snapshot(snapshot, header)
                    self._expr(stmt.condition, scope)
                    after_condition = self._snapshot_values(snapshot)
                    exits.append(dict(after_condition))
                    self._stmts(stmt.body, Scope(scope))
                    after_body = self._snapshot_values(snapshot)
                    self._restore_snapshot(snapshot, entry)
                    self._merge_flow_paths(snapshot, [entry, after_body])
                    new_header = self._snapshot_values(snapshot)
                    if new_header == header:
                        break
                    header = new_header
            finally:
                self.loop_depth -= 1
            self._restore_snapshot(snapshot, header)
            if exits:
                self._merge_flow_paths(snapshot, exits)
            return
        if isinstance(stmt, ast.ForStmt):
            for e in (stmt.source, stmt.start, stmt.stop, stmt.step):
                if e is not None:
                    self._expr(e, scope)
            snapshot = self._binding_snapshot(scope)
            entry = self._snapshot_values(snapshot)
            header = dict(entry)
            exits: list[dict[int, str | None]] = [dict(entry)]
            self.loop_depth += 1
            try:
                while True:
                    self._restore_snapshot(snapshot, header)
                    loop_scope = Scope(scope)
                    if stmt.var is not None:
                        loop_scope.bindings[stmt.var] = Binding(stmt.var)
                    self._stmts(stmt.body, loop_scope)
                    after_body = self._snapshot_values(snapshot)
                    exits.append(dict(after_body))
                    self._restore_snapshot(snapshot, entry)
                    self._merge_flow_paths(snapshot, [entry, after_body])
                    new_header = self._snapshot_values(snapshot)
                    if new_header == header:
                        break
                    header = new_header
            finally:
                self.loop_depth -= 1
            self._restore_snapshot(snapshot, header)
            self._merge_flow_paths(snapshot, exits)
            return
        if isinstance(stmt, (ast.BreakStmt, ast.ContinueStmt)):
            if self.loop_depth <= 0:
                raise SemanticError(f"{type(stmt).__name__.replace('Stmt','').lower()} used outside a loop")
            return

    def _analyze_function(self, stmt: ast.FunctionDecl, scope: Scope, as_method: bool) -> None:
        fn_scope = Scope(scope)
        saw_default = False
        for p in stmt.params:
            if p.default is not None:
                saw_default = True
                self._expr(p.default, fn_scope)
                if p.type_code:
                    self._check_contract_expr(p.type_code, p.default, fn_scope, f"default for parameter {p.name}")
            elif saw_default:
                raise SemanticError("required parameter cannot follow a defaulted parameter")
            fn_scope.bindings[p.name] = Binding(p.name, False, p.type_code, p.type_code)
        if stmt.variadic:
            if stmt.variadic in fn_scope.bindings:
                raise SemanticError(f"variadic binding {stmt.variadic!r} duplicates a fixed parameter")
            fn_scope.bindings[stmt.variadic] = Binding(stmt.variadic, False, "list", None)
        saved_loop = self.loop_depth
        saved_depth = self.function_depth
        saved_returns = self.current_return_types
        saved_static = self.current_static_method
        saved_ctor, saved_dtor = self.in_constructor, self.in_destructor
        saved_catch = self.catch_depth
        self.loop_depth = 0
        self.catch_depth = 0
        self.function_depth += 1
        self.current_return_types = stmt.return_types
        self.current_static_method = bool(as_method and stmt.static)
        self.in_constructor = False
        self.in_destructor = False
        try:
            self._stmts(stmt.body, fn_scope)
        finally:
            self.loop_depth = saved_loop
            self.function_depth = saved_depth
            self.current_return_types = saved_returns
            self.current_static_method = saved_static
            self.in_constructor, self.in_destructor = saved_ctor, saved_dtor
            self.catch_depth = saved_catch

    def _analyze_class(self, stmt: ast.ClassDecl, scope: Scope) -> None:
        class_scope = Scope(scope)
        saw_default = False
        for p in stmt.params:
            if p.default is not None:
                saw_default = True
                self._expr(p.default, scope)
                if p.type_code:
                    self._check_contract_expr(p.type_code, p.default, scope, f"default for constructor parameter {p.name}")
            elif saw_default:
                raise SemanticError("required constructor parameter cannot follow a defaulted parameter")
            class_scope.bindings[p.name] = Binding(p.name, False, p.type_code, p.type_code)

        saved_class = self.current_class
        saved_static = self.current_static_method
        saved_ctor, saved_dtor = self.in_constructor, self.in_destructor
        self.current_class = stmt.name
        self.current_static_method = False
        self.in_constructor = True
        self.in_destructor = False
        self.class_depth += 1
        try:
            # Parent construction rule.
            explicit_super_positions = [i for i, x in enumerate(stmt.body) if isinstance(x, ast.SuperInitStmt)]
            if len(explicit_super_positions) > 1:
                raise SemanticError(f"class {stmt.name} invokes its parent constructor more than once")
            if stmt.parent is not None:
                parent = self.classes[stmt.parent]
                ctor_actions = [
                    x for x in stmt.body
                    if not isinstance(x, (ast.CommentStmt, ast.FunctionDecl, ast.DestructorDecl))
                    and not (self._field_decl_from_stmt(x) is not None and self._field_decl_from_stmt(x)[0].static)
                ]
                explicit = next((x for x in ctor_actions if isinstance(x, ast.SuperInitStmt)), None)
                if explicit is not None and ctor_actions and ctor_actions[0] is not explicit:
                    raise SemanticError("explicit ^^[...] must be the first child construction statement")
                if explicit is None and parent.required_arity > 0:
                    raise SemanticError(f"parent {stmt.parent} requires constructor arguments; use ^^ [...]")
            elif explicit_super_positions:
                raise SemanticError(f"class {stmt.name} has no parent but uses ^^[...]")

            self._stmts(stmt.body, class_scope)
        finally:
            self.class_depth -= 1
            self.current_class = saved_class
            self.current_static_method = saved_static
            self.in_constructor, self.in_destructor = saved_ctor, saved_dtor

    # ---------- expressions ----------

    def _expr(self, expr: ast.Expr, scope: Scope) -> None:
        self._expr_impl(expr, scope)
        self.expr_type_codes[id(expr)] = self._infer_expr_type(expr, scope)

    def _expr_impl(self, expr: ast.Expr, scope: Scope) -> None:
        if isinstance(expr, ast.Literal):
            if expr.kind == "int" and not (0 <= int(expr.value) <= 0xFFFFFFFFFFFFFFFF):
                raise SemanticError("integer literal exceeds SLUG's 64-bit adaptive integer carrier")
            return
        if isinstance(expr, ast.FormattedString):
            # Interpolations are ordinary value expressions evaluated in source order.
            # Native lowering applies explicit @s conversion to each result.
            for part in expr.parts:
                if not isinstance(part, str):
                    self._expr(part, scope)
            return
        if isinstance(expr, (ast.Var, ast.ExtendedName, ast.ModuleVar)):
            # Undefined variables are still diagnosed by codegen in this bootstrap; the
            # parser intentionally permits them while exploring candidates. ModuleVar
            # validity is established by the linker using the provider symbol table.
            return
        if isinstance(expr, ast.DefaultArg):
            return
        if isinstance(expr, ast.AssignExpr):
            self._expr(expr.value, scope)
            inferred = self._infer_expr_type(expr.value, scope)
            declared = expr.target_types if expr.target_types else (None,) * len(expr.targets)
            if len(declared) != len(expr.targets):
                raise SemanticError("internal target/type contract arity mismatch")
            effective: list[str | None] = []
            for name, requested in zip(expr.targets, declared):
                existing_here = scope.bindings.get(name)
                if existing_here and existing_here.immutable:
                    raise SemanticError(f"cannot assign to immutable binding {name!r}")
                immutable = expr.op == "::="
                if existing_here is None:
                    scope.bindings[name] = Binding(name, immutable, requested or inferred, requested)
                    effective.append(requested)
                elif immutable:
                    raise SemanticError(f"binding {name!r} already exists in this scope")
                else:
                    if requested is not None and existing_here.contract not in {None, requested}:
                        raise SemanticError(
                            f"binding {name!r} already has contract @{existing_here.contract}; cannot redeclare as @{requested}"
                        )
                    if requested is not None and existing_here.contract is None:
                        existing_here.contract = requested
                    contract = existing_here.contract
                    existing_here.inferred = contract or inferred
                    effective.append(contract)
            for name, contract in zip(expr.targets, effective):
                if contract is not None:
                    self._check_contract_expr(contract, expr.value, scope, f"binding {name}")
            self.assignment_contracts[id(expr)] = tuple(effective)
            return
        if isinstance(expr, ast.SetMemberExpr):
            self._member_access(expr.target, scope, writing=True, defining=True, immutable=expr.immutable)
            self._expr(expr.value, scope)
            return
        if isinstance(expr, ast.LambdaExpr):
            fn_scope = Scope(scope)
            saw_default = False
            for p in expr.params:
                if p.default is not None:
                    saw_default = True
                    self._expr(p.default, fn_scope)
                    if p.type_code:
                        self._check_contract_expr(p.type_code, p.default, fn_scope, f"default for lambda parameter {p.name}")
                elif saw_default:
                    raise SemanticError("required lambda parameter cannot follow a defaulted parameter")
                fn_scope.bindings[p.name] = Binding(p.name, False, p.type_code, p.type_code)
            if expr.variadic:
                if expr.variadic in fn_scope.bindings:
                    raise SemanticError(f"variadic binding {expr.variadic!r} duplicates a fixed lambda parameter")
                fn_scope.bindings[expr.variadic] = Binding(expr.variadic, False, "list", None)
            saved_loop = self.loop_depth
            saved_depth = self.function_depth
            saved_returns = self.current_return_types
            self.loop_depth = 0
            self.function_depth += 1
            self.current_return_types = expr.return_types
            try:
                self._stmts(expr.body, fn_scope)
            finally:
                self.loop_depth = saved_loop
                self.function_depth = saved_depth
                self.current_return_types = saved_returns
            return
        if isinstance(expr, ast.Call):
            fn = self.functions.get(expr.name)
            if fn is not None:
                self._check_call_args(fn.params, fn.variadic, expr.args, expr.name)
                for i, a in enumerate(expr.args):
                    if not isinstance(a, ast.DefaultArg):
                        self._expr(a, scope)
                        if i < len(fn.params) and fn.params[i].type_code:
                            self._check_contract_expr(fn.params[i].type_code, a, scope, f"argument {i+1} of {expr.name}")
                return
            for a in expr.args:
                if isinstance(a, ast.DefaultArg):
                    raise SemanticError(f"xx is not valid for builtin callable {expr.name}")
                self._expr(a, scope)
            return
        if isinstance(expr, ast.ClassCall):
            ci = self.classes.get(expr.name)
            if ci is None:
                raise SemanticError(f"unknown class {expr.name}")
            self._check_call_args(ci.decl.params, None, expr.args, expr.name)
            for i, a in enumerate(expr.args):
                if not isinstance(a, ast.DefaultArg):
                    self._expr(a, scope)
                    if i < len(ci.decl.params) and ci.decl.params[i].type_code:
                        self._check_contract_expr(ci.decl.params[i].type_code, a, scope, f"argument {i+1} of {expr.name}")
            return
        if isinstance(expr, ast.MethodCall):
            self._method_call(expr, scope)
            return
        if isinstance(expr, ast.MemberExpr):
            self._member_access(expr, scope, writing=False)
            return
        if isinstance(expr, ast.CallableInvoke):
            self._expr(expr.callee, scope)
            for a in expr.args:
                self._expr(a, scope)
            return
        if isinstance(expr, ast.Cast):
            self._expr(expr.value, scope); return
        if isinstance(expr, ast.DynamicCast):
            self._expr(expr.type_expr, scope); self._expr(expr.value, scope); return
        if isinstance(expr, ast.Unary):
            self._expr(expr.value, scope); return
        if isinstance(expr, ast.Binary):
            self._expr(expr.left, scope); self._expr(expr.right, scope); return
        if isinstance(expr, ast.BoolExpr):
            self._expr(expr.value, scope); return
        if isinstance(expr, ast.Compare):
            self._expr(expr.left, scope); self._expr(expr.right, scope); return
        if isinstance(expr, ast.LogicNot):
            self._expr(expr.value, scope); return
        if isinstance(expr, ast.LogicBinary):
            self._expr(expr.left, scope); self._expr(expr.right, scope); return
        if isinstance(expr, ast.ListLiteral):
            for i in expr.items: self._expr(i, scope)
            return
        if isinstance(expr, ast.MapLiteral):
            for k, v in expr.entries: self._expr(k, scope); self._expr(v, scope)
            return
        if isinstance(expr, ast.IndexExpr):
            self._expr(expr.base, scope); self._expr(expr.index, scope); return
        if isinstance(expr, ast.SliceExpr):
            self._expr(expr.base, scope)
            for part in (expr.start, expr.stop, expr.step):
                if part is not None: self._expr(part, scope)
            return
        if isinstance(expr, ast.SetIndexExpr):
            self._expr(expr.target.base, scope); self._expr(expr.target.index, scope); self._expr(expr.value, scope)
            return

    def _check_call_args(self, params: tuple[ast.Param, ...], variadic: str | None, args: tuple[ast.Expr, ...], label: str) -> None:
        required = sum(1 for p in params if p.default is None)
        if len(args) < required:
            raise SemanticError(f"missing required argument for {label}")
        if variadic is None and len(args) > len(params):
            raise SemanticError(f"too many arguments for {label}")
        for i, a in enumerate(args[:len(params)]):
            if isinstance(a, ast.DefaultArg) and params[i].default is None:
                raise SemanticError(f"xx used for non-defaulted argument {i+1} of {label}")
        if variadic is not None:
            for a in args[len(params):]:
                if isinstance(a, ast.DefaultArg):
                    raise SemanticError("xx is invalid in variadic tail")

    def _method_call(self, expr: ast.MethodCall, scope: Scope) -> None:
        owner: str | None = None
        fn: ast.FunctionDecl | None = None
        if expr.super_call:
            if self.current_class is None or self.current_static_method:
                raise SemanticError("^^.method is only valid in an instance class context")
            parent = self.classes[self.current_class].decl.parent
            if parent is None:
                raise SemanticError(f"class {self.current_class} has no parent method")
            found = self._lookup_method(parent, expr.name, False)
            if found is None:
                raise SemanticError(f"parent method {expr.name} does not exist")
            owner, fn = found
        elif expr.class_name is not None:
            if expr.class_name not in self.classes:
                raise SemanticError(f"unknown class {expr.class_name}")
            found = self._lookup_method(expr.class_name, expr.name, True)
            if found is None:
                raise SemanticError(f"unknown static method {expr.class_name}.{expr.name}")
            owner, fn = found
        elif expr.receiver is not None:
            self._expr(expr.receiver, scope)
            typ = self._infer_expr_type(expr.receiver, scope)
            if typ and typ.startswith("class:"):
                found = self._lookup_method(typ[6:], expr.name, False)
                if found is None:
                    raise SemanticError(f"unknown instance method {typ[6:]}.{expr.name}")
                owner, fn = found
            else:
                # Dynamic receiver: require at least one implementation to keep spelling
                # errors compile-time visible, then runtime dispatch verifies class.
                for cn in self.classes:
                    found = self._lookup_method(cn, expr.name, False)
                    if found is not None:
                        owner, fn = found
                        break
                if fn is None:
                    raise SemanticError(f"unknown instance method {expr.name}")
        else:
            if self.current_class is None:
                raise SemanticError("current method call used outside class")
            if expr.static:
                found = self._lookup_method(self.current_class, expr.name, True)
            else:
                if self.current_static_method:
                    raise SemanticError("instance method call is invalid inside static method")
                found = self._lookup_method(self.current_class, expr.name, False)
            if found is None:
                raise SemanticError(f"unknown method {self.current_class}.{expr.name}")
            owner, fn = found
        assert owner is not None and fn is not None
        self._check_private(owner, fn.private, f"method {expr.name}")
        self._check_call_args(fn.params, fn.variadic, expr.args, f"{owner}.{expr.name}")
        for i, a in enumerate(expr.args):
            if not isinstance(a, ast.DefaultArg):
                self._expr(a, scope)
                if i < len(fn.params) and fn.params[i].type_code:
                    self._check_contract_expr(fn.params[i].type_code, a, scope, f"argument {i+1} of {owner}.{expr.name}")

    def _member_access(
        self,
        expr: ast.Expr,
        scope: Scope,
        *,
        writing: bool,
        defining: bool = False,
        immutable: bool = False,
    ) -> None:
        if not isinstance(expr, ast.MemberExpr):
            self._expr(expr, scope)
            return
        owner_class: str | None = None
        field: FieldInfo | None = None
        if expr.class_name is not None:
            if expr.class_name not in self.classes:
                raise SemanticError(f"unknown class {expr.class_name}")
            owner_class = expr.class_name
            field = self._lookup_field(owner_class, expr.name, True)
        elif expr.base is not None:
            self._expr(expr.base, scope)
            typ = self._infer_expr_type(expr.base, scope)
            if typ and typ.startswith("class:"):
                owner_class = typ[6:]
                field = self._lookup_field(owner_class, expr.name, False)
        else:
            if self.current_class is None:
                raise SemanticError(".field/..field used outside class")
            owner_class = self.current_class
            if not expr.static and self.current_static_method:
                raise SemanticError("instance field access is invalid inside static method")
            field = self._lookup_field(owner_class, expr.name, expr.static)

        # During collection-backed constructor analysis a declaration is already present
        # in metadata. Outside that exact context, writing an undeclared field is an error.
        if field is None:
            if defining and self.in_constructor and expr.base is None and expr.class_name is None:
                field = self.classes[self.current_class].fields.get((expr.static, expr.name)) if self.current_class else None
            if field is None and owner_class is not None:
                raise SemanticError(f"unknown {'static ' if expr.static else ''}field {owner_class}.{expr.name}")
            if field is None and expr.base is not None:
                # Truly dynamic object type: runtime will validate field existence.
                return
        if field is not None:
            self._check_private(field.owner, field.private, f"field {expr.name}")
            if writing and field.immutable:
                declaration_write = defining and self.in_constructor and expr.base is None and expr.class_name is None and field.owner == self.current_class
                if not declaration_write:
                    raise SemanticError(f"cannot assign to immutable field {field.owner}.{expr.name}")

    @staticmethod
    def _contract_base(code: str) -> str:
        return code[0] if code and code[0] in "iufsb" else code

    def _const_numeric(self, expr: ast.Expr) -> int | float | None:
        if isinstance(expr, ast.Literal):
            if expr.kind in {"int", "float"}: return expr.value
            return None
        if isinstance(expr, ast.Unary) and expr.op == "-":
            v=self._const_numeric(expr.value);return -v if v is not None else None
        if isinstance(expr, ast.Cast) and expr.type_code[0] in "iuf":
            v=self._const_numeric(expr.value)
            if v is None:return None
            if expr.type_code[0] in "iu":return int(v)
            return float(v)
        if isinstance(expr, ast.Binary):
            a=self._const_numeric(expr.left);b=self._const_numeric(expr.right)
            if a is None or b is None:return None
            try:
                if expr.op=="+":return a+b
                if expr.op=="-":return a-b
                if expr.op=="*":return a*b
                if expr.op=="/":return a/b if b!=0 else None
                if expr.op=="//":
                    if b==0 or not isinstance(a,int) or not isinstance(b,int): return None
                    q=abs(a)//abs(b)
                    return -q if (a<0)!=(b<0) else q
                if expr.op=="%":
                    if b==0 or not isinstance(a,int) or not isinstance(b,int): return None
                    q=abs(a)//abs(b)
                    if (a<0)!=(b<0): q=-q
                    return a-q*b
                if expr.op=="^":
                    if isinstance(b,int) and abs(b)>1024:return None
                    return a**b
            except (OverflowError,ZeroDivisionError,ValueError):return None
        return None

    def _check_contract_expr(self, contract: str, expr: ast.Expr, scope: Scope, label: str) -> None:
        """Validate an annotated binding/parameter/return contract.

        Contracts are assertions, never conversions.  A source carrier must already
        match the contract carrier; callers that want conversion must write an
        explicit cast first.  Width-qualified integer contracts additionally reject
        statically-known out-of-range constants.
        """
        base=self._contract_base(contract)
        inferred=self._infer_expr_type(expr,scope)
        ibase=self._contract_base(inferred) if inferred else None
        if ibase is not None and ibase != base:
            raise SemanticError(f"{label} @{contract} requires an @{base} value, but expression is statically {inferred}; use an explicit cast to convert")
        if base not in {"i","u"}:
            return
        v=self._const_numeric(expr)
        if v is None:
            return
        # A matching integer carrier cannot be a float at this point.  Keep this
        # defensive guard so future inference changes cannot accidentally turn a
        # contract back into a truncating cast.
        if isinstance(v,float):
            return
        n=int(v)
        width_text=contract[1:]
        width=int(width_text) if width_text.isdigit() else 64
        if base=="i":
            lo=-(1<<(width-1));hi=(1<<(width-1))-1
            if n<lo or n>hi:raise SemanticError(f"{label} @{contract} constant is out of range")
        else:
            hi=(1<<width)-1
            if n<0 or n>hi:raise SemanticError(f"{label} @{contract} constant is out of range")

    def _infer_expr_type(self, expr: ast.Expr, scope: Scope) -> str | None:
        """Return the strongest cheap static fact known by the bootstrap.

        This is intentionally a sound HIR fact, not a promise that every value has a
        monomorphic native representation yet. Unknown/dynamic expressions return None.
        """
        if isinstance(expr, ast.Literal):
            if expr.kind == "int":
                # Source integers use the adaptive 64-bit carrier: ordinary signed
                # values are `i`; values above INT64_MAX (through UINT64_MAX) are `u`.
                return "u" if int(expr.value) > 0x7FFFFFFFFFFFFFFF else "i"
            return {"float": "f", "string": "s", "null": "null"}.get(expr.kind)
        if isinstance(expr, ast.FormattedString):
            return "s"
        if isinstance(expr, ast.ClassCall):
            return "class:" + expr.name
        if isinstance(expr, ast.LambdaExpr):
            return "callable"
        if isinstance(expr, (ast.Var, ast.ExtendedName)):
            b = scope.nearest(expr.name)
            return (b.contract or b.inferred) if b else None
        if isinstance(expr, ast.AssignExpr):
            declared = expr.target_types if expr.target_types else ()
            if len(declared) == 1 and declared[0] is not None:
                return declared[0]
            return self._infer_expr_type(expr.value, scope)
        if isinstance(expr, ast.Cast):
            return expr.type_code
        if isinstance(expr, ast.DynamicCast):
            return None
        if isinstance(expr, (ast.BoolExpr, ast.Compare, ast.LogicNot, ast.LogicBinary)):
            return "b"
        if isinstance(expr, ast.Unary):
            inner = self._infer_expr_type(expr.value, scope)
            base = self._contract_base(inner) if inner else None
            # Width contracts constrain bindings/casts, not the result width of an
            # arithmetic operator. Unary minus of an unsigned value is dynamically
            # signed when representable and otherwise traps, so `i` is the strongest
            # useful result fact here.
            if expr.op == "-" and base in {"i", "u", "b"}:
                return "i"
            return inner
        if isinstance(expr, ast.Binary):
            a = self._infer_expr_type(expr.left, scope)
            b = self._infer_expr_type(expr.right, scope)
            if expr.op == "+" and (a == "s" or b == "s"):
                return "s"
            if expr.op == "/":
                return "f"
            numeric = {"i", "u", "f", "b"}
            abase = a[0] if a and a[0] in "iuf" else a
            bbase = b[0] if b and b[0] in "iuf" else b
            if abase in numeric and bbase in numeric:
                if "f" in {abase, bbase}: return "f"
                if abase == "u" and bbase == "u": return "u"
                if "u" in {abase, bbase} and "i" in {abase, bbase}:
                    # Mixed signed/unsigned integer arithmetic may produce either
                    # runtime carrier depending on signs/magnitude. Keep it dynamic
                    # rather than publishing an unsound signed fact to the optimizer.
                    return "integer"
                return "i"
            return None
        if isinstance(expr, ast.ListLiteral): return "list"
        if isinstance(expr, ast.MapLiteral): return "map"
        if isinstance(expr, ast.SliceExpr):
            base = self._infer_expr_type(expr.base, scope)
            return "s" if base == "s" else ("list" if base == "list" else None)
        if isinstance(expr, ast.IndexExpr):
            base = self._infer_expr_type(expr.base, scope)
            return "s" if base == "s" else None
        if isinstance(expr, ast.SetIndexExpr):
            return self._infer_expr_type(expr.value, scope)
        if isinstance(expr, ast.SetMemberExpr):
            return self._infer_expr_type(expr.value, scope)
        if isinstance(expr, ast.Call):
            fn = self.functions.get(expr.name)
            if fn is not None:
                if fn.return_types is not None and len(fn.return_types) == 1:
                    return fn.return_types[0]
                return None
            spec = builtin(expr.name)
            if spec is not None:
                return spec.return_kind
            return None
        if isinstance(expr, ast.MethodCall):
            owner: str | None = None
            if expr.class_name is not None:
                owner = expr.class_name
            elif expr.receiver is not None:
                typ = self._infer_expr_type(expr.receiver, scope)
                if typ and typ.startswith("class:"): owner = typ[6:]
            elif self.current_class is not None:
                owner = self.current_class
            if owner is not None:
                found = self._lookup_method(owner, expr.name, expr.static if expr.class_name is not None else False)
                if found is not None:
                    fn = found[1]
                    if fn.return_types is not None and len(fn.return_types) == 1:
                        return fn.return_types[0]
            return None
        if isinstance(expr, ast.MemberExpr):
            return None
        if isinstance(expr, ast.CallableInvoke):
            return None
        return None



@dataclass(slots=True)
class AnalysisResult:
    program: ast.Program
    assignment_contracts: dict[int, tuple[str | None, ...]]
    expr_type_codes: dict[int, str | None]


def analyze_details(program: ast.Program) -> AnalysisResult:
    program = materialize_traits(program)
    analyzer = Analyzer()
    checked = analyzer.analyze(program)
    return AnalysisResult(checked, dict(analyzer.assignment_contracts), dict(analyzer.expr_type_codes))


def analyze(program: ast.Program) -> ast.Program:
    return analyze_details(program).program

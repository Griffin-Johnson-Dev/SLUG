from __future__ import annotations

"""Conservative MIR optimizer used by the v0.1.5 bootstrap backend."""

from dataclasses import dataclass, field
import math

from .ir import TypeFact
from .builtins import caller_write_free_builtin_names, nonretaining_builtin_names
from .mir import MIRBlock, MIRFunction, MIRInstr, MIRModule, MIRPhi, MIRTerminator


@dataclass(frozen=True, slots=True)
class ConstValue:
    kind: str
    value: object


@dataclass(frozen=True, slots=True)
class OptimizationStats:
    constants_folded: int = 0
    branches_simplified: int = 0
    dead_instructions_removed: int = 0
    unreachable_blocks_removed: int = 0
    phis_simplified: int = 0
    cse_eliminated: int = 0
    calls_specialized: int = 0
    call_clobbers_elided: int = 0

    def add(self, other: "OptimizationStats") -> "OptimizationStats":
        return OptimizationStats(
            self.constants_folded + other.constants_folded,
            self.branches_simplified + other.branches_simplified,
            self.dead_instructions_removed + other.dead_instructions_removed,
            self.unreachable_blocks_removed + other.unreachable_blocks_removed,
            self.phis_simplified + other.phis_simplified,
            self.cse_eliminated + other.cse_eliminated,
            self.calls_specialized + other.calls_specialized,
            self.call_clobbers_elided + other.call_clobbers_elided,
        )


@dataclass(frozen=True, slots=True)
class OptimizerResult:
    module: MIRModule
    constants_by_source: dict[int, ConstValue]
    stats: OptimizationStats
    # Source expressions whose evaluation was proven pure and total for the exact
    # invocation, so the C backend may replace the entire subtree with its constant.
    elidable_sources: frozenset[int] = frozenset()
    # Allocation source id -> conservative escape class (local/escapes). This is
    # intentionally diagnostic groundwork for later object stack allocation; v0.1.5
    # only stack-promotes lexical cells whose lifetime proof is complete.
    escape_classes: dict[int, str] = field(default_factory=dict)


_PURE = {
    "const", "cast", "truthy", "logic.not",
    "unary.-",
    "binary.+", "binary.-", "binary.*", "binary./", "binary.%", "binary.^",
    "cmp.==", "cmp.!=" , "cmp.<", "cmp.>", "cmp.<=", "cmp.>=", "cmp.===", "cmp.!==",
}

# DCE has a stricter rule than constant folding. Arithmetic/casts/comparisons are
# foldable only when the optimizer proves a non-trapping result; their unfurled
# runtime forms may overflow, divide by zero, reject a cast, or reject comparison.
_DCE_SAFE = {"const"}


def _literal(instr: MIRInstr) -> ConstValue | None:
    if instr.op != "const" or not instr.args:
        return None
    raw = instr.args[0]
    try:
        if instr.detail == "int":
            return ConstValue("uint" if instr.type.kind == "u" else "int", int(raw))
        if instr.detail == "float":
            return ConstValue("float", float(raw))
        if instr.detail == "string":
            # HIR/MIR uses repr() for textual identity.
            import ast as pyast
            return ConstValue("string", pyast.literal_eval(raw))
        if instr.detail == "bool":
            return ConstValue("bool", raw == "True")
        if instr.detail == "null":
            return ConstValue("null", None)
    except Exception:
        return None
    return None


def _truthy(v: ConstValue) -> bool | None:
    if v.kind == "null": return False
    if v.kind == "bool": return bool(v.value)
    if v.kind in {"int", "uint", "float"}: return v.value != 0
    if v.kind == "string": return len(str(v.value)) != 0
    return None


def _safe_numeric_binary(op: str, a: ConstValue, b: ConstValue) -> ConstValue | None:
    if a.kind not in {"int", "uint", "float"} or b.kind not in {"int", "uint", "float"}:
        return None
    av, bv = a.value, b.value
    try:
        if op == "+": val = av + bv
        elif op == "-": val = av - bv
        elif op == "*": val = av * bv
        elif op == "/":
            if bv == 0: return None
            val = av / bv
            return ConstValue("float", float(val))
        elif op in {"//", "%"}:
            if bv == 0 or a.kind not in {"int", "uint"} or b.kind not in {"int", "uint"}: return None
            # SLUG integer quotient/remainder is truncation toward zero.  Keep the
            # computation entirely in integer space so UINT64/INT64 boundary values
            # never lose low bits through host floating point.
            aa, bb = int(av), int(bv)
            q = abs(aa) // abs(bb)
            if (aa < 0) != (bb < 0):
                q = -q
            if op == "//":
                val = q
            else:
                val = aa - q * bb
        elif op == "^":
            if b.kind not in {"int", "uint"}: return None
            exp = int(bv)
            if exp < 0:
                if av == 0 or abs(exp) > 1024: return None
                return ConstValue("float", float(av) ** exp)
            # Avoid constructing enormous host integers just to discover the runtime
            # would trap. Non-trivial integer bases overflow the 64-bit carrier long
            # before exponents above this bound.
            if exp > 64 and abs(int(av)) not in {0, 1}: return None
            val = av ** exp
        else: return None
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    if isinstance(val, float):
        if not math.isfinite(val): return None
        return ConstValue("float", val)
    iv = int(val)
    if op == "%":
        prefer_unsigned = (a.kind == "uint" or b.kind == "uint") and iv >= 0
    elif op == "^":
        prefer_unsigned = b.value != 0 and a.kind == "uint" and iv >= 0
    else:
        prefer_unsigned = (a.kind == "uint" or b.kind == "uint") and iv >= 0
    # Match the adaptive carrier's representation choice: unsigned operands preserve
    # unsigned representation for non-negative integer results; negative results are
    # necessarily signed. Never fold beyond the runtime's checked carrier.
    if prefer_unsigned and 0 <= iv <= (1 << 64) - 1:
        return ConstValue("uint", iv)
    if -(1 << 63) <= iv <= (1 << 63) - 1:
        return ConstValue("int", iv)
    return None


def _fold(instr: MIRInstr, consts: dict[str, ConstValue]) -> ConstValue | None:
    lit = _literal(instr)
    if lit is not None: return lit
    args = [consts.get(a) for a in instr.args]
    if instr.op == "bind" and args and args[0] is not None:
        # A typed binding is a runtime conversion/check boundary, not a copy.
        if instr.detail and "@" in instr.detail:
            return None
        return args[0]
    if instr.op == "truthy" and args and args[0] is not None:
        b = _truthy(args[0]); return None if b is None else ConstValue("bool", b)
    if instr.op == "logic.not" and args and args[0] is not None:
        b = _truthy(args[0]); return None if b is None else ConstValue("bool", not b)
    if instr.op == "unary.-" and args and args[0] is not None:
        a = args[0]
        if a.kind == "int" and a.value != -(1 << 63): return ConstValue("int", -int(a.value))
        if a.kind == "uint" and int(a.value) <= (1 << 63): return ConstValue("int", -int(a.value))
        if a.kind == "float": return ConstValue("float", -float(a.value))
        return None
    if instr.op.startswith("binary.") and len(args) == 2 and all(x is not None for x in args):
        return _safe_numeric_binary(instr.op[7:], args[0], args[1])  # type: ignore[arg-type]
    if instr.op.startswith("cmp.") and len(args) == 2 and all(x is not None for x in args):
        a, b = args  # type: ignore[misc]
        op = instr.op[4:]
        try:
            if op in {"===", "!=="}:
                # Heap identity cannot be reconstructed from value constants: two
                # equal string literals may be distinct allocations, while aliases may
                # share one. Fold identity only for non-heap scalar tags.
                scalar = {"int", "uint", "float", "bool", "null"}
                if a.kind not in scalar or b.kind not in scalar:
                    return None
                same = a.kind == b.kind and a.value == b.value
                return ConstValue("bool", same if op == "===" else not same)
            if op in {"==", "!="}:
                numeric = {"int", "uint", "float"}
                if a.kind in numeric and b.kind in numeric:
                    # Mixed float/integer equality in the bootstrap goes through
                    # double; leave it to runtime rather than introduce a subtly
                    # different host-Python precision rule for large integers.
                    if "float" in {a.kind, b.kind} and a.kind != b.kind:
                        return None
                    v = a.value == b.value
                elif a.kind == b.kind and a.kind in {"bool", "string", "null"}:
                    v = a.value == b.value
                else:
                    v = False
                return ConstValue("bool", bool(v if op == "==" else not v))
            integer = {"int", "uint"}
            if a.kind in integer and b.kind in integer:
                av, bv = int(a.value), int(b.value)
            elif a.kind == b.kind == "float":
                av, bv = float(a.value), float(b.value)
            elif a.kind == b.kind == "string":
                av, bv = str(a.value), str(b.value)
            else:
                # Runtime also permits Boolean/numeric ordering, but keeping that
                # dynamic is safer until MIR carries the exact comparison coercion.
                return None
            if op == "<": v = av < bv
            elif op == ">": v = av > bv
            elif op == "<=": v = av <= bv
            elif op == ">=": v = av >= bv
            else: return None
            return ConstValue("bool", bool(v))
        except TypeError:
            return None
    if instr.op == "cast" and args and args[0] is not None and instr.detail:
        a = args[0]; code = instr.detail
        try:
            numeric = {"int", "uint", "float", "bool"}
            if code.startswith("i") and a.kind in numeric:
                n = int(a.value); width = int(code[1:]) if code[1:].isdigit() else 64
                if -(1 << (width - 1)) <= n <= (1 << (width - 1)) - 1: return ConstValue("int", n)
            if code.startswith("u") and a.kind in numeric:
                # SLUG rejects every negative float before truncation; Python's
                # int(-0.5) would otherwise silently become 0 and miscompile it.
                if a.kind == "float" and float(a.value) < 0.0:
                    return None
                n = int(a.value); width = int(code[1:]) if code[1:].isdigit() else 64
                if 0 <= n <= (1 << width) - 1: return ConstValue("uint", n)
            if code.startswith("f") and a.kind in numeric:
                return ConstValue("float", float(a.value))
            if code == "b":
                b = _truthy(a); return None if b is None else ConstValue("bool", b)
            if code == "s" and a.kind in {"int", "uint", "bool", "string"}:
                return ConstValue("string", str(a.value).lower() if a.kind == "bool" else str(a.value))
            # Runtime float->string uses C %.17g formatting. Python's str(float) has
            # different canonical spelling for values such as 1.0, so leave that
            # conversion to the runtime until MIR has an exact formatting primitive.
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def _const_instr(instr: MIRInstr, value: ConstValue) -> MIRInstr:
    if value.kind == "bool":
        return MIRInstr(instr.result, "const", ("True" if value.value else "False",), TypeFact("b"), "bool", instr.source_id)
    if value.kind in {"int", "uint"}:
        if value.kind == "uint":
            kind = instr.type if instr.type.kind == "u" else TypeFact("u")
        else:
            kind = instr.type if instr.type.kind in {"i", "integer"} else TypeFact("i")
        return MIRInstr(instr.result, "const", (repr(int(value.value)),), kind, "int", instr.source_id)
    if value.kind == "float":
        return MIRInstr(instr.result, "const", (repr(float(value.value)),), TypeFact("f"), "float", instr.source_id)
    if value.kind == "string":
        return MIRInstr(instr.result, "const", (repr(str(value.value)),), TypeFact("s"), "string", instr.source_id)
    if value.kind == "null":
        return MIRInstr(instr.result, "const", ("None",), TypeFact("null"), "null", instr.source_id)
    return instr


def _successors(term: MIRTerminator) -> tuple[str, ...]:
    if term.op == "jump" and term.args: return (term.args[0],)
    if term.op == "branch" and len(term.args) >= 3: return (term.args[1], term.args[2])
    return ()


def _reachable(fn: MIRFunction) -> set[str]:
    if not fn.blocks: return set()
    by = {b.label: b for b in fn.blocks}; seen: set[str] = set(); todo = [fn.blocks[0].label]
    while todo:
        x = todo.pop()
        if x in seen or x not in by: continue
        seen.add(x); todo.extend(_successors(by[x].terminator))
    return seen


def _rewrite_arg(arg: str, copies: dict[str, str]) -> str:
    seen: set[str] = set()
    while arg in copies and arg not in seen:
        seen.add(arg); arg = copies[arg]
    return arg



def _apply_scalar_contract(value: ConstValue, typ: TypeFact) -> ConstValue | None:
    """Apply a SLUG scalar call/return contract to one constant value.

    This mirrors the native boundary casts closely enough for optimizer use.  Returning
    ``None`` means either the boundary would trap or the conversion has semantics we do
    not model exactly enough to erase the call.  In both cases specialization must stop.
    """
    if typ.kind in {"any", "integer"}:
        # ``any`` is no contract. ``integer`` is an analysis join rather than a source
        # cast code, so there is no runtime boundary conversion to perform.
        return value

    numeric = {"int", "uint", "float", "bool"}
    try:
        if typ.kind == "i":
            if value.kind not in numeric:
                return None
            if value.kind == "uint" and int(value.value) > (1 << 63) - 1:
                return None
            if value.kind == "float":
                x = float(value.value)
                if not math.isfinite(x) or x < -(1 << 63) or x >= (1 << 63):
                    return None
                n = math.trunc(x)
            else:
                n = int(value.value)
            width = typ.width or 64
            lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
            if n < lo or n > hi:
                return None
            return ConstValue("int", n)

        if typ.kind == "u":
            if value.kind not in numeric:
                return None
            if value.kind == "float":
                x = float(value.value)
                # Runtime checks sign/range before truncation.
                if not math.isfinite(x) or x < 0.0 or x >= float(1 << 64):
                    return None
                n = math.trunc(x)
            else:
                n = int(value.value)
            width = typ.width or 64
            hi = (1 << width) - 1
            if n < 0 or n > hi:
                return None
            return ConstValue("uint", n)

        if typ.kind == "f":
            if value.kind not in numeric:
                return None
            out = float(value.value)
            if not math.isfinite(out):
                return None
            return ConstValue("float", out)

        if typ.kind == "b":
            truth = _truthy(value)
            return None if truth is None else ConstValue("bool", truth)

        # String casts allocate and have formatting/identity details; heap/object-like
        # contracts likewise are outside the scalar evaluator.  Keep those calls live.
        return None
    except (OverflowError, ValueError, TypeError):
        return None


def _eval_function_constant(
    fn: MIRFunction,
    args: tuple[ConstValue, ...],
    fnmap: dict[str, MIRFunction],
    cache: dict[tuple[str, tuple[ConstValue, ...]], ConstValue | None],
    stack: set[str],
) -> ConstValue | None:
    """Interpret the pure scalar subset of MIR for one exact constant invocation.

    Returning None means either dynamic/unsupported or potentially effectful/trapping.
    That conservative failure mode is what makes call-site specialization safe.
    """
    key = (fn.name, args)
    if key in cache:
        return cache[key]
    if fn.name in stack or len(args) != len(fn.params):
        return None
    stack.add(fn.name)
    try:
        values: dict[str, ConstValue] = {}
        for (_name, slot, typ), arg in zip(fn.params, args):
            converted = _apply_scalar_contract(arg, typ)
            if converted is None:
                cache[key] = None
                return None
            values[slot] = converted
        by = {b.label: b for b in fn.blocks}
        if not fn.blocks:
            cache[key] = None
            return None
        label = fn.blocks[0].label
        pred: str | None = None
        steps = 0
        while label in by and steps < 2048:
            steps += 1
            block = by[label]
            for phi in block.phis:
                chosen = None
                for p, v in phi.incoming:
                    if p == pred:
                        chosen = v
                        break
                if chosen is None or chosen not in values:
                    cache[key] = None
                    return None
                values[phi.result] = values[chosen]

            for instr in block.instructions:
                if instr.result is None:
                    cache[key] = None
                    return None
                if instr.op == "call":
                    if not instr.args:
                        cache[key] = None
                        return None
                    target = fnmap.get(instr.args[0])
                    if target is None or any(a not in values for a in instr.args[1:]):
                        cache[key] = None
                        return None
                    nested = _eval_function_constant(
                        target,
                        tuple(values[a] for a in instr.args[1:]),
                        fnmap,
                        cache,
                        stack,
                    )
                    if nested is None:
                        cache[key] = None
                        return None
                    values[instr.result] = nested
                    continue
                if instr.op.startswith("clobber") or instr.op.startswith("barrier"):
                    cache[key] = None
                    return None
                local = _fold(instr, values)
                if local is None:
                    cache[key] = None
                    return None
                values[instr.result] = local

            term = block.terminator
            if term.op == "return":
                if len(term.args) != 1 or term.args[0] not in values:
                    cache[key] = None
                    return None
                result = values[term.args[0]]
                if fn.returns is not None:
                    if len(fn.returns) != 1:
                        cache[key] = None
                        return None
                    result = _apply_scalar_contract(result, fn.returns[0])
                    if result is None:
                        cache[key] = None
                        return None
                cache[key] = result
                return result
            if term.op == "jump" and len(term.args) == 1:
                pred, label = block.label, term.args[0]
                continue
            if term.op == "branch" and len(term.args) >= 3 and term.args[0] in values:
                truth = _truthy(values[term.args[0]])
                if truth is None:
                    cache[key] = None
                    return None
                pred, label = block.label, term.args[1] if truth else term.args[2]
                continue
            cache[key] = None
            return None
        cache[key] = None
        return None
    finally:
        stack.remove(fn.name)


def _call_constant(
    instr: MIRInstr,
    consts: dict[str, ConstValue],
    fnmap: dict[str, MIRFunction],
    cache: dict[tuple[str, tuple[ConstValue, ...]], ConstValue | None],
) -> ConstValue | None:
    if instr.op != "call" or not instr.args:
        return None
    target = fnmap.get(instr.args[0])
    if target is None:
        return None
    vals: list[ConstValue] = []
    for arg in instr.args[1:]:
        if arg.startswith("@default"):
            return None
        value = consts.get(arg)
        if value is None:
            return None
        vals.append(value)
    return _eval_function_constant(target, tuple(vals), fnmap, cache, set())


def _scalar_cse(blocks: list[MIRBlock]) -> tuple[list[MIRBlock], int]:
    """Block-local value numbering for identity-free scalar expressions."""
    copies: dict[str, str] = {}
    eliminated = 0
    out: list[MIRBlock] = []
    scalar_kinds = {"i", "u", "integer", "f", "b", "null"}
    eligible = _PURE | {"bind"}
    for block in blocks:
        table: dict[tuple[object, ...], str] = {}
        ins: list[MIRInstr] = []
        for raw in block.instructions:
            args = tuple(_rewrite_arg(a, copies) for a in raw.args)
            instr = MIRInstr(raw.result, raw.op, args, raw.type, raw.detail, raw.source_id)
            if (
                instr.result
                and instr.op in eligible
                and instr.type.kind in scalar_kinds
                and not (instr.op == "bind" and instr.detail and "@" in instr.detail)
                and not (instr.op == "const" and instr.detail == "string")
            ):
                key = (instr.op, instr.args, instr.type, instr.detail)
                prior = table.get(key)
                if prior is not None:
                    copies[instr.result] = prior
                    eliminated += 1
                    continue
                table[key] = instr.result
            ins.append(instr)
        phis = tuple(
            MIRPhi(p.result, p.binding, tuple((pred, _rewrite_arg(v, copies)) for pred, v in p.incoming), p.type)
            for p in block.phis
        )
        term = MIRTerminator(block.terminator.op, tuple(_rewrite_arg(a, copies) for a in block.terminator.args))
        out.append(MIRBlock(block.label, phis, tuple(ins), term))
    if copies:
        rewritten: list[MIRBlock] = []
        for block in out:
            phis = tuple(
                MIRPhi(p.result, p.binding, tuple((pred, _rewrite_arg(v, copies)) for pred, v in p.incoming), p.type)
                for p in block.phis
            )
            ins = tuple(
                MIRInstr(i.result, i.op, tuple(_rewrite_arg(a, copies) for a in i.args), i.type, i.detail, i.source_id)
                for i in block.instructions
            )
            term = MIRTerminator(block.terminator.op, tuple(_rewrite_arg(a, copies) for a in block.terminator.args))
            rewritten.append(MIRBlock(block.label, phis, ins, term))
        out = rewritten
    return out, eliminated

def _external_write_free_functions(fnmap: dict[str, MIRFunction]) -> frozenset[str]:
    """Return named functions proven not to mutate caller-visible SLUG state.

    This is intentionally weaker than "pure": a function may perform I/O, allocate,
    read globals, or trap and still be write-free.  The only optimization licensed by
    this summary is preserving caller binding facts across a normal return.  Heap
    mutation through parameters, unknown dispatch, closures, constructors and opaque
    try regions remain conservatively effectful.
    """
    candidates = set(fnmap)
    readonly_builtins = caller_write_free_builtin_names()

    def local_write_free(fn: MIRFunction, assumed: set[str]) -> bool:
        locals_: set[str] = {name for name, _slot, _typ in fn.params}
        for block in fn.blocks:
            for instr in block.instructions:
                op = instr.op
                if op == "bind":
                    detail = (instr.detail or "").split()
                    if not detail:
                        return False
                    name = detail[0]
                    # := / ::= definitions introduce a function-local cell.  Any
                    # other first write to a nonlocal name is an external mutation.
                    if "mutable" in detail or "immutable" in detail:
                        locals_.add(name)
                    elif name not in locals_:
                        return False
                    continue
                if op.startswith("mutate."):
                    name = instr.detail or ""
                    if name not in locals_:
                        return False
                    continue
                if op == "call":
                    target = instr.args[0] if instr.args else ""
                    if target in readonly_builtins:
                        continue
                    # sl mutates its list argument.  User calls are safe only after
                    # fixed-point proof of the callee.
                    if target not in assumed:
                        return False
                    continue
                if op in {"setindex", "setmember", "method", "invoke", "new",
                          "super.init", "dynamic", "barrier.try", "barrier.stmt"}:
                    return False
                # clobber is an analysis artifact emitted after a call.  The call
                # itself, above, determines whether the effect is real.
        return True

    # Greatest fixed point: recursion/mutual recursion can be write-free as long as
    # every concrete operation in the strongly connected component is write-free.
    while True:
        nxt = {name for name in candidates if local_write_free(fnmap[name], candidates)}
        if nxt == candidates:
            return frozenset(nxt)
        candidates = nxt


def _optimize_function(
    fn: MIRFunction,
    fnmap: dict[str, MIRFunction],
    eval_cache: dict[tuple[str, tuple[ConstValue, ...]], ConstValue | None],
    write_free: frozenset[str],
) -> tuple[MIRFunction, dict[int, ConstValue], OptimizationStats, set[int]]:
    stats = OptimizationStats(); consts: dict[str, ConstValue] = {
        "@bool:false": ConstValue("bool", False),
        "@bool:true": ConstValue("bool", True),
        "@null": ConstValue("null", None),
    }
    specialized_results: set[str] = set()
    # SSA makes constant discovery monotonic; iterate to resolve phis, forward defs,
    # and pure scalar calls. A successfully specialized call also proves its immediately
    # following call-clobber versions are copies of the old values.
    for _ in range(max(2, sum(len(b.instructions) + len(b.phis) for b in fn.blocks) + 1)):
        changed = False
        for b in fn.blocks:
            for p in b.phis:
                vals = [consts.get(v) for _, v in p.incoming]
                if vals and all(v is not None for v in vals) and all(v == vals[0] for v in vals[1:]) and p.result not in consts:
                    consts[p.result] = vals[0]  # type: ignore[assignment]
                    changed = True
            active_write_free_call: str | None = None
            for i in b.instructions:
                if not i.result:
                    active_write_free_call = None
                    continue
                if i.op == "call":
                    target_name = i.args[0] if i.args else ""
                    v = _call_constant(i, consts, fnmap, eval_cache)
                    if v is not None:
                        specialized_results.add(i.result)
                    active_write_free_call = target_name if target_name in write_free else None
                elif i.op == "clobber" and active_write_free_call is not None and i.detail == f"call {active_write_free_call}":
                    v = consts.get(i.args[1]) if len(i.args) > 1 else None
                else:
                    active_write_free_call = None
                    v = _fold(i, consts)
                if v is not None and consts.get(i.result) != v:
                    consts[i.result] = v
                    changed = True
        if not changed:
            break

    source_consts: dict[int, ConstValue] = {}
    elidable_sources: set[int] = set()
    folded = 0; branch_count = 0; specialized_count = 0; clobbers_elided = 0
    effect_copies: dict[str, str] = {}
    blocks: list[MIRBlock] = []
    for b in fn.blocks:
        ins: list[MIRInstr] = []
        active_write_free_call: str | None = None
        for i in b.instructions:
            v = consts.get(i.result or "")
            is_specialized = bool(i.result and i.result in specialized_results and i.op == "call" and v is not None)
            if i.source_id is not None and v is not None and (i.op in _PURE or is_specialized):
                source_consts[i.source_id] = v
                if is_specialized:
                    # Knowing a user call's scalar return value does NOT prove that
                    # evaluating the call is observationally removable. The callee may
                    # mutate caller-visible/captured state, perform I/O, allocate, trap,
                    # or otherwise have effects even when its return is constant. Keep
                    # the source call on the native path until we have a separate,
                    # explicit proof of full effect-freedom (stronger than write-free).
                    pass
            if is_specialized:
                ins.append(_const_instr(i, v))  # type: ignore[arg-type]
                folded += 1
                specialized_count += 1
                target_name = i.args[0] if i.args else ""
                active_write_free_call = target_name if target_name in write_free else None
                continue
            if i.op == "call":
                target_name = i.args[0] if i.args else ""
                active_write_free_call = target_name if target_name in write_free else None
            if i.op == "clobber" and active_write_free_call is not None and i.detail == f"call {active_write_free_call}":
                if i.result and len(i.args) > 1:
                    effect_copies[i.result] = i.args[1]
                clobbers_elided += 1
                continue
            if i.op != "call":
                active_write_free_call = None
            if i.result and v is not None and i.op in _PURE and i.op != "const":
                ins.append(_const_instr(i, v)); folded += 1
            else:
                ins.append(i)
        term = b.terminator
        if term.op == "branch" and term.args:
            cv = consts.get(term.args[0])
            truth = _truthy(cv) if cv is not None else None
            if truth is not None:
                term = MIRTerminator("jump", (term.args[1] if truth else term.args[2],)); branch_count += 1
        blocks.append(MIRBlock(b.label, b.phis, tuple(ins), term))
    if effect_copies:
        rewritten: list[MIRBlock] = []
        for block in blocks:
            phis = tuple(MIRPhi(p.result, p.binding, tuple((pred, _rewrite_arg(v, effect_copies)) for pred, v in p.incoming), p.type) for p in block.phis)
            ins = tuple(MIRInstr(i.result, i.op, tuple(_rewrite_arg(a, effect_copies) for a in i.args), i.type, i.detail, i.source_id) for i in block.instructions)
            term = MIRTerminator(block.terminator.op, tuple(_rewrite_arg(a, effect_copies) for a in block.terminator.args))
            rewritten.append(MIRBlock(block.label, phis, ins, term))
        blocks = rewritten
    stats = stats.add(OptimizationStats(constants_folded=folded, branches_simplified=branch_count, calls_specialized=specialized_count, call_clobbers_elided=clobbers_elided))
    fn = MIRFunction(fn.name, fn.params, fn.returns, tuple(blocks))

    # Remove unreachable blocks after branch folding.
    reachable = _reachable(fn); removed_blocks = len(fn.blocks) - len(reachable)
    blocks = [b for b in fn.blocks if b.label in reachable]
    preds: dict[str, set[str]] = {b.label: set() for b in blocks}
    for b in blocks:
        for dst in _successors(b.terminator):
            if dst in preds: preds[dst].add(b.label)

    # Simplify phis whose dead predecessors disappeared or whose live inputs agree.
    copies: dict[str, str] = {}; phi_simplified = 0; tmp_blocks: list[MIRBlock] = []
    for b in blocks:
        phis: list[MIRPhi] = []
        for p in b.phis:
            incoming = tuple((pred, value) for pred, value in p.incoming if pred in preds.get(b.label, set()))
            vals = [v for _, v in incoming]
            if vals and all(v == vals[0] for v in vals[1:]):
                copies[p.result] = vals[0]; phi_simplified += 1
            else:
                phis.append(MIRPhi(p.result, p.binding, incoming, p.type))
        tmp_blocks.append(MIRBlock(b.label, tuple(phis), b.instructions, b.terminator))

    if copies:
        blocks = []
        for b in tmp_blocks:
            phis = tuple(MIRPhi(p.result, p.binding, tuple((pred, _rewrite_arg(v, copies)) for pred, v in p.incoming), p.type) for p in b.phis)
            ins = tuple(MIRInstr(i.result, i.op, tuple(_rewrite_arg(a, copies) for a in i.args), i.type, i.detail, i.source_id) for i in b.instructions)
            term = MIRTerminator(b.terminator.op, tuple(_rewrite_arg(a, copies) for a in b.terminator.args))
            blocks.append(MIRBlock(b.label, phis, ins, term))
    else:
        blocks = tmp_blocks

    blocks, cse_count = _scalar_cse(blocks)
    stats = stats.add(OptimizationStats(cse_eliminated=cse_count))

    # SSA dead-value elimination, deliberately restricted to operations that cannot
    # allocate, mutate, call, trap after successful folding, or observe runtime state.
    used: set[str] = set()
    for b in blocks:
        for p in b.phis:
            used.update(v for _, v in p.incoming if v.startswith("%"))
        for i in b.instructions:
            used.update(a for a in i.args if a.startswith("%"))
        used.update(a for a in b.terminator.args if a.startswith("%"))
    dead = 0; out_blocks: list[MIRBlock] = []
    for b in reversed(blocks):
        kept: list[MIRInstr] = []
        for i in reversed(b.instructions):
            if i.result and i.result not in used and i.op in _DCE_SAFE:
                dead += 1; continue
            if i.result and i.result in used:
                used.update(a for a in i.args if a.startswith("%"))
            kept.append(i)
        kept.reverse(); out_blocks.append(MIRBlock(b.label, b.phis, tuple(kept), b.terminator))
    out_blocks.reverse()
    stats = stats.add(OptimizationStats(dead_instructions_removed=dead, unreachable_blocks_removed=removed_blocks, phis_simplified=phi_simplified))
    return MIRFunction(fn.name, fn.params, fn.returns, tuple(out_blocks)), source_consts, stats, elidable_sources



def _escape_analysis(module: MIRModule) -> dict[int, str]:
    out: dict[int, str] = {}
    safe_calls = nonretaining_builtin_names()
    for fn in (module.top,) + module.functions:
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            if not (a.startswith("%") and b.startswith("%")):
                return
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        allocs: dict[str, int] = {}
        for block in fn.blocks:
            for phi in block.phis:
                for _pred, value in phi.incoming:
                    union(phi.result, value)
            for instr in block.instructions:
                if instr.result and instr.op == "bind" and instr.args:
                    union(instr.result, instr.args[0])
                if instr.result and instr.op in {"list", "map", "new", "lambda"} and instr.source_id is not None:
                    allocs[instr.result] = instr.source_id

        escaped_roots: set[str] = set()

        def mark(value: str) -> None:
            if value.startswith("%"):
                escaped_roots.add(find(value))

        for block in fn.blocks:
            if block.terminator.op == "return":
                for value in block.terminator.args:
                    mark(value)
            for instr in block.instructions:
                if instr.op == "call":
                    target = instr.args[0] if instr.args else ""
                    if target not in safe_calls:
                        for value in instr.args[1:]:
                            mark(value)
                elif instr.op in {"invoke", "method", "new", "setmember", "setindex"}:
                    # Unknown callees and heap stores may retain arguments beyond the
                    # originating expression. Conservatively mark all SSA operands.
                    for value in instr.args:
                        mark(value)
        for value, source_id in allocs.items():
            out[source_id] = "escapes" if find(value) in escaped_roots else "local"
    return out

def optimize_mir(module: MIRModule) -> OptimizerResult:
    fnmap = {fn.name: fn for fn in module.functions}
    write_free = _external_write_free_functions(fnmap)
    eval_cache: dict[tuple[str, tuple[ConstValue, ...]], ConstValue | None] = {}
    top, constants, stats, elidable = _optimize_function(module.top, fnmap, eval_cache, write_free)
    funcs: list[MIRFunction] = []
    for fn in module.functions:
        opt, cs, st, es = _optimize_function(fn, fnmap, eval_cache, write_free)
        funcs.append(opt)
        constants.update(cs)
        elidable.update(es)
        stats = stats.add(st)
    optimized = MIRModule(top, tuple(funcs))
    return OptimizerResult(optimized, constants, stats, frozenset(elidable), _escape_analysis(optimized))

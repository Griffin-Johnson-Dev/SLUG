from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuiltinSpec:
    """One authoritative description of a native SLUG capability.

    The parser uses arity, semantic/HIR analysis uses ``return_kind``, MIR uses the
    effect flags, and the C backend uses ``c_name``.  Keeping those facts together is
    deliberate: a builtin must not be "pure" to one compiler layer and effectful to
    another.
    """

    name: str
    min_arity: int
    max_arity: int | None
    return_kind: str | None
    c_name: str
    pure: bool = False
    deterministic: bool = False
    allocates: bool = False
    mutates_args: bool = False
    external_io: bool = False
    may_trap: bool = True
    retains_args: bool = False
    dense_infer: bool = False

    @property
    def variadic(self) -> bool:
        return self.max_arity is None

    @property
    def caller_write_free(self) -> bool:
        # External I/O is observable but does not mutate a caller lexical binding.
        return not self.mutates_args and not self.retains_args


# v0.1.6 grows this table into the native capability layer.  Keep the legacy core
# here first so every compiler layer can stop carrying its own hard-coded name set.
_SPECS = (
    BuiltinSpec("co", 1, 1, "null", "sv_builtin_co", external_io=True, dense_infer=True),
    # Input is deliberately text-only in audited v1. Explicit casts perform parsing.
    BuiltinSpec("ci", 0, 1, "s", "sv_builtin_ci", allocates=True, external_io=True, dense_infer=True),
    BuiltinSpec("ty", 1, 1, "s", "sv_builtin_ty", pure=True, deterministic=True, allocates=True, may_trap=False, dense_infer=False),
    BuiltinSpec("cv", 2, 2, "b", "sv_builtin_cv", pure=True, deterministic=True, may_trap=False, dense_infer=False),
    BuiltinSpec("in", 2, 2, "b", "sv_builtin_in", pure=True, deterministic=True, dense_infer=True),
    BuiltinSpec("iv", 2, 2, "b", "sv_builtin_iv", pure=True, deterministic=True, dense_infer=True),
    BuiltinSpec("ln", 1, 1, None, "sv_builtin_ln", pure=True, deterministic=True, dense_infer=True),
    BuiltinSpec("sl", 1, 1, "list", "sv_builtin_sl", mutates_args=True, dense_infer=True),
    BuiltinSpec("by", 1, 1, "bytes", "sv_builtin_by", pure=True, deterministic=True, allocates=True),
    # Process/runtime facts.  Reads are externally observable but never retain args.
    BuiltinSpec("av", 0, 0, "list", "sv_builtin_av", allocates=True),
    BuiltinSpec("ev", 1, 1, None, "sv_builtin_ev", allocates=True),
    BuiltinSpec("cw", 0, 0, "s", "sv_builtin_cw", allocates=True, external_io=True),
    BuiltinSpec("pf", 0, 0, "map", "sv_builtin_pf", allocates=True, deterministic=True),
    # Host-capability query.  The public spelling lives at @std/sys.cp; it is not a
    # root builtin.  The argument is the canonical "@std/module.export" facility id
    # and the result says whether this compiler/runtime target implements that
    # operation.  Unknown names are simply false so feature probes remain forward
    # compatible.
    BuiltinSpec("cp", 1, 1, "b", "sv_builtin_cp", pure=True, deterministic=True, may_trap=False),
    # Time/entropy.  A deterministic PRNG intentionally remains implementable in SLUG.
    BuiltinSpec("tm", 0, 0, "f", "sv_builtin_tm", external_io=True),
    BuiltinSpec("mt", 0, 0, "f", "sv_builtin_mt", external_io=True),
    BuiltinSpec("wt", 1, 1, "null", "sv_builtin_wt", external_io=True),
    BuiltinSpec("en", 1, 1, "bytes", "sv_builtin_en", allocates=True, external_io=True),
    # Filesystem primitives.  Copy/walk/glob/recursive operations are intentionally
    # absent: they compose cleanly from this orthogonal surface in ordinary SLUG.
    BuiltinSpec("fr", 1, 1, "bytes", "sv_builtin_fr", allocates=True, external_io=True),
    BuiltinSpec("ft", 1, 1, "s", "sv_builtin_ft", allocates=True, external_io=True),
    BuiltinSpec("fw", 2, 2, None, "sv_builtin_fw", external_io=True),
    BuiltinSpec("fa", 2, 2, None, "sv_builtin_fa", external_io=True),
    BuiltinSpec("fe", 1, 1, "b", "sv_builtin_fe", external_io=True),
    BuiltinSpec("fd", 1, 1, "list", "sv_builtin_fd", allocates=True, external_io=True),
    BuiltinSpec("fm", 1, 1, "map", "sv_builtin_fm", allocates=True, external_io=True),
    BuiltinSpec("md", 1, 1, "b", "sv_builtin_md", external_io=True),
    BuiltinSpec("rm", 1, 1, "b", "sv_builtin_rm", external_io=True),
    BuiltinSpec("mv", 2, 2, "null", "sv_builtin_mv", external_io=True),
    # Streaming/random-access file handles. Whole-file helpers above are ergonomic
    # shortcuts; these are the orthogonal primitives needed for large/binary streams.
    BuiltinSpec("fo", 2, 2, "file", "sv_builtin_fo", allocates=True, external_io=True),
    BuiltinSpec("hr", 2, 2, "bytes", "sv_builtin_hr", allocates=True, mutates_args=True, external_io=True),
    BuiltinSpec("hw", 2, 2, None, "sv_builtin_hw", mutates_args=True, external_io=True),
    BuiltinSpec("hs", 3, 3, "i", "sv_builtin_hs", mutates_args=True, external_io=True),
    BuiltinSpec("hp", 1, 1, "i", "sv_builtin_hp", external_io=True),
    BuiltinSpec("hf", 1, 1, "null", "sv_builtin_hf", mutates_args=True, external_io=True),
    BuiltinSpec("hc", 1, 1, "null", "sv_builtin_hc", mutates_args=True, external_io=True),
    BuiltinSpec("pc", 1, 1, "i", "sv_builtin_pc", external_io=True),
    # TCP socket bones. HTTP/WebSocket framing stays implementable in SLUG.
    BuiltinSpec("so", 0, 0, "socket", "sv_builtin_so", allocates=True, mutates_args=True, external_io=True),
    BuiltinSpec("cn", 3, 3, "null", "sv_builtin_cn", mutates_args=True, external_io=True),
    BuiltinSpec("bn", 3, 3, "null", "sv_builtin_bn", mutates_args=True, external_io=True),
    BuiltinSpec("ls", 2, 2, "null", "sv_builtin_ls", mutates_args=True, external_io=True),
    BuiltinSpec("ac", 1, 1, "socket", "sv_builtin_ac", allocates=True, mutates_args=True, external_io=True),
    BuiltinSpec("sd", 2, 2, None, "sv_builtin_sd", mutates_args=True, external_io=True),
    BuiltinSpec("rc", 2, 2, "bytes", "sv_builtin_rc", allocates=True, mutates_args=True, external_io=True),
    BuiltinSpec("sc", 1, 1, "null", "sv_builtin_sc", mutates_args=True, external_io=True),
    BuiltinSpec("gp", 1, 1, "i", "sv_builtin_gp", external_io=True),
    # v0.1.7 low-level multimedia/device bones. Higher-level GUI widgets, image
    # formats, synthesis/mixing, protocols, and device framing remain ordinary SLUG.
    BuiltinSpec("sf", 2, 2, "surface", "sv_builtin_sf", allocates=True),
    BuiltinSpec("px", 4, 4, "null", "sv_builtin_px", mutates_args=True),
    BuiltinSpec("rf", 6, 6, "null", "sv_builtin_rf", mutates_args=True),
    BuiltinSpec("dl", 6, 6, "null", "sv_builtin_dl", mutates_args=True),
    BuiltinSpec("sb", 1, 1, "bytes", "sv_builtin_sb", allocates=True),
    BuiltinSpec("wn", 3, 3, "window", "sv_builtin_wn", allocates=True, external_io=True),
    BuiltinSpec("wf", 2, 2, "null", "sv_builtin_wf", mutates_args=True, external_io=True),
    BuiltinSpec("pe", 1, 1, None, "sv_builtin_pe", allocates=True, mutates_args=True, external_io=True),
    BuiltinSpec("wx", 1, 1, "null", "sv_builtin_wx", mutates_args=True, external_io=True),
    BuiltinSpec("au", 2, 2, "audio", "sv_builtin_au", allocates=True, external_io=True),
    BuiltinSpec("aq", 2, 2, "null", "sv_builtin_aq", mutates_args=True, external_io=True, retains_args=False),
    BuiltinSpec("ax", 1, 1, "null", "sv_builtin_ax", mutates_args=True, external_io=True),
    BuiltinSpec("do", 2, 2, "device", "sv_builtin_do", allocates=True, external_io=True),
    BuiltinSpec("dv", 2, 2, "device", "sv_builtin_dv", allocates=True, external_io=True),
    BuiltinSpec("dr", 2, 2, "bytes", "sv_builtin_dr", allocates=True, mutates_args=True, external_io=True),
    BuiltinSpec("dw", 2, 2, None, "sv_builtin_dw", mutates_args=True, external_io=True),
    BuiltinSpec("dx", 1, 1, "null", "sv_builtin_dx", mutates_args=True, external_io=True),
)

CORE_NAMES = ("co", "ci", "ty", "cv", "in", "iv", "ln", "sl", "by")

# Public standard-module surface. Capability spellings are intentionally *not* root
# builtins in language v1.0. The compiler rewrites an imported module member to an
# impossible-in-source internal builtin key, preserving user freedom to define e.g.
# a normal function named `fr` without colliding with @std/fs.fr.
STD_MODULE_NAMES: dict[str, tuple[str, ...]] = {
    "@std/sys": ("av", "ev", "cw", "pf", "cp", "pc"),
    "@std/time": ("tm", "mt", "wt"),
    "@std/rand": ("en",),
    "@std/fs": ("fr", "ft", "fw", "fa", "fe", "fd", "fm", "md", "rm", "mv", "fo", "hr", "hw", "hs", "hp", "hf", "hc"),
    "@std/net": ("so", "cn", "bn", "ls", "ac", "sd", "rc", "sc", "gp"),
    "@std/gfx": ("sf", "px", "rf", "dl", "sb", "wn", "wf", "pe", "wx"),
    "@std/audio": ("au", "aq", "ax"),
    "@std/dev": ("do", "dv", "dr", "dw", "dx"),
    "@std/list": ("ap", "ip", "rm", "pp"),
}

# Most historical standard capabilities have globally unique two-letter export names,
# so they can reuse the legacy public spec table.  Explicit modules are namespaces,
# though, and are allowed to reuse an export spelling.  Keep module-specific specs
# here instead of forcing artificial global uniqueness (for example LI.rm vs FS.rm).
_STD_MODULE_SPEC_OVERRIDES: dict[tuple[str, str], BuiltinSpec] = {
    ("@std/list", "ap"): BuiltinSpec("ap", 2, 2, "list", "sv_builtin_list_ap", mutates_args=True),
    ("@std/list", "ip"): BuiltinSpec("ip", 3, 3, "list", "sv_builtin_list_ip", mutates_args=True),
    ("@std/list", "rm"): BuiltinSpec("rm", 2, 2, "b", "sv_builtin_list_rm", mutates_args=True),
    ("@std/list", "pp"): BuiltinSpec("pp", 1, 2, None, "sv_builtin_list_pp", mutates_args=True),
}

_PUBLIC_SPECS: dict[str, BuiltinSpec] = {spec.name: spec for spec in _SPECS}
CORE_BUILTINS: dict[str, BuiltinSpec] = {name: _PUBLIC_SPECS[name] for name in CORE_NAMES}
STD_MODULE_EXPORTS: dict[str, dict[str, str]] = {}
INTERNAL_MODULE_EXPORTS: dict[str, dict[str, str]] = {
    "@internal/cli": {
        "ex": "__slug_internal_cli_ex",
        "se": "__slug_internal_cli_se",
        "so": "__slug_internal_cli_so",
        "ep": "__slug_internal_cli_ep",
    }
}
BUILTINS: dict[str, BuiltinSpec] = dict(CORE_BUILTINS)
BUILTINS.update({
    "__slug_internal_cli_ex": BuiltinSpec("__slug_internal_cli_ex", 1, 1, "null", "sv_builtin_cli_ex", external_io=True),
    "__slug_internal_cli_se": BuiltinSpec("__slug_internal_cli_se", 1, 1, "null", "sv_builtin_cli_se", external_io=True),
    "__slug_internal_cli_so": BuiltinSpec("__slug_internal_cli_so", 1, 1, "null", "sv_builtin_cli_so", external_io=True),
    "__slug_internal_cli_ep": BuiltinSpec("__slug_internal_cli_ep", 0, 0, "s", "sv_builtin_cli_ep", allocates=True, external_io=True),
})
for uri, names in STD_MODULE_NAMES.items():
    exports: dict[str, str] = {}
    module_tag = uri.removeprefix("@std/").replace("/", "_")
    for public_name in names:
        base = _STD_MODULE_SPEC_OVERRIDES.get((uri, public_name), _PUBLIC_SPECS.get(public_name))
        if base is None:
            raise RuntimeError(f"missing builtin spec for {uri}.{public_name}")
        internal = f"__slug_std_{module_tag}_{public_name}"
        exports[public_name] = internal
        BUILTINS[internal] = BuiltinSpec(
            internal, base.min_arity, base.max_arity, base.return_kind, base.c_name,
            base.pure, base.deterministic, base.allocates, base.mutates_args,
            base.external_io, base.may_trap, base.retains_args, False,
        )
    STD_MODULE_EXPORTS[uri] = exports


def builtin(name: str) -> BuiltinSpec | None:
    return BUILTINS.get(name)


def is_builtin(name: str) -> bool:
    return name in BUILTINS


def standard_module_exports(uri: str) -> dict[str, str] | None:
    exports = STD_MODULE_EXPORTS.get(uri)
    return None if exports is None else dict(exports)

def internal_module_exports(uri: str) -> dict[str, str] | None:
    exports = INTERNAL_MODULE_EXPORTS.get(uri)
    return None if exports is None else dict(exports)


def public_spec(name: str) -> BuiltinSpec | None:
    return _PUBLIC_SPECS.get(name)


def caller_write_free_builtin_names() -> frozenset[str]:
    return frozenset(name for name, spec in BUILTINS.items() if spec.caller_write_free)


def nonretaining_builtin_names() -> frozenset[str]:
    return frozenset(name for name, spec in BUILTINS.items() if not spec.retains_args)

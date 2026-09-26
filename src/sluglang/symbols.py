from __future__ import annotations

from dataclasses import dataclass, field

from .builtins import CORE_BUILTINS


@dataclass(frozen=True, slots=True)
class CallableSig:
    name: str
    min_arity: int
    max_arity: int | None
    returns: int | None = 1
    builtin: bool = False
    dense_infer: bool = True

    @property
    def variadic(self) -> bool:
        return self.max_arity is None


@dataclass(frozen=True, slots=True)
class VarSig:
    name: str
    type_code: str | None = None
    immutable: bool = False
    # Internal module origin used only for direct-imported bindings. Alias imports
    # carry their origin in ModuleVar itself.
    origin: str | None = None


@dataclass(frozen=True, slots=True)
class MethodSig:
    name: str
    min_arity: int
    max_arity: int | None
    static: bool = False
    private: bool = False


@dataclass(frozen=True, slots=True)
class InterfaceSig:
    name: str
    methods: tuple[MethodSig, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassSig:
    name: str
    min_arity: int = 0
    max_arity: int | None = 0
    methods: tuple[MethodSig, ...] = ()
    static_fields: tuple[str, ...] = ()

    def method(self, name: str, static: bool) -> MethodSig | None:
        for method in self.methods:
            if method.name == name and method.static == static and not method.private:
                return method
        return None


@dataclass(slots=True)
class Symbols:
    callables: dict[str, CallableSig] = field(default_factory=dict)
    classes: dict[str, ClassSig] = field(default_factory=dict)
    variables: dict[str, VarSig] = field(default_factory=dict)
    interfaces: dict[str, InterfaceSig] = field(default_factory=dict)

    @classmethod
    def core(cls) -> "Symbols":
        s = cls()
        for spec in CORE_BUILTINS.values():
            s.callables[spec.name] = CallableSig(
                spec.name, spec.min_arity, spec.max_arity, 1, True, spec.dense_infer
            )
        return s

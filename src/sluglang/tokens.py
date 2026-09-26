from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    start: int
    end: int
    line: int
    column: int
    preserve: bool = False

    def __repr__(self) -> str:
        extra = ", preserve=True" if self.preserve else ""
        return f"Token({self.kind!r}, {self.text!r}, {self.line}:{self.column}{extra})"

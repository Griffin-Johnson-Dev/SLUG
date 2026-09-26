from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Span:
    start: int
    end: int
    line: int = 1
    column: int = 1


class SlugError(Exception):
    """Base class for front-end diagnostics."""

    code = "SLG000"

    def __init__(self, message: str, *, span: Span | None = None):
        super().__init__(message)
        self.message = message
        self.span = span

    def render(self, source: str | None = None, path: str | None = None) -> str:
        where = ""
        if self.span:
            where = f"{path or '<source>'}:{self.span.line}:{self.span.column}: "
        out = f"{where}{self.code}: {self.message}"
        if source is not None and self.span is not None:
            lines = source.splitlines() or [source]
            if 1 <= self.span.line <= len(lines):
                line = lines[self.span.line - 1]
                caret_len = max(1, self.span.end - self.span.start)
                out += f"\n  {line}\n  {' ' * (self.span.column - 1)}{'^' * min(caret_len, max(1, len(line) - self.span.column + 1))}"
        return out


class LexError(SlugError):
    code = "SLG101"


class ParseError(SlugError):
    code = "SLG102"


class AmbiguityError(SlugError):
    code = "SLG103"


class SemanticError(SlugError):
    code = "SLG201"


class CodegenError(SlugError):
    code = "SLG301"

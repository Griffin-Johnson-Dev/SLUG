from __future__ import annotations

from .diagnostics import LexError, Span
from .tokens import Token

# Longest first. Context decides semantics; lexer only records hard punctuation.
# `//` is executable exact integer division in language v1.0.
_MULTI = (
    "<:.", "::=", "!==", "===", "<:", ":=", "==", "!=", "<=", ">=", "++", "--", "^^", "~-", "~~", "//",
)
_SINGLE = set("{}[](),:;.#~@!?+-*/%^=<>$|`")


def normalize_source(source: str) -> str:
    """Return the normative v1 logical source stream.

    SLUG v1 source is UTF-8 text. Python callers have already decoded bytes, so this
    routine implements the remaining lexical normalization: one optional BOM at byte/
    character zero and CRLF/CR -> LF. A BOM anywhere else remains an invalid source
    character and is diagnosed by the lexer.
    """
    if source.startswith("\ufeff"):
        source = source[1:]
    return source.replace("\r\n", "\n").replace("\r", "\n")


def _span(source: str, start: int, end: int) -> Span:
    line = source.count("\n", 0, start) + 1
    prev = source.rfind("\n", 0, start)
    col = start + 1 if prev < 0 else start - prev
    return Span(start, end, line, col)


def lex(source: str) -> list[Token]:
    """Lex audited SLUG v1 source into deliberately low-level tokens.

    Lowercase and uppercase letters are emitted one at a time. This is intentional:
    SLUG parsing is context-sensitive enough that ``ab`` may mean variables ``a,b``
    or callable ``ab``. Decimal digit runs are likewise left splittable so RPN can
    resolve ``52/`` as ``5 2 /`` while a one-value context keeps ``52``.
    """

    source = normalize_source(source)
    out: list[Token] = []
    i = 0
    n = len(source)
    line = 1
    col = 1

    def emit(kind: str, text: str, start: int, start_line: int, start_col: int, preserve: bool = False) -> None:
        out.append(Token(kind, text, start, start + len(text), start_line, start_col, preserve))

    while i < n:
        ch = source[i]
        if ch.isspace():
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1
            continue

        start, sl, sc = i, line, col

        # v1 line comments. `##!` survives crush; ordinary `##` does not.
        if source.startswith("##", i):
            preserve = source.startswith("##!", i)
            j = source.find("\n", i)
            if j < 0:
                j = n
            text = source[i:j]
            emit("COMMENT", text, start, sl, sc, preserve)
            col += j - i
            i = j
            continue

        # v1 nested block comments. `#*! ... *#` survives crush.
        if source.startswith("#*", i):
            preserve = source.startswith("#*!", i)
            depth = 0
            j = i
            while j < n:
                if source.startswith("#*", j):
                    depth += 1
                    j += 2
                    continue
                if source.startswith("*#", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                    continue
                j += 1
            if depth != 0:
                raise LexError("unterminated block comment", span=_span(source, start, n))
            text = source[i:j]
            emit("COMMENT", text, start, sl, sc, preserve)
            line += text.count("\n")
            if "\n" in text:
                col = len(text.rsplit("\n", 1)[-1]) + 1
            else:
                col += len(text)
            i = j
            continue

        # v1 has exactly one source string quoting form: single quotes.  The lexer is
        # interpolation-aware: an unescaped ``{`` in literal text enters ordinary
        # SLUG expression source until its matching ``}``.  Quotes inside that region
        # are nested SLUG string literals, not the end of the outer formatted string.
        # This is what makes e.g. ``'x{cv['i',a]}'`` lexically possible without a
        # second quoting syntax.
        if ch == "'":
            j = i + 1
            interp_depth = 0
            while j < n:
                c = source[j]
                if c == "\n":
                    raise LexError("physical newline inside string; use \\n", span=_span(source, start, j))
                if interp_depth == 0:
                    if c == "\\":
                        if j + 1 >= n:
                            raise LexError("trailing backslash in string", span=_span(source, start, n))
                        j += 2
                        continue
                    if c == "{":
                        interp_depth = 1
                        j += 1
                        continue
                    if c == "'":
                        j += 1
                        break
                    j += 1
                    continue

                # Interpolation body: skip nested SLUG string literals so their
                # braces/quotes do not affect interpolation nesting.
                if c == "'":
                    j += 1
                    while j < n:
                        q = source[j]
                        if q == "\n":
                            raise LexError("physical newline inside nested string; use \\n", span=_span(source, start, j))
                        if q == "\\":
                            if j + 1 >= n:
                                raise LexError("trailing backslash in nested string", span=_span(source, start, n))
                            j += 2
                            continue
                        if q == "'":
                            j += 1
                            break
                        j += 1
                    else:
                        raise LexError("unterminated nested string in interpolation", span=_span(source, start, n))
                    continue

                # Nested block comments are lexically opaque to brace matching.
                if source.startswith("#*", j):
                    comment_depth = 1
                    j += 2
                    while j < n and comment_depth:
                        if source[j] == "\n":
                            raise LexError("physical newline inside string interpolation", span=_span(source, start, j))
                        if source.startswith("#*", j):
                            comment_depth += 1; j += 2; continue
                        if source.startswith("*#", j):
                            comment_depth -= 1; j += 2; continue
                        j += 1
                    if comment_depth:
                        raise LexError("unterminated block comment in interpolation", span=_span(source, start, n))
                    continue

                # A line comment cannot reach a matching interpolation brace because
                # physical newlines are not permitted inside the source string.
                if source.startswith("##", j):
                    raise LexError("line comment cannot terminate inside string interpolation", span=_span(source, j, min(n, j + 2)))

                if c == "{":
                    interp_depth += 1
                elif c == "}":
                    interp_depth -= 1
                j += 1
            else:
                if interp_depth:
                    raise LexError("unterminated string interpolation", span=_span(source, start, n))
                raise LexError("unterminated string", span=_span(source, start, n))
            text = source[i:j]
            emit("STRING", text, start, sl, sc)
            i = j
            col += len(text)
            continue

        if ch == '"':
            raise LexError("double-quoted strings are not part of SLUG v1; use single quotes", span=_span(source, start, start + 1))

        # Extended identifier: one or more ASCII alphanumerics delimited by
        # underscores, e.g. _x_, _currentIndex_, _a1B2_. Interior underscores
        # are not part of an identifier.
        if ch == "_":
            j = i + 1
            if j >= n or not source[j].isalnum() or not source[j].isascii():
                raise LexError("invalid extended identifier", span=_span(source, start, min(n, j + 1)))
            while j < n and source[j].isalnum() and source[j].isascii():
                j += 1
            if j >= n or source[j] != "_":
                raise LexError("extended identifier must end with '_'", span=_span(source, start, min(n, j + 1)))
            j += 1
            text = source[i:j]
            emit("EXT", text, start, sl, sc)
            i = j
            col += len(text)
            continue

        # Decimal float: .23, 23., 23.4. A bare '.' remains traversal. Exponent
        # notation is deliberately not a source-literal form in language v1.
        if ch == "." and i + 1 < n and source[i + 1].isdigit():
            j = i + 1
            while j < n and source[j].isdigit():
                j += 1
            text = source[i:j]
            emit("FLOAT", text, start, sl, sc)
            i = j
            col += len(text)
            continue

        if ch.isdigit() and ch.isascii():
            j = i
            while j < n and source[j].isdigit() and source[j].isascii():
                j += 1
            if j < n and source[j] == ".":
                j += 1
                while j < n and source[j].isdigit() and source[j].isascii():
                    j += 1
                text = source[i:j]
                emit("FLOAT", text, start, sl, sc)
                i = j
                col += len(text)
            else:
                emit("DIGIT", ch, start, sl, sc)
                i += 1
                col += 1
            continue

        matched = next((op for op in _MULTI if source.startswith(op, i)), None)
        if matched:
            emit("OP", matched, start, sl, sc)
            i += len(matched)
            col += len(matched)
            continue

        if ch in _SINGLE:
            emit("PUNC", ch, start, sl, sc)
            i += 1
            col += 1
            continue

        if "a" <= ch <= "z":
            emit("LOWER", ch, start, sl, sc)
            i += 1
            col += 1
            continue

        if "A" <= ch <= "Z":
            emit("UPPER", ch, start, sl, sc)
            i += 1
            col += 1
            continue

        raise LexError(f"unexpected character {ch!r}", span=_span(source, start, start + 1))

    out.append(Token("EOF", "", n, n, line, col))
    return out

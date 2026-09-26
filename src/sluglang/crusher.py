from __future__ import annotations

from .formatter import compact_program, semantic_key
from .lexer import lex
from .parser import parse
from .symbols import Symbols


def _trial_same(args) -> bool:
    source, target, symbols, modules = args
    try:
        return semantic_key(parse(lex(source), source, symbols, modules)) == target
    except Exception:
        return False


def _drop_positions(source: str, positions: set[int]) -> str:
    return "".join(ch for i, ch in enumerate(source) if i not in positions)


def crush(source: str, symbols: Symbols | None = None, modules: dict[str, Symbols] | None = None) -> str:
    """Crush SLUG only when reparsing proves the exact same semantic AST.

    Boundary deletion is proof-driven, never textual guesswork.  Semicolons are tested
    in progressively smaller groups: if a whole group can disappear while reparsing to
    the same semantic AST, that removal is committed at once; if not, the group is split
    until the genuinely necessary boundaries are isolated.  This avoids both O(n)
    repeated full parses in the common "one real boundary" case and the fragility of
    spawning worker processes from compilers/test runners/IDEs.
    """
    original = parse(lex(source), source, symbols, modules)
    target = semantic_key(original)
    base = compact_program(original, with_semicolons=True)
    semi_positions = [t.start for t in lex(base) if t.text == ";"]

    if not semi_positions:
        if not _trial_same((base, target, symbols, modules)):
            raise RuntimeError("internal crusher error: compact source changed the AST")
        return base

    # Most SLUG programs genuinely need no statement terminators. Prove that in one go.
    all_removed = _drop_positions(base, set(semi_positions))
    if _trial_same((all_removed, target, symbols, modules)):
        return all_removed

    # Proof-driven chunk elimination. Positions refer to the immutable `base`, so we can
    # accumulate removals without index-shift bookkeeping.
    removed: set[int] = set()
    pending: list[list[int]] = [semi_positions]
    while pending:
        chunk = pending.pop()
        if not chunk:
            continue
        trial_removed = removed | set(chunk)
        trial = _drop_positions(base, trial_removed)
        if _trial_same((trial, target, symbols, modules)):
            removed = trial_removed
            continue
        if len(chunk) > 1:
            mid = len(chunk) // 2
            # Process the left half first while keeping deterministic source order.
            pending.append(chunk[mid:])
            pending.append(chunk[:mid])

    candidate = _drop_positions(base, removed)
    if not _trial_same((candidate, target, symbols, modules)):
        raise RuntimeError("internal crusher error: crushed source changed the AST")
    return candidate

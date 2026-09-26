# Stage-2 compiler architecture

Stage 2 exists to replace the intentionally restrictive Stage-1 bootstrap with a compiler
that can become the maintained implementation.

## Bootstrap boundary

Stage 1 is frozen. Readable Stage-2 source is maintained under `compiler/stage2/`; the
Python oracle currently expands it into canonical bootstrap source under
`compiler/stage2_bootstrap/` when that bridge must be refreshed. Frozen a2 can compile the
canonical tree, after which Stage 2 compiles itself.

This separation prevents Stage-1 formatting/ambiguity restrictions from becoming permanent
style rules for the maintained compiler.

## Module graph

The Stage-2 loader keeps one record per canonical module path. A module record owns:

- a stable module ID;
- its parsed AST;
- direct dependency records;
- its source-level functions and module globals;
- native C symbol tables for functions and globals.

Dependency order is stored separately for deterministic initialization. Import cycles are
detected explicitly. Source names are no longer forced to be globally unique across the
transitive graph.

## Native symbol mangling

C symbols combine module identity with a byte-safe source-name encoding. Each UTF-8 byte of
the source identifier is emitted as decimal digits plus `_`, avoiding dependence on C
identifier spelling and leaving room for extended/Unicode SLUG names.

## Ordered C lowering

Stage 2 does not build complex C expressions whose operand order could differ from SLUG.
It recursively emits temporaries in source evaluation order. Calls, arithmetic, comparisons,
collection construction/indexing, and other composed expressions therefore acquire explicit
sequencing before the final operation is emitted.

Loop conditions are re-lowered inside generated loop bodies so side effects are evaluated on
every iteration rather than once before entering the loop.

## Runtime

v0.3.0a1 still uses a C runtime resource derived from the proven bootstrap runtime. The
application locates it from `SLUG_RUNTIME`, the source-tree path, or `runtime_stage2.c` in the
current packaged directory. Embedding/install-time resource discovery and final GC/rooting
policy are later Stage-2 work.

## Verification

`tests/run_stage2_bootstrap.py` proves compiler convergence and the two Stage-2 architectural
properties that directly remove Stage-1 restrictions. `tests/run_stage2_app.py` proves the
application surface end-to-end.

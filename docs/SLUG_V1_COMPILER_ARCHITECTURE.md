# SLUG 1.0 Compiler Architecture

## Authority and bootstrap

The maintained compiler is written in audited SLUG v1 under `compiler/`. The Python implementation under `src/sluglang/` is a readable reference/oracle and bootstrap bridge; it is not required by the installed native compiler.

`bootstrap/slug_seed.c` is a checked-in generated-C seed used to reconstruct the native compiler from a clean source archive. Public release proof requires later self-host generations to converge byte-for-byte before that seed is promoted.

## Front end

The lexer records source offsets on tokens. The ambiguity-aware parser chooses the unique lowest-cost complete parse and rejects unresolved equal-cost ambiguity rather than using arbitrary beam limits. Semantic validation is layered over the selected AST and module graph.

Normal successful parsing does not carry editor provenance through parser candidate exploration. Diagnostic location work is failure-only: lexer failures record their boundary directly; parse/structural failures run a separate locator; semantic failures replay the selected AST with temporary statement provenance and then run the ordinary validators.

## Module graph

The compiler maintains one record per canonical module identity. Ordinary imports resolve relative to the importer, `@dep/*` resolves through the root project's deterministic local dependency map, and `@std/*` is distribution-owned and never filesystem-searched. Repeated imports share one module/state identity and initialization order is deterministic.

## Native lowering

The v1 backend emits C11 plus a private runtime ABI. Source evaluation order is made explicit through generated temporaries rather than relying on unspecified C operand ordering. Runtime values, exceptions, collection behavior, string lengths, module state, and standard capabilities are implemented by the versioned native runtime shipped with the compiler.

The backend artifact is intentionally deterministic. Release proof compares consecutive native self-host emissions byte-for-byte.

## Runtime and installation

An installed compiler locates `lib/slug/1.0/runtime_stage2.c` relative to its own executable. The compiler and generated programs are native and do not require Python. Tooling assets live under `share/slug/1.0/` so the compiler, language server, extension, standard-module registry, documentation, and language contract remain version-paired.

## Tooling

`slug-lsp` is a thin JSON-RPC bridge to the native compiler. Unsaved documents are passed through stdin overlays while retaining their logical path, preserving project discovery and import semantics. The VS Code extension is likewise a thin client and contains no independent SLUG parser or semantic implementation.

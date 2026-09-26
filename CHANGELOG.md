# Changelog

## 1.0.1 — 2026-09-26

- Fixed a language-contract conformance bug where structural/comparison punctuation such as `:=`, `::=`, `==`, `!=`, `<=`, `>=`, `<:`, and their three-character relatives required physical adjacency even though spacing must not be needed to express those grammar forms.
- Those whitespace-transparent composites are now recognized across spaces, tabs, and logical newlines without globally stripping source text; string contents and comment boundaries remain intact.
- Preserved the established token identity of executable compound operators `++`, `--`, `^^`, `~-`, `~~`, and `//`: exact contiguous spellings remain compound tokens, while separated component punctuation keeps its pre-existing tokenization instead of being greedily fused.
- Added a dedicated whitespace-invariance/compatibility regression gate plus expanded lexer/program differentials covering spaced and multi-line structural spellings.
- Updated the VS Code grammar to highlight spaced core builtins, keywords, classes, and whitespace-transparent structural operators consistently with the compiler, without falsely coloring separated executable punctuation as a compound token.
- Kept the language contract at `1.0`; this is an implementation repair, not a new language version.

## 1.0.0 — 2026-09-25

- Self-hosted audited-v1 compiler with deterministic native C backend convergence.
- Stable public CLI contract and explicit language/compiler version separation.
- Deterministic importer-relative modules, local `@dep/*` project dependencies, and reserved `@std/*` capabilities.
- Native tooling boundary, stdin overlays, LSP bridge, and thin VS Code client.
- Failure-only diagnostic provenance for lexical, parse/structural, and semantic failures without successful-parser hot-path bookkeeping.
- Deterministic install layout, source archive/manifests, Apache-2.0 licensing, security guidance, and v1-only public examples/docs.

Historical development milestones are retained under `historical/` and are not part of the public language contract.

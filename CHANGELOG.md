# Changelog

## 1.0.0 — 2026-09-25

- Self-hosted audited-v1 compiler with deterministic native C backend convergence.
- Stable public CLI contract and explicit language/compiler version separation.
- Deterministic importer-relative modules, local `@dep/*` project dependencies, and reserved `@std/*` capabilities.
- Native tooling boundary, stdin overlays, LSP bridge, and thin VS Code client.
- Failure-only diagnostic provenance for lexical, parse/structural, and semantic failures without successful-parser hot-path bookkeeping.
- Deterministic install layout, source archive/manifests, Apache-2.0 licensing, security guidance, and v1-only public examples/docs.

Historical development milestones are retained under `historical/` and are not part of the public language contract.

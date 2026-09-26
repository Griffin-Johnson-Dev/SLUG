# K9E manifest-driven local projects

K9E adds `slug.json` schema 1, upward project-root discovery, source-optional `check`/`build`/`run`, and deterministic local dependency URIs of the form `@dep/<name>/<exact-file.slg>`.

The layer is deliberately local and reproducible. Ordinary source imports remain relative to the importing file, `@std/*` remains distribution-owned, and `@dep/*` is resolved only through the root manifest's declared project-relative dependency roots. There is no network fetch, registry, semver solver, implicit source suffix, or global search path in K9E.

The project-manifest/reference-native differential is `tests/run_v1_project_manifest.py`. K9D1 provider identity remains the underlying linkage contract, including shared mutable state through repeated/diamond dependency imports.

## Canonical K9E compiler

- compiler version: `0.9.0-dev+k9e`
- generated C bytes: **3,183,289**
- SHA-256: `288f9d4795a54176872090ba99ebea04745e15d41d9b5f6641ccc65396e8dbbb`
- native Stage-4 -> Stage-5 comparison: **byte-identical**
- project-manifest differential: **22/22**
- provider/module linkage: **33/33** (21 base + 12 imported inheritance)

The exact generated C above is the K9E fixed-point candidate promoted to `bootstrap/slug_seed.c`; release promotion additionally requires the clean fresh-extraction bootstrap and installed-distribution proofs.

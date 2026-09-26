# K9F native tooling boundary

K9F hardens the existing native formatter/crusher/diagnostic surface and adds a minimal stable machine-readable handshake for editors without introducing a Python runtime dependency or a second compiler implementation.

New native commands:

- `slug tooling-info`
- `slug project-info [source-file]`

Both commands emit compact schema-1 JSON and do not parse SLUG source. Existing `fmt`, `crush`, `expand`, JSON diagnostics, project manifests, provider-aware module linkage, and language semantics remain unchanged.

The permanent K9F tooling gate is `tests/run_v1_tooling.py` and covers 23 cases: transform idempotence/safety/Unicode/comment behavior, atomic-output cleanup, machine-diagnostic schema stability, and native/reference tooling/project JSON parity.

Accurate non-placeholder native parser spans remain future work. An attempted farthest-token instrumentation was rejected before promotion because even semantically-correct bookkeeping in the ambiguity parser's hot path caused unacceptable self-host performance regression. K9F intentionally keeps ordinary compilation free of tooling bookkeeping.

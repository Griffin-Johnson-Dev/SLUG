# SLUG K9A clean optimized recovery/bootstrap snapshot

This is the optimized successor to the K9 self-contained recovery base. It retains full K8/K8A correctness and fixed-point guarantees while adding literal-string interning to the self-host compiler and using a lower-memory bootstrap GC profile.

It intentionally does **not** depend on Recovery J or any historical K1-K8 delta archive.

## What is authoritative here

- `compiler/v1/` — maintained audited-v1 frontend/semantic sources.
- `compiler/stage2/` — maintained self-host compiler/runtime sources.
- `bootstrap/slug_seed.c` — exact canonical K9A optimized fixed-point generated C translation unit.
- `bootstrap/verify_bootstrap.sh` — clean bootstrap/fixed-point verification.
- `src/sluglang/` plus audited tests — Python/reference oracle retained for conformance and recovery diagnostics.

## Recovery procedure (POSIX host with a C11 compiler)

```sh
./bootstrap/verify_bootstrap.sh
```

The verifier compiles the canonical seed, uses it to regenerate the compiler from `compiler/stage2/app.slg`, requires the regenerated C to be byte-identical to the seed, compiles that regenerated compiler, checks the maintained compiler root, emits one more generation, and requires byte identity again.

The seed is a bootstrap artifact, not a separate language implementation: it is generated output of the SLUG compiler source and is required only to cross the usual self-hosting bootstrap boundary.

The verifier defaults to `SLUG_GC_INTERVAL=262144`, selected from the K9A memory profile as the best tested balance of bootstrap memory and throughput.

This K9A snapshot is a recovery checkpoint, not yet the public v1.0 release package. Cross-platform installers, release CLI polish, standard-library packaging, LSP/VS Code tooling, and release documentation remain later milestones.

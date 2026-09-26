# SLUG

SLUG is a compact, compiled programming language built around dense syntax, deterministic ambiguity resolution, RPN arithmetic, explicit module identities, and a self-hosted native compiler.

**Language contract:** 1.0  
**Compiler:** 1.0.0 (untagged final candidate until all platform gates are certified)  
**License:** Apache-2.0

The v1 language design is frozen. The compiler is self-hosted, converges to a byte-identical native C fixed point, and provides failure-only native provenance for lexical, parse/structural, and semantic diagnostics without adding source-position bookkeeping to successful ambiguity parsing.

## What is here

- `compiler/` — maintained self-hosted SLUG compiler and native runtime.
- `bootstrap/` — canonical generated-C bootstrap seed. It is bootstrap evidence, not the language specification.
- `docs/SLUG_V1_SPECIFICATION.md` — normative language semantics.
- `docs/SLUG_V1_COMPILER_ARCHITECTURE.md` — self-host/compiler/runtime/tooling architecture.
- `docs/SLUG_PUBLIC_CLI_V1.md` — public compiler CLI contract.
- `docs/SLUG_V1_STANDARD_MODULES.md` — reserved standard-module surface.
- `docs/SLUG_V1_SUPPORTED_PLATFORMS.md` — release-certified platform/toolchain matrix.
- `docs/SLUG_V1_RELEASE_PROCESS.md` — reproducible RC/final-release procedure.
- `examples/` — **v1-only** user-facing examples.
- `historical/` and `recovery_authority/` — development history; historical syntax is non-normative.
- `tooling/lsp/` and `tooling/vscode/` — native-backed editor integration.
- `tests/` — conformance, bootstrap, tooling, linkage, hardening, and adversarial gates.

## Bootstrap from source

A source build needs a C11 compiler. Python is used by release/developer tooling, but generated SLUG programs and the installed compiler do not require Python.

On Linux with GCC:

```sh
gcc -std=c11 -O2 bootstrap/slug_seed.c -lm -o slug
./slug --version
./slug --language-version
./slug check examples/hello.slg
```

To create the canonical versioned install tree:

```sh
python tools/build_install_tree.py --prefix "$HOME/.local" --cc gcc
```

Add `$HOME/.local/bin` to `PATH` if it is not already present.

The install contains the native compiler, versioned runtime, public contract metadata, LSP bridge, documentation, standard-module registry, and VS Code extension package.

## First program

```slug
co['Hello, SLUG!']
```

Save it as `hello.slg`, then:

```sh
slug check hello.slg
slug run hello.slg
```

See `examples/README.md` for more v1 examples.

## Editor support

The VS Code client in `tooling/vscode/` is intentionally thin. Diagnostics, formatting, project discovery, relative imports, and `@dep/*` resolution remain native-backed through `slug-lsp`.

Diagnostics use failure-only provenance: successful ambiguity parsing is not burdened with position bookkeeping. The editor receives substantiated native ranges for lexical, parse/structural, and semantic failures.

## Projects

A project may use a `slug.json` manifest with an entry file and deterministic local dependency roots. No registry or network package resolution is part of v1. See `docs/SLUG_V1_INSTALL_AND_PROJECT_LAYOUT.md`.

## Security model

`slug run` is **not a sandbox**. It compiles and executes the requested program with the operating-system permissions of the invoking user. Do not use it to evaluate untrusted SLUG source. See `SECURITY.md`.

## Authority

If historical files disagree with current behavior, use this order:

1. `docs/SLUG_V1_SPECIFICATION.md`
2. `docs/SLUG_PUBLIC_CLI_V1.md`
3. `docs/SLUG_V1_STANDARD_MODULES.md`
4. audited v1 conformance tests
5. `docs/SLUG_V1_STABILITY_AND_AUTHORITY.md`

Recovery checkpoints and pre-v1 examples exist for provenance only.

## Release status

The tree is frozen as the untagged `1.0.0` final candidate. The public tag is withheld until the exact clean archive passes bootstrap convergence, conformance, tooling/LSP/editor gates, adversarial tests, metadata verification, release-manifest verification, and every platform certification claimed for 1.0.0. No source edit is permitted between the final platform PASS records and the tag.

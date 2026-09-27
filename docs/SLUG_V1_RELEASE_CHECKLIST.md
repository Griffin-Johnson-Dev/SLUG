# SLUG V1 Release Checklist

This is the public-release closure gate. A recovery checkpoint being green is necessary but not sufficient for a public tag.

## Identity and source

- [ ] `VERSION` is the compiler-version source of truth; `LANGUAGE_VERSION` is the language-contract source of truth.
- [ ] `python tools/release_metadata.py` passes with no drift.
- [ ] Source archive contains no build products, caches, editor packages, temporary probes, or shadow files.
- [ ] `SOURCE_SHA256SUMS.txt` covers every intended source file exactly once and verifies from a fresh extraction.
- [ ] Release manifest records archive hash, canonical generated-C hash, bootstrap seed hash, compiler/language/CLI versions, and tested platform/toolchain identities.
- [ ] Platform certificates record the SHA-256 of the actual installed native compiler(s), not only the seed/source tree.

## Compiler and language

- [ ] Reference-vs-native lexer, expression, program, semantic, and audited-conformance suites pass.
- [ ] Public CLI contract, identifiers, exceptions, project/dependency graph, provider/module linkage, and standard-module gates pass.
- [ ] Optimizer on/off differential and native O0/O3 + ASan/UBSan hardening pass.
- [ ] Deterministic adversarial/fuzz corpus produces no crash, hang, nondeterministic diagnostic, or unbounded malformed-source behavior.
- [ ] Stage N and N+1 self-host emissions converge byte-for-byte to the canonical backend artifact.
- [ ] A fresh extraction independently reproduces that fixed point.

## Diagnostics and tooling

- [ ] Native tooling gate passes, including stdin overlays and zero source/temp debris.
- [ ] Lexical, parse/structural, and semantic failures produce substantiated native ranges.
- [ ] LSP converts Unicode scalar columns to UTF-16 correctly and clears stale diagnostics.
- [ ] VS Code client works against the installed distribution and does not require project-source-tree paths.
- [ ] `slug run` non-sandbox trust model is documented.

## Distribution

- [ ] Clean 64-bit Linux build is certified with GCC and Clang for the exact claimed versions.
- [ ] Clean 64-bit Windows build is certified with MSVC and/or clang-cl for the exact claimed versions.
- [ ] UTF-8 console/path behavior is exercised on each claimed OS.
- [ ] Canonical install tree passes `tests/run_v1_install_layout.py` and `tools/verify_install_layout.py`.
- [ ] VSIX is reproducible from source and has release license metadata.
- [ ] Public README, examples, specification, CLI reference, standard-module reference, installation guide, LSP/VS Code docs, security note, and license contain only current v1 guidance.

## Publication

- [ ] Build one release candidate from the exact clean archive and freeze it.
- [ ] Run the entire gate against artifacts installed from that RC, not a developer worktree.
- [ ] Record known limitations without silently broadening platform/support claims.
- [ ] The final compiler version is frozen before certification; after all claimed platforms pass, tag and publish the exact unchanged certified tree.

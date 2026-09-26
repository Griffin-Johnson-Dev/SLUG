# SLUG 1.0 Release Process

This file defines the mechanical path from a green development tree to a public release candidate and, eventually, `1.0.0`.

## 1. Freeze identity

`VERSION` is the compiler-version source of truth and `LANGUAGE_VERSION` is the language-contract source of truth. Synchronize and verify generated metadata:

```sh
python tools/release_metadata.py --write
python tools/release_metadata.py
```

Do not change language semantics during release closure.

## 2. Prove the native fixed point

Use the reference compiler only as the bridge when needed. The release authority is consecutive **native self-host** emissions. Promote the byte-identical native fixed-point C to `bootstrap/slug_seed.c`, update `bootstrap/CANONICAL_SEED_SHA256.txt`, then run:

```sh
bash bootstrap/verify_bootstrap.sh
```

The canonical seed must report the current compiler and language versions and regenerate itself byte-for-byte.

## 3. Run the release gate

Build or identify the native candidate, then run:

```sh
python tools/run_release_gate.py --slug /path/to/slug
```

For an already-created install prefix, add `--prefix /path/to/prefix` so installed-layout and real VS Code/LSP client smoke tests are included.

The full gate covers public contracts, project/dependency behavior, identifiers, exceptions, module linkage, editor tooling, deterministic adversarial input, differential parsers/semantics, audited conformance, native sanitizer/optimizer hardening, and bootstrap convergence.

## 4. Freeze the exact final version before platform certification

Once the source content is frozen, set `VERSION` to the intended final version (for the first release, `1.0.0`), synchronize metadata, and reconverge the canonical seed **before** final platform certification. The tree may remain untagged/unpublished while certification is pending. This avoids certifying one embedded compiler version and then invalidating that exact binary by changing only the version afterward.

Any source change after a platform PASS invalidates that platform's exact-tree certification and requires the affected final gates to be rerun.

## 5. Certify platforms

Run the exact final-version, untagged release candidate on every platform/toolchain claimed in `SLUG_V1_SUPPORTED_PLATFORMS.md`. Do not convert source-level portability into an unsupported platform claim.

At minimum for the planned first release, certify x86-64 Linux with GCC and Clang and certify x86-64 Windows with the selected MSVC/clang-cl toolchain. Exercise UTF-8 source/console/path behavior and the installed editor path on each claimed OS.

On Windows, `scripts/certify_windows.ps1` builds the installed distribution with `clang-cl` by default, proves native bootstrap convergence with that MSVC-style driver, then runs the full release gate with the LLVM `clang` driver so optimizer/sanitizer hardening is exercised as well. A Windows PASS must come from a real Windows host; cross-platform source inspection is not certification. The script writes `build/WINDOWS_CERTIFICATION.json` containing the exact compiler/language versions, host/toolchain identities, canonical-seed SHA-256, source-manifest SHA-256, and PASS status so the certification can be bound to the release artifacts.

## 6. Build a versioned install tree

```sh
python tools/build_install_tree.py --prefix /desired/prefix --cc gcc
```

The builder stages the complete SLUG-owned tree before touching the destination and never recursively deletes the requested prefix. Existing unrelated files in a common prefix such as `~/.local` must survive an install or upgrade.

## 7. Build the deterministic source archive

```sh
python tools/build_release_archive.py --out build/SLUG-source.zip
```

The builder regenerates `SOURCE_SHA256SUMS.txt`, excludes build/cache/editor-package debris, uses deterministic ZIP metadata, extracts the archive into a fresh temporary directory, and verifies every manifest-covered file.

Then create the sidecar release record:

```sh
python tools/build_release_manifest.py \
  --archive build/SLUG-source.zip \
  --compiler-c bootstrap/slug_seed.c
```

## 8. Final artifact proof and tag

Build the final artifacts from the exact clean source archive and repeat the install/release gate against artifacts installed from that archive rather than a developer worktree. Record any remaining limitation explicitly.

For `1.0.0`, the compiler version must already be `1.0.0` during the final platform certifications. Once every claimed platform is green and the certification records match the canonical seed/source manifest, tag and publish that **unchanged** tree. Do not rebuild or edit between the final certification and tag.

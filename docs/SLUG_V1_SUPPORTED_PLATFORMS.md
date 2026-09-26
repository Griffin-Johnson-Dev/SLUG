# SLUG 1.0 Supported Platforms

Support is claimed only after the exact release candidate passes the release gate on that host/toolchain. A compiler accepting the generated C is not, by itself, a support claim.

## Release-candidate matrix

| Platform | Toolchain | Status |
| --- | --- | --- |
| x86-64 Linux | GCC 14.2.0, C11 | **PASS — certified 2026-09-25** |
| x86-64 Linux | Clang 17.0.0, C11 | **PASS — certified 2026-09-25** |
| x86-64 Windows | clang-cl 23.1.1 + LLVM clang 23.1.1 | **PASS — 1.0.0 certified 2026-09-26; 1.0.1 exact-tree recertification required before 1.0.1 publication** |
| macOS | — | not claimed for 1.0 unless separately tested |

Each claimed platform must exercise compiler build, installed-prefix layout, UTF-8 source/console/path behavior, runtime conformance, LSP discovery, and the supported memory-safety diagnostics available on that host.

The Linux certifications above are release requirements for the exact `1.0.0` canonical seed on x86-64 Linux and are re-run during final artifact closure. Both installed distributions passed the install/layout, public CLI, project/dependency, identifier, exception-control, provider/module-linkage, native tooling, LSP, VS Code, deterministic malformed-source, and dedicated UTF-8 path/import/stdin/stdout gates. The common native conformance battery also passed reference/native lexer, expression, program, and semantic differentials, audited conformance, O0/O3 optimizer differential, ASan, and UBSan.

The source tree may contain portability code for additional hosts without implying support for them.

### Windows certification command

On an x86-64 Windows host with Python 3.11+, Node.js, LLVM `clang-cl`, and LLVM `clang` on `PATH`:

```powershell
.\scripts\certify_windows.ps1
```

That script is the release-authority path for certifying each exact Windows release tree. It performs an installed `clang-cl` build, fixed-point bootstrap proof, the full native/differential release gate, editor/install smoke, UTF-8 coverage, and public-example execution. A prior-version PASS does not automatically certify a later patch tree.

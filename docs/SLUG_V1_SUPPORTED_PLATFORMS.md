# SLUG V1 Supported Platforms

Support is claimed only after the **exact release source tree** passes the release gate on that host/toolchain. A compiler accepting generated C is not, by itself, a support claim. Final per-release PASS records are published as external certification sidecars so the certified source archive does not need to be edited after testing.

## Required V1 certification matrix

| Platform | Toolchain | Requirement |
| --- | --- | --- |
| x86-64 Linux | GCC 14.x or release-recorded equivalent, C11 | full bootstrap + installed distribution + full release gate |
| x86-64 Linux | Clang 17.x or release-recorded equivalent, C11 | full bootstrap + installed distribution + full release gate |
| x86-64 Windows 11 | clang-cl + LLVM clang, release-recorded versions | installed clang-cl build + bootstrap + full LLVM release gate |
| macOS | — | not claimed unless separately certified |

Each claimed platform exercises compiler build, installed-prefix layout, UTF-8 source/console/path behavior, runtime conformance, LSP discovery, editor packaging, public examples, and the available native hardening/sanitizer gates. A prior-version PASS never certifies a later source tree.

Certification sidecars bind the release to the compiler/language versions, canonical-seed SHA-256, source-manifest SHA-256, toolchain/host identity, and SHA-256 of the actual installed compiler executable.

### Windows certification command

On an x86-64 Windows host with Python 3.11+, Node.js, LLVM `clang-cl`, and LLVM `clang` on `PATH`:

```powershell
.\scripts\certify_windows.ps1
```

### Linux certification command

On the Linux certification host with Python 3.11+, Node.js, GCC, and Clang:

```sh
bash scripts/certify_linux.sh
```

Both helpers are release-authority paths for the exact extracted source tree.

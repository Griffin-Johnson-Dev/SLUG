# SLUG 1.0 Installation and Project Layout

## Installation prefix

A normal installation rooted at `PREFIX` uses a versioned layout:

```text
PREFIX/
  bin/slug[.exe]
  bin/slug-lsp[.cmd]
  lib/slug/1.0/runtime_stage2.c
  share/slug/1.0/
    VERSION
    LANGUAGE_VERSION
    CLI_CONTRACT_VERSION
    PUBLIC_CONTRACT.json
    INSTALL_LAYOUT.json
    LICENSE
    SECURITY.md
    README.md
    std/registry.json
    docs/...
    examples/...
    tooling/slug-lsp.js
    tooling/vscode/slug-language.vsix
```

The installed compiler resolves its runtime relative to its own executable through `lib/slug/1.0/`. `SLUG_RUNTIME` is a developer/recovery override, not the ordinary installation mechanism.

### Linux source install

A C11 compiler and Python 3.11+ are needed to construct the install tree:

```sh
./scripts/install.sh
```

The default prefix is `$HOME/.local`; set `PREFIX` and `CC` to override it.

### Windows source install

From PowerShell with Python 3.11+ and a supported C compiler:

```powershell
.\scripts\install.ps1
```

The default prefix is `%LOCALAPPDATA%\Programs\SLUG`. The script does not silently modify the user's persistent `PATH`; add the prefix's `bin` directory explicitly if desired.

Python is release/build tooling only. The installed compiler and generated programs are native. The standalone JavaScript LSP launcher requires Node.js 18+, while the VS Code extension normally uses VS Code's embedded runtime.

## Projects and `slug.json`

A project may place `slug.json` at its root:

```json
{
  "schema": 1,
  "name": "my-project",
  "entry": "src/main.slg",
  "dependencies": {
    "math": "vendor/math"
  }
}
```

Rules:

- `schema` is exactly integer `1`.
- `name` is `[a-z][a-z0-9-]*`, at most 64 characters.
- `entry` is a canonical project-relative forward-slash path naming an exact `.slg` file.
- `dependencies` is optional and maps dependency names to canonical project-relative local roots.
- Absolute paths, drive-like paths, backslashes, empty segments, `.`, `..`, and repeated/trailing separators are rejected.
- Unknown or duplicate manifest fields are errors.

The manifest is optional for explicit-file workflows. It is required when a command omits its entry file or when source uses `@dep/*`.

With no source argument, `slug check`, `slug build`, and `slug run` search upward from the current working directory for the nearest `slug.json`. An explicit source remains authoritative and only uses an upward manifest search to provide project/dependency context.

## Import resolution

SLUG 1.0 has three disjoint import classes:

1. ordinary source imports resolve exactly relative to the importing file;
2. `@std/*` resolves to compiler/runtime-owned standard capabilities and never searches project or network paths;
3. `@dep/<name>/<exact-file.slg>` resolves `<name>` through the root project's deterministic local dependency map.

There is no registry, network fetcher, version solver, lockfile, implicit `.slg` suffix, or environment-dependent global module search path in v1.

## Editor installation

The canonical install contains `slug-lsp` and `share/slug/1.0/tooling/vscode/slug-language.vsix`. The VS Code extension discovers the matching installed compiler/server pair automatically or can be pointed at explicit paths through `slug.compilerPath` and `slug.lspPath`.

# SLUG 1.0 for VS Code

The SLUG extension is a thin client over the native-backed language server. It contains no independent SLUG parser, semantic checker, formatter, project resolver, compiler backend, or runtime implementation.

## Distribution

The canonical install prefix contains the deterministic extension package at:

`share/slug/1.0/tooling/vscode/slug-language.vsix`

The extension supports `.slg` and `.slgc`, syntax highlighting, language configuration, diagnostics, document formatting, and commands for tooling/project information.

## Server discovery

The extension searches in this order:

1. explicit `slug.lspPath` / `slug.compilerPath` settings;
2. the versioned `share/slug/1.0/tooling/slug-lsp.js` adjacent to the configured or PATH-resolved compiler;
3. a `slug-lsp` launcher on `PATH`.

When the versioned JavaScript server is available, the extension launches it with VS Code's own Electron executable in Node mode and passes the matching native compiler explicitly. This keeps the compiler and language server paired within one versioned SLUG installation.

## Diagnostics

Unsaved buffers use the compiler's stdin-overlay tooling path. Lexical, parse/structural, and supported semantic failures receive substantiated native ranges using `failure-provenance-v2`; Unicode columns are converted to LSP UTF-16 positions by the server. The client never invents diagnostic positions.

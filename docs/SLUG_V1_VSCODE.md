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

## Marketplace identity and whitespace-aware highlighting

The public extension identity is `griffinjohnson.slug-devkit`, displayed as **SLUG Lang DevKit**. The installed source distribution may continue to store the deterministic VSIX under the compatibility filename `slug-language.vsix`; the Marketplace identity is defined by the embedded manifest rather than that filename.

DevKit 1.0.2 introduced the TextMate grammar with compiler 1.0.1's whitespace-invariance repair for same-line spellings. Core two-letter builtins/keywords/classes and whitespace-transparent structural punctuation such as `: =`, `: : =`, and `= =` receive the same broad syntax scopes as their compact spellings. Compatibility-sensitive executable compounds remain exact: separated `+ +`, `- -`, `^ ^`, `~ -`, `~ ~`, and `/ /` are deliberately not colored as `++`, `--`, `^^`, `~-`, `~~`, or `//`. TextMate coloring is intentionally only a lexical approximation; semantic validity and diagnostics remain native-backed through the compiler/LSP.

## Current package identity

SLUG Lang DevKit **1.0.3** is the current public editor package. It preserves the 1.0.2 grammar and repairs VSIX content-type metadata for the Marketplace icon. Compiler 1.0.2 does not require a new DevKit syntax release for `@std/list`; the existing client discovers the upgraded installed compiler/LSP through the same prefix/PATH. After a compiler upgrade, reload VS Code or run **SLUG: Restart Language Server**.

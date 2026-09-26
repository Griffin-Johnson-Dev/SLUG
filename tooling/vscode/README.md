# SLUG Language Support for VS Code

Thin VS Code client for the native-backed SLUG 1.0 language server.

The extension contains no separate SLUG parser or compiler. It discovers an installed toolchain, starts the matching versioned `slug-lsp.js`, and provides diagnostics, formatting, project/tooling inspection, syntax highlighting, and language configuration for `.slg` and `.slgc` files.

## Requirements

Install a SLUG 1.0-compatible toolchain. Normally the extension discovers `slug` from `PATH` and locates the matching versioned language server beside it. `slug.compilerPath` and `slug.lspPath` can override discovery.

## Commands

- `SLUG: Restart Language Server`
- `SLUG: Show Tooling Info`
- `SLUG: Show Project Info`

Diagnostic ranges come from native failure-only provenance and are reported faithfully by the client.

# K9G native-backed LSP bridge

K9G adds the first editor protocol layer on top of the frozen K9F tooling contract without introducing a second compiler implementation.

## Server

`tooling/lsp/slug-lsp.js` is a dependency-free Node.js stdio language server. It speaks standard `Content-Length` framed JSON-RPC and launches the installed native `slug` compiler for all language work.

Implemented protocol surface:

- `initialize` / `initialized` / `shutdown` / `exit`;
- full-text `textDocument/didOpen`, `didChange`, `didSave`, and `didClose`;
- `textDocument/publishDiagnostics`;
- `textDocument/formatting`;
- custom read-only requests `slug/toolingInfo` and `slug/projectInfo`.

The server never contains a SLUG parser, semantic checker, formatter, or project resolver. Those remain authoritative in the native compiler.

## Unsaved buffers

K9G adds two native tooling-only commands:

- `slug tooling-check <logical-path> [--diagnostic-format human|json]`
- `slug tooling-format <logical-path>`

Both read source text from stdin. `tooling-check` overlays only the root document in memory while retaining the real logical path for importer-relative modules and upward `slug.json` discovery. Imported modules continue to come from their canonical filesystem paths. `tooling-format` transforms stdin without touching the document on disk.

This replaces K9F-era same-directory shadow files for a K9G compiler. The LSP server retains the shadow strategy only as a backward-compatible fallback when launched against an older compiler that does not advertise `stdin_overlay`.

## Diagnostics

K9G transports native schema-1 diagnostics into LSP diagnostics. Native parser spans are still the frozen placeholder span where K9F left them; K9G does not reintroduce parser-hot-path position bookkeeping. Accurate spans remain a later diagnostic architecture task.

## Runtime

The compiler remains native and Python-free. The LSP bridge itself requires Node.js 18 or newer; this is a tooling runtime, not a compiler/runtime dependency. VS Code already embeds a compatible Node runtime, so the later extension can ship the server as a thin client asset.

## K9G fixed-point status

Canonical compiler C is 3,210,223 bytes with SHA-256 `94c6e158af6754ba7e5fab861397e483bf55c9577976a9e41c1368e796256386`. Two consecutive native generations are byte-identical. Permanent K9G gates: tooling 29/29 and LSP 18/18; frozen K9E/K9F/K9D1 compatibility gates remain green.

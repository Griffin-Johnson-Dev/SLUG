# SLUG 1.0 Language Server Protocol support

SLUG ships a thin native-backed language server at `tooling/lsp/slug-lsp.js`. The server speaks standard `Content-Length` framed JSON-RPC over stdio and delegates language decisions to the installed native `slug` compiler rather than maintaining a second parser or semantic implementation.

## Protocol surface

The v1 server implements initialize/shutdown/exit, full-text document synchronization, diagnostics, document formatting, and the read-only `slug/toolingInfo` and `slug/projectInfo` requests.

## Unsaved buffers

`slug tooling-check <logical-path>` and `slug tooling-format <logical-path>` read the current document from stdin while preserving its real logical path. Relative imports, `@dep/*` dependencies, and upward `slug.json` discovery therefore behave the same for unsaved editor buffers as they do for files on disk. Imported modules continue to come from their canonical filesystem paths. No shadow source file is required when the compiler advertises `stdin_overlay`.

## Diagnostic provenance

SLUG 1.0 uses failure-only native diagnostic provenance. Successful ambiguity parsing remains free of source-position bookkeeping.

After a failed check, `slug tooling-locate <logical-path>` may perform a second failure-only analysis against the same stdin overlay and module context:

- lexical failures report the offending source token directly from the lexer failure boundary;
- parse/structural failures use delimiter structure and farthest-reachable parsing;
- syntactically complete semantic failures replay only the selected AST with failure-only statement provenance and run the normal semantic validators.

Substantiated ranges are advertised as `failure-provenance-v2`. If the compiler cannot substantiate a location it returns no fabricated position. The LSP converts SLUG Unicode-scalar columns to the UTF-16 character offsets required by the protocol.

## Runtime requirements

The compiler remains native and Python-free. The standalone JavaScript LSP launcher requires Node.js 18 or newer. The VS Code extension normally launches the versioned server with VS Code's own Node/Electron runtime, so a separate Node installation is not required for the ordinary VS Code path.

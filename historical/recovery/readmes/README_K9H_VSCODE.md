# K9H — thin VS Code client distribution

K9H adds the first packaged VS Code client on top of the completed K9G native-backed LSP/tooling contract.

The native compiler remains exactly K9G (`0.9.0-dev+k9g`); its canonical seed and compiler/runtime sources are byte-unchanged. K9H is intentionally an editor/distribution milestone rather than another compiler generation.

The extension is dependency-free at runtime and contains no SLUG parser/compiler. It contributes syntax/language configuration, diagnostics, formatting, project/tooling inspection commands, and cross-platform discovery of the version-matched K9G+ `slug-lsp`/`slug` installation.

Permanent gate: `tests/run_v1_vscode_extension.py`.

Canonical install artifact: `share/slug/1.0/tooling/vscode/slug-language-k9h.vsix`.

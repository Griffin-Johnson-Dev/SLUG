# Changelog

## 1.0.3

- Repair VSIX Open Packaging Convention metadata so `icon.png` is declared in `[Content_Types].xml` and the Marketplace can resolve the existing icon asset.
- Preserve the SLUG 1.0 whitespace-aware TextMate grammar shipped in DevKit 1.0.2 unchanged.
- Add package validation that requires a content-type declaration for every file extension carried by the VSIX.

## 1.0.2

- Align syntax highlighting with SLUG 1.0 whitespace invariance for core builtins, reserved two-letter keywords, class names, namespace punctuation, and hard operators such as spaced `: =`.
- Publish under the stable `griffinjohnson.slug-devkit` identity as **SLUG Lang DevKit**.
- Include the banana-slug Marketplace icon and explicit public/non-prerelease VSIX metadata.

## 0.9.0-preview

- Thin VS Code client over the native-backed SLUG 1.0 LSP contract.
- Diagnostics with lexical, parse/structural, and semantic failure provenance.
- Document formatting.
- Tooling/project inspection commands.
- Cross-platform installed-prefix discovery.
- SLUG syntax highlighting and language configuration.

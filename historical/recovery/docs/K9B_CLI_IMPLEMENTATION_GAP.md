> **Historical K9B note:** the implementation gaps recorded below were the state at K9B. The native/self-hosted Public CLI Contract v1 implementation was completed at K9C; this file is retained as provenance.

# K9B Public CLI Implementation Gap

K9B freezes the target public CLI contract. It does **not** claim the existing bootstrap/reference CLI or the self-host Stage-2 application shell already implements that contract.

## Python/reference CLI today

Already present in some form:

- `check`
- `build`
- `run`
- `crush`
- `expand`
- `--version`
- `--language-version`
- developer AST/IR/MIR/C commands

Still divergent from Public CLI Contract v1:

- no public `fmt` command with stdout/`--write`/`--check` modes;
- successful `check` currently prints `PASS ...` rather than being silent;
- build/transform commands print output paths;
- public exit-code classes are currently `2`/`3`-style bootstrap codes instead of 64/65/69/70;
- no `--diagnostic-format json` schema-1 output;
- overwrite/output safety must be aligned to the frozen contract.

## Self-host Stage-2 CLI today

The current `compiler/stage2/app.slg` still identifies itself as an alpha application shell and exposes only the bootstrap-era command set (`check`, `emit-c`, `build`, `run`, `version`, `help`). Its hard-coded implementation version is stale development metadata.

Still required for public CLI convergence:

- rename/finalize public executable behavior as `slug`;
- implement `--version`, `--language-version`, `--help` and `help` exactly as contracted;
- implement `fmt`, `crush`, and `expand` or route them through maintained SLUG tooling;
- forward `run` arguments after `--`;
- implement output defaults and overwrite safety;
- implement compiler-owned exit-code classes 64/65/69/70;
- implement schema-1 JSON diagnostics;
- remove normal-install dependence on `SLUG_RUNTIME`/bootstrap path discovery;
- keep developer `emit-c` behavior outside the compatibility-stable command set.

## Next engineering gate

A subsequent checkpoint should bring the **native self-hosted CLI** into conformance with `docs/SLUG_PUBLIC_CLI_V1.md`, then run command/exit/output/UTF-8 regression tests before tooling such as the LSP and VS Code extension treats the CLI as stable.

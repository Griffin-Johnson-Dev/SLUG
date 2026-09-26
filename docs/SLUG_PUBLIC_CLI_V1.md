# SLUG Public Compiler CLI Contract v1

Status: **Frozen CLI Contract v1 with schema-1 tooling extensions.**

CLI contract version: **1**

Language contract: **SLUG 1.0**

This document defines the public command-line surface that the native compiler, documentation, formatter integration, language server launcher, VS Code extension, installers, and automation may rely on. Internal/bootstrap commands may exist but are outside this compatibility promise.

## 1. Executable and global behavior

The public executable name is:

`slug`

All compiler-controlled textual input/output is UTF-8. Generated text files use LF newlines. Human diagnostics go to stderr. A successful command MUST NOT emit warnings/errors to stderr.

Supported global queries:

- `slug --version`
- `slug --language-version`
- `slug --help`
- `slug help`

`slug --version` prints the compiler implementation version. It does not imply a language version.

`slug --language-version` prints exactly the implemented language contract major/minor, beginning with `1.0` for the first public release.

The implementation version may advance independently while continuing to implement language 1.0/1.x.

## 2. Stable public commands

### `slug check`

`slug check [file] [--diagnostic-format human|json]`

Lexes, parses, resolves imports, performs semantic validation, and validates all compiler-visible contracts without producing a native executable.

Success is silent and exits 0 unless an explicitly requested reporting option is added by a future compatible release. If `file` is omitted, the compiler discovers the nearest `slug.json` upward from the current directory and checks its declared entry.
If no manifest can be discovered for a source-optional project command, the invocation exits 64 because the required project context is absent.

### `slug build`

`slug build [file] [-o <output>] [--cc <compiler>] [--keep-c] [--diagnostic-format human|json]`

Builds a native executable from the program.

If an explicit `file` is supplied and `-o` is omitted, the default output is the input path with its source suffix removed, in the same directory, plus the platform executable suffix where required. If `file` is omitted, the compiler discovers `slug.json`; the default output is `build/<project-name>` beneath that project root (plus the platform executable suffix where required).

`--cc` selects the host C compiler used by the current C backend. `--keep-c` preserves the generated C next to the requested output. The generated C is implementation output, not a stable ABI.

Successful build is silent by default.

### `slug run`

`slug run [file] [--cc <compiler>] [-- <program-args>...]`

Builds in a temporary location, executes the resulting program, forwards program stdout/stderr, and removes temporary build output.

If `file` is omitted, the compiler discovers `slug.json` and runs its declared entry. Arguments after `--` are passed to the SLUG program unchanged as host argument strings.

Once execution begins, `slug run` forwards the program's exit status. Pre-execution compiler/tool failures use the compiler exit-code classes below.

### `slug fmt`

`slug fmt <file> [--check] [--write | -o <output>]`

Produces the canonical readable SLUG representation.

Modes:

- default: formatted source is written to stdout;
- `--write`: atomically replace the input file;
- `-o <output>`: write the formatted source to the named file;
- `--check`: write no formatted source; exit 0 if the file is already canonical, otherwise exit 65.

`--write`, `-o`, and `--check` are mutually exclusive.

Formatting MUST preserve semantic AST and preserved-comment semantics.

### `slug crush`

`slug crush <file> [-o <output>]`

Writes canonical crushed source. If `-o` is omitted, output is the input path with extension replaced by `.slgc`.

The command is silent on success.

### `slug expand`

`slug expand <file> [-o <output>]`

Expands `.slg` or `.slgc` to canonical formatted `.slg`. If `-o` is omitted, the result is written to stdout; an existing source file is never overwritten implicitly.

The command is silent on success except for requested source written to stdout.

## 3. Developer interfaces

The implementation may expose developer/debug commands such as:

- AST dump;
- high-level IR;
- MIR/optimized MIR;
- generated C emission;
- parser/semantic probes;
- bootstrap verification helpers.

These are not part of Public CLI Contract v1 unless separately promoted. Their spelling, textual representation, and presence may change within compiler 1.x.

In particular, generated C is not a stable source-level ABI.

## 4. Exit-code classes

Compiler-owned failures use these stable classes:

| Code | Meaning |
| ---: | --- |
| `0` | command succeeded |
| `64` | invalid CLI usage or invalid mutually-exclusive option combination |
| `65` | SLUG source, lexical, parse, semantic, contract, transform-check, or compile-time program error |
| `69` | required host tool/capability unavailable before program execution |
| `70` | compiler internal error/invariant failure |

A native SLUG program's uncaught runtime/finalizer failure convention remains **66** unless a platform launcher cannot preserve it.

`slug run` forwards the executed program's actual exit status after execution begins. Therefore a user program may return a code numerically equal to a compiler class; callers that require phase distinction should use `slug build` followed by direct execution.

## 5. Diagnostics

### Human format

Human diagnostic wording and layout may improve within compiler releases. It MUST identify the relevant error kind/message and source position when known. Cause/suppressed context must be shown for structured errors when relevant.

### JSON format

`--diagnostic-format json` emits newline-delimited JSON objects to stderr. Each object has this compatibility-stable core:

```json
{
  "schema": 1,
  "severity": "error",
  "kind": "parse",
  "message": "...",
  "file": "path/to/file.slg",
  "span": {
    "start": {"line": 1, "column": 1},
    "end": {"line": 1, "column": 2}
  }
}
```

Rules:

- `schema` is integer `1` for this contract;
- line and column numbers are 1-based;
- `severity` is at least `error`, `warning`, or `note`;
- `kind`, `message`, `file`, and `span` are stable core fields;
- additional fields may be added compatibly;
- an unknown added field MUST be ignored by consumers;
- the CLI exits with the ordinary code for the underlying failure.

Tooling SHOULD use compiler APIs/LSP where available rather than scraping human diagnostic text.

## 6. Files and overwrite safety

Commands MUST NOT overwrite a source file implicitly except `slug fmt --write`.

When a command writes a named file, implementations SHOULD write atomically where the host permits it.

Failed transformation/build commands MUST NOT leave a destination file falsely appearing to be successful output. Temporary/intermediate files should be cleaned unless `--keep-c` or a future explicit preservation option requests otherwise.

## 7. Environment and host compiler

The public C-backend compiler recognizes `CC` as the default host-C-compiler override when `--cc` is not supplied.

Bootstrap-only variables such as `SLUG_GC_INTERVAL` and `SLUG_RUNTIME` are implementation/recovery controls and are not ordinary SLUG program semantics. They may remain documented for developers but tooling MUST NOT require them for a normal installed compiler.

## 8. Stability promise

The commands and semantics in sections 1–7 are the Public CLI Contract v1. Compatible compiler 1.x releases may add optional flags/commands but MUST NOT silently change the meaning of an existing valid invocation.

A future incompatible CLI design requires an explicit contract-version change. The language version and CLI contract version are separate.

## Tooling schema-1 extension

The v1 toolchain includes optional, backward-compatible machine-readable commands for editor and language-tool integration. They do not change CLI Contract v1 semantics for existing commands.

### `slug tooling-info`

Prints one compact JSON object to stdout and exits 0. Schema 1 contains the compiler implementation version, language version, CLI-contract version, manifest schema, diagnostic schema, and boolean capability flags for native formatting/crushing/expansion, JSON diagnostics, project discovery, and deterministic local dependencies.

Consumers MUST ignore unknown added fields. Incompatible meaning changes require a new tooling schema value.

### `slug project-info [source-file]`

Prints one compact JSON object to stdout and exits 0. If no project is discoverable, the result is `{"schema":1,"found":false}`; absence of a project is not an error. When found, schema 1 reports the manifest path, project root, project name, manifest entry, resolved entry path, and declared dependency count.

With `source-file`, discovery proceeds upward from that source file. Without it, discovery begins at the current working directory. This command does not parse or compile SLUG source and is intended as a zero-hot-path editor/project handshake.

### `slug tooling-check <logical-path> [--diagnostic-format human|json]`

Reads the root source buffer from stdin, checks it as though it were located at `logical-path`, and preserves that real path for project discovery, importer-relative imports, and `@dep/*` resolution. The command must not overwrite the logical source or create a sibling shadow source file.

### `slug tooling-format <logical-path>`

Reads source from stdin and writes the formatted source to stdout while using `logical-path` only for contextual project/module resolution. It does not mutate the source on disk.

### `slug tooling-locate <logical-path>`

Reads source from stdin and performs the failure-only diagnostic locator. The line protocol begins with `0` when no substantiated failure location exists, or `1` followed by one-based start/end line and Unicode-scalar column fields plus the localized token text. The locator is advisory metadata for an already-failed check; it does not replace schema-1 compiler diagnostics.

A v1 compiler advertising `failure-provenance-v2` may locate lexical, parse/structural, and semantic failures. Consumers must not fabricate a position when the compiler returns none. LSP bridges are responsible for converting Unicode-scalar columns to UTF-16 protocol character offsets.

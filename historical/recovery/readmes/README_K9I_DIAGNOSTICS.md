# K9I — failure-only native diagnostic locations

K9I adds accurate native source locations for parse/structural failures without adding bookkeeping to SLUG's successful ambiguity-parser hot path.

## Architecture

Ordinary `check`, `build`, `run`, code generation, and successful LSP validation use the same parser path as K9H/K9G. The shortest-path parser (`po`) is not instrumented with position maps, counters, or per-candidate span tracking.

Only after an editor/tooling check fails, `slug tooling-locate <logical-path>` performs a second failure-only localization pass over the already-lexable source and its real module/project context. The pass combines delimiter structure with farthest-reachable statement parsing and can descend into malformed balanced blocks. It returns no location for syntactically complete failures that occur later in semantic validation.

The native-backed LSP invokes `tooling-locate` only after `tooling-check` fails. Returned SLUG Unicode-scalar columns are converted to UTF-16 LSP character positions before diagnostics are published.

## Position modes

- `failure-pass-v1`: parse/structural failures localized by the K9I failure-only pass.
- placeholder behavior remains for lexical and semantic failures when K9I cannot honestly derive a parse location.

The LSP never fabricates a source range for a failure category the native compiler cannot localize.

## Safety/performance invariant

Successful compilation does not call the locator. No locator state is updated during successful parsing. This is the explicit replacement for the rejected K9F diagnostic-span experiments that materially slowed self-host compilation.

## Canonical fixed point

K9I fixed-point generated C:

- bytes: 3,294,872
- SHA-256: `bd57b81a755dc5cc123eac19620a2fa8cf6af241c8d1bfce4df2707937eff132`
- Stage-4 vs Stage-5: byte-identical

Permanent K9I-specific gates:

- tooling: 34/34
- LSP: 23/23
- program differential: 129/129 valid + 28/28 rejects

Frozen compatibility gates remain mandatory before release promotion.

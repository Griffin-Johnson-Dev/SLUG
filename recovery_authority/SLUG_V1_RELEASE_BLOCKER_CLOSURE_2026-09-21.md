# SLUG v1 — Release-Blocker Closure & Final Design Pass

Date: 2026-09-21
Baseline: `slug_compiler_v0_3_0a13_v1_member_reads`
Authority: extends `SLUG_V1_LANGUAGE_AUDIT_CHECKPOINT_2026-09-21.md`

This checkpoint does **not** claim the current compiler already implements these rules. It closes the remaining design/runtime questions so implementation can resume against one fixed target.

## A. Closure of the previously listed release blockers

### A1 — Deep/cyclic display and host-stack recursion

**Decision:** remove every fixed display-depth cutoff. Display, structural equality, GC graph walks, and other core traversals over arbitrary user data use explicit iterative worklists. Display uses the literal marker `<cycle>` when traversal encounters a container/object/error already active on the current expansion path. Shared but acyclic substructure is rendered normally again. The marker is diagnostic only; display is not a source serializer.

### A2 — Binary-safe string/file/socket/device writes

**Decision:** SLUG strings become representation-wide length-tracked values. `SlugString` stores `len` plus UTF-8 bytes; an extra trailing zero may exist only as an interoperability sentinel and is never semantic. File writes, socket sends, device writes, `co`, concatenation, equality, membership, numeric conversion, quoting, slicing, and hashing/comparison use `len`, never `strlen`.

Text file reads accept every valid UTF-8 scalar sequence, including U+0000. Embedded NUL is not a reason to reject a text file.

### A3 — OS-boundary NUL handling

**Decision:** a single boundary helper converts a SLUG string to native terminated text only after checking that its `len` bytes contain no embedded NUL. Paths, process argv entries, environment names, host names, device paths, window titles, and similar terminated OS text use that helper and raise a catchable boundary/encoding error on embedded NUL. File/network/device **content** never uses this rule.

### A4 — Arbitrary I/O and graphics limits

**Decision:** remove the historical 16 MiB request caps and 32,768 dimension caps. Host syscall field widths are chunk sizes, not language limits.

- entropy `n`: returns exactly `n` bytes or errors, filling in chunks;
- regular-file handle read `n`: reads up to `n`, chunking until `n`, EOF, or error;
- socket/device receive `n`: performs at-most-`n` receive semantics and may return fewer bytes; a backend may pass a smaller host-maximum chunk to one syscall because short receive is already legal;
- writes/send operations loop over host-sized chunks until all data is written or an error occurs;
- surfaces have no fixed dimension ceiling beyond positive dimensions, checked pixel-count arithmetic, host representability, and actual resources;
- windows/audio/devices validate against the selected backend/device rather than SLUG-invented constants.

Protocol-defined domains remain real domains: TCP/UDP-style ports are 0..65535 because the protocol field is 16-bit.

### A5 — Allocation/capacity overflow

**Decision:** all runtime growth goes through checked helpers equivalent to `size_add`, `size_mul`, and `grow_capacity`. They cover strings, bytes, lists, maps, objects, GC stacks, root stacks, results, diagnostic buffers, process quoting, surfaces, and every other dynamic buffer. Capacity doubling never wraps. Representational size overflow raises catchable `resource`/`range`; actual allocator exhaustion may remain fatal under the v1 OOM rule.

### A6 — Snapshot iteration

**Decision:** source/bounds are evaluated once at loop entry.

- list foreach: shallow snapshot of element values/references;
- map foreach: shallow snapshot of keys in insertion order;
- string/bytes foreach: immutable source plus fixed entry length is sufficient;
- sliced iterable loops iterate the materialized slice/snapshot.

Mutating the original container cannot alter the current loop's visit set. Referenced objects inside the snapshot remain ordinary references and may mutate.

### A7 — Slice normalization

**Decision:** one shared normalization implementation defines list/string/bytes slicing and sliced loops. It implements Python-style half-open start/stop/step behavior mathematically, including omitted bounds, negative bounds, negative step, clamping, and step-zero error. It does not implement normalization by unsafe signed C arithmetic. Slice count is calculated with checked arithmetic before allocation. Frozen-list slices stay frozen.

### A8 — `cv` and embedded NUL

**Decision:** `cv[type,value]` is length-aware and non-trapping. NUL is simply another character unless the conversion grammar forbids it. Therefore `cv['i','12\0']` is false; `@i '12\0'` raises `cast`; `cv['s',bytes]` is true for valid UTF-8 bytes even when those bytes contain NUL.

### A9 — Runtime error taxonomy

**Decision:** `ER` becomes an immutable built-in record with public read-only members:

- `.kind` — canonical lower-case kind string;
- `.message` — human-readable string;
- `.payload` — arbitrary value or `nn`;
- `.cause` — prior `ER` or `nn`;
- `.suppressed` — frozen list of secondary `ER` values.

Stable v1 runtime kinds are: `user`, `type`, `cast`, `range`, `overflow`, `divide`, `index`, `key`, `immutable`, `binding`, `arity`, `state`, `capability`, `io`, `encoding`, and `resource`.

`er x` raises an existing `ER` unchanged or wraps a non-error as `kind='user'`. Bare `er` in a catch rethrows unchanged. If `finally` raises while another error is pending, the new error wins; the old error becomes its cause when possible, otherwise it is appended to `suppressed`.

An uncaught error prints at least kind + message and its cause/suppressed chain before the process exits nonzero. Diagnostic stack/source information may be added without becoming value equality semantics.

### A10 — Capability namespace placement

**Decision:** only the nine audited core builtins remain global. Native capabilities become canonical bundled modules under a reserved `@std/` URI namespace and must be imported with an alias, e.g. `>'@std/fs':FS`. `<:FS` may then be used deliberately for dense local access.

Canonical v1 modules:

- `@std/sys`: `av`, `ev`, `cw`, `pf`, `cp`, `pc`;
- `@std/time`: `tm`, `mt`, `wt`;
- `@std/rand`: `en`;
- `@std/fs`: `fr`, `ft`, `fw`, `fa`, `fe`, `fd`, `fm`, `md`, `rm`, `mv`, `fo`, `hr`, `hw`, `hs`, `hp`, `hf`, `hc`;
- `@std/net`: `so`, `cn`, `bn`, `ls`, `ac`, `sd`, `rc`, `sc`, `gp`;
- `@std/gfx`: `sf`, `px`, `rf`, `dl`, `sb`, `wn`, `wf`, `pe`, `wx`;
- `@std/audio`: `au`, `aq`, `ax`;
- `@std/dev`: `do`, `dv`, `dr`, `dw`, `dx`.

`SY.cp[name]`-style capability query (`cp`) reports whether a named optional host facility is implemented. Importing an `@std` module itself succeeds on supported compiler targets; an unavailable operation raises `capability` rather than disappearing from the module surface.

The `@std/` prefix is resolved from the compiler/runtime installation, never relative to the importing file or current working directory, and participates in normal one-module-instance identity rules.

### A11 — Self-hosting migration

**Decision:** the historical bootstrap remains frozen as evidence, not as the final language definition. The audited-v1 Python/reference compiler is the seed used to build the final compiler written in audited SLUG v1. The resulting compiler rebuilds itself twice. Release requires normalized Stage-2 and Stage-3 emitted compiler artifacts to reach a fixed point and requires differential conformance between the reference compiler and the self-hosted compiler.

### A12 — Audited-v1 release gate

**Decision:** historical tests remain a legacy/bootstrap oracle. A separate v1 conformance suite is the release authority. Public v1.0 is not stamped until every conformance category below is green.

---

# B. Additional blockers discovered by the final pass

## #155 — Parser completeness was limited by more than the 256-path beam

**Finding:** the baseline also contains a 192-state RPN search limit, an 8-value RPN stack ceiling, an 8-result return parser ceiling, and 96/64 call-candidate truncations. Recursive helper structure can additionally inherit Python's recursion limit.

**Resolution:** none of these numbers are language semantics. The v1 parser must be complete for every finite source program that fits real machine resources. Use memoized candidate DAG/packed-forest techniques, deterministic dominance/deduplication, and iterative work queues. Candidate pruning is legal only when it is proven semantically dominated, never because a counter was reached. After normative priorities, multiple valid parses are `AmbiguityError`. Legal source nesting/arity must not depend on Python's recursion limit.

## #156 — Length tracking must replace, not wrap, C-string semantics

**Finding:** fixing only write calls would leave `strcmp`, `strstr`, `strtod` helpers, quotes, concatenation, `by`, `@s`, numeric casts, environment/path utilities, and display still treating NUL as end-of-string.

**Resolution:** the authoritative C representation is conceptually:

`SlugString { heap; size_t len; unsigned char data[len + 1]; }`

`data[len] == 0` is convenience only. Every language operation receives `(data,len)`. Raw C-string helpers may exist only in explicitly validated OS/host boundary adapters.

## #157 — Internal `int`/`int64_t` indexing creates hidden collection ceilings

**Finding:** map/object lookup returns `int`; collection lengths are cast to `int64_t`; `ln` and multiple write-count APIs return signed-only counts.

**Resolution:** collection positions/lengths use `size_t` internally with checked conversion to/from the language's adaptive integer model. Lookup APIs return `(found,size_t index)` or `SIZE_MAX` only when safe, never `int`. `ln` and byte/write counts return `i` through `INT64_MAX`, otherwise `u`. No collection becomes unusable merely because its valid host size exceeds `INT_MAX` or `INT64_MAX`.

## #158 — I/O request size and syscall size are different concepts

**Resolution:** requested lengths are nonnegative SLUG integers. Backends convert them with checked host representability. Host APIs with `int`, `DWORD`, or `ssize_t` length fields are called in legal chunks. A host chunk width must never become a source-language maximum. APIs whose semantics permit short reads/receives remain permitted to return short results.

## #159 — Several remaining constants are backend accidents, not semantic domains

**Finding:** baseline code additionally limits socket backlog to 65535, Windows sleep to one `DWORD` interval, audio to 8 kHz..384 kHz and <=8 channels, and audio submission to one `DWORD` buffer.

**Resolution:**

- listen backlog: any nonnegative integer representable by the backend API; the OS may further clamp it;
- sleep: chunk long waits rather than rejecting durations only because one host call is narrower;
- PCM audio: require positive rate/channels, checked format arithmetic, and let the backend/device accept or reject the requested format; no invented universal 384 kHz/8-channel ceiling;
- large audio buffers: submit frame-aligned host-sized chunks;
- serial baud: unsupported backend/device rates produce `capability`, not a generic fatal failure.

## #160 — C exception propagation must obey `setjmp`/`longjmp` rules

**Finding:** mutable automatic C objects modified after `setjmp` can have indeterminate values after `longjmp`. The baseline stores exception/scope state and potentially promoted SLUG cells in automatic storage reachable across exception edges.

**Resolution:** v1's correctness-first C backend keeps exception frames and mutable unwind/scope metadata in heap/runtime-owned storage. For the initial public release, lexical cells that can be live across a catch edge are heap cells; stack promotion is disabled unless data-flow proves the cell cannot cross a `setjmp`/`longjmp` boundary. No catch path reads an automatic temporary whose value became indeterminate under C's rules. Optimized `-O2/-O3` builds are part of exception conformance testing.

## #161 — Full-range loops must not narrow to signed 64-bit host counters

**Finding:** current repeat/range lowering stores counts/bounds in `int64_t` and increments signed C counters.

**Resolution:** `fl n{}` accepts every nonnegative v1 integer that can be represented by the runtime and has no artificial signed-64 ceiling. Numeric range uses exact mathematical comparison/increment under the v1 `i/u` rules; if either bound carries unsigned provenance, nonnegative values can be represented as `u`, including ranges above `INT64_MAX`. The implementation must not perform signed C overflow while advancing or comparing the iterator.

## #162 — Runtime support code itself needs a C-undefined-behavior rule

**Finding:** helper algorithms can overflow even when SLUG arithmetic is checked (examples include coordinate subtraction/`llabs`, buffer-growth addition, multiplication in format setup, and quoting-count arithmetic).

**Resolution:** runtime/compiler-support arithmetic that depends on user-controlled magnitudes uses checked unsigned math, exact sign/magnitude math, or a wider checked intermediate. C signed overflow, invalid shifts, narrowing before validation, and pointer-size multiplication overflow are forbidden implementation techniques. Release builds run UBSan/ASan where supported in addition to normal optimized builds.

## #163 — Finalizer execution needs an implementation-safe isolation rule

**Resolution:** an object is temporarily rooted while its finalizer runs; its finalized bit is set so it can never finalize twice. Resurrection preserves the object but not a second finalization. A finalizer runs in an isolated runtime exception context. An error escaping a finalizer cannot be caught by an unrelated user catch: during normal execution it is reported as an uncaught finalizer error and terminates after runtime invariants are restored; during orderly shutdown, native-handle cleanup continues best-effort and the process exits failure after diagnostics.

## #164 — OS-originated text must not be silently lossy

**Resolution:** SLUG text is UTF-8/Unicode scalar text. Windows UTF-16 OS text is converted strictly to UTF-8. POSIX argv/environment/directory-entry bytes that are not valid UTF-8 are not silently replaced; a text-returning standard-library operation encountering such data raises `encoding`/`io`. v1's portable filesystem API therefore addresses Unicode/UTF-8 path names; a future bytes-path facility may expose non-UTF-8 POSIX names without weakening SLUG string semantics.

## #165 — Standard-module identity/versioning must be stable

**Resolution:** `@std/...` module URIs are reserved by the language distribution and map to the standard-library version shipped with that compiler's v1 implementation. They do not search the current directory, network, or user package paths. User/package import resolution remains separate. A v1.x compiler may add exports to an explicit standard module only when doing so does not alter already-valid source under the normal namespace ambiguity rules.

## #166 — Float zero and numeric map-key equivalence need canonical treatment

**Resolution:** finite IEEE `+0.0` and `-0.0` compare equal. Because typed identity for value floats is same type + same value, they are also `===`. Numeric map-key equality therefore treats `0`, `0u`, `0.0`, and `-0.0` as one equal key when numeric equality says they are the same mathematical value. Any future hash-map backend must canonicalize numerically equal keys to compatible hashes.

## #167 — Uncaught diagnostics are part of compiler/runtime usability

**Resolution:** a public release may not reduce an uncaught error to `SLUG uncaught error`. It reports the error kind and message, source/function context when available, and cause/suppressed context. Diagnostic formatting is not part of program equality and may improve within v1.x, but the underlying `ER` fields above are stable.

## #168 — Self-hosting proof must not depend on changing the historical oracle

**Resolution:** bootstrap history is immutable. The release proof records hashes for the seed/reference compiler, audited-v1 compiler source, generated C/IR manifests, and the two self-host rebuilds. Rebuilding a historical oracle to make it accept v1 is explicitly forbidden; compatibility is established by the new seed/self-host chain instead.

## #169 — Release/version compatibility must be explicit

**Resolution:** the first public semantics described by these checkpoints is **SLUG language v1.0**. Compiler implementation versions may change independently. `slug --version` reports compiler version; `slug --language-version` reports the language contract. v1.x changes must preserve already-valid v1 source semantics except for clearly documented bug fixes where the old behavior contradicted the v1 specification. Intentional incompatible syntax/semantic changes require a new major language version.

---

# C. Final cross-pass: no remaining unresolved design blockers found

The audit rechecked the following boundaries after A1–A12 and #155–#169:

1. lexer/comments/operators and crushing/expansion;
2. ambiguity resolution and arbitrary parser/search/recursion limits;
3. bindings, scopes, defaults, calls, returns, multi-results, and target-atomic writes;
4. signed/unsigned/float arithmetic, full-range loops, exact comparison, finite floats, and signed zero;
5. stable map keys, insertion order, freezing, sorting, slicing, and mutation during iteration;
6. UTF-8 scalar strings, embedded NUL, bytes, display, numeric text conversion, and OS text boundaries;
7. catchable errors, rethrow, finally supersession, cause/suppression, finalizers, resource lifecycle, and fatal/OOM boundaries;
8. object shape, initialization barriers, overrides/interfaces, privacy, equality, and shared exported state;
9. GC identity, iterative graph traversal, allocation growth, runtime C arithmetic, and setjmp/longjmp correctness;
10. modules, canonical `@std` capability placement, module identity, initialization order, and active namespaces;
11. C backend implementation ABI vs public language ABI;
12. self-host bootstrap/fixed-point proof and release-version compatibility.

**Result:** no known unresolved **language-design or runtime-contract blocker** remains after this pass. This is not a mathematical guarantee that no implementation bug can ever exist; it means the known semantic questions now have explicit answers and the remaining work is implementation + verification against this frozen target.

---

# D. Required v1.0 conformance/release gates

A build may be called the first public SLUG v1.0 release candidate only after all of these pass:

- positive and negative tests for every audited semantic rule;
- parser stress cases that exceed every historical 8/64/96/192/256 cap without semantic truncation;
- ambiguity tests proving ambiguous source errors rather than score-based selection;
- decimal-only source, new comments, exact `//`/`%`, strict `=` and contract-vs-cast tests;
- full `INT64_MIN..UINT64_MAX` arithmetic/comparison/range/index/count boundaries;
- finite-float and `+0.0/-0.0` tests;
- embedded-NUL strings through concat, equality, membership, slice, `co`, bytes conversion, file I/O, socket/device content, and failed OS-boundary conversion;
- deep acyclic and cyclic equality/display/GC tests with no fixed depth cutoff;
- snapshot-iteration mutation tests for lists/maps and sliced loops;
- stable/exception-safe sort tests;
- catchable error-kind tests, nested cause/suppression, rethrow, every `finally` transfer path, and finalizer isolation;
- resource open/close/idempotence/use-after-close tests;
- optimized exception tests (`-O2`/`-O3`) plus sanitizer runs where available;
- checked-allocation/growth boundary tests and no wraparound under fuzzing;
- optimizer-on/off differential execution preserving outputs, errors, effects, identity, and finalizers;
- crush/expand AST+semantic fixed-point tests for the final v1 grammar;
- standard-module import/identity/capability tests;
- clean Windows and Linux builds for whichever targets are claimed supported by the release;
- reference compiler vs self-hosted compiler differential suite;
- self-host Stage-2/Stage-3 normalized fixed point;
- clean build/test from the exact release archive with hashes/manifests regenerated and verified.

Once these gates are green, the remaining step is packaging/documentation rather than another language redesign.

# SLUG v1 Language Audit Checkpoint — 2026-09-21

**Status:** language-design audit closed with no known unresolved semantic contradiction after applying the resolutions below. Compiler implementation is **not** yet compliant with all of these rules.

**Authoritative inputs used for this reconstruction:**

- the uploaded `slug_compiler_v0_3_0a13_v1_member_reads(1).zip`;
- its `README.md`, `SLUG_V0_SNAPSHOT.md`, Stage-2 architecture/history, and v1 checkpoint files through `V1_MEMBER_READS_CHECKPOINT.md`;
- the accepted decisions recoverable from the immediately preceding September 21 SLUG audit discussion.

The exact text of the original numbered items **1–74 is lost**, so this file does **not** pretend to reconstruct their wording. Instead, it records the accepted rules that were recoverable and continues the audit from **#75**. Some #75+ items intentionally revalidate an earlier concern when the repository exposed a deeper interaction.

---

## 1. Recovered v1 decisions that remain authoritative

These are the important design directions recoverable from the lost first pass and from the user's explicit responses.

1. **Hexadecimal integer source is removed from v1.** Ordinary integer source is decimal.
2. **`$` is no longer hexadecimal syntax.** It is an optional decimal-integer boundary marker used only where whitespace-independent dense source needs a hard lexical boundary.
3. **Whitespace remains non-semantic outside strings/comments.** The formatted and crushed forms must therefore agree without depending on spaces.
4. **Comments must move away from `//` and `/*...*/`** because `/` and `*` are executable RPN operators and comments must not appear accidentally after crushing.
5. **No arbitrary hidden semantic resource cap.** A parser beam, fixed input line length, artificial nesting depth, etc. may not change program meaning. Physical host/resource exhaustion is different.
6. **Evaluation order is left-to-right** and must not inherit C's unspecified operand/argument order.
7. **Runtime/program errors that a program can reasonably handle are catchable.** Fatal runtime abort is reserved for genuinely unrecoverable/internal conditions.
8. **Casts convert; contracts validate.** A parameter/binding/return contract must not silently coerce a value into the required type.
9. **`=` is strict update, not implicit declaration.** `:=` remains the value-producing current-scope definition/update operator and may appear inside larger expressions/conditions/loop-related expressions.
10. **`::=` is the immutable-definition form.** It must have precise one-time-definition behavior rather than being another spelling of assignment.
11. **Integer width semantics must be exact and checked.** No silent overflow or routing 64-bit integer decisions through floating point.
12. **`f` / `f64` is the implemented float type.** Other float widths must not pretend to exist until they truly do.
13. **Multiple returns/assignments need explicit, exact rules.** Silent result loss is not acceptable.
14. **The language may reserve syntax/names when needed for long-term grammar stability.** Future features must not reinterpret existing valid source.
15. **OOP, collections, equality, and exception behavior must be made internally sound**, not merely left as “whatever the current C runtime happens to do.”
16. **Two-character named callables remain a core SLUG design goal.** The audit should solve ambiguity around them rather than abandoning the feature unnecessarily.
17. **Stage-2's module-identity preservation and ordered lowering are correct directions** and remain part of v1.
18. **`.slg` / `.slgc` transformation must preserve semantic AST**, with a deterministic expanded form.

---

# 2. Post-74 continuation and full second-pass audit

## Lexing, comments, source encoding, and grammar

### #75 — Hidden 256-path parser beam changes language meaning

**Finding:** the historical/reference parser deliberately keeps only the best 256 statement-sequence candidates. A valid parse can therefore become unreachable solely because more than 256 alternatives score ahead of it.

**Resolution:** v1 has **no semantic ambiguity beam**. Parsing may use pruning internally only when the compiler can prove that pruned states cannot lead to a distinct valid parse. Otherwise it must continue until it can determine the unique parse, report ambiguity, or exhaust real machine resources. Resource exhaustion is a compiler failure, not a different language interpretation.

**Implementation delta:** remove the fixed `len(chosen) < 256` semantic cutoff from the v1 frontend.

### #76 — Old comment delimiters collide with executable operators

**Finding:** `//` and `/*...*/` can be created accidentally when spaces disappear around `/` and `*` RPN operators.

**Resolution:** v1 comments are:

- `## ...` — ordinary line comment;
- `##! ...` — preserved line comment;
- `#* ... *#` — ordinary nested block comment;
- `#*! ... *#` — preserved nested block comment.

`//` and `/*...*/` cease to be comments.

### #77 — Preserved-comment transform behavior was underspecified

**Resolution:** ordinary comments disappear in `.slgc`. Preserved comments survive as source metadata but never enter runtime semantics. A preserved line comment always forces a physical newline after itself in crushed source so it cannot consume following code. Nested preserved block comments retain their text. Comment presence never changes AST identity.

### #78 — Source bytes/newlines/BOM were not fully specified

**Resolution:** SLUG source is strict UTF-8. An optional UTF-8 BOM is accepted only at byte 0 and is non-semantic. LF, CRLF, and CR are all recognized as source newlines and normalized logically. Invalid UTF-8 is a lexical error.

### #79 — Identifier Unicode/normalization could drift between backends

**Resolution:** v1 identifiers are intentionally **ASCII-only**, preserving the compact grammar:

- variables: `a`–`z`;
- classes/interfaces: exactly two ASCII uppercase letters;
- named functions/methods: exactly two ASCII lowercase letters;
- extended identifiers: the existing underscore-separated ASCII alphanumeric form.

Unicode remains fully available in string/comment/path data. Because identifiers are ASCII-only, identifier Unicode normalization/confusable rules are unnecessary in v1.

### #80 — Decimal integer token boundaries need a final rule

**Resolution:** decimal integer literals contain ASCII digits only. `$` is a zero-value **integer terminator**, not part of the numeric value. Thus `10 == 10$`. The formatter/crusher inserts `$` only where adjacent digits would otherwise merge or repartition. `$` after a float or non-integer token is invalid.

Examples retained from the accepted redesign:

```slug
10      ## decimal ten
93-     ## 9 3 -
9$3-    ## 9 3 - with an explicit integer boundary
123+    ## 12 3 + when that partition is required by the expression grammar
123*+   ## 1 2 3 * +
```

### #81 — Float literal grammar and `e` ambiguity

**Finding:** exponent-form source such as `1e3` conflicts directly with SLUG's one-letter variable grammar.

**Resolution:** source float literals **must contain a decimal point**: `.5`, `5.`, `5.25`. Exponent notation is not a source-literal form in v1. String-to-float conversion may accept decimal exponent text because it occurs after lexical parsing. Only finite values are accepted.

### #82 — Parser preference scores must not become semantics

**Resolution:** the language has explicit grammar priorities, not “whatever candidate has the lowest implementation score.” Variable partitions are preferred when they validly satisfy the required expression shape; inferred two-letter calls are used only when the variable interpretation cannot satisfy the grammar. After all normative rules, more than one valid semantic parse is an **AmbiguityError** rather than an arbitrary score choice.

### #83 — Two-character callable inference must remain monotonic

**Resolution:** exactly two-lowercase named callables remain. Adding a function/import/builtin may make previously invalid text valid, but may **not silently change the meaning of already-valid source**. When a variable partition is already valid, it keeps priority. `!ab...` and explicit `ab[...]` remain escape hatches to force the callable interpretation. Variadic calls remain explicit-pack only.

### #84 — Growing builtin registry can consume grammar and names forever

**Finding:** the historical registry grew to 59 global two-letter names and earlier worked around grammar drift by making newer builtins explicit-pack-only.

**Resolution:** v1 freezes the global core builtin set at exactly **nine** names: `co`, `ci`, `ty`, `cv`, `in`, `iv`, `ln`, `sl`, and `by`. No later v1.x release adds another implicit global builtin. OS, graphics, audio, networking, device, and future facilities move behind explicit standard-library/module namespaces. These nine core spellings are reserved and cannot be overwritten by root user definitions. This preserves two-letter callable space and grammar monotonicity.

### #85 — Active namespace fallback can silently capture a root name

**Finding:** historical active namespace lookup chooses the active module first and root only when absent. If a later version of a dependency exports a previously absent name, unchanged source can silently bind differently.

**Resolution:** if a bare name is simultaneously valid in the selected active namespace and the root/current namespace, compilation reports a name ambiguity. Use explicit `MA.name` for the module or backtick root escape for the root meaning. Explicit qualification never falls back.

### #86 — Module identity and initialization order must be normative

**Resolution:** each canonical imported source module is instantiated exactly once per program. Import cycles are compile-time errors in v1. Dependencies initialize before importers; sibling dependency initialization follows source import order. Module-global executable statements execute in source order. Diamond imports share one module state instance. Canonicalization must prevent two syntactic paths to the same source from silently producing duplicate module instances.

---

## Bindings, scope, calls, returns, and evaluation

### #87 — `=` previously created missing bindings

**Resolution:** `=` is **statement-only, non-value-producing, update-only**. It updates the nearest existing mutable binding. If none exists, compilation fails when provable; otherwise runtime raises a catchable binding error. It never creates a binding.

### #88 — `:=` inside conditions/headers needs a scope rule

**Resolution:** `:=` defines or replaces a binding in the **current lexical scope at the textual location of the expression** and yields the assigned value. Conditions and loop source/bound expressions are evaluated in the enclosing scope before the body block exists, so a `:=` there affects that enclosing scope. A `:=` written inside `{...}` belongs to that block scope and shadows an outer binding.

### #89 — `::=` needs one-time-definition semantics

**Resolution:** `::=` creates a new immutable binding in the current scope and yields its value. Re-defining an already existing name in that same scope with `::=` is an error. The binding cannot later be written through any aliasing spelling of that binding.

### #90 — Multiple assignment could partially update or ignore results

**Resolution:** assignment is target-atomic. Evaluate the RHS exactly once, left-to-right internally. Preflight target existence, mutability, contracts, and result arity before committing any target write. Then commit as one language-level assignment operation.

- one result may broadcast to multiple targets;
- multiple results must exactly match the target count;
- extra results are **not ignored**;
- too few or too many multi-results is an error;
- if validation fails, no assignment target is changed.

External side effects that occurred while evaluating the RHS are not rolled back.

### #91 — Function result count could vary by path

**Resolution:** every callable has one result **arity**. If no return contract is written, result count is inferred from reachable `rv`/fallthrough paths. All reachable paths must agree. Fallthrough is zero-result. A declared return-contract list fixes the exact result count. Result *types* may remain dynamic when unconstrained, but count may not vary per execution path.

### #92 — Multi-return values in ordinary expressions were ambiguous

**Resolution:** an N>1 return can be consumed only by a multi-target assignment, directly forwarded by a compatible multi-return `rv`, or discarded by using the call as a statement. It cannot silently collapse to its first value in an arithmetic operand, single argument, condition, index, etc.

### #93 — Default argument timing/dependencies need exact semantics

**Resolution:** defaults are evaluated at **call time**, left-to-right, after earlier explicit/defaulted parameters have been bound. A default may refer to earlier parameters and captured/module state but not to a later parameter. `xx` means “use this parameter's declared default” only inside an actual argument position. It is an error for a required parameter or anywhere outside call-argument handling.

### #94 — Variadic inference could make dense calls open-ended

**Resolution:** variadic named functions/lambdas require explicit `[...]` argument packs. The variadic tail is a fresh mutable list for each call. Fixed-arity/defaulted callables may use dense inference only where #82/#83 produce one normative parse.

### #95 — Left-to-right evaluation must cover every composite construct

**Resolution:** left-to-right applies to function/method arguments, RPN operands as they become executable, list items, map key then value pairs, assignment RHSs, receiver/index evaluation, interpolated string expressions, constructor arguments, defaults, comparisons, and boolean atoms. `+`/`/` in logic mode short-circuit left-to-right. Optimizers must preserve this observable order.

---

## Types, casts, integers, floats, operators

### #96 — Contracts and casts were still conflated in code generation

**Resolution:**

- a **cast** (`@...`) performs an explicit checked conversion and returns the converted value;
- a **contract** attached to a binding/parameter/return validates the incoming value and rejects a mismatch; it does **not** convert it.

This applies equally at function entry, constructor entry, assignment, exported-state writes, and return boundaries.

### #97 — Float width syntax advertised unimplemented widths

**Finding:** the current parser accepts `f16/f32/f64/f128` type descriptors while the runtime stores them all as C `double`/binary64.

**Resolution:** v1 implements only `f` and `f64`, both IEEE-754 binary64. `f16`, `f32`, and `f128` are rejected/reserved until separately implemented with real semantics.

### #98 — Boolean values are silently treated as numbers in the runtime

**Resolution:** Boolean is not an implicit numeric type. Arithmetic, numeric ordering, indexing, counts, sizes, and byte values reject Boolean unless the user explicitly casts it. Explicit `@i/@u/@f` conversion of Boolean may produce 0/1 or 0.0/1.0. `@b` remains truthiness conversion.

### #99 — Signed/unsigned adaptive integer result rules were sticky and surprising

**Resolution:** `i`/`u` are exact 64-bit carrier categories with deterministic checked promotion, never wraparound arithmetic. Operators first compute the mathematical integer result, then apply this matrix:

- `i` with `i` keeps an `i` result and raises `OverflowError` if it leaves `INT64_MIN..INT64_MAX`;
- when at least one operand is `u`, a nonnegative result is `u` through `UINT64_MAX`; a negative result becomes `i` if representable; otherwise it overflows;
- unary negation produces `i` when the mathematical result fits signed 64-bit.

This preserves explicit unsigned provenance without introducing wrapping, while still allowing exact negative subtraction from values that involved an unsigned carrier. A binding/parameter/return `@u*` contract still rejects a negative `i` at that boundary.

Decimal integer literals use `i` when they fit signed 64-bit, otherwise `u` through `UINT64_MAX`; larger literals are compile-time range errors.

### #100 — `@i(a/b)` is not an exact integer-quotient operator

**Finding:** true division converts to binary64, so casting its rounded result cannot produce exact 64-bit integer quotient semantics.

**Resolution:** because comments no longer consume `//`, v1 assigns **`//` to exact integer quotient** in RPN. It accepts integer operands, divides exactly with truncation toward zero, and raises on division by zero or when the exact result violates the integer promotion/range rules in #99. `/` remains true division to `f64`.

### #101 — Remainder must be tied to quotient semantics

**Resolution:** `%` accepts integer operands and is defined by:

`a == (a // b) * b + (a % b)`

with `//` truncating toward zero. The remainder therefore has the dividend's sign (or zero). Division/remainder by zero raises a catchable numeric error.

### #102 — Float operations can currently produce NaN/Infinity

**Resolution:** SLUG v1 float values are finite binary64 values only. Float literals, casts, `/`, negative-exponent `^`, and other float-producing operations must reject non-finite results with a catchable numeric/range error. `0^0 == 1` remains. Zero to a negative exponent errors. A real-domain failure such as a negative base to a non-integral exponent errors rather than creating NaN.

### #103 — Mixed integer/float equality/order currently loses 64-bit precision

**Resolution:** comparisons between `i/u` and `f64` are mathematical/exact with respect to the represented binary64 value; integer operands are never first rounded to `double` merely to compare. Equality is true only when the finite float represents exactly the same integer value. Ordering is likewise exact.

### #104 — Index/count APIs silently truncate floats

**Finding:** the current `sv_int_num` path accepts floats and C-casts them for indexes/slice bounds and other integer positions.

**Resolution:** indexes, slice bounds/steps, repeat counts, lengths requested from I/O, ports, dimensions, and other integral quantities require integer values (`i/u`) unless a specific API documents a different numeric domain. Explicit casts are required to convert floats.

### #105 — Text-to-number conversion needed a stable grammar

**Resolution:** explicit numeric casts from strings trim ASCII whitespace, allow an optional leading sign, and otherwise require the entire string to match the target numeric grammar. Integer casts accept decimal integer text only. Float casts may additionally accept decimal exponent notation. Float-to-integer casts truncate toward zero after finite/range validation. No numeric cast wraps.

### #106 — `==` and `===` disagreed on what is a value

**Resolution:**

- `==` / `!=` are value/structural equality;
- `===` / `!==` are **typed identity**.

For value types (`nn`, Boolean, `i`, `u`, `f`, string, bytes), `===` means same runtime type and same value. For reference types (list, map, object, callable, error, resource handles), it means the same reference. Consequently `1 == 1.0` may be true while `1 === 1.0` is false; equal independently-created strings/bytes are `===` when their type and contents match.

### #107 — Cyclic equality needs an alias-topology rule

**Resolution:** structural `==` is coinductive graph-value equality and terminates on cycles. Internal sharing topology is not itself a value difference: a shared equal substructure and two separately allocated equal copies may compare equal. Object structural equality additionally requires the same dynamic class. `===` remains the tool for reference-sharing questions.

---

## Collections and data structures

### #108 — Arbitrary mutable map keys make key equality unstable

**Finding:** historical maps permit any structurally comparable value as a key. Mutating a list/map/object after insertion can change whether it equals another key, making lookup semantics unstable and blocking a sound hash-map implementation.

**Resolution:** v1 map keys are restricted to stable value types: `nn`, Boolean, integer, finite float, string, and bytes. Lists, maps, objects, callables, errors, and resource handles are not map keys, even if a collection is frozen. Numeric key equality follows `==`, so numerically equal `i/u/f` forms identify the same key.

### #109 — Duplicate keys and iteration order were not fully specified

**Resolution:** duplicate-equal keys in a map literal are an error rather than “last entry wins.” `m[k]:=v` intentionally updates an existing equal key or inserts a new key. Maps preserve insertion order for iteration and display; updating an existing key does not move it.

### #110 — Frozen collection semantics could be read as transitive

**Resolution:** `@[...]` is a **shallow container freeze**. It prevents mutation of that list/map container but does not recursively freeze referenced children. A list slice preserves the source list's frozen/mutable status. `::=` still freezes only a binding, independently of the value's mutability.

### #111 — Resource truthiness changes after close

**Finding:** current file/socket/window/audio/device truthiness depends on the handle's open/closed state, while other reference types are always truthy.

**Resolution:** truthiness is based on value category/value, not mutable resource state. Falsey values are exactly: `nn`, false, numeric zero, empty string, empty bytes, empty list, and empty map. Every object, callable, error, and non-null resource reference is truthy even when closed. Operating on a closed handle raises a catchable state error.

### #112 — Ordering domain was partly inherited from C helpers

**Resolution:** `< <= > >=` are defined only for:

- numeric values (`i/u/f`) using exact mixed comparison;
- strings by Unicode scalar-value sequence;
- bytes lexicographically by unsigned byte sequence.

Boolean is not numeric ordering. Collections, objects, callables, errors, and resources are unordered unless future explicit comparators are introduced.

### #113 — In-place sort can partially mutate before an error

**Resolution:** `sl` is stable and exception-safe. It sorts a mutable list according to #112. If any required comparison is invalid, the original list remains unchanged. Implementations may sort a temporary ordering/copy and commit only after success. Frozen lists reject sorting.

### #114 — String `+` currently implicitly stringifies arbitrary values

**Resolution:** `+` does not perform hidden string conversion. It means:

- numeric addition for numeric operands;
- string concatenation only for string + string;
- bytes concatenation only for bytes + bytes.

Other combinations raise a catchable type error. Use interpolation or explicit `@s` conversion for formatting.

### #115 — Strings are C-NUL-terminated internally and cannot represent U+0000

**Resolution:** a SLUG string is a length-tracked sequence of valid UTF-8 encoding Unicode scalar values and **may contain U+0000**. Runtime storage/APIs must carry length explicitly rather than using `strlen` as language semantics. Bytes remain arbitrary binary data.

### #116 — Unknown string escapes silently lose the backslash

**Resolution:** unknown escapes are lexical errors. v1 defines at least `\n`, `\r`, `\t`, `\0`, `\\`, `\'`, `\"`, `\{`, and `\}`. Unicode characters may be written directly in UTF-8 source; v1 does not require a separate `\uXXXX` escape to represent ordinary Unicode.

### #117 — Unicode normalization policy was unstated

**Resolution:** SLUG does **no implicit Unicode normalization**. Strings compare/index by their actual Unicode scalar sequence. NFC and NFD spellings can therefore differ unless user/library code normalizes them explicitly.

### #118 — String index/slice unit is fixed at Unicode scalar value

**Resolution:** `ln[string]`, direct indexing, iteration, and slicing operate on Unicode scalar values/code points, not UTF-8 bytes and not grapheme clusters. Indexing returns a one-scalar string. This is backend-independent.

### #119 — Intended formatted strings lacked exact semantics

**Resolution:** the intended `{...}` formatting is retained. Unescaped `{expression}` inside a string evaluates one SLUG value expression, left-to-right with other interpolations, and inserts the result of explicit `@s` conversion. `\{` / `\}` produce literal braces. Interpolation may not change surrounding lexical scope except through normal explicit expression side effects such as `:=`; those effects obey ordinary evaluation order. The formatter must preserve equivalent interpolation boundaries.

### #120 — `ci` has a 4,096-byte hidden cap and value-sensitive return type

**Finding:** the current runtime uses `char buf[4096]` and auto-parses decimal-looking input into `i/u/f`. An empty line and EOF are also not cleanly distinct.

**Resolution:** `ci[]` / `ci[prompt]` reads one logical input line with dynamic growth limited only by real available resources. It returns the line as a **string**, never implicit numeric inference. One terminal newline sequence is removed. A genuine EOF before any bytes returns `nn`; a blank line returns `''`. The optional prompt must be a string (use explicit formatting/conversion otherwise). Numeric input uses explicit casts.

### #121 — Display/stringification has an artificial depth-32 cutoff

**Finding:** current list/map rendering becomes `[...]` / `[:...]` after depth 32.

**Resolution:** there is no fixed display depth limit. Rendering is cycle-aware. A cycle is represented with deterministic cycle/back-reference markers instead of infinite expansion; deep acyclic data renders completely subject only to real resource availability. Rendering is diagnostic/display syntax, not promised as a source serializer.

### #122 — Removing the depth cutoff still leaves recursive host-stack limits

**Resolution:** core traversals over arbitrary user data that are expected to handle deep structures—structural equality, collection display/stringification, GC marking, and similar graph walks—use iterative worklists/stacks where practical rather than an arbitrary C/Python recursion depth. Ordinary user function recursion may still consume the target platform's call stack; that is an execution resource, not a fixed SLUG semantic cap.

### #123 — Collection mutation during `fl` iteration was unspecified

**Resolution:** foreach/sliced-iterable loops iterate a **snapshot of the source sequence/keys selected at loop entry**. Mutations to the original container during the loop do not add/remove visits from that loop's already-selected iteration set. Values/references inside the snapshot remain normal references and may themselves mutate.

### #124 — Indexed `=` / `:=` need category-specific creation rules

**Resolution:**

- list `x[i]=v` and `x[i]:=v` both require an existing in-range element; neither auto-grows a list; `:=` is value-producing while `=` is statement update;
- map `m[k]=v` requires an existing key;
- map `m[k]:=v` inserts or updates and yields `v`;
- string/bytes indexed mutation is rejected;
- indexed `::=` remains invalid because immutability is a binding/declared-field/container property, not a one-element binding declaration.

### #125 — Negative-step slice behavior needs one portable definition

**Resolution:** list/string/bytes slices use Python-style half-open normalization for omitted/negative start, stop, and positive/negative integer step. Step zero errors. Direct indexes error when out of range; slices clamp. List slicing preserves frozen state; strings/bytes remain immutable.

### #126 — Bytes conversions need to remain binary-safe after string repair

**Resolution:** bytes length/index/slice/iteration are byte-based. Byte indexing yields an unsigned integer 0..255. `by[string]` yields the exact UTF-8 bytes including embedded NUL. `@s bytes` decodes only valid UTF-8 and may produce strings containing U+0000; invalid UTF-8 raises a catchable conversion error. No C-string assumption is allowed at this boundary.

---

## Exceptions, errors, cleanup, and resources

### #127 — Runtime failures currently collapse into fatal `sv_fail`

**Finding:** the Stage-2 runtime contains hundreds of `sv_fail` call sites, including division-by-zero, range, type, missing-key, frozen-mutation, I/O, and closed-resource failures that programs should be able to catch.

**Resolution:** ordinary program/runtime failures raise catchable `ER` values. v1 gives runtime errors a stable kind plus message/payload so different failures can be distinguished after `cae`. Recommended stable kinds include type, cast, range, overflow, divide, index, key, immutable, binding, arity, state, capability, and I/O categories. User `er value` creates/raises a user error wrapping that payload.

### #128 — Raise/rethrow behavior needs a precise distinction

**Resolution:** `er x` raises `x`; a non-error value is wrapped as a user `ER`. Bare `er` inside an active catch rethrows the currently caught error unchanged. Bare `er` elsewhere is a compile-time/context error. Catch-without-binding catches any catchable error; `cae` binds the actual error object.

### #129 — `finally` overriding an in-flight transfer/error was not fully specified

**Resolution:** `fn` runs exactly once on normal completion, catchable error propagation, `rv`, `bl`, and `cl`. If `fn` itself performs a control transfer, that new transfer supersedes the pending one. If it raises while another error is pending, the new error propagates and the previous error is retained as its cause/suppressed context rather than silently discarded.

### #130 — Fatal and catchable failures need a hard boundary

**Resolution:** syntax/semantic compile errors never become runtime catches. At runtime, type/range/overflow/index/key/immutability/I/O/capability/state/etc. are catchable. Out-of-memory, corrupted runtime invariants, impossible internal state, or unrecoverable host process failure may terminate without a language catch. The implementation must not use the fatal path merely because it is convenient.

### #131 — User destructors have nondeterministic GC timing

**Resolution:** `~-{...}` is formally a **finalizer**, not a deterministic RAII destructor. It runs at most once after an object becomes unreachable or during orderly runtime shutdown, with child-class finalizer before parent-class finalizer. Exact collection time/order among unrelated objects is unspecified. Resurrection remains allowed once; a finalized resurrected object is never finalized a second time. Correct programs must use explicit cleanup/`tr...fn` for deterministic external-resource release.

An uncaught error escaping a finalizer is treated as an unhandled finalizer error; it cannot jump into an unrelated ordinary catch frame. Runtime/library finalizers for handles remain best-effort fallback cleanup.

### #132 — Resource close/truth/use-after-close rules were inconsistent

**Resolution:** explicit close is idempotent for standard handles. GC/shutdown auto-close is fallback only. A closed handle remains a valid reference value and stays truthy; operations requiring an open resource raise catchable `StateError`. Equality/identity of resource handles is reference identity.

### #133 — Length-tracked strings create OS-boundary NUL questions

**Resolution:** SLUG strings may contain NUL, but an OS API whose native contract forbids embedded NUL (paths, argv entries, environment names, etc.) validates and rejects such input with a catchable boundary error. File/network **contents** remain length-tracked and may freely contain NUL. This keeps language text semantics independent from C/OS string conventions.

---

## OOP, interfaces, initialization, modules

### #134 — Arbitrary external field creation undermines class shape/privacy

**Resolution:** class instance/static field declarations belong to the class implementation. `:=`/`::=` may define current-instance/current-class fields in the appropriate class construction/declaration context. External `obj.x:=...` does not invent an undeclared field on one instance; external code may only update an existing public mutable field with `=`. This makes typos diagnosable and permits stable object layouts later.

### #135 — Parent construction and `self` use need an initialization barrier

**Resolution:** a child whose parent needs construction arguments must perform `^^[...]` exactly once before reading/writing inherited instance state or dispatching instance methods on the partially constructed object. If every required parent parameter has a default, the compiler may insert the zero-explicit-argument parent construction automatically. Parent construction completes before child-field initialization proceeds.

### #136 — Override/interface compatibility needs a sound v1 rule

**Resolution:** v1 uses **invariant callable shape/contracts for overrides**: same fixed/variadic shape, compatible parameter count/default availability, and the same declared contract positions/result count. This deliberately avoids unsound ad-hoc variance in a dynamic language. A class must supply every required interface method. Conflicting inherited interface defaults require an explicit class override.

### #137 — Private-member scope must not leak through inheritance/qualification

**Resolution:** private fields/methods/statics are accessible only from the declaring class's implementation. Subclasses do not gain direct access merely through inheritance; they interact through protected/public behavior (v1 has no separate protected access level). Aliasing, active namespaces, root escape, or imported qualification cannot bypass privacy.

### #138 — Object structural equality needs a field set rule

**Resolution:** two objects can be `==` only if they have the same dynamic class and the same declared instance-field set with structurally equal values, including private/immutable fields. Static fields, methods, and finalizer state are not part of object value equality. `===` is reference identity.

### #139 — Reads before initialization/definition were not normative

**Resolution:** mutable/immutable value bindings have a temporal initialization rule: a value may not be read before its defining initializer has completed. Module/global executable bindings initialize in source order. Named functions/classes/interfaces are declaration-hoisted for recursion/forward reference; ordinary value bindings are not magical preinitialized `nn` cells. Similar rules apply to static fields and object fields during construction.

### #140 — Exported shared state writes must obey the same assignment model

**Resolution:** external writes to exported mutable module state use strict existing-binding update, contract validation without coercion, left-to-right RHS evaluation, and target atomicity. Exported immutable bindings cannot be written. All import/alias/active-namespace paths refer to the same linked state cell.

---

## Source transforms, compiler, optimizer, lifetime, future boundaries

### #141 — Crush/expand “reversible” needed a precise promise

**Resolution:** reversibility is **semantic/canonical**, not byte-for-byte recovery of the author's whitespace and ordinary comments:

- `parse(crush(s))` has the same semantic AST as `parse(s)`;
- `expand(crush(s))` is a canonical formatted representation of that AST;
- `crush(expand(crush(s)))` is stable/canonical;
- ordinary comments may disappear; preserved comments survive according to #77.

Crushing must not depend on hidden parser caps or heuristics. Future language versions may not reinterpret valid v1 source; any genuinely breaking grammar change requires an explicit language-version boundary rather than silent drift.

### #142 — Optimizer legality must include errors, order, identity, and finalizers

**Resolution:** optimization obeys an as-if rule preserving left-to-right observable effects, catchable error kind/timing where observable, I/O ordering, `===` identity for reference types, module/shared-state effects, and finalizer constraints. An allocation may disappear only when its identity/finalization is proven unobservable. Contracts and casts may not be reordered across side effects if doing so changes which effect/error occurs first.

### #143 — GC is the semantic fallback; object identity must stay stable

**Resolution:** v1 source has no manual ownership requirement. Reachability tracing remains the semantic fallback; stack promotion/ref-count/move specialization are implementation optimizations. Reference identity is stable for a value's lifetime regardless of relocation/optimization. Cycles are collectable. GC timing is non-semantic except within the explicitly weak finalizer guarantee in #131.

### #144 — Concurrency has no memory model yet

**Resolution:** v1 is explicitly a **single-language-thread execution model**. No source-level threads/atomics/data-race semantics are implied by the native backend. Blocking I/O blocks that execution thread. A future concurrency feature must define its own memory/atomic/callback model instead of inheriting accidental C behavior.

### #145 — C backend representation must not become SLUG's public ABI by accident

**Resolution:** generated C/tag layouts/runtime structs are implementation details, not a stable source-level FFI ABI. v1 has no general source-level foreign-function ABI promise. Future FFI must be an explicit typed facility. `emit-c` is a compiler output format, not permission for programs to depend on internal `SlugValue` layout.

### #146 — Platform-only capabilities need one failure model

**Resolution:** unsupported window/audio/device/platform operations raise catchable `CapabilityError` (or an equivalent stable runtime kind). They never silently emulate a different behavior. Portable library code can catch/query capability availability.

### #147 — Dynamic allocation growth can integer-overflow before OOM

**Resolution:** list/map/string/bytes/buffer capacity arithmetic is checked. Size/capacity multiplication/addition overflow is a resource/range failure, not wrapped allocation size. There is no fixed language collection-size limit below the platform's representable/resource limits.

### #148 — Function recursion should not gain an arbitrary SLUG counter

**Resolution:** v1 specifies no artificial recursion-depth counter. Native call-stack exhaustion or equivalent process resource exhaustion may terminate as a resource failure, comparable to a systems language such as C. Implementations are free to use heap/segmented frames later but may not silently change ordinary recursion meaning at a small fixed number.

### #149 — Length/count results should not be artificially signed-64-only

**Resolution:** `ln` and byte/count/position APIs return an exact adaptive integer representable by v1's integer carrier. Implementations must not overflow a signed `i64` merely because an underlying size is a valid `u64`. APIs still raise when a physical host value exceeds the language's `UINT64_MAX` maximum.

### #150 — Standard-library placement is part of grammar stability

**Resolution:** the low-level OS/network/graphics/audio/device primitives currently implemented as dozens of global two-letter builtins are treated as **standard runtime/library capabilities**, not permission to reserve ever more global callable names. The final v1 packaging should expose them through stable explicit modules/namespaces while keeping the global core registry frozen.

### #151 — `ty` / `cv` need a contract-vs-conversion distinction

**Resolution:** `ty[x]` reports the value's canonical runtime kind/carrier (for objects including class identity as appropriate). `cv[type,value]` answers whether the explicit cast/conversion to that type would succeed; it does **not** mean “already satisfies this binding contract.” Contract satisfaction is a separate compiler/runtime validation concept. Dynamic cast type strings accept only actually implemented conversion targets.

### #152 — Atomic assignment cannot imply transactional external effects

**Resolution:** target writes are atomic as stated in #90, but evaluating an RHS can perform I/O, mutate referenced objects, call functions, or otherwise create effects. Those effects are not rolled back if later target validation fails. Compiler diagnostics/documentation must use “target-atomic assignment,” not imply general transactions.

### #153 — Integral repeat/range boundary behavior needs a final rule

**Resolution:** counted `fl n{}` requires a nonnegative integer count; negative count raises a range error rather than silently doing zero iterations. Numeric range `fl i a b{}` is start-inclusive/stop-exclusive with implicit +1; if `a >= b` it executes zero times. Iterable sliced loops use the same normalized slice semantics as #125. Source/bounds are evaluated once at loop entry; a `wl` condition is re-evaluated before each iteration.


### #154 — String quote syntax was broader than the intended language

**Finding:** the historical lexer accepts both single- and double-quoted strings, while the intended SLUG surface uses single-quoted strings. Keeping both spends grammar/escape surface without adding expressive power.

**Resolution:** v1 source strings are **single-quoted only**. Double quote is reserved for possible future syntax and is a lexical error in ordinary v1 source. A literal single quote inside a string uses `\'`.

---

# 3. Cross-feature interaction pass

The following interactions were explicitly rechecked after the #75–#154 resolutions.

1. **Comments ↔ integer quotient:** moving comments from `//` makes `//` available as an unambiguous exact integer-quotient operator, eliminating the old lossy `@i(a/b)` workaround.
2. **Decimal integers ↔ class names:** deleting A–F hexadecimal source removes the worst historical `ABA$` class-vs-hex ambiguity entirely.
3. **`$` ↔ crushing:** `$` now has exactly one lexical job—decimal integer separation—so the formatter can insert it mechanically without changing numeric base/value.
4. **Two-letter callables ↔ future builtins:** var-first normative parsing plus a frozen core registry prevents future library growth from changing old valid source.
5. **Active namespace ↔ dependency evolution:** collision-as-error prevents a newly exported dependency name from silently stealing a root lookup.
6. **Contracts ↔ optimizer:** validation (not conversion) lets optimization reason about a stable incoming value while explicit casts remain visible effect/trap boundaries.
7. **Adaptive integers ↔ exact comparisons:** mathematical integer result selection and non-floating mixed comparisons remove the signed/unsigned/float precision traps.
8. **Finite floats ↔ map keys:** excluding NaN/Infinity and using exact numeric equality makes numeric key equality stable enough for a future hash-map backend.
9. **Typed identity ↔ optimization:** strings/bytes have value identity rather than allocation identity, allowing safe interning/CSE without making `===` backend-dependent.
10. **Stable map keys ↔ structural equality:** mutable graph objects cannot invalidate key equivalence after insertion.
11. **Shallow freeze ↔ map keys:** freezing a list/map does not magically make it a key; this avoids recursive/hash/cycle ambiguity.
12. **Length-tracked strings ↔ OS APIs:** strings can contain NUL internally while boundary APIs explicitly reject NUL only where the operating system requires it.
13. **`ci` ↔ casts/contracts:** input always arrives as text (or EOF `nn`), so numeric conversion is explicit and no binding type changes merely because a user typed different characters.
14. **Cycle-aware display ↔ no hidden limits:** cyclic values terminate through explicit cycle markers; acyclic values no longer truncate at arbitrary depth 32.
15. **Catchable runtime errors ↔ `finally`:** errors raised by numeric/container/I/O operations now participate in the same unwinding guarantees as user `er`.
16. **Target-atomic assignment ↔ effects:** assignment cannot partially update destinations, while the language remains honest that arbitrary function/I/O side effects are not transactional.
17. **Finalizers ↔ optimizer/GC:** finalizers are deliberately weak/nondeterministic, preventing ordinary program correctness from depending on a precise collection point that optimization could change.
18. **Snapshot iteration ↔ collection mutation:** loop visit sets stay deterministic without banning useful mutation of the underlying structures.
19. **Class shape ↔ privacy/layout:** disallowing one-off external field creation makes privacy checks meaningful and leaves room for optimized object layouts.
20. **Single-threaded v1 ↔ shared state:** module/export/collection operations do not need an accidental data-race model; concurrency can be designed deliberately later.

No contradiction was found among these chosen rules in this pass.

---

# 4. Concrete mismatches in the uploaded v0.3.0a13 project

The uploaded project is valuable and internally coherent as a recovery/oracle checkpoint, but it is **not yet the implementation of this final audited v1 contract**. The following are known mismatches, not speculative concerns:

- historical hex parsing/class-vs-hex logic is still present;
- old `//` / `/*...*/` comments are still lexed;
- parser still has the 256-path beam;
- `ci` still has a 4,096-byte buffer and implicit scalar inference;
- display still truncates lists/maps after nesting depth 32;
- runtime strings rely heavily on NUL termination / `strlen` and reject embedded NUL in bytes→string conversion;
- the runtime treats Boolean as numeric in arithmetic/conversion/comparison helpers;
- mixed integer/float equality/order currently routes through `double` in cases that can lose `u64/i64` exactness;
- `===` currently uses allocation identity for string/bytes rather than typed value identity;
- maps currently admit mutable/reference keys through structural lookup;
- closed resource handles currently become falsey;
- many ordinary runtime errors call fatal `sv_fail` rather than raise a catchable error;
- `@i(a/b)` remains the historical integer-quotient approach;
- multi-result assignment still tolerates extra returned values;
- historical snapshot semantics still allow `=` to create a binding when none exists;
- float type parsing accepts widths that the runtime does not truly implement;
- string `+` currently performs implicit stringification when either operand is a string;
- numeric position helpers currently accept/truncate float values;
- `ci` EOF is not distinct from an empty input line;
- user finalizers/destructors still need the audited error/timing contract enforced.

These are the primary implementation targets before calling the compiler language-complete against this audit.

---

# 5. Evidence/checkpoint health from the uploaded tree

The repository itself records the following already-certified recovery state at `v0.3.0a13`:

- v1 member-read checkpoint built on earlier expression/program/semantic differential milestones;
- Stage-2 explicitly preserves module identity;
- Stage-2 explicitly lowers expression evaluation left-to-right;
- v1 type/input unit suite in this environment: **13/13 PASS**;
- the failed attempt to run the standalone expression differential was environmental/build-state related (missing native `build/v1/expr_cli` probe), not evidence of a semantic test failure.

The old frozen reference remains useful as an oracle for syntax/features that have not yet been deliberately changed by v1, but it must **not** override the audited v1 decisions above when they conflict.

---

# 6. Audit coverage matrix

| Area | Second-pass status |
|---|---|
| Lexing / comments / whitespace | Closed |
| Integer / float literal grammar | Closed |
| RPN arithmetic / quotient / remainder / exponent | Closed |
| Boolean logic / short circuit / truthiness | Closed |
| Equality / identity / ordering | Closed |
| Variables / scope / assignment / immutability | Closed |
| Functions / defaults / variadics / closures | Closed |
| Return arity / multi-return / multi-assignment | Closed |
| Control flow / loops / break / continue | Closed |
| Exceptions / catch / rethrow / finally | Closed |
| Lists / maps / bytes / strings / slicing | Closed |
| Map keys / order / freezing / mutation during iteration | Closed |
| Unicode / NUL / console input / display | Closed |
| Classes / fields / inheritance / privacy | Closed |
| Interfaces / override compatibility | Closed |
| Finalization / GC / resource handles | Closed |
| Imports / modules / active namespaces / shared state | Closed |
| `.slg` / `.slgc` crush/expand guarantees | Closed |
| Evaluation order / optimizer legality | Closed |
| Resource-limit policy | Closed |
| Native C backend ABI leakage | Closed |
| Platform capability failure model | Closed |
| Concurrency | Explicitly out of v1; single-threaded model defined |
| General source-level FFI | Explicitly out of v1; no accidental ABI promise |

---

# 7. Final audit conclusion

After reconstructing the recoverable decisions, inspecting the v0.3.0a13 repository, and running a second feature-by-feature plus cross-feature audit, **there is no known unresolved v1 language-semantic issue in this checkpoint**. Every issue found in this pass has a selected resolution above, and future concurrency/FFI are explicitly scoped out rather than left undefined.

That is the strongest defensible meaning of “the language audit is complete.” It is not a mathematical proof that no human will ever discover another design bug. More importantly, **the compiler is not yet compliant with the audited language**: the mismatch list in section 4 is concrete work that still has to be implemented and regression-tested.

The next engineering phase should therefore stop inventing semantics opportunistically and treat this file as the v1 design checkpoint: implement the deltas in dependency order, then build differential/negative/property/torture tests around each rule before advancing the compiler version.

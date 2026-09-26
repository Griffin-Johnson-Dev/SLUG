# SLUG Language Specification 1.0

Status: **Normative language contract for SLUG 1.x**

Language version: **1.0**

This document consolidates the audited-v1 language decisions into the canonical public language contract. The historical audit and blocker-closure documents remain provenance and rationale; when prose differs, this specification is the public statement of the SLUG 1.0 contract.

Normative terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are used in their ordinary standards sense.

## 1. Compatibility and scope

SLUG 1.0 is the first public language contract. Compiler implementation versions are independent of the language version.

A SLUG 1.x implementation:

- MUST preserve the meaning of already-valid SLUG 1 source;
- MAY fix behavior that contradicted this specification;
- MAY add standard-module exports only when doing so does not silently reinterpret already-valid source;
- MUST NOT add implicit root builtins beyond the nine frozen v1 core names;
- MUST use a new major language version for intentional incompatible syntax or semantic changes.

SLUG 1 is single-language-threaded. It defines no source-level thread, atomic, data-race, general FFI, or stable generated-C ABI.

The normal source extension is `.slg`. Canonically crushed source uses `.slgc`.

## 2. Source text and lexical model

### 2.1 Encoding and newlines

Source MUST be strict UTF-8. One UTF-8 BOM is accepted only at the beginning of the file and is non-semantic. LF, CRLF, and CR are logically normalized to LF. Invalid UTF-8 is a lexical error.

Whitespace outside strings and comments is non-semantic. Whitespace MUST NOT be required to disambiguate valid source.

### 2.2 Comments

SLUG 1 comments are:

- `## ...` ordinary line comment;
- `##! ...` preserved line comment;
- `#* ... *#` ordinary nested block comment;
- `#*! ... *#` preserved nested block comment.

`//` and `/* ... */` are not comments. `//` is exact integer division.

Ordinary comments may disappear during crushing. Preserved comments survive source transforms as metadata and never change runtime semantics. A preserved line comment in crushed source forces a physical newline after itself.

### 2.3 Names

The compact identifier model is ASCII-only:

- ordinary variables are one lowercase ASCII letter, `a` through `z`;
- named functions and methods are exactly two lowercase ASCII letters;
- classes and interfaces are exactly two uppercase ASCII letters;
- extended identifiers are one or more ASCII alphanumeric characters enclosed by a leading and trailing underscore, for example `_x_`, `_currentIndex_`, `_a1B2_`, and `_1_`; interior underscores are not part of one extended identifier. Extended identifiers are case-sensitive.

The pre-release underscore-between-every-character spelling is superseded. It is not a compatibility syntax in SLUG 1.0. Because whitespace is non-semantic and `_` remains a hard delimiter, a retired spelling is not globally reserved as one lexical error: for example `_a_b_c_` tokenizes as `_a_`, `b`, `_c_`, while `_n_e_x_t_` is lexically invalid because its final delimiter cannot begin a complete identifier. Source migration must therefore rewrite identifier tokens mechanically rather than relying on old spellings to fail. Canonical SLUG 1.0 source uses only the new spelling.

Unicode is permitted in strings, comments, and path data, but not in identifiers.

### 2.4 Reserved core names

The root builtin set is frozen at exactly:

`co`, `ci`, `ty`, `cv`, `in`, `iv`, `ln`, `sl`, `by`.

These names are reserved at root scope and no SLUG 1.x release may add another implicit root builtin.

### 2.5 Statement boundaries and ambiguity

`;` is an explicit statement boundary. It may be omitted where the grammar yields one unique interpretation. Whitespace does not create a statement boundary.

Parser implementation scores, beams, recursion limits, candidate-count caps, stack-width caps, or similar implementation counters are not language semantics. After the normative grammar priorities are applied, multiple valid semantic parses are an ambiguity error rather than an arbitrary implementation choice.

## 3. Literal values

### 3.1 Null

`nn` is the hard null literal.

### 3.2 Integers

Source integer literals are decimal only. A literal contains ASCII digits and represents an exact integer through `UINT64_MAX`.

`$` is an optional hard decimal-integer terminator. It contributes no value: `10` and `10$` denote the same integer. It is used when dense source needs an unambiguous integer boundary. `$` following a float or a non-integer token is invalid.

Literals through `INT64_MAX` use signed integer carrier `i`; larger nonnegative literals through `UINT64_MAX` use unsigned carrier `u`. Larger literals are range errors.

Hexadecimal source literals are not part of SLUG 1.

### 3.3 Floats

Source float literals MUST contain a decimal point, for example `.5`, `5.`, or `5.25`. Exponent notation is not a source-literal syntax, although explicit string-to-float conversion may accept decimal exponent text.

SLUG 1 float values are finite IEEE-754 binary64 values only. `f` and `f64` name that type. `f16`, `f32`, and `f128` are reserved and invalid in v1.

### 3.4 Strings

Source strings are single-quoted only. Double quote is reserved syntax and is a lexical error as a source-string delimiter.

Defined escapes include `\n`, `\r`, `\t`, `\0`, `\\`, `\'`, `\"`, `\{`, and `\}`. Unknown escapes are lexical errors. A physical newline may not appear inside a source string.

A runtime string is a length-tracked sequence of Unicode scalar values encoded as valid UTF-8 and may contain U+0000. SLUG performs no implicit Unicode normalization.

Unescaped `{expression}` inside a string is interpolation. Interpolations evaluate left-to-right and insert explicit string conversion of the resulting value. `\{` and `\}` are literal braces.

### 3.5 Bytes

Bytes values are arbitrary binary data. Byte indexing and iteration yield unsigned integers `0..255`. `by[string]` returns the exact UTF-8 bytes of the string, including embedded NUL. Converting bytes to string requires valid UTF-8.

## 4. Values, truthiness, equality, and ordering

### 4.1 Runtime categories

The v1 runtime includes null, Boolean, signed integer, unsigned integer, finite float, string, bytes, list, map, callable, object, error, and resource/reference categories exposed by the implementation and standard modules.

Boolean is not an implicit numeric type. Numeric use requires explicit conversion.

### 4.2 Truthiness

Exactly the following are falsey:

- `nn`;
- false;
- numeric zero;
- empty string;
- empty bytes;
- empty list;
- empty map.

Objects, callables, errors, and non-null resource references are truthy, including a closed resource handle.

### 4.3 Equality and identity

`==` and `!=` are structural/value equality.

`===` and `!==` are typed identity:

- for null, Boolean, integer, float, string, and bytes, identity means same runtime type and same value;
- for list, map, object, callable, error, and resource references, identity means the same reference.

Structural equality terminates on cyclic data and compares graph values coinductively. Sharing topology alone is not a value difference.

Two objects are structurally equal only when they have the same dynamic class and equal declared instance fields, including private and immutable fields. Static fields, methods, and finalizer state are not object value state.

Finite `+0.0` and `-0.0` are equal and are typed-identical as floats.

### 4.4 Ordering

`<`, `<=`, `>`, `>=` are defined only for:

- numbers, with exact mixed integer/float comparison;
- strings, lexicographically by Unicode scalar sequence;
- bytes, lexicographically by unsigned byte sequence.

Boolean is not numerically ordered. Collections, objects, callables, errors, and resource references have no implicit ordering.

## 5. Expressions and evaluation order

SLUG's arithmetic surface is reverse Polish notation. Binary arithmetic operators include `+`, `-`, `*`, `/`, `//`, `%`, and `^`. Unary negation is supported where grammar requires one operand.

Evaluation is observably **left-to-right**. This applies to callable arguments, method/constructor arguments, RPN operands as operations become executable, list items, map key/value pairs, assignment RHS computation, receiver/index expressions, interpolation expressions, defaults, comparisons, and Boolean atoms.

### 5.1 Arithmetic

`+` means numeric addition, string+string concatenation, or bytes+bytes concatenation. It does not implicitly stringify unrelated values.

`/` is true division producing finite `f64`.

`//` accepts integer operands and performs exact integer quotient with truncation toward zero.

`%` is defined with the same truncation rule so that `a == (a // b) * b + (a % b)`; the remainder has the dividend's sign or is zero.

Integer arithmetic never silently wraps. For `i`+`i` provenance, results must remain in signed 64-bit range. When at least one operand has `u` provenance, nonnegative results may remain unsigned through `UINT64_MAX`; a negative result becomes signed when representable. Otherwise an overflow error is raised.

Float-producing operations MUST reject NaN or infinity with a catchable numeric/range error. `0^0 == 1`; zero to a negative exponent errors; real-domain-invalid exponentiation errors rather than producing NaN.

### 5.2 Boolean mode

`?` introduces a Boolean/comparison expression and produces a real Boolean value.

Within Boolean mode:

- `!` is logical NOT when it is not the explicit callable-invocation prefix;
- `+` is short-circuit AND;
- `/` is short-circuit OR;
- `[]` groups Boolean expressions;
- `==`, `!=`, `===`, `!==`, `<`, `<=`, `>`, `>=` are comparison atoms;
- ordinary values may be used by truthiness.

Boolean short-circuiting is left-to-right and suppresses unevaluated effects.

### 5.3 Casts and contracts

A cast is explicit `@...` conversion. Static v1 cast descriptors are:

- `@i`, `@i8`, `@i16`, `@i32`, `@i64`;
- `@u`, `@u8`, `@u16`, `@u32`, `@u64`;
- `@f`, `@f64`;
- `@s`;
- `@b`.

`|...|` may provide a hard operand boundary, for example `@i|1 2 +|`. Dynamic cast syntax may obtain an implemented descriptor from `ty[...]` or from an explicitly grouped type expression.

Casts convert and validate range/encoding. Contracts on bindings, parameters, fields, and returns only validate; they MUST NOT silently convert.

String-to-number casts trim ASCII whitespace, accept an optional sign, and require the entire remaining string to match the target grammar. Float-to-integer conversion truncates toward zero after finite/range checks. No cast wraps.

## 6. Bindings and lexical scope

### 6.1 Mutable definition/update `:=`

`:=` defines or replaces a binding in the **current lexical scope** and yields the assigned value. It is an expression and may appear inside a larger expression, condition, or loop-bound expression.

A `:=` in a condition or loop source/bound expression executes in the enclosing scope because the body block does not yet exist. A `:=` inside `{...}` belongs to that block and may shadow an outer binding.

### 6.2 Immutable definition `::=`

`::=` creates a new immutable binding in the current scope and yields its value. Re-defining the same name with `::=` in that scope is an error. The binding cannot later be updated.

### 6.3 Strict update `=`

`=` is statement-only and non-value-producing. It updates the nearest existing mutable binding. It never creates a binding.

### 6.4 Contracts

A binding target may carry a contract such as `a@i:=1`. Validation occurs at the binding boundary without coercion.

### 6.5 Multiple targets/results

Assignments are target-atomic:

1. evaluate the RHS exactly once;
2. validate target existence, mutability, contracts, and result arity;
3. commit target writes together.

One result may broadcast to multiple targets. Multiple results must exactly match target count. Extra or missing results are errors. Observable external effects produced while evaluating the RHS are not rolled back.

## 7. Collections, indexing, slicing, and iteration

### 7.1 Lists and maps

`[...]` is a mutable list when it contains sequence items. Map literals use key/value entries such as `['name':1]`. `@[...]` and `@[:]` create shallow-frozen containers.

A shallow freeze prevents mutation of that container but does not recursively freeze children.

Map keys are restricted to stable values: null, Boolean, integers, finite floats, string, and bytes. Numeric keys that are equal under numeric `==` denote the same key. Duplicate-equal keys in a map literal are errors.

Maps preserve insertion order for iteration and display. Updating an existing key does not move it.

### 7.2 Index writes

- list `x[i]=v` and `x[i]:=v` require an existing in-range element;
- map `m[k]=v` requires an existing key;
- map `m[k]:=v` inserts or updates and yields `v`;
- string and bytes indexed mutation is invalid;
- indexed `::=` is invalid.

### 7.3 Slices

List, string, and bytes slices use Python-style half-open normalization for omitted/negative bounds and positive/negative integer steps. Step zero errors. Direct indexes error when out of range; slices clamp.

String indexes/slices use Unicode scalar values. Bytes indexes/slices use bytes. List slices preserve the frozen state of the source list.

### 7.4 Sorting

`sl` performs a stable, exception-safe in-place sort of a mutable list using the v1 ordering domain. If comparison fails, the original list remains unchanged. Frozen lists reject sorting.

### 7.5 Foreach snapshots

Foreach and sliced-iterable loops iterate a snapshot of the selected sequence/items/keys established at loop entry. Mutating the original container does not change the visits already selected for that loop. Referenced values inside the snapshot remain ordinary mutable references.

## 8. Calls, functions, lambdas, and returns

### 8.1 Named callables

Named functions use exactly two lowercase letters and are declared with `~ab ... { ... }`. `~~ab ... { ... }` is the static-method form in class context. `-~ab ... { ... }` declares a private method/function where the context permits it.

Optional return contracts precede parameters, for example `~ab@i ...` or a multi-result list such as `~ab[@i,@s] ...`.

Parameters are ordinary/extended names, optionally followed by a contract and/or a default. Defaults are evaluated at call time, left-to-right, after earlier parameters have been bound. A default may use earlier parameters but not later ones.

A variadic tail is written as `[name]` after fixed parameters. Variadic callables require an explicit argument pack and receive a fresh mutable list for the tail.

### 8.2 Lambdas and callable values

`lb ... { ... }` creates a first-class lambda with the same parameter/default/return-contract rules. Callable values are invoked explicitly with `!value[...]`.

`!ab...` or explicit `ab[...]` forces named-callable interpretation where dense source could otherwise be read as variables.

### 8.3 Dense callable inference

Fixed-arity/defaulted two-letter callables may use dense inference only when the normative grammar produces one meaning. Adding a later callable or module MUST NOT silently change the meaning of already-valid source.

### 8.4 Default placeholder

`xx` means “use this parameter's declared default” only in an actual call-argument position. It is invalid for a required parameter or outside call argument handling.

### 8.5 Return arity

`rv` returns zero results. `rv a` returns one; `rv a b` returns multiple.

Every callable has one result arity. A declared return-contract list fixes it. Otherwise all reachable return/fallthrough paths must agree; fallthrough is zero-result.

A call returning more than one result may only be consumed by a compatible multi-target assignment, forwarded directly by a compatible multi-return, or discarded as a statement. It may not silently collapse to one value inside an ordinary expression.

## 9. Control flow

Blocks use `{ ... }` and establish lexical scope.

### 9.1 Conditionals

The forms are `if?cond{...}`, `ei?cond{...}`, and `ee{...}`. The leading `if` may be omitted for the first branch where `?cond{...}` is unambiguous.

### 9.2 While

`wl?cond{...}` reevaluates the condition before each iteration.

### 9.3 For loops

`fl` supports:

- repeat: `fl count{...}`;
- foreach: `fl i source{...}`;
- numeric range: `fl i start stop{...}`;
- sliced iterable/range forms with additional start/stop/step expressions as accepted by the grammar.

Repeat counts must be nonnegative integers. Numeric range is start-inclusive and stop-exclusive with implicit `+1`; `start >= stop` executes zero iterations. Bounds/source are evaluated once at loop entry.

`bl` breaks the nearest loop. `cl` continues the nearest loop.

## 10. Errors, try/catch/finally, and finalizers

Ordinary program/runtime failures are catchable structured error values. Stable error information includes kind, message, payload, cause, and suppressed context. User `er value` raises that value, wrapping a non-error value as a user error.

Bare `er` inside an active catch rethrows the currently caught error unchanged. Bare `er` elsewhere is invalid.

Structured exception syntax uses:

- `tr{...}` try body;
- `ca{...}` catch without binding;
- `cae{...}` catch with the error bound to `e` (or the grammar-equivalent explicit catch binding);
- `fn{...}` finally.

`fn` executes exactly once on normal completion, error propagation, return, break, and continue. A transfer performed by `fn` supersedes the pending transfer. A new error from `fn` supersedes a pending error while retaining the prior error as cause/suppressed context.

Fatal process/internal failures are reserved for genuinely unrecoverable implementation/resource conditions and are not catchable ordinary errors.

Object destructors use `~-{...}`. Finalizer timing is not deterministic, but each object finalizes at most once. The object is rooted while its finalizer runs. Errors escaping finalizers execute in an isolated runtime exception context and cannot be intercepted by an unrelated user catch.

## 11. Classes, interfaces, members, and inheritance

Classes are exactly two uppercase letters and begin with `#`, for example `#AB{...}`. A leading `-` makes the class private. Constructor parameters follow the class name. A class may name one parent with `<CD` and interfaces with `:EF` forms.

Interfaces begin `#?AB{...}` and contain method declarations; interfaces may extend interfaces.

Class constructor headers use constructor parameters only: function return-contract and variadic-tail syntax is invalid there.

Instance fields and methods are declared by the class implementation. External `obj.x:=...` may not invent a field. External code may update only an existing public mutable field with `=`.

Current-instance access uses `.x` / `.ab[...]`. Current-class static access uses `..x` / `..ab[...]`. Explicit class static access uses `AB.x` / `AB.ab[...]`. Ordinary receiver traversal uses `obj.x` / `obj.ab[...]`.

Private members are visible only inside the declaring class implementation; subclasses do not inherit private access.

Parent construction uses `^^[...]`. If the parent has required constructor parameters, the child MUST perform parent construction exactly once before inherited instance state is accessed or instance dispatch is used. If all required parent parameters have defaults, the compiler may insert a zero-explicit-argument parent construction. Parent-method implementation access uses `^^.ab[...]`.

Overrides use invariant callable shape/contracts in v1. A class must satisfy required interface methods. Conflicting inherited interface defaults require an explicit class override.

## 12. Modules, imports, exports, and namespaces

A canonical imported source module is instantiated once per program. Import cycles are compile-time errors. Dependencies initialize before importers; siblings initialize in source import order; executable module globals execute in source order. Diamond imports share one module state.

Source imports use the import statement form such as:

`>'path/to/module.slg'`

and may use an alias, for example:

`>'path/to/module.slg':MA`

Standard modules use reserved URIs such as `@std/fs` and do not search the working directory, network, or user package paths.

`<:alias` selects an imported module as the active lexical namespace. `<:.` restores the current/default namespace. If a bare name is valid both in the active namespace and root/current namespace, compilation reports ambiguity. Explicit qualification is required. Backtick is a one-shot root/default-namespace escape for the immediately following name.

Exports and imported mutable state obey the same strict update, contract validation, left-to-right evaluation, and target-atomic assignment rules as local bindings. Imported aliases refer to the same linked state cell, not copies.

## 13. Standard runtime modules

The following explicit standard-module identities are reserved in SLUG 1.0:

- `@std/sys`
- `@std/time`
- `@std/rand`
- `@std/fs`
- `@std/net`
- `@std/gfx`
- `@std/audio`
- `@std/dev`

They are distribution modules, not root builtin expansion points. Unsupported platform facilities raise a catchable capability error rather than silently emulating unrelated behavior.

The v1.0 implementation export surface is recorded in `docs/SLUG_V1_STANDARD_MODULES.md`. A v1.x release may add an explicit export only when doing so preserves already-valid source under the namespace ambiguity rules.

Host text boundaries such as paths, environment keys, and similar C/OS text interfaces reject embedded NUL. File/socket/device **contents** remain length-tracked and binary-safe.

## 14. The nine root builtins

The frozen root builtins are:

- `co[value]`: console output;
- `ci[]` / `ci[prompt]`: read one logical line as string; EOF-before-data returns `nn`, blank line returns `''`;
- `ty[value]`: canonical runtime kind/carrier description;
- `cv[type,value]`: whether the explicit conversion would succeed;
- `in[needle,container]`: membership;
- `iv[needle,map]`: whether `needle` is equal to one of the map's values;
- `ln[value]`: exact length/count using adaptive integer result;
- `sl[list]`: stable exception-safe in-place list sort;
- `by[value]`: bytes conversion, including exact UTF-8 bytes for strings.

No other native capability is implicitly visible at root scope in SLUG 1.x.

## 15. Resource handles and I/O

Resource truthiness is reference-based, not open/closed-state-based. Closing is idempotent where the standard operation defines it. Use-after-close raises a catchable state error.

Requested I/O sizes are SLUG integers and are converted to host chunk sizes with checked arithmetic. A host syscall width MUST NOT become a language-level maximum. Large operations may be chunked.

OS-originated text MUST be decoded strictly. Invalid host text is an encoding/I/O error rather than silently lossy replacement.

## 16. Garbage collection and identity

Reachability tracing is the semantic memory-management fallback. Cycles are collectable. Implementations may optimize storage or allocation provided observable identity and finalizer constraints are preserved.

Reference identity remains stable for the lifetime of a value. Core graph traversals such as equality, display, and marking MUST NOT impose small arbitrary depth cutoffs; they should use iterative traversal where needed.

User function recursion has no arbitrary SLUG recursion counter. Native stack/resource exhaustion remains a real implementation resource limit.

## 17. Display and diagnostics

Display/stringification has no fixed depth limit and is cycle-aware with deterministic cycle/back-reference markers. Display syntax is not a guaranteed source serializer.

An uncaught error must report its error kind and message, and cause/suppressed context where present. Human diagnostic formatting may improve in SLUG 1.x; the structured error fields are the stable semantic data.

## 18. Source transforms: format, crush, expand

Source transformation is canonical/semantic, not byte-for-byte restoration of the author's original whitespace.

For valid source `s`:

- `parse(crush(s))` MUST have the same semantic AST as `parse(s)`;
- `expand(crush(s))` MUST be a canonical readable representation of that AST;
- `crush(expand(crush(s)))` MUST be stable/canonical;
- ordinary comments may disappear;
- preserved comments survive according to the comment rules.

Formatting and crushing MUST NOT rely on hidden parser caps or heuristic meaning changes.

## 19. Optimizer and backend obligations

Optimization follows an as-if rule preserving:

- left-to-right observable effects;
- catchable error kind/timing where observable;
- I/O ordering;
- reference identity;
- module/shared-state effects;
- finalizer constraints.

Allocation elimination is legal only where identity/finalization is unobservable.

Generated C, runtime structs, tags, helper names, and layout are implementation details. `emit-c` is not a public ABI or general FFI promise.

Runtime/compiler-support arithmetic influenced by user magnitudes must avoid C undefined behavior: checked growth, no signed overflow, no invalid shifts, and no unsafe narrowing before validation.

## 20. Conformance

A conforming SLUG 1 implementation must match this specification for accepted source and reject invalid source consistently, subject only to real resource exhaustion.

The release authority includes positive/negative language conformance, frontend/semantic differentials, optimized/unoptimized behavior comparison, sanitizer runs where supported, deep/cyclic data tests, exception/finalizer tests, source-transform fixed points, standard-module tests, and the self-host fixed-point proof.

Historical audit files are rationale/provenance; they do not authorize an implementation to preserve historical behavior that contradicts this specification.

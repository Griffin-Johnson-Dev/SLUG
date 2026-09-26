# SLUG example battery

The `basic/` directory contains ten small `.slg` programs. All ten are accepted by the
current native bootstrap backend; example 10 specifically checks that class-vs-hex contextual
parsing survives all the way through native lowering.

| # | File | Focus | Native expected output |
|---|---|---|---|
| 01 | `01_hex_literals.slg` | hexadecimal source integers; decimal console rendering | `10`, `16` |
| 02 | `02_contextual_digit_partition.slg` | `52/` contextual RPN partition; explicit `$` subtraction boundary | `2.5`, `6` |
| 03 | `03_rpn_arithmetic.slg` | nested RPN arithmetic | `14` |
| 04 | `04_division_cast_remainder.slg` | true division, `@i` quotient, `%` | `2.5`, `2`, `1` |
| 05 | `05_power_and_negative_operand.slg` | `^`, unary `-` as an RPN operand, `0^0` | `8`, `0.125`, `1` |
| 06 | `06_strings_and_conversion.slg` | string `+`, canonical `@s` conversion | greeting, `10` |
| 07 | `07_multiple_assignment_broadcast.slg` | `=` creation/update + RHS broadcast | same/same/new/new |
| 08 | `08_assignment_expression_and_mutation.slg` | nested `:=`, explicit argument pack, `++`/`--` | `3`, `3`, `10`, `11`, `10` |
| 09 | `09_immutable_extended_comments.slg` | `::=`, extended names, nested/preserved comments | `11`, `15` |
| 10 | `10_class_hex_disambiguation.slg` | `ABA$` becomes `AB(A$)` when class `AB/1` exists | no stdout |

`control/` adds five native examples covering Boolean mode, short-circuiting, branch chains,
lexical shadowing, while/break/continue, counted repeat, and numeric ranges.

`collections/` adds six native examples covering mutable/frozen lists and maps, indexing,
negative indices, slicing, Unicode code-point strings, membership, length, sort/alias behavior,
map creation/update, foreach, and sliced-iterable loops.

`functions/` adds six native examples covering inferred fixed-arity calls, defaults and `xx`,
explicit call packs, multiple returns and broadcast assignment, variadic captures, recursion, module
bindings, optional return contracts, and zero-value `rv`.

`oop/` adds seven native examples covering constructor fields, instance/static methods and state,
inheritance, explicit/automatic parent construction, `^^` super dispatch, private members, object
structural-vs-identity equality, destructor order, constructor defaults, and method multi-return.

`closures/` adds five native examples covering first-class lambdas, escaping mutable lexical captures,
defaults/`xx`, variadic lambda tails, nested closures, multiple returns, and current-object capture.

`exceptions/` adds five native examples covering catch binding, catch-any, wrapping raised values as
`ER`, nested rethrow, `finally` on return, and `finally` across break/continue.

`modules/` adds seven file-aware examples covering aliased imports, direct public-symbol imports, nested imports, persistent executable module state, all three alias shapes, `<:` active namespaces, and imported-class static traversal. Import privacy/collision/cycle/diamond cases are covered by unit tests.

`hardening/` adds native examples for checked int64/width behavior and graph-aware cyclic structural equality.

`lifetime/` adds three v0.1.2 examples covering cyclic reclamation, closure/captured-cell cycles, and reachability-driven object destruction.

`type_ir/` adds three v0.1.3 examples covering persistent binding type contracts, exact full-range `u64`, and typed function/data flow used by the new HIR.

`optimizer/` adds three v0.1.4 examples covering straight-line constant folding, CFG-correct short-circuit side effects, and loop-carried SSA phi state. Use `slug mir` to inspect raw CFG/SSA and `slug opt-ir` to inspect the optimized form.

`completion/` adds four v0.1.5 pre-self-hosting examples covering trait requirements/default methods, typed shared public module state, exact `INT64_MAX` remainder optimization, and common-base flow typing through CFG/SSA.

`salt/` contains the v0.1.6 **SALT** super-acceptance program and its intentionally tangled fixture graph. It is run as one heavy acceptance test through `run_salt.ps1`; see `examples/salt/README.md` for its runtime assertions, compiler-side checks, hostile-input coverage, local-web integration, and native capability composition, hostile-data coverage, and the remaining deliberately non-native library boundaries.

`examples/torture/compiler_torture.slg` is the first combined regression program.
`examples/torture/implicit_gauntlet.slg` is intentionally much nastier: it pushes
context-sensitive parsing until many substrings have several tempting readings but the
whole program still has one uniquely preferred AST under SLUG's parsing rules. Both have crushed/expanded forms and exact
expected native stdout stored beside them.

From the project root on Windows:

```powershell
.\run_examples.ps1
```

Or manually:

```powershell
py .\slug.py check .\examples\torture\compiler_torture.slg
py .\slug.py crush .\examples\torture\compiler_torture.slg
py .\slug.py expand .\examples\torture\compiler_torture.slgc
py .\slug.py run .\examples\torture\compiler_torture.slg

py .\slug.py check .\examples\torture\implicit_gauntlet.slg
py .\slug.py crush .\examples\torture\implicit_gauntlet.slg
py .\slug.py expand .\examples\torture\implicit_gauntlet.slgc
py .\slug.py run .\examples\torture\implicit_gauntlet.slg

py .\tests\run_release_tests.py
```

## Deliberately questionable cases

The torture file records several choices that are easy to misread:

- `93-` is `-(0x93)` because the longest digit-only hex literal is already a valid
  operand for unary `-`. To force `9 - 3`, write `9$3-` (or the roomy `9$ 3 -`).
- `23-^` resolves as `2 (3 neg) ^`, because treating `-` as binary subtraction would
  leave `^` without two operands.
- `co[q:=C$]` uses explicit argument-pack syntax. `coq:=C$` would instead collide with
  the valid multi-target assignment `c,o,q := C$`, so the formatter retains brackets.
- `@s10` means `@s(0x10)` because `s` has no width variants. Width digits are consumed
  only for actual fixed-width types (`i8/i16/i32/i64`, `u8/...`, `f16/f32/f64/f128`).
- Whitespace is never a disambiguator. The bootstrap formatter is intentionally conservative
  and may print semicolons even when implicit boundaries would suffice; `slug crush` reparses
  and removes every boundary it can prove unnecessary.

## Implicit gauntlet highlights

The gauntlet deliberately includes cases such as:

- `coin=F$` => targets `c,o,i,n`, despite `co` and `in` both being known callables.
- `a:=ABA$` inside a scope where `AB/1` exists => `a := AB(A$)`, not integer `0xABA`.
- `c:=zzab` where `zz/2` is known => a call because four bare variables cannot form one RHS value.
- `123+` => `12 3 +`; `123*+` => `1 2 3 * +`; `23-^` => `2 (3 neg) ^`.
- `@s10` => `@s(0x10)` while `@i32FF$` consumes `32` as a real width.
- Adjacent assignments such as `a:=123+b:=123*+` need no terminator once the first RHS is complete.
- `k:=@i52/m:=52%` ends the cast at `5 2 /`; the following `m:=` begins a new statement.
- `co_xY_co_n_` needs no separator because an extended name's closing underscore is a lexical endpoint.
- `~~uv` static declaration, `-~xy` private callable, private/inherited classes, lists,
  frozen lists, callable-value invocation, null, extended names, and nested returns.

The current semicolon-free gauntlet also exercises v0.0.6 Boolean/control-flow, v0.0.7
collection/runtime syntax, v0.0.8 named-function semantics, v0.0.9 OOP, and v0.0.10 closures/exceptions: maps, collections,
Unicode, collection-backed loops, defaults/`xx`, multiple returns, variadics, recursion, adjacent
field definitions, private/static members, inheritance, `^^` super dispatch, method multi-return,
object equality/identity, escaping mutable closures, callable defaults/`xx`, variadic lambdas, wrapped
errors, catch binding, and finally. Its crushed form is reparsed and executed alongside the readable and
expanded forms.

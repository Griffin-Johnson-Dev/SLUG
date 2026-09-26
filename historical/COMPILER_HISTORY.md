# SLUG Compiler v0.2.0a2 — Self-Hosting Bootstrap

SLUG — **Symbolic Low-overhead Unified Grammar** — has reached its first converged
self-hosting checkpoint. The frozen v0.1.7.1 Python compiler remains the behavioral
oracle and Stage-0 seed, but the Stage-1 compiler logic is now written in SLUG and can
compile its own canonical source repeatedly to byte-identical generated C.

This is intentionally the **ugly bootstrap compiler**, not yet the polished official
implementation. Stage 1 uses a stricter canonical source contract, a flattened bootstrap
module graph, conservative evaluation-order rules, and direct C lowering so correctness
and bootstrap reproducibility stay auditable while the cleaner compiler is built on top.

### v0.2.0a2 Windows CRLF bootstrap hardening

v0.2.0a2 fixes the first cross-platform defect found in the converged self-hosted
compiler.  The frozen Python lexer accepts ordinary whitespace with
`str.isspace()`, but the Stage-1 SLUG lexer recognized only space, tab, and LF.
A Windows-created CRLF source therefore reached the Stage-1 lexer as an unexpected
`\r` character.  The fix does not invent a `\r` SLUG string escape (SLUG does
not define one); instead the lexer fast-paths space/tab/LF and classifies the
remaining ASCII control whitespace by its real UTF-8 byte value.  The regression
now covers CRLF, vertical tab, form feed, carriage return, and ASCII 0x1C–0x1F.

The heavy bootstrap proof deliberately writes its independent phase-5 smoke source
with CRLF bytes on every host, so POSIX CI now catches the exact Windows failure.
The corrected three-generation compiler converges byte-for-byte at **298,454
bytes**, SHA-256
`9a2907b1eb9619d46e0e2c102e7b44feb7e1b221ffac3defd333d152f0cb2c31`.

### v0.2.0a1 first converged self-hosting checkpoint

The self-host stack now includes a native SLUG lexer, canonical structural parser,
expression and statement/program AST lowering, bootstrap semantic validation, recursive
direct-import loading, and a direct-C backend. The hardened bootstrap proof seeds
Generation 1 with the frozen Python oracle, then uses Generation 1 to emit Generation 2
and Generation 2 to emit Generation 3. All three generated compiler C files must be
byte-for-byte identical, and two converged generations must independently emit identical
C for a native smoke program.

The frozen convergence artifact is 297,016 bytes with SHA-256
`552ccdee5d20509e50587070c2c2023606dfa24b1d416395a117c1c5022c7308`. See
`SELFHOST_CONVERGED_CHECKPOINT.md` and `selfhost/bootstrap/` for the exact proof,
converged C source, reproduction command, and explicit Stage-1 limitations. The heavy
proof runner is resumable so an interrupted build can content-hash its completed phases
and continue instead of trusting partial artifacts.


### v0.1.7.1 Windows native-link hotfix

v0.1.7.1 fixes a release-blocking Windows linker regression introduced by the v0.1.7 native window/audio runtime. Because the generated runtime always contains managed window cleanup, even programs that never open a window retain a `DestroyWindow` reference. The Windows compiler driver now links `user32` and `gdi32` in addition to the existing Winsock, Shell, and WinMM libraries for both GNU-style Clang/GCC and MSVC/clang-cl command lines. Generated Windows C also defines `_CRT_SECURE_NO_WARNINGS` before CRT headers so deprecation noise cannot bury the actual linker diagnostic. No SLUG source-language semantics changed in this hotfix.

### v0.1.7 namespace/root escape + native surface/device foundation

v0.1.7 finishes the namespace rules needed for dense real programs and expands the native capability registry from **42 to 59** two-letter builtins. An active namespace selected with `<:MA` now resolves a bare name in `MA` first and then falls back to the current/root module when the active module does not define that name. Explicit qualification such as `MA.co` remains exact and never falls back. A backtick is a one-expression root escape: under `<:MA`, `` `co[...] ``, `` `a ``, or `` `AB[...] `` resolves that name only in the root/default namespace without changing the active namespace for following source or for call arguments. Crusher/pretty output preserves the escape in the AST, so namespace shadowing survives round trips.

Root user definitions intentionally overwrite builtin spellings. That rule is now enforced consistently in semantic typing, HIR/MIR behavior, optimizer clobber assumptions, and C lowering—not only in parser symbol discovery. SALT exposed the concrete collision because its historical helper `rf` now shares the spelling of the rectangle-fill primitive; SALT's helper was renamed, and a permanent regression verifies that a genuine user `rf` still replaces the builtin when desired.

The statement-sequence parser's 256-path ambiguity beam is now a **score-ranked lazy k-best beam**. Older code retained the first generated candidates and could discard a later, lower-cost parse in large dense programs. v0.1.7 uses a heap merge over already-ranked dependency paths and compact rest-path deduplication, preserving the best 256 candidates without the combinatorial materialization/quadratic fingerprinting that an initial correctness fix exposed on the torture corpus.

The 17 new explicit-pack capability primitives are: `sf` software RGBA surface creation; `px` pixel write; `rf` filled rectangle; `dl` line draw; `sb` exact RGBA byte export; `wn` native window creation; `wf` surface presentation; `pe` event polling; `wx` window close; `au` audio output open; `aq` synchronous S16LE PCM submission; `ax` audio close; `do` raw device open; `dv` serial open/configure at requested baud with 8N1 framing; `dr` device read; `dw` device write; and `dx` device close. Surfaces and raw device streams are portable across the current Windows/POSIX backends. Native window/event presentation and PCM output are implemented with Win32 GDI/message APIs and WinMM on Windows; unsupported hosts fail explicitly rather than silently emulating them. Higher GUI widgets, image formats, mixers/synthesis, protocols, parsers, and device framing remain ordinary SLUG-library work.

RGBA colors use packed `RRGGBBAA` integers. `sf[w,h]` creates zeroed RGBA storage; `px[s,x,y,c]` writes one in-range pixel; `rf[s,x,y,w,h,c]` and `dl[s,x0,y0,x1,y1,c]` clip drawing at the surface edge; `sb[s]` returns a copy of the exact row-major RGBA bytes. Raw devices use `do[path,'r'|'w'|'rw']`; `dw` accepts bytes and returns the count written, while `dr[d,n]` returns up to `n` bytes. Window/audio/device handles are managed heap values, auto-close at reclamation/shutdown, support idempotent explicit close, and reject use after close. Windows native builds now link `winmm` in addition to the existing socket/shell dependencies.

The isolated ordinary release battery now contains **323 tests**. SALT remains a separate deliberately heavy acceptance gate and passes optimized and optimizer-disabled builds with its 173 runtime assertions and zero-live-heap requirement.

### v0.1.6.2 Windows newline-portability test hardening

v0.1.6.2 fixes the release tests, not SLUG runtime semantics. Windows text-mode stdout correctly represents logical `\n` as CRLF (`\r\n`), while POSIX uses LF. The v0.1.6.1 hostile-codepage regressions correctly proved that Unicode argv/output/paths were UTF-8, but two assertions then compared raw Windows bytes against POSIX-only LF expectations. The tests now decode strict UTF-8, compare logical lines, permit only the host's ordinary LF/CRLF translation, and reject stray carriage returns or content drift. A dedicated two-line non-ASCII regression (`α`, `🐌`) permanently verifies the distinction.

### v0.1.6.1 Unicode bootstrap-CLI hardening

v0.1.6.1 fixes a Windows bootstrap-CLI boundary exposed by the real Windows release battery: `slug run file.slg -- ...` correctly decoded native SLUG output as UTF-8, but redirected Python `stdout`/`stderr` could still inherit a legacy ANSI/OEM codec such as cp1252. Relaying a non-BMP value such as `🐌` could therefore raise a host `charmap` encoding exception after the native program had executed successfully. The CLI now reconfigures its own text streams to strict UTF-8 at startup, matching the language/runtime UTF-8 contract. Permanent regressions force a legacy `PYTHONIOENCODING=cp1252` even on non-Windows hosts and verify Unicode argv relay, native stdout, Unicode source paths, and Unicode diagnostics.

### v0.1.6 native capability foundation

v0.1.6 adds the smallest native OS/runtime capability layer needed to make higher-level facilities implementable in SLUG instead of hard-coding convenience APIs into the compiler.  Native builtins now come from one authoritative registry shared by symbols, semantic/HIR typing, MIR effect/escape analysis, and C lowering.  The registry keeps the dense two-letter callable surface centralized and prevents compiler layers from disagreeing about arity, result kinds, allocation, mutation, retention, or external effects.

Explicit cast boundaries use `@type|expression|`.  The pipe pair is recognized only immediately after a cast type, nests with other grouped casts, survives crush/expand, and does not steal list/index syntax.  Ungrouped casts retain ordinary whitespace-insensitive parsing: `@i87F$` is adaptive `@i(87F$)`, while `@i8|7F$|` unambiguously means the checked `i8` conversion of `0x7F`.

The runtime now has first-class managed `bytes`, managed file handles, and managed TCP sockets.  The primitive capability surface covers UTF-8/bytes conversion; binary/text whole-file I/O; file existence/stat/list/create/remove/move; streaming open/read/write/seek/tell/flush/close; argv/environment/cwd/platform facts; wall/monotonic clocks and sleep; OS entropy; explicit argv-list subprocess execution with no implicit shell; and TCP create/connect/bind/listen/accept/send/receive/port/close.  Handles are graph-managed and auto-close when reclaimed or at shutdown, while explicit close remains idempotent.  Windows paths/argv/environment use wide-character APIs, and native builds link the platform socket/shell dependencies without reintroducing the old `m.lib` bug.

Capability builtins deliberately use **explicit argument packs** rather than inferred dense calling. For example, `so[]`, `tm[]`, `fr[path]`, and `ac[socket]` are valid, while bare `so` / inferred `ac socket` are not. The six legacy core builtins (`co`, `ci`, `in`, `iv`, `ln`, `sl`) keep their historical dense inferred forms. This rule is a grammar-stability guarantee: adding a future builtin such as `ac` cannot retroactively reinterpret old text such as `a co[...]` as a different two-letter callable.

HTTP, deterministic PRNGs, JSON, file copy/walk/glob, matrix libraries, WebSocket framing, and similar conveniences intentionally remain ordinary SLUG-library territory because they compose from these primitives.  SALT now proves that composition directly: its SLUG executable performs binary/text/stream file I/O, hostile argv/environment/file handling, safe subprocess arguments, secure entropy/time checks, and serves a real loopback HTTP response using only bytes + TCP.  The executable currently self-checks **173 runtime invariants**, optimized and optimizer-disabled builds must agree, all temporary filesystem state is removed, and shutdown must report a zero-live managed heap.

### v0.1.5.2 SALT acceptance hardening

v0.1.5.2 adds **SALT** (`examples/salt/salt.slg` + `run_salt.ps1`), one monolithic acceptance test that cross-combines the implemented scalar/control/collection/function/closure/exception/OOP/trait/module/namespace/lifetime/optimizer surface rather than testing each feature only in isolation. The executable self-checks 128 runtime invariants, is differentially compiled with and without optimizer facts, consumes hostile stdin/source strings as inert data, generates a small HTML page that is loopback-hosted by the acceptance harness, and must terminate with a zero-live managed heap. The surrounding one-test harness also checks deterministic HIR/MIR/C, crush/expand equivalence, compiler-side file I/O, negative semantic/runtime cases, unsupported-capability probes, and a 5,000-statement parser stress case.

SALT exposed two bootstrap correctness/clarity issues that are now permanent regressions. Nested named class/function/interface declarations were previously accepted even though the bootstrap had no nested named-symbol namespace; they are now rejected explicitly (nested callables use lambdas). Fixed-width casts now consume the **longest valid width prefix** instead of greedily swallowing the following operand digits first, so whitespace-insensitive `@i8 7F$`/`@i87F$` correctly mean `@i8(0x7F)` while invalid-width `@i52/` remains adaptive `@i(5 2 /)`. The ordinary isolated release battery now contains **276 tests**, with SALT retained as one additional intentionally heavy acceptance test.

Runtime filesystem, built-in RNG, and socket/HTTP APIs are still not part of the v0.1.5.2 runtime; SALT marks those as explicit capability boundaries rather than faking coverage. Compiler-time module/file I/O is tested, a deterministic PRNG is implemented in SLUG, and generated HTML is served by the host-side loopback acceptance harness. A standalone self-hosted compiler will need a defined runtime/standard-library filesystem surface in a subsequent milestone.

### v0.1.5.1 Windows differential-harness hardening

v0.1.5.1 is a patch release over the v0.1.5 language/optimizer milestone.  The optimizer differential corpus now compiles both optimized and unoptimized generated C through the production `_build_ctext` / `_compiler_command` path instead of duplicating linker flags inside the test.  This fixes native Windows Clang runs where the old harness unconditionally passed `-lm`, which lld-link translated to the nonexistent `m.lib`.  Compiler-family detection also normalizes Windows-style paths, and the driver regression matrix now covers GNU-style (`clang`, `gcc`, `cc`) and CL-style (`cl`, `clang-cl`) frontends under Windows/POSIX policies.

### v0.1.5 pre-self-hosting completion milestone

v0.1.5 closes the major language-surface gaps that remained after CFG/SSA arrived. `#?IF{...}` declares an interface/trait contract; empty methods are required, methods with bodies are defaults, interfaces may inherit other interfaces, and classes implement one or more interfaces with `#AA:IF{...}` / `#AA:IA:IB{...}`. Required/default instance and static methods participate in normal class inheritance, diamond defaults are deduplicated when they originate from the same definition, incompatible defaults are rejected unless the class overrides them explicitly, and imported interfaces work through direct imports, aliases, and active namespaces.

Module state can now be exported explicitly with `+:x:=value`, `+:x::=value`, and typed forms such as `+:x@i8:=value`. Direct imports, alias-qualified access, and active namespaces all resolve to the same linked state cell, including diamond imports; mutable exports can be assigned externally while immutable exports and binding contracts remain enforced. Direct-imported exported names may not be silently redeclared as locals, avoiding a split read/write binding. Public class metadata also carries inherited public static method/field information needed for inferred calls across module boundaries.

Flow-sensitive typing now joins facts across `if`/`else`, loops, and exception paths instead of allowing analysis order to determine a binding's inferred type. Signed/unsigned integer paths join to `integer`, related classes join to their nearest common base, and unknown predecessors remain `any` rather than being incorrectly narrowed. Those expression-site facts are preserved into HIR and through CFG/SSA phi nodes. Fixed/default-arity member calls can now infer argument shape for instance, current-instance, static, inherited static, and `^^` super dispatch; variadic calls remain explicit.

The optimizer is deeper but still proof-driven. v0.1.5 adds block-local scalar CSE/copy propagation, exact scalar interprocedural specialization, fixed-point write-effect summaries that let proven write-free named calls retain caller facts, conservative allocation escape classification, stack promotion for non-captured lexical cells, and GC safe-point elision only where managed reachability provably cannot change. Typed parameter/return contracts are modeled at specialization boundaries, identity-bearing strings are excluded from scalar CSE, calls/heap mutation/unknown effects stay conservative, and exceptional regions remain barriers where necessary. Signed `%` folding uses integer-only truncation-toward-zero math so 64-bit values never round through host floating point.

The bootstrap parser's statement-sequence solver is now iterative rather than one Python frame per statement; a permanent regression parses 2,500 flat statements without depending on the host recursion limit. The v0.1.5 completion groups now contain **44 tests**, including positive/negative trait cases, cross-module state/trait cases, optimizer-vs-unoptimized native differential execution across hundreds of generated scalar expressions, typed-boundary traps, closure-default captures, flow-join lattices, escape/GC behavior, and large-program parsing. Together with every historical group, the isolated release battery now totals **276 tests**.

### v0.1.4 CFG / SSA optimizer milestone

v0.1.4 turns the v0.1.3 typed HIR into an actual optimization boundary. The compiler now lowers checked HIR into deterministic **CFG/SSA MIR** with explicit basic blocks, branch/jump/return terminators, SSA binding versions, and phi nodes at branch and loop merges. Loop-carried mutation is represented explicitly, and Boolean short-circuiting is lowered as control flow rather than as eager operands, so an optimizer cannot accidentally execute a conditional RHS assignment or call. `slug mir file.slg` emits raw MIR and `slug opt-ir file.slg` emits the optimized form.

The first optimizer pipeline performs monotonic SSA constant propagation, safe scalar constant folding, constant-branch simplification, unreachable-block removal, trivial-phi simplification, and conservative dead-value elimination. Checked integer overflow, invalid narrowing casts, calls, heap mutation, allocation, and other effectful/trapping operations are deliberately not optimized away. Arbitrary user/closure/method/constructor calls conservatively clobber visible binding facts until interprocedural effect summaries exist, and try/catch/finally remains an explicit optimization barrier so exceptional control cannot leak stale constants into normal flow.

Optimization is now part of native compilation rather than a side report. The C backend consumes optimizer-proven scalar constants and condition facts while retaining the existing runtime path whenever a proof is unavailable. This means simple expressions such as constant arithmetic are emitted directly, while checked-overflow cases still call the runtime checked operators and trap exactly as before.

This milestone is the **foundation**, not the end of optimization. Exceptional edges are still conservative rather than full SSA CFG edges; interprocedural purity/effect summaries, inlining/specialization, richer flow-sensitive type refinement, escape analysis, stack promotion, move/unique/reference-count specialization, and GC elision remain future optimizer work. v0.1.4 adds **18 optimizer regressions**, bringing the isolated release battery from 211 to **229 tests**.

### v0.1.3 type / IR strengthening milestone

v0.1.3 turns type annotations from mostly call-boundary checks into persistent **binding contracts**.
`a@i8:=...`, `b@u64:=...`, and per-target contracts on broadcast assignments are represented in
the AST, survive crush/expand, persist across later `=`/same-scope `:=` writes, and are enforced both
statically when a value is provably invalid and dynamically when the source value remains unknown.
Contracts are still source-level constraints, not mandatory ownership or representation annotations.

The adaptive integer carrier now covers the full 64-bit unsigned range. Literals through
`FFFFFFFFFFFFFFFF$` are exact `u64` values, signed/unsigned equality and ordering do not round through
`double`, and mixed/unsigned arithmetic remains checked. Plain signed arithmetic retains its existing
overflow contract rather than silently widening into unsigned storage.

A typed high-level IR now sits between semantic analysis and backend lowering. `slug ir file.slg` emits
deterministic `.slgir` containing explicit temporaries, evaluation order, binding contracts, inferred
type facts, calls, allocations, structured-control markers, class constructors/methods/destructors,
and lambda bodies. The C backend consumes the same analyzed contract map, so the HIR is part of the
compiler pipeline rather than a debug-only side representation. This HIR is intentionally structured;
v0.1.4 now lowers it to optimizer-oriented CFG/SSA form without teaching optimization passes the
context-sensitive source grammar.

The v0.1.3 regression group adds **26 tests**, bringing the isolated release battery to **211 tests**.

### v0.1.2 managed lifetime / cycle-collection milestone

v0.1.2 replaces the bootstrap's process-lifetime heap with a compiler-managed lifetime system.
Strings, lists, maps, objects, lexical cells, closures, and error values now live in one tracked native
heap. Generated lexical scopes register their cells as roots while active; escaping closures keep
captured cells reachable through graph edges; module globals and class static fields are permanent
roots until runtime shutdown. Heap management remains invisible in SLUG source.

Collection is graph-tracing and cycle-safe. The runtime marks from active lexical scopes, module/static
roots, exception state, and short-lived compiler-generated temporary roots, then reclaims unreachable
graphs. Self-referential lists/maps, closure/captured-cell cycles, and object cycles are therefore
collectible. This is the correctness-first lifetime foundation; later native optimization may replace
provably unique/local cases with stack lifetime, moves, or reference counting without changing SLUG
semantics.

`~-{...}` destructors are now tied to object reachability instead of only process shutdown. Before an
unreachable object graph is swept, destructors run child-before-parent through the existing class
dispatch. The collector then re-marks roots so a destructor that deliberately makes an object reachable
does not cause that object to be freed underneath the new reference. Exception `longjmp` paths unwind
lexical root frames, `rv` preserves heap-valued results across `fn{}` execution, and loop-temporary
iterables are rooted across per-statement collection safe points.

`SlugResult` arrays are now disposed after calls instead of leaking backend call-result buffers. A
debug-only runtime report is available by setting `SLUG_HEAP_REPORT=1`; it prints managed allocations,
frees, live nodes, peak live nodes, and collection count to stderr. This is a test/debug facility, not
a SLUG language feature. The v0.1.2 lifetime regression group adds 11 tests, bringing the isolated
release battery to **185 tests**.

### v0.1.1 module aliases and active namespaces

v0.1.1 extends module naming without spending SLUG's callable spelling. Aliased imports now accept
one lowercase symbol (`:m`), one two-uppercase symbol (`:MA`), or an extended identifier
(`:_m_a_t_h_`). Exactly two lowercase letters remain callable syntax and are never consumed as one
module alias. The same module can therefore be written for maximum density, visual namespace
distinction, or descriptive source without changing its semantics.

`<:ALIAS` selects an imported module as the active **compile-time lexical namespace**. Bare exported
functions/classes are then resolved from that module first; names absent there fall back to ordinary current-module/direct-import/builtin lookup. Single-character locals remain ordinary values. `<:.` restores the current/default module. Namespace selection inherits into `{}`
blocks and is automatically restored when the block closes; it emits no runtime instruction. The
selector consumes exactly one alias atom, so `<:MA.ma` means "select MA, then immediately use
MA.ma" rather than selecting a hypothetical `MA.ma` namespace. Whitespace remains meaningless.

Explicit qualification remains available (`MA.sq[...]`, `MA.AB.mk[]`), and imported-class static
member/method traversal now works through both explicit aliases and an active namespace. The crusher
understands namespace-resolved AST nodes, so it does not reinsert redundant module qualification.

The v0.1.1 regression set adds 13 namespace/alias tests and brings the isolated release battery to
**174 passing tests**.

### v0.1.0 hardening milestone

v0.1.0 is the first release focused primarily on correctness invariants instead of adding another
large syntax family. Imported modules may now own executable top-level state. Every canonical module
path receives one private lexical namespace, dependency initialization is topological, and diamond
imports share exactly one module instance rather than cloning state through each import path.

The numeric bootstrap runtime is now checked instead of relying on C overflow behavior. Integer
`+`, `-`, `*`, positive-integer `^`, unary negation, and narrowing integer casts trap on overflow;
large int64 operations and comparisons no longer round through `double`. Typed function/lambda/class
parameters are cast/validated at their call boundary, and typed returns keep the same width checks.
At the v0.1.0 milestone the tagged carrier was still signed-64, so literals above
`0x7FFFFFFFFFFFFFFF` were rejected. v0.1.3 supersedes that limitation with an exact signed/unsigned
64-bit adaptive carrier through `UINT64_MAX`.

Structural equality is now graph-aware rather than depth-capped. Independent cyclic lists/maps/objects
can be compared without recursion loops, while deeply nested acyclic values no longer become unequal
just because they cross an arbitrary recursion depth.

Hardening regressions also exercise random whitespace layouts over the same token stream, textual and
semantic `crush` fixed points, deterministic C emission, module initialization order, diamond imports,
checked numeric boundaries, cyclic equality, and deep structural equality. The v0.1.0 hardening battery originally contained **161 passing tests** in isolated groups.

### v0.0.10 lambdas, closures, exceptions, and modules milestone

v0.0.10 adds first-class callable values and the remaining major high-level control machinery.
`lb...{}` lambdas lower natively, `!f[...]` invokes callable values, and escaping closures keep
lexical bindings alive by reference so mutable captures continue to work after the defining frame
returns. Lambda defaults, `xx`, variadic tails, multiple returns, nested closures, and closures that
capture the current object are covered by native regressions.

Exceptions now execute with `tr{}`, `ca{}`, `cae{}`, `fn{}`, and `er`. Non-error raised values are
wrapped as `ER(...)`; nested rethrow works; and `fn{}` executes across normal completion, exceptions,
returns, `bl`, and `cl`. Uncaught errors terminate with a nonzero exit after required finally cleanup.

File-aware compilation now resolves native SLUG imports. `>'path'` directly imports public symbols;
aliased imports may use `:m`, `:MA`, or an extended alias, with access such as `m.ab[...]`, `MA.AB[...]`, or namespace selection via `<:`. Nested imports, cycles,
direct-name collisions, alias collisions, imported inheritance, private module implementation, and
imported functions returning escaping closures are regression-tested. The v0.1 linker supersedes v0.0.10's declaration-only restriction: imported modules may now execute module-global initialization and retain private mutable module state.

The parser's cyclic-GC scheduling was also corrected: large ambiguity searches temporarily defer
Python's cyclic collector, then the module-level `parse()` wrapper releases the Parser and its candidate
caches before collection. Release tests run in isolated test-class processes because the bootstrap
Python host still accumulates enough allocator state across repeated crush/native stress tests to make
a single monolithic test process unnecessarily slow; this isolation does not change SLUG semantics.

The v0.0.10 release battery contains **139 passing tests** across parser/semantic checks, native
execution, crush/expand equivalence, OOP, closures, exceptions, imports, and the readable/crushed/
expanded implicit gauntlet.

### v0.0.9 native OOP milestone

v0.0.9 turns the class/member syntax that earlier bootstraps only recognized into executable
native objects. Constructor parameters live on `#AB...{}` declarations; class-body field
definitions initialize each instance; `.x`/`..x` address current instance/static state; and
`a.x`, `a.ab[...]`, `AB.x`, and `AB.ab[...]` lower through the native C bootstrap runtime.

Single inheritance now executes too. `^^[...]` explicitly invokes a required parent constructor,
parents whose required arguments are fully covered by defaults auto-initialize, ordinary overriding
uses dynamic dispatch, and `^^.ab[...]` directly names the parent implementation. Private fields and
methods use the existing `-` declaration prefix and are rejected from external access. `==` compares
object structure while `===` compares object identity. `~-{...}` destructors run child-before-parent
for bootstrap-owned objects at shutdown.

The OOP parser also extends SLUG's implicit-boundary rules rather than retreating to separators:
adjacent `.x:=x.y:=y` field definitions need no semicolon, `.x.y+` can become `.x .y +` when RPN
requires two operands, while explicit two-letter method packs such as `a.sp[]` bind as hard postfix
syntax. This same rule fixes private/static streams such as `-~~gt{...}~~ok{rv..gt[]}` without
letting the one-letter field reading steal the method call.

v0.0.9 retains the v0.0.8 native named-function milestone: fixed/defaulted/typed parameters, `xx`,
return contracts, zero/one/multiple returns, multiple-return assignment, variadics, recursion, mutual
forward references, and module-global access all lower through native call frames. Parser sequence
memoization remains per-parser so completed parses can be garbage-collected. Crush now removes
terminators with deterministic proof-driven chunk elimination instead of spawning worker processes.

The final release battery contains the original scalar/control/collection/function tests plus OOP
examples, semantic rejection tests, native inheritance/dispatch/destruction tests, and the readable,
crushed, and expanded implicit gauntlet.

### v0.0.7.1 Windows UTF-8 hotfix

Native SLUG text is UTF-8. On Windows, v0.0.7 correctly emitted UTF-8 bytes but the
Python test harness decoded redirected stdout with the machine ANSI code page (cp1252),
and an inherited PowerShell console could render the same bytes through an OEM code page.
v0.0.7.1 makes UTF-8 explicit end-to-end: generated Windows executables initialize the
console to UTF-8, `slug run` captures/decodes native output as UTF-8 before writing it to
the terminal, and native tests decode subprocess output as UTF-8 rather than relying on
locale defaults.

### v0.0.7 collections + heap-runtime milestone

v0.0.7 adds executable collections instead of only parsing collection-shaped syntax. Mutable
and frozen lists/maps now lower natively, along with indexing, negative indices, slicing,
Unicode code-point string indexing/slicing, `in`, `iv`, `ln`, `sl`, map/list element updates,
structural collection equality, collection identity, foreach, and sliced-iterable loops.

`::=` still freezes only the binding; `@[...]` freezes the collection. `m[k]=x` updates an
existing key while `m[k]:=x` creates/updates and yields the assigned value. Strings remain
immutable and index/slice by Unicode code point. v0.0.7 initially used process-lifetime heap-backed list/map representations. That historical
bootstrap limitation is superseded by v0.1.2's managed graph lifetime runtime.

The crusher also gained a proof-first all-semicolon fast path. A genuinely terminator-free
program such as the implicit gauntlet is proven in one parse instead of reparsed once per
possible boundary.

### v0.0.6 Boolean + control-flow milestone

v0.0.6 turned the parser proof into a language that can actually make decisions. Boolean
`?` mode, comparisons, short-circuit `+`/`/`, `!`, standalone conditionals,
`if`/`ei`/`ee`, `wl`, counted `fl`, numeric-range `fl`, `bl`, and `cl` parse,
round-trip through crush/expand, and lower to native C. Block-local `:=` shadowing is also
preserved by the backend instead of being flattened into one global C variable namespace.

### v0.0.5 implicit-boundary correction

v0.0.5 fixes the parser behavior exposed by the semicolon-free gauntlet. Adjacent
assignments now form statement boundaries when the preceding RHS is already complete;
assignment expressions are still embedded when later RPN syntax requires them. Prefix
casts also stop before a provable following assignment instead of greedily swallowing
subsequent statements. Extended-name closing underscores are now true lexical endpoints, so
`co_x_Y_co_n_` needs neither whitespace nor a semicolon. The implicit gauntlet and its
crushed `.slgc` now both contain **zero semicolons**.

### v0.0.5 ambiguity-gauntlet pass

v0.0.5 adds a much harsher `implicit_gauntlet.slg`: one program intentionally combines
callable-looking assignment targets, class-vs-hex collisions, contextual digit
partitioning, unary/binary RPN ambiguity, nested `:=`, fixed-width casts, lists/frozen
lists, callable-value syntax, private/static declarations, inheritance, preserved
comments, mutations, extended names, and deep RPN stacks. Its `.slg`, `.slgc`, and
re-expanded `.slg` forms are all checked for the same AST and native output.

Earlier gauntlet passes exposed two compiler issues that remain covered here: `~~` static
declarations were lexed but not parsed correctly, and parser deduplication was spending
most of its time rendering giant ASTs with `repr()`. The latter is removed; large crush
passes also probe removable boundaries in parallel and verify the combined result before
accepting it.

## Source forms

- `.slg` — normal human-readable/formatted SLUG source.
- `.slgc` — AST-equivalent crushed SLUG source produced by `slug crush`.

`slug expand` goes the other direction: it parses `.slgc` and regenerates roomy `.slg`
with indentation and one logical statement per line. The formatter operates on the AST,
not by adding spaces blindly.

### Surviving comments (bootstrap convention)

Ordinary comments are discarded by `slug crush`. This bootstrap currently treats:

```slug
//! this line comment survives crush
/*! this block comment survives crush */
```

as crush-surviving comments. They are still source metadata and do **not** enter the
native executable. The marker is intentionally centralized in the lexer so it can be
changed if the final SLUG syntax chooses a different spelling.

Nested `/* ... */` comments are supported.

## Install

From PowerShell in this folder you can run it immediately, with no installation:

```powershell
py .\slug.py check examples\cursed_counter.slg
py .\slug.py crush examples\cursed_counter.slg
py .\slug.py expand examples\cursed_counter.slgc
py .\slug.py run examples\cursed_counter.slg
```

If you want a global-ish `slug` command while developing the project:

```powershell
py -m pip install -e . --no-build-isolation
```

Then the same commands become `slug check ...`, `slug crush ...`, and so on.

`slug build` / `slug run` currently use Clang, GCC, `cc`, or MSVC `cl` when available.
On Windows, Clang is the simplest initial route.

## Current commands

```text
slug check file.slg
slug ast file.slg
slug crush file.slg [-o file.slgc]
slug expand file.slgc [-o file.slg]
slug ir file.slg [-o file.slgir]
slug mir file.slg [-o file.mir]
slug opt-ir file.slg [-o file.opt.mir]
slug emit-c file.slg [-o file.c]
slug build file.slg [-o program.exe] [--cc clang] [--keep-c generated.c]
slug run file.slg [--cc clang]
```

## What is real already

The current front end is context-sensitive on purpose. It already demonstrates several
of the rules that make SLUG unusual:

- Lowercase one-character variables only (`a`–`z`).
- Two-uppercase class names and two-lowercase named callables.
- Extended `_x_` / `_n_e_x_t_` names.
- Whitespace-insensitive parsing.
- `:=`, `::=`, and statement-only `=` distinction.
- Multiple assignment targets for `=`.
- RPN `+ - * / % ^` and postfix `++` / `--` statements.
- Prefix casts such as `@i`, including `@iab/` => `@i(a b /)`.
- Hexadecimal integer source syntax, including digit-only integers without `$`.
- Contextual digit partitioning: `10` is hexadecimal 0x10 when one value is needed,
  but `52/` becomes `5 2 /` because RPN division needs two operands.
- `ABA$` is integer 0xABA unless a known class `AB` has a valid constructor parse,
  in which case `AB(A$)` wins.
- Built-ins currently registered: `co`, `ci`, `in`, `iv`, `ln`, `sl`.
- `ci'prompt'` and `coa` arity-directed parsing.
- Native named functions with required/defaulted/typed parameters, `xx`, optional return contracts,
  zero/one/multiple `rv` values, recursion, module-global access, explicit call packs, and variadics.
- Multiple-return assignment follows SLUG's broadcast/left-to-right rules; variadic tails become lists.
- Native classes/objects with constructor parameters, instance/static fields, instance/static
  methods, privacy, single inheritance, parent construction, overriding, `^^` super dispatch,
  structural-vs-identity object equality, and `~-{}` destructor chains.
- First-class native lambdas via `lb`, callable-value invocation via `!f[...]`, lexical capture by
  binding, escaping mutable closures, lambda defaults/`xx`, variadic tails, and multiple returns.
- Native `tr`/`ca`/`cae`/`fn`/`er` exception control with finally unwinding across returns and loops.
- File-aware `>` imports with direct public-symbol import and aliased module access; nested imports and
  imported classes/functions/closures are linked into one native program.
- Immutable binding checks for `::=`.
- `slug crush` reparses its own output and refuses to accept a changed semantic AST.
- `slug expand` works from the parsed AST.
- Native bootstrap backend for scalar integers/floats/strings/null, arithmetic, casts,
  assignments, increment/decrement, `co`, and `ci`.
- `?` Boolean mode with truthiness, `== != < > <= >= === !==`, `!`, short-circuit AND `+`,
  and short-circuit OR `/`; arithmetic RPN remains valid inside comparison operands.
- Standalone `?condition{}`, `if`/`ei`/`ee`, `wl`, `bl`, `cl`, counted `fl`, and
  stop-exclusive numeric-range `fl` lower natively.
- Control-flow blocks now preserve SLUG lexical shadowing: `:=` creates/updates the current
  block binding while plain `=` still reaches the nearest existing binding.
- `0^0` returns 1; `0` to a negative power errors at runtime.

For example, this valid crushed program:

```slug
a:=9a++coa
```

builds natively and prints:

```text
10
```

And:

```slug
a:=5b:=2x:=@iab/r:=ab%coxcor
```

prints:

```text
2
1
```

## Important bootstrap boundary

This is **v0.1.7.1**, the Windows-link hotfix over the native-capability bootstrap milestone, not the final language/runtime. The major planned language surface now lowers through native code: scalars, collections, control flow, named functions, classes/inheritance, interfaces/traits, lambdas/closures, exceptions, file imports, and shared exported module state. The architecture still deliberately separates lexer, constraint parser, semantic analysis, formatter/crusher, linker, typed HIR, CFG/SSA MIR, optimizer, and backend so self-hosting work can harden implementation details without redefining source syntax.

The remaining work is primarily the self-hosting/Ouroboros phase and optional deeper performance specialization, not a known missing core source feature. The runtime still keeps graph tracing as the semantic fallback; escape classes are conservative, only lexical cells with complete non-capture proofs are stack-promoted, and broader object/collection stack allocation, unique/move/reference-count specialization, richer interprocedural inlining, and fully explicit exceptional SSA edges remain future optimization opportunities. These are performance/compiler-engineering milestones rather than prerequisites for ordinary SLUG semantics.


## Example / torture battery

Version 0.1.5 includes ten focused `.slg` programs under `examples/basic/`, five native
control-flow programs under `examples/control/`, six collection programs under `examples/collections/`,
six named-function programs under `examples/functions/`, seven native OOP programs under
`examples/oop/`, five closure/lambda programs under `examples/closures/`, five exception programs
under `examples/exceptions/`, seven module/import programs under `examples/modules/`, two hardening programs under `examples/hardening/`, three lifetime programs under `examples/lifetime/`, three type/IR programs under `examples/type_ir/`, three optimizer programs under `examples/optimizer/`, four pre-self-hosting completion programs under `examples/completion/`, the original
`examples/torture/compiler_torture.slg`, and the much denser
`examples/torture/implicit_gauntlet.slg`. On Windows, run the whole battery from the
project root with:

```powershell
.\run_examples.ps1
```

All ten basic programs compile and run through the native backend; basic 10 now proves contextual
`ABA$` class-vs-hex parsing through class construction as well. The OOP programs and both torture
programs are checked, crushed/expanded for AST equivalence, executed natively, and covered by unit
tests. See `examples/README.md` for each case and expected output.

The torture passes have exposed several real bootstrap bugs now covered by regressions:

- unary `-` now remains a candidate on the top RPN operand even with deeper stack state,
  so `23-^` can resolve to `2^(−3)`;
- `ab[...]` now has lexical priority as an explicit callable argument pack rather than
  also being reinterpreted as an inferred call receiving a list literal;
- nested `:=` bindings are recursively collected by the native backend;
- type-width parsing consumes digits only for real width codes, so `@s10` is
  `@s(0x10)` and `@i52/` is `@i(5 2 /)`;
- crush equivalence ignores literal source spelling (`3` versus `3$`) while preserving
  semantic value;
- the crusher/expander now retain real `$`, `[]`, and `;` boundaries when whitespace
  would otherwise change the AST.

## Tests

For the release battery, use the isolation runner:

```powershell
py .\tests\run_release_tests.py
```

`run_examples.ps1` invokes the same runner after executing all examples. The tests are intentionally
separated into fresh Python processes by test class so repeated giant ambiguity/crush workloads cannot
accumulate bootstrap-host allocator/GC state and distort runtime. The same complete battery is executed in isolated groups; v0.1.7.1 currently totals 323 ordinary tests, with SALT retained as a separate deliberately heavy acceptance gate.

The v0.1.5 suite retains every previous scalar/control/collection/function/OOP, closure, exception, module, lifetime, type/IR, and v0.1.4 optimizer regression. It adds interfaces/traits and default conflicts, imported interfaces, public shared module bindings, external contract enforcement, broader inferred member calls, branch/loop/exception type joins, common-base class phis, typed interprocedural specialization boundaries, write-effect summaries, scalar CSE identity safety, escape classification, lexical-cell stack promotion, GC safe-point elision guards, closure-default capture lifetime, exact 64-bit remainder folding, optimizer-vs-unoptimized differential execution, inherited static module metadata, diamond-state linking, and large flat-program parser scalability.


## Ouroboros target

The intended progression is:

```text
Python bootstrap compiler
        ↓
working SLUG compiler/runtime
        ↓
compiler rewritten in SLUG
        ↓
SLUG compiles SLUG
```

A later reproducible-build milestone can compile the SLUG compiler with itself repeatedly
and compare the resulting compiler binaries/behavior.

## K9E — manifest-driven local projects

K9E introduces strict `slug.json` schema 1 project discovery and a deterministic local dependency namespace without changing SLUG 1.0 expression/runtime semantics. `slug check`, `slug build`, and `slug run` may discover the nearest manifest when their source argument is omitted; explicit-source behavior remains compatible. `@dep/<name>/<exact-file.slg>` resolves only through the root manifest's project-relative dependency map, while ordinary relative imports and reserved `@std/*` retain their K9D1 rules. Network fetching, version solving, lockfiles, and implicit source lookup are intentionally deferred.

## K9F — native tooling handshake and transform-boundary hardening

K9F adds schema-1 `tooling-info` and `project-info` JSON handshakes for editor integration while keeping the installed compiler Python-free. Existing formatter/crusher/expander behavior receives a permanent 23-case tooling safety gate. A parser-span instrumentation experiment was explicitly rejected because it materially slowed the ambiguity-aware self-host parser; K9F therefore adds no bookkeeping to the parse hot path.

## K9G — native-backed LSP bridge

K9G adds a dependency-free Node.js stdio LSP bridge over the native compiler tooling contract. It introduces stdin root-source overlays (`tooling-check` / `tooling-format`) so unsaved editor buffers retain their real logical path for relative imports and project discovery without creating or overwriting source files. The LSP server implements initialization/shutdown, full-text synchronization, publishDiagnostics, document formatting, and read-only tooling/project context requests. Language semantics, project manifest schema, provider linkage, and diagnostic schema remain frozen from K9F/K9E/K9D1.

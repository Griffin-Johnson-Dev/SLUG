# SLUG 1.x Standard Runtime Module Surface

This file records the current public standard-module identities and capability export names for the SLUG V1 line implementing language contract 1.0. These names are explicitly namespaced and do not expand the nine-name root builtin grammar.

| Module | Current V1 exports |
| --- | --- |
| `@std/sys` | `av`, `ev`, `cw`, `pf`, `cp`, `pc` |
| `@std/time` | `tm`, `mt`, `wt` |
| `@std/rand` | `en` |
| `@std/fs` | `fr`, `ft`, `fw`, `fa`, `fe`, `fd`, `fm`, `md`, `rm`, `mv`, `fo`, `hr`, `hw`, `hs`, `hp`, `hf`, `hc` |
| `@std/net` | `so`, `cn`, `bn`, `ls`, `ac`, `sd`, `rc`, `sc`, `gp` |
| `@std/gfx` | `sf`, `px`, `rf`, `dl`, `sb`, `wn`, `wf`, `pe`, `wx` |
| `@std/audio` | `au`, `aq`, `ax` |
| `@std/dev` | `do`, `dv`, `dr`, `dw`, `dx` |
| `@std/list` | `ap`, `ip`, `rm`, `pp` |

### `@std/list` — mutable-list operations

Compiler 1.0.2 adds this explicit namespaced module as a backward-compatible V1 capability addition; language version remains 1.0.

Import with `>'@std/list':LI`. Because `LI` is an ordinary module alias, calls may stay explicit (`LI.ap[a,x]`) or the module may be selected with `<:LI` for bare `ap[...]`, `ip[...]`, `rm[...]`, and `pp[...]` calls. The normal active-namespace ambiguity rule still applies.

- `ap[list,value] -> list` appends `value` in place and returns the same list.
- `ip[list,index,value] -> list` inserts before `index` and returns the same list. Index `ln[list]` inserts at the end; negative indexes normalize from the current end. Out-of-range indexes error.
- `rm[list,value] -> Boolean` removes the first element structurally equal (`==`) to `value`; it returns `true` when an element was removed and `false` when no match exists.
- `pp[list] -> value` removes and returns the final element. `pp[list,index] -> value` removes and returns the indexed element; negative indexes follow ordinary list indexing. Empty/out-of-range pops error.

All four operations reject frozen lists. `rm` is intentionally distinct from `@std/fs.rm`; explicit module namespaces permit the same compact export spelling to have module-specific meaning.

`@std/sys.cp` is the capability-query operation. It accepts canonical operation identifiers such as `@std/fs.fr` and returns false for unknown/future identifiers rather than reserving new root names.

A SLUG 1.x release may add an explicit standard module or export only when doing so does not silently reinterpret already-valid source. Module URIs under `@std/` are resolved by the language distribution and never by working-directory, package, or network search.

The detailed argument/return/error behavior remains defined by the audited implementation contract and API reference generated for the release. Unsupported platform facilities raise catchable capability errors.

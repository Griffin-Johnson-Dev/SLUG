# SLUG 1.0 Standard Runtime Module Surface

This file records the public standard-module identities and the capability export names implemented for SLUG 1.0. These names are explicitly namespaced and do not expand the nine-name root builtin grammar.

| Module | v1.0 exports |
| --- | --- |
| `@std/sys` | `av`, `ev`, `cw`, `pf`, `cp`, `pc` |
| `@std/time` | `tm`, `mt`, `wt` |
| `@std/rand` | `en` |
| `@std/fs` | `fr`, `ft`, `fw`, `fa`, `fe`, `fd`, `fm`, `md`, `rm`, `mv`, `fo`, `hr`, `hw`, `hs`, `hp`, `hf`, `hc` |
| `@std/net` | `so`, `cn`, `bn`, `ls`, `ac`, `sd`, `rc`, `sc`, `gp` |
| `@std/gfx` | `sf`, `px`, `rf`, `dl`, `sb`, `wn`, `wf`, `pe`, `wx` |
| `@std/audio` | `au`, `aq`, `ax` |
| `@std/dev` | `do`, `dv`, `dr`, `dw`, `dx` |

`@std/sys.cp` is the capability-query operation. It accepts canonical operation identifiers such as `@std/fs.fr` and returns false for unknown/future identifiers rather than reserving new root names.

A SLUG 1.x release may add an export to an explicit standard module only when doing so does not silently reinterpret already-valid source. Module URIs under `@std/` are resolved by the language distribution and never by working-directory, package, or network search.

The detailed argument/return/error behavior remains defined by the audited implementation contract and API reference generated for the release. Unsupported platform facilities raise catchable capability errors.

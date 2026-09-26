# SLUG v1 Audit-to-Spec Crosswalk

This file maps the consolidated public specification to the historical audit areas so future edits can be checked against the decisions that produced v1.

| Public spec area | Primary audit decisions |
| --- | --- |
| source/encoding/comments/names | recovered 1–6, #75–#86, #154–#155 |
| scope/assignment/calls/returns/order | #87–#95, #152 |
| types/casts/numbers/operators | #96–#107, #149, #151, #153, #166 |
| collections/strings/bytes/iteration | #108–#126, #156–#159 |
| errors/finally/resources/finalizers | #127–#133, #160, #163, #167 |
| OOP/interfaces/modules | #134–#140, #165 |
| transforms/optimizer/GC/backend boundaries | #141–#150, #162, #168–#169 |
| release conformance | blocker closure A12 and section D |

The crosswalk is guidance, not a second specification. If the historical text includes transitional implementation notes, the consolidated public specification governs current v1 semantics.

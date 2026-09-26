# SLUG v1 Authority and Stability Order

For SLUG 1 development and release decisions, use this authority order:

1. `docs/SLUG_V1_SPECIFICATION.md` — normative public language semantics.
2. `docs/SLUG_PUBLIC_CLI_V1.md` — normative public compiler CLI contract.
3. `docs/SLUG_V1_STANDARD_MODULES.md` — v1.0 standard-module identities/export surface.
4. audited v1 conformance tests — executable acceptance evidence.
5. `recovery_authority/SLUG_V1_RELEASE_BLOCKER_CLOSURE_2026-09-21.md` — normative rationale where the consolidated spec is silent.
6. `recovery_authority/SLUG_V1_LANGUAGE_AUDIT_CHECKPOINT_2026-09-21.md` — historical audit rationale.
7. older recovery/checkpoint documents — development provenance only.

The implementation does not become normative merely because it currently behaves a certain way. If implementation behavior contradicts the specification, the implementation is the bug unless the specification is intentionally revised under the compatibility/versioning rules.

SLUG language version and compiler implementation version are independent. `LANGUAGE_VERSION` records the language contract. `CLI_CONTRACT_VERSION` records the public CLI compatibility contract.

## Pre-release identifier amendment

Before the public 1.0.0 release, the extended-identifier spelling was simplified from the audit-era underscore-separated character form to the canonical `_[A-Za-z0-9]+_` form. This is a pre-release contract amendment, not a post-1.0 compatibility change. The canonical specification and `PUBLIC_CONTRACT.json` govern. Historical recovery/audit documents retain the old spelling only as provenance.

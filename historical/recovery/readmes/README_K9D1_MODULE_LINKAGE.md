# K9D1 provider-aware module linkage

K9D1 closes the pre-release user-source-module linkage blocker carried from K9D/K9D-ID and preserves one provider identity across aliases, direct imports, nested/diamond graphs, mutable exported storage, classes/statics, namespaces, and imported inheritance.

The permanent module-linkage gate contains 32 cases: 20 provider/linkage cases and 12 imported-inheritance constructor/privacy/redeclaration cases. Installed-project acceptance also exercises an aliased user module whose provider has a nested direct dependency.

K9D1 additionally removes a bootstrap-scale parser performance regression introduced while adding provider-aware module resolution. Non-module syntax now rejects before module-registry/namespace work, module-variable writes use deterministic syntax detection instead of a second full expression parse, and explicit standard-module aliases no longer compete through two qualified parse paths.

Canonical K9D1 seed:

- compiler version: `0.9.0-dev+k9d1`
- generated C bytes: `3,076,922`
- SHA-256: `806b91ead33acd82234ea0691968142de68067e368a348ce532cf486de7bbc72`
- fixed point: native generation reproduces the canonical C byte-for-byte

See `K9D1_IMPLEMENTATION_MANIFEST.json` for the machine-readable proof summary and `tests/run_v1_module_linkage.py` for the permanent linkage corpus.

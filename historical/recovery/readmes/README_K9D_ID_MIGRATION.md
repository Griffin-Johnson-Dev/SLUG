# K9D-ID extended identifier migration

SLUG 1.0 extended identifiers use `_[A-Za-z0-9]+_`: a leading underscore, one or more ASCII alphanumerics, and a trailing underscore. Names are case-sensitive; interior underscores terminate an identifier rather than belonging to it. `_1_` is valid.

This supersedes the pre-release underscore-between-every-character spelling. Compiler sources, tests, examples, formatter/crusher behavior, public contract metadata, and the self-host bootstrap seed are migrated together. See `docs/SLUG_V1_SPECIFICATION.md` and `K9D_ID_MIGRATION_MANIFEST.json`.

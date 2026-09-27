"""Read-only data-source adapters: csv, parquet, postgres.

Mirrors design.md 6.1. An adapter only materialises a source into a derived snapshot;
it performs no joins and no derivations — complex derivation belongs in a SQL view
maintained by the data owner.

The postgres adapter's read-only guarantee comes from database account permissions,
not from code (design.md principle 3); ``causpec-mcp doctor`` verifies that the
account genuinely cannot write.

Not implemented yet — see plan.md Phase 1 task 1 and Phase 3 task 3.
"""

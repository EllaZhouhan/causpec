"""Lightweight mapping from source columns to the canonical schema.

Mirrors design.md 6.4. Six operations only (rename, cast, recode_null,
map_categories, unit_convert, aggregate over a window) and **no arbitrary
expressions**: the mapping is drafted by the agent and confirmed by the user, so a
smaller surface is a reviewable one.

This package also holds the variable catalogue (design.md 6.2): source column, unit,
measurement window relative to time zero, aggregation. Without a measurement window
the post-treatment check can only report `suspected`.

Not implemented yet, see plan.md Phase 1 task 2.
"""

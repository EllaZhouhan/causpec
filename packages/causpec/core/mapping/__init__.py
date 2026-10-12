"""Lightweight mapping from source columns to the canonical schema.

Mirrors design.md 6.4. Six operations only (rename, cast, recode_null,
map_categories, unit_convert, aggregate over a window) and **no arbitrary
expressions**: the mapping is drafted by the agent and confirmed by the user, so a
smaller surface is a reviewable one.

Two of the six operations are implemented, ``recode_null`` and ``cast``, because those are
the two any check can currently suggest and an operation no caller can reach is an operation
nobody reviews. See ``operations.py``; the rest wait for a caller.

The lightweight column mapping is still open (plan.md Phase 1 task 2).

The variable catalogue of design.md 6.2 was dropped. Its only consumer with teeth was a
post-treatment check that is not being built, and what it would have stored is already in
the spec, in the user's own words: when they confirm a covariate, `said` carries "the maximum
over the first 24 hours" and the report prints it. A second home for the same fact, with
nothing keeping the two in agreement, is a document that drifts while people still trust it.
"""

from causpec.core.mapping.operations import PreprocessingError, StepRecord, apply

__all__ = ["PreprocessingError", "StepRecord", "apply"]

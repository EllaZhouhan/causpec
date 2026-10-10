# ADR-0003: The basic layer is written by hand, not with pandera

- Status: accepted
- Date: 2026-10-11

## Context

design.md 8.1 named pandera as the implementation of the basic check layer, with
"NULL-variant detection written here". plan.md Phase 1 task 4 repeated it, and
THIRD_PARTY_NOTICES listed it. Implementing the layer made the trade-off concrete, and it
came out the other way.

What pandera offers is a declarative DataFrame schema: dtype, range, nullability and
uniqueness per column, validated in one call, with failure cases returned as a frame.

## Decision

Write the basic layer by hand. Remove pandera from the dependency list, from design.md 8.1
and from THIRD_PARTY_NOTICES, since no code and no practice is taken from it.

## Why

**The checks it would perform are one pandas call each.** `is_numeric_dtype`, `isna().sum()`,
`duplicated(subset=key)`. There is no complexity here for a library to absorb.

**The output format is the work, and pandera does not produce it.** Every check in this
project emits a `QualityIssue` carrying a severity from a config file, an addressed evidence
dictionary for the report to cite, the columns affected, what the problem does to the
analysis, and a suggested repair. Pandera returns failure cases. Translating those into
issues, and attaching the impact and repair text, is most of the code either way, so the
library would sit between the data and a layer that has to be written regardless.

**There are no declared ranges to validate.** Pandera's value grows with the schema, and this
project has no per-column clinical ranges: the spec names which columns are the treatment,
the outcome and the covariates, and nothing declares that creatinine lies in [30, 900].
Asking the user to declare ranges for forty covariates would be a worse workflow than the
one check that actually matters.

**That check is the one pandera does not do.** NULL-variant detection was already marked
"written here" in the design. It is also where the value of this layer is concentrated: a
missing value eventually reaches a nuisance regression and complains, while a sentinel does
not fail anywhere. A creatinine column holding -999 for "not measured" is arithmetic all the
way down, every other check passes, and the conclusion becomes a statement about an export
convention.

So the dependency would carry the easy third of the layer, in a format that has to be
rewritten, while the hard part stays hand-written either way.

## Consequences

- One fewer direct dependency. design.md's dependency policy lists four; this removes one of
  them and the remaining three (EconML, DoWhy, DoubleML) all carry estimation or diagnostics
  that would be substantial to reimplement, which is the test this one failed.
- The thresholds live in `core/quality/basic_checks.yaml`, the same pattern as the
  claim-level rules, and the manifest records its hash: change what counts as a placeholder
  and the same data can pass or block.
- If range validation is ever wanted, this decision should be revisited rather than worked
  around. Per-column ranges are where pandera earns its place, and a schema declared once
  per deployment is a different proposition from a schema derived from a spec.

## What would make this wrong

If the basic layer grows to the point where the schema is the artefact: ranges per column,
coercion rules, a schema versioned and shared across deployments. At that point the
declarative form is worth the translation layer, and this ADR should be superseded rather
than patched.

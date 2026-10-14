# Architecture decision records

One file per significant decision, recording **the situation at the time, what was
chosen, why, and what was rejected**.

## What belongs here

Only three kinds:

1. **Things the design document does not cover, discovered during implementation**,
   e.g. 0001
2. **Genuine trade-offs, where an alternative was rejected**
3. **Counter-intuitive decisions someone will later try to "simplify" away**: e.g.
   the counter-check in 0001

**Do not** record decisions the design document already explains. Copying design.md
into an ADR is pure duplication, and the two will drift apart. "Computation on the
server", "field-level confirmation" and "the core/family split" all fall into that
category: they are in design.md, and each has an executable counterpart (the gate code,
the import-linter contract).

## Existing records

| Number | Subject | Status |
|---|---|---|
| [0001](0001-literal-numbers-in-reports.md) | Literal numbers in report prose (the `lit:` namespace) | accepted |
| [0002](0002-data-source-boundary.md) | Data-source boundaries (enforcing `root` / `allowed_relations`) | proposed |
| [0003](0003-basic-checks-without-pandera.md) | The basic check layer is written here, not with pandera | accepted |
| [0004](0004-linearmodels-for-overidentification-only.md) | linearmodels for one statistic, the robust overidentification test | accepted |

## How to write one

Copy `0000-template.md`, increment the number, name the file `NNNN-short-title.md`. A
superseded decision is **not deleted**; set `status: superseded by ADR-NNNN`.

The "options rejected" section is worth more than the rationale, six months later it
is what shows you had in fact thought of the alternative.

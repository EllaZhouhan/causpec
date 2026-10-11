"""Applying the preprocessing steps a user agreed to.

Mirrors design.md 6.4. Two operations are implemented, `recode_null` and `cast`, because
those are the two any check can currently suggest, and an operation no caller can reach is
an operation nobody reviews. The other four in the design (rename, map_categories,
unit_convert, aggregate over a window) wait for a caller.

Three properties hold whatever is added later.

**The source is never touched.** Steps return a new frame. The read-only guarantee on the
data source is a safety boundary rather than a convenience (ADR-0002), and a preprocessing
step that wrote back would quietly make it unenforceable.

**Order is part of the meaning.** Recoding a sentinel to missing and then casting is not the
same as casting first: a lenient cast would turn "-999" and "NA" alike into missing values
with no record that it had happened, which is the whole thing this layer exists to prevent.
So `cast` is strict and refuses what it cannot convert, and the recode has to come first and
be written down.

**Nothing here repairs anything.** Recoding a sentinel to missing does not fix the data; it
converts a hidden problem into a visible one, and the missingness check then says so. That
is the point. A step that made a blocking check pass by concealing what it was reporting
would be worse than no step at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.spec import PreprocessingStep

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


class PreprocessingError(Exception):
    """A step could not be applied. Structured enough to tell the user what to do."""


@dataclass(frozen=True)
class StepRecord:
    """What one step actually did, for the report to print.

    A step that changed nothing is worth seeing: it usually means the column was not what the
    user thought it was.
    """

    op: str
    column: str
    detail: str
    rows_changed: int

    def describe(self) -> str:
        return f"{self.op} on {self.column}: {self.detail} ({self.rows_changed:,} rows)"


def apply(
    data: pd.DataFrame, steps: list[PreprocessingStep]
) -> tuple[pd.DataFrame, list[StepRecord]]:
    """Apply every step in order to a copy, returning the copy and what each one did."""
    if not steps:
        return data, []
    working = data.copy()
    records: list[StepRecord] = []
    for step in steps:
        if step.column not in working.columns:
            raise PreprocessingError(
                f"{step.op} names column {step.column!r}, which is not in the data. "
                f"Columns are set before preprocessing, so this is a typo in the spec rather "
                f"than something an earlier step removed."
            )
        if step.op == "recode_null":
            working, record = _recode_null(working, step)
        else:
            working, record = _cast(working, step)
        records.append(record)
    return working, records


def _recode_null(data: pd.DataFrame, step: PreprocessingStep) -> tuple[pd.DataFrame, StepRecord]:
    """Replace the named values with missing, leaving everything else alone.

    Matching is by value and, for text, case-insensitively after stripping, because "NA",
    "na" and " NA " are the same placeholder and asking the user to enumerate the spellings
    would be asking them to do the computer's work.
    """
    column = data[step.column]
    targets_text = {str(value).strip().lower() for value in step.values}
    targets_numeric: set[float] = set()
    for value in step.values:
        try:
            targets_numeric.add(float(value))
        except (TypeError, ValueError):
            continue

    raw = np.asarray(column, dtype=object)
    matched = np.zeros(len(raw), dtype=bool)
    for index, value in enumerate(raw):
        if value is None:
            continue
        if isinstance(value, str):
            matched[index] = value.strip().lower() in targets_text
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            matched[index] = str(value).strip().lower() in targets_text
            continue
        if np.isnan(number):
            continue
        matched[index] = number in targets_numeric

    out = data.copy()
    if matched.any():
        out.loc[matched, step.column] = np.nan
    shown = ", ".join(str(value) for value in step.values)
    return out, StepRecord(
        op="recode_null",
        column=step.column,
        detail=f"{shown} treated as missing",
        rows_changed=int(matched.sum()),
    )


def _cast(data: pd.DataFrame, step: PreprocessingStep) -> tuple[pd.DataFrame, StepRecord]:
    """Convert a column to numbers, refusing anything that is not one.

    Strict on purpose. `pd.to_numeric(errors="coerce")` would turn every unconvertible value
    into a missing one, which is a recode nobody declared and nobody can see afterwards. If a
    value here is a placeholder, it needs a `recode_null` step before this one, named and
    agreed to.
    """
    import pandas as pd

    # Any because pandas types column indexing as a union that includes scalars; what comes
    # back here is a Series, and asserting otherwise would be the lie.
    column: Any = data[step.column]
    if step.to != "number":
        raise PreprocessingError(
            f"cast supports `to: number`; got {step.to!r}. A cast to anything else is not "
            f"implemented, and guessing would change values silently."
        )
    converted: Any
    try:
        converted = pd.to_numeric(column, errors="raise")
    except (ValueError, TypeError) as error:
        offenders = _unconvertible(column)
        raise PreprocessingError(
            f"cast cannot convert {step.column!r} to numbers: {error}. "
            f"Values in the way: {offenders}. If those mean missing, add a recode_null step "
            f"for them before this one, so that the substitution is recorded rather than "
            f"happening inside a conversion."
        ) from error

    before = int(np.asarray(column.isna(), dtype=bool).sum())
    after = int(np.asarray(converted.isna(), dtype=bool).sum())
    out = data.copy()
    out[step.column] = converted
    return out, StepRecord(
        op="cast",
        column=step.column,
        detail=f"{column.dtype} to {converted.dtype}",
        # A strict cast cannot create missing values; reported so that a future lenient path
        # could not quietly do so without this number moving.
        rows_changed=after - before,
    )


def _unconvertible(column: Any, limit: int = 5) -> str:
    """The distinct values standing in the way of a cast, for the error message."""
    import pandas as pd

    coerced: Any = pd.to_numeric(column, errors="coerce")
    bad = column[np.asarray(coerced.isna(), dtype=bool) & ~np.asarray(column.isna(), dtype=bool)]
    distinct = [repr(value) for value in pd.unique(bad)[:limit]]
    more = "" if len(distinct) < limit else ", and others"
    return ", ".join(distinct) + more if distinct else "(none found on a second pass)"

"""Applying the population filters, and counting what each one removed.

Mirrors design.md 7.2's `population`. A filter is not a preprocessing step and the
difference is the whole reason this module is separate: a step changes how a value is
written down, a filter changes **who the answer is about**.

Excluding the patients with no creatinine is not cleaning. It redefines the population as
"patients who had a creatinine drawn", and in an ICU whether a test was ordered is a
clinical decision driven by how sick someone looked. So the tool will do it, and will not do
it quietly:

- every filter is counted into an **exclusion ledger** that the report prints, in the form a
  reader of a study already knows how to audit
- the checks run on the filtered frame, so they describe the population being analysed rather
  than one nobody asked about
- `core.quality.population` separately looks at the people each filter removed and reports
  whether they differ from the people it kept, which is the cost of the exclusion rather than
  an opinion about it

Filters are conjunctive and applied in order. There is no `or`, no nesting and no arbitrary
expression, for the same reason the mapping has none: a criterion deciding who is in the
analysis has to be reviewable by someone who did not write it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.spec import PopulationFilter, Spec

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


class PopulationError(Exception):
    """A filter could not be applied."""


@dataclass(frozen=True)
class ExclusionRecord:
    """What one filter removed. The row of a CONSORT-style ledger."""

    criterion: str
    said: str
    n_before: int
    n_removed: int

    @property
    def n_after(self) -> int:
        return self.n_before - self.n_removed

    def describe(self) -> str:
        return (
            f"{self.criterion}: {self.n_removed:,} excluded, {self.n_before:,} to {self.n_after:,}"
        )


def keep_mask(data: pd.DataFrame, criterion: PopulationFilter) -> np.ndarray:
    """The rows one filter keeps.

    Missing values never satisfy a comparison. A patient whose creatinine is unknown is not
    known to be above 300 and is not known to be below it, so `max_creatinine ge 300` drops
    them, and the ledger shows it. The alternative, keeping them, would silently treat
    "unknown" as "qualifies".
    """
    if criterion.column not in data.columns:
        raise PopulationError(
            f"the filter names column {criterion.column!r}, which is not in the data"
        )
    column: Any = data[criterion.column]
    present = ~np.asarray(column.isna(), dtype=bool)
    if criterion.op == "not_missing":
        return present

    if criterion.op in ("in", "not_in"):
        values = list(criterion.value)
        inside = np.asarray(column.isin(values), dtype=bool)
        return (inside if criterion.op == "in" else ~inside) & present

    comparisons = {
        "eq": lambda left, right: left == right,
        "ne": lambda left, right: left != right,
        "lt": lambda left, right: left < right,
        "le": lambda left, right: left <= right,
        "gt": lambda left, right: left > right,
        "ge": lambda left, right: left >= right,
    }
    try:
        outcome = comparisons[criterion.op](column, criterion.value)
    except TypeError as error:
        raise PopulationError(
            f"cannot compare {criterion.column!r} with {criterion.value!r}: {error}. "
            f"If the column holds text that should be numbers, add a cast step first."
        ) from error
    return np.asarray(outcome, dtype=bool) & present


def apply_filters(data: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, list[ExclusionRecord]]:
    """Apply every filter in order, returning the kept rows and the ledger.

    Refuses to leave nothing behind: an empty analysis set is a specification error that
    would otherwise surface as an unrelated failure inside an estimator.
    """
    filters = spec.population.filters
    if not filters:
        return data, []
    working = data
    ledger: list[ExclusionRecord] = []
    for criterion in filters:
        mask = keep_mask(working, criterion)
        before = len(working)
        working = working.loc[mask]
        ledger.append(
            ExclusionRecord(
                criterion=criterion.describe(),
                said=criterion.said,
                n_before=before,
                n_removed=before - len(working),
            )
        )
        if working.empty:
            trail = "; ".join(record.describe() for record in ledger)
            raise PopulationError(
                f"the population filters leave no rows. The ledger so far: {trail}. "
                f"Either a criterion is the wrong way round, or the population asked for is "
                f"not in this extract."
            )
    return working.reset_index(drop=True), ledger

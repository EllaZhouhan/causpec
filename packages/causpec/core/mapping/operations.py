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

**An imputation is allowed, and it is charged for.** The two original operations only change
how a value is written down. The four imputations fill values nobody measured, and every one
of them produces an interval narrower than the evidence supports, because the arithmetic
downstream cannot tell a filled value from a measured one. So a spec containing any of them
runs with `interval_calibration: exploratory`, which forbids a significance claim, and each
step records what it did to the column's spread. That shrinking standard deviation *is* the
attenuation, made visible rather than argued about.

The honest version is multiple imputation with the uncertainty carried into the interval
through Rubin's rules, which needs m datasets, m analyses and a pooling step. That is a
change to the estimation path rather than to this module, and it is not built. Until it is,
the price of a single fill is a report that cannot claim significance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.spec import PreprocessingStep, Spec

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
    evidence: dict[str, float] = field(default_factory=dict)

    def describe(self) -> str:
        return f"{self.op} on {self.column}: {self.detail} ({self.rows_changed:,} rows)"


def _spread_shift(before: Any, after: Any) -> tuple[dict[str, float], str]:
    """What the fill did to the column's spread, as numbers and as a phrase.

    Two statistics, because they answer different questions and only the second is
    unambiguous.

    ``sd_before`` against ``sd_after`` is the column's own spread, which is what a reader
    comparing the report against the source would compute. It does not always shrink: filling
    a right-skewed column at its median puts values away from the mean, which can widen it.
    That is not the fill preserving information, it is the fill moving the centre.

    ``sd_filled`` is the spread **among the values written**, and it is the honest measure of
    how much of the distribution the fill invented away. A median fill gives exactly zero: 200
    patients who now hold the same number. An iterative fill gives something positive, because
    each filled value came from that row's own predictors, which is the whole case for it.
    """
    import numpy as np

    observed = np.asarray(before, dtype=float)
    filled = np.asarray(after, dtype=float)
    changed = np.isnan(observed) & ~np.isnan(filled)
    sd_before = float(np.nanstd(observed))
    sd_after = float(np.nanstd(filled))
    sd_filled = float(np.std(filled[changed])) if changed.any() else 0.0
    evidence = {
        "sd_before": round(sd_before, 6),
        "sd_after": round(sd_after, 6),
        "sd_filled": round(sd_filled, 6),
    }
    if sd_before <= 0:
        return evidence, ""
    evidence["sd_change"] = round((sd_after - sd_before) / sd_before, 6)
    # Compared against the column's own spread rather than against zero: the standard
    # deviation of two hundred copies of the same number comes out at 1e-14, not at 0.
    identical = sd_filled <= 1e-9 * max(sd_before, 1.0)
    spread_of_fills = (
        "every filled value identical" if identical else f"spread {sd_filled:.4g} among the filled"
    )
    return evidence, f", {spread_of_fills}, column spread {sd_before:.4g} to {sd_after:.4g}"


def apply(
    data: pd.DataFrame, steps: list[PreprocessingStep], spec: Spec | None = None
) -> tuple[pd.DataFrame, list[StepRecord]]:
    """Apply every step in order to a copy, returning the copy and what each one did.

    ``spec`` is needed by the two operations that cannot be decided column by column:
    `impute_iterative` reads the other analysis columns to predict from, and `impute_locf`
    reads the unit and period columns so that a value is carried forward within a patient
    rather than across the whole table.
    """
    if not steps:
        return data, []
    working = data.copy()
    records: list[StepRecord] = []
    handlers = {
        "recode_null": _recode_null,
        "cast": _cast,
        "impute_constant": _impute_constant,
        "impute_median": _impute_median,
        "add_missing_indicator": _add_missing_indicator,
    }
    for step in steps:
        if step.column not in working.columns:
            raise PreprocessingError(
                f"{step.op} names column {step.column!r}, which is not in the data. "
                f"Columns are set before preprocessing, so this is a typo in the spec rather "
                f"than something an earlier step removed."
            )
        if step.op == "impute_iterative":
            working, record = _impute_iterative(working, step, spec)
        elif step.op == "impute_locf":
            working, record = _impute_locf(working, step, spec)
        else:
            working, record = handlers[step.op](working, step)
        records.append(record)
    return working, records


# ---- filling values nobody measured ----


def _filled(
    data: pd.DataFrame, step: PreprocessingStep, values: Any, detail: str
) -> tuple[pd.DataFrame, StepRecord]:
    """Write a fill into a copy, recording the count and what it did to the spread."""
    import numpy as np

    before = np.asarray(data[step.column], dtype=float)
    out = data.copy()
    out[step.column] = values
    after = np.asarray(out[step.column], dtype=float)
    evidence, phrase = _spread_shift(before, after)
    # What actually changed, not what was missing. A carry-forward with a limit leaves some
    # gaps open on purpose, and a record that counted the gaps would claim work it did not do.
    filled = int((np.isnan(before) & ~np.isnan(after)).sum())
    still_missing = int((np.isnan(before) & np.isnan(after)).sum())
    evidence["n_filled"] = float(filled)
    evidence["n_still_missing"] = float(still_missing)
    remainder = f", {still_missing:,} left missing" if still_missing else ""
    return out, StepRecord(
        op=step.op,
        column=step.column,
        detail=detail + phrase + remainder,
        rows_changed=filled,
        evidence=evidence,
    )


def _impute_constant(
    data: pd.DataFrame, step: PreprocessingStep
) -> tuple[pd.DataFrame, StepRecord]:
    """Fill a value the user named.

    The one imputation that is sometimes exactly right: a missing infusion rate usually means
    no infusion, and zero is then a measurement rather than a guess. It is also the one that
    is worst when wrong, because a plausible number is indistinguishable from a real one, so
    the value is required and never defaulted.
    """
    column: Any = data[step.column]
    return _filled(data, step, column.fillna(step.value), f"filled with {step.value!r}")


def _impute_median(data: pd.DataFrame, step: PreprocessingStep) -> tuple[pd.DataFrame, StepRecord]:
    """Fill the median of the observed values.

    Transparent and wrong in a predictable direction: every filled patient is placed at the
    centre, so the column's spread shrinks and any association it carries is diluted. The
    median rather than the mean because ICU labs are right-skewed. Pair it with
    `add_missing_indicator` and the model can at least tell which patients were placed there.
    """
    import numpy as np

    column: Any = data[step.column]
    observed = np.asarray(column, dtype=float)
    if bool(np.all(np.isnan(observed))):
        raise PreprocessingError(
            f"{step.column!r} has no observed values to take a median from, so there is "
            f"nothing to impute with. A column that is entirely missing has to be dropped."
        )
    median = float(np.nanmedian(observed))
    return _filled(data, step, column.fillna(median), f"filled with the median {median:.4g}")


def _impute_iterative(
    data: pd.DataFrame, step: PreprocessingStep, spec: Spec | None
) -> tuple[pd.DataFrame, StepRecord]:
    """Fill from a model of this column given the others, one draw.

    Better than the median because it keeps the column's relationships with the rest of the
    table instead of flattening them. **The predictors include the treatment and the outcome**,
    which is the part everyone gets wrong: imputing a covariate from the other covariates
    alone makes the filled values independent of the outcome given those covariates, which
    biases the association towards zero and weakens exactly the confounding adjustment the
    column was there to provide. It feels like cheating and it is the opposite.

    One draw, so it still understates the uncertainty. Multiple imputation is the version
    that does not, and it needs a pooling step this project has not built.
    """
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401
    from sklearn.impute import IterativeImputer

    if spec is None:
        raise PreprocessingError(
            "impute_iterative needs the spec, to know which columns may predict this one"
        )
    predictors = _congenial_predictors(data, spec, step.column)
    if not predictors:
        raise PreprocessingError(
            f"impute_iterative on {step.column!r} found no other numeric analysis column to "
            f"predict from. With nothing to condition on it would reduce to the mean, so ask "
            f"for impute_median and have the record say so."
        )
    frame = data[[step.column, *predictors]].astype(float)
    imputer = IterativeImputer(max_iter=10, random_state=0, sample_posterior=False)
    # Any because sklearn types fit_transform as a union covering sparse matrices; this call
    # is on a dense frame and gets a dense array back.
    completed: Any = imputer.fit_transform(frame)
    detail = f"filled from {len(predictors)} predictor(s): {', '.join(predictors)}"
    return _filled(data, step, completed[:, 0], detail)


def _congenial_predictors(data: pd.DataFrame, spec: Spec, target: str) -> list[str]:
    """The columns an imputation model must be allowed to use: the analysis columns.

    Including the treatment and the outcome. See `_impute_iterative` for why leaving them out
    is the error rather than the precaution.
    """
    import pandas as pd

    from causpec.core.quality.basic import analysis_columns

    return [
        column
        for column in analysis_columns(spec, data)
        if column != target and pd.api.types.is_numeric_dtype(data[column])
    ]


def _impute_locf(
    data: pd.DataFrame, step: PreprocessingStep, spec: Spec | None
) -> tuple[pd.DataFrame, StepRecord]:
    """Carry the last observed value forward within a unit, up to a declared limit.

    The panel operation, and the only imputation with a defensible mechanism behind it: a
    measurement not repeated often means nothing changed. The limit is what makes that
    defensible, because the claim decays with time. Carrying forward only, never backward: a
    value from after the gap is information the clinician did not have.
    """
    if spec is None:
        raise PreprocessingError("impute_locf needs the spec, to know which column is the unit")
    unit = _declared_column(spec, data, "unit_id")
    period = _declared_column(spec, data, "period_index")
    if unit is None or period is None:
        raise PreprocessingError(
            "impute_locf needs unit_id and period_index declared in the spec: carrying a "
            "value forward across patients would invent a trajectory nobody had."
        )
    ordered = data.sort_values([unit, period], kind="stable")
    carried: Any = ordered.groupby(unit, sort=False)[step.column].ffill(limit=step.limit)
    restored = carried.reindex(data.index)
    detail = f"carried forward within {unit}, up to {step.limit} period(s)"
    return _filled(data, step, restored, detail)


def _declared_column(spec: Spec, data: pd.DataFrame, field_name: str) -> str | None:
    entry = spec.fields.get(field_name)
    if entry is None or entry.value is None:
        return None
    name = str(entry.value)
    return name if name in data.columns else None


def _add_missing_indicator(
    data: pd.DataFrame, step: PreprocessingStep
) -> tuple[pd.DataFrame, StepRecord]:
    """Add a 0/1 column recording whether the value was observed.

    The only operation here that adds information rather than substituting it: that a test was
    ordered is itself a fact, and in an ICU often an informative one. It has to be put in the
    covariate set to do anything, which is a spec change the user confirms separately, so the
    record says plainly when the column is sitting there unused.
    """
    import numpy as np

    name = f"{step.column}_was_measured"
    if name in data.columns:
        raise PreprocessingError(f"{name!r} already exists; the indicator was added twice")
    observed = ~np.asarray(data[step.column].isna(), dtype=bool)
    if bool(observed.all()):
        raise PreprocessingError(
            f"{step.column!r} has no missing values at this point, so the indicator would be 1 "
            f"for every row and carry nothing. If a fill for this column comes earlier in the "
            f"list, move the indicator before it: once the gaps are filled there is no record "
            f"of where they were, which is the information the indicator exists to keep."
        )
    out = data.copy()
    out[name] = observed.astype(float)
    n_missing = int((~observed).sum())
    return out, StepRecord(
        op="add_missing_indicator",
        column=step.column,
        detail=(
            f"added {name}, 0 for the {n_missing:,} unmeasured. Add it to the covariate set "
            f"in the spec, or it changes nothing"
        ),
        rows_changed=n_missing,
        evidence={"n_unmeasured": float(n_missing)},
    )


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

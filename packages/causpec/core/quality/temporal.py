"""The temporal layer: do the times in this table order the way the question assumes?

Mirrors design.md 8.1. Four checks, all of them comparisons between declared time columns,
and all of them for the same underlying error: a cohort or an outcome defined by something
that had not happened yet.

The one worth the layer is immortal time. "Patients dialysed within 24 hours" is a group you
can only join by being alive at 24 hours, so the comparison group carries a mortality risk
the treated group was selected out of, and the treatment looks protective in proportion to
how long the window is. It is the most common error in this literature and it leaves no trace
in any estimate: the standard errors are fine, the overlap is fine, the number is wrong.

**Most specs declare no times at all**, and then these checks say so rather than passing.
A check that reports nothing when it could not run is worse than no check, because the report
reads as a clean bill of health. Each issue carries ``assessed`` in its evidence, and the
summary says which field was missing.

Time representations: anything orderable. Timestamps parse, and a number of days or hours
since admission compares just as well. Only the follow-up check needs a duration, and it
takes ``outcome_horizon`` in whatever unit the columns already use, because converting units
on the user's behalf is how a 28-day horizon becomes 28 hours.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# The spec fields this layer reads. All optional: a cross-sectional study with no timestamps
# is a legitimate thing to analyse, and saying so is this layer's job rather than blocking.
TIME_FIELDS = ("time_zero", "treatment_time", "outcome_time", "followup_end")


def _column(spec: Spec, data: pd.DataFrame, field: str) -> str | None:
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return None
    name = str(entry.value)
    return name if name in data.columns else None


def _as_ordered(series: pd.Series) -> np.ndarray | None:
    """A column of times as comparable floats, or None when it is neither times nor numbers.

    Datetimes become nanoseconds and numbers stay numbers, which is all an ordering check
    needs. Mixing the two in one table would compare a timestamp against a day count, so a
    column that parses as neither is reported rather than coerced.
    """
    import pandas as pd

    if pd.api.types.is_numeric_dtype(series):
        return series.to_numpy(dtype=float)
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.astype("int64").to_numpy(dtype=float)
    parsed = pd.to_datetime(series, errors="coerce")
    if bool(parsed.isna().all()):
        return None
    values = parsed.astype("int64").to_numpy(dtype=float)
    # NaT becomes the smallest int64, which would compare as "long before everything".
    values[np.asarray(parsed.isna(), dtype=bool)] = np.nan
    return values


def _issue(
    config: dict[str, Any],
    check_id: str,
    passed: bool,
    summary: str,
    evidence: dict[str, float | int | str | bool],
    columns: list[str] | None = None,
    impact: str = "",
    repair: str = "",
) -> QualityIssue:
    entry = config.get(check_id, {})
    return QualityIssue(
        check_id=check_id,
        layer=Layer(entry.get("layer", "temporal")),
        severity=Severity.INFO if passed else Severity(entry.get("severity", "warning")),
        waivable=bool(entry.get("waivable", True)),
        summary=summary,
        evidence={**evidence, "passed": passed},
        affected_columns=columns or [],
        impact_on_analysis=impact,
        recommended_repair=repair,
    )


def _not_assessed(config: dict[str, Any], check_id: str, missing: list[str]) -> QualityIssue:
    """Say which field was missing, rather than passing quietly.

    The project's own rule for an unimplemented report section: an empty section does not
    mean the check passed. The same applies to a check that had nothing to read.
    """
    return _issue(
        config,
        check_id,
        passed=True,
        summary=(
            f"not assessed: the spec declares no {' or '.join(missing)}, so nothing was compared"
        ),
        evidence={"assessed": False, "missing_fields": ", ".join(missing)},
        impact=(
            "This check did not run. Its absence from the report is not evidence that the "
            "timing is sound."
        ),
        repair=(
            f"Declare {' and '.join(missing)} in the spec if the data has them. If it does "
            f"not, the timing cannot be checked from this table and has to be argued instead."
        ),
    )


def check_temporal(
    data: pd.DataFrame, spec: Spec, config: dict[str, Any] | None = None
) -> QualityReport:
    """Every temporal check, each skipping with an explanation when its columns are absent."""
    import pandas as pd

    from causpec.core.quality.basic import load_config

    config = config if config is not None else load_config()
    columns = {field: _column(spec, data, field) for field in TIME_FIELDS}
    times: dict[str, np.ndarray | None] = {}
    unparseable: list[str] = []
    for field, name in columns.items():
        if name is None:
            times[field] = None
            continue
        values = _as_ordered(pd.Series(np.asarray(data[name])))
        if values is None:
            unparseable.append(f"{name} ({field})")
        times[field] = values

    issues = [_time_columns_parse(config, unparseable, columns)]
    issues.append(_treatment_before_time_zero(config, columns, times))
    issues.append(_outcome_before_treatment(config, columns, times))
    issues.append(_time_inversion(config, columns, times))
    issues.append(_insufficient_followup(config, spec, columns, times))
    return QualityReport(issues=issues)


def _time_columns_parse(
    config: dict[str, Any], unparseable: list[str], columns: dict[str, str | None]
) -> QualityIssue:
    declared = [name for name in columns.values() if name is not None]
    if not declared:
        return _not_assessed(config, "temporal_time_columns_parse", ["time columns"])
    passed = not unparseable
    return _issue(
        config,
        "temporal_time_columns_parse",
        passed=passed,
        summary=(
            f"{len(declared)} time columns declared and readable"
            if passed
            else "not a time or a number: " + ", ".join(unparseable)
        ),
        evidence={
            "assessed": bool(declared),
            "n_declared": len(declared),
            "n_unparseable": len(unparseable),
        },
        columns=[entry.split(" ")[0] for entry in unparseable],
        impact=(
            "A time column that is neither a timestamp nor a number cannot be ordered, so "
            "every check below it is skipped and the timing goes unexamined."
        ),
        repair=(
            "Export the column as an ISO timestamp, or as a number of days or hours since the "
            "anchor. A mixed column, part date and part text, usually has a placeholder in it."
        ),
    )


def _treatment_before_time_zero(
    config: dict[str, Any], columns: dict[str, str | None], times: dict[str, np.ndarray | None]
) -> QualityIssue:
    """Immortal time: the exposure is dated before the clock it is measured against starts.

    This is the check the layer exists for. A cohort defined as "treated within the first
    24 hours" can only be joined by surviving 24 hours, so the untreated group carries a
    mortality risk the treated group was selected out of, and the treatment looks protective
    in proportion to the length of the window. Nothing in the estimate shows it.
    """
    check_id = "temporal_treatment_before_time_zero"
    missing = [field for field in ("time_zero", "treatment_time") if times.get(field) is None]
    if missing:
        return _not_assessed(config, check_id, missing)
    zero = times["time_zero"]
    treated_at = times["treatment_time"]
    assert zero is not None and treated_at is not None
    comparable = ~(np.isnan(zero) | np.isnan(treated_at))
    before = comparable & (treated_at < zero)
    count = int(np.sum(before))
    share = count / int(np.sum(comparable)) if int(np.sum(comparable)) else 0.0
    return _issue(
        config,
        check_id,
        passed=count == 0,
        summary=(
            "every recorded treatment time is at or after time zero"
            if count == 0
            else f"{count:,} units ({share:.1%}) were treated before time zero"
        ),
        evidence={
            "assessed": True,
            "n_before_time_zero": count,
            "share_before_time_zero": round(share, 4),
            "n_comparable": int(np.sum(comparable)),
        },
        columns=[columns["time_zero"] or "", columns["treatment_time"] or ""],
        impact=(
            "Treatment dated before the clock starts means the anchor is wrong, and a cohort "
            "anchored after its own exposure is immortal-time biased: membership requires "
            "surviving to the exposure, so the comparison group carries a risk the treated "
            "group was selected out of. The estimate looks ordinary and is wrong in a "
            "direction that favours treatment."
        ),
        repair=(
            "Anchor time zero at a point every unit reaches, before any treatment decision, "
            "such as admission or the moment eligibility is met. Then either define the "
            "exposure over a window after that anchor and count follow-up from it, or treat "
            "the exposure as time-varying, which is a different design."
        ),
    )


def _outcome_before_treatment(
    config: dict[str, Any], columns: dict[str, str | None], times: dict[str, np.ndarray | None]
) -> QualityIssue:
    check_id = "temporal_outcome_before_treatment"
    missing = [field for field in ("treatment_time", "outcome_time") if times.get(field) is None]
    if missing:
        return _not_assessed(config, check_id, missing)
    treated_at = times["treatment_time"]
    outcome_at = times["outcome_time"]
    assert treated_at is not None and outcome_at is not None
    comparable = ~(np.isnan(treated_at) | np.isnan(outcome_at))
    before = comparable & (outcome_at < treated_at)
    count = int(np.sum(before))
    share = count / int(np.sum(comparable)) if int(np.sum(comparable)) else 0.0
    return _issue(
        config,
        check_id,
        passed=count == 0,
        summary=(
            "no outcome is dated before the treatment it is attributed to"
            if count == 0
            else f"{count:,} units ({share:.1%}) have an outcome dated before their treatment"
        ),
        evidence={
            "assessed": True,
            "n_outcome_first": count,
            "share_outcome_first": round(share, 4),
            "n_comparable": int(np.sum(comparable)),
        },
        columns=[columns["treatment_time"] or "", columns["outcome_time"] or ""],
        impact=(
            "An event that happened before the exposure cannot have been caused by it. These "
            "rows contribute to the estimate as though it could, so the effect is diluted "
            "towards zero or reversed, depending on which arm they fall in."
        ),
        repair=(
            "Usually a join on the wrong key or a timestamp in a different time zone. Find "
            "where the two columns come from before changing either: dropping the rows hides "
            "a problem that probably affects the rest of the table too."
        ),
    )


def _time_inversion(
    config: dict[str, Any], columns: dict[str, str | None], times: dict[str, np.ndarray | None]
) -> QualityIssue:
    """Follow-up that ends before it starts, or an outcome dated after it closed."""
    check_id = "temporal_inversion"
    if times.get("followup_end") is None:
        return _not_assessed(config, check_id, ["followup_end"])
    end = times["followup_end"]
    assert end is not None
    findings: list[str] = []
    evidence: dict[str, float | int | str | bool] = {"assessed": True}
    affected = [columns["followup_end"] or ""]

    zero = times.get("time_zero")
    if zero is not None:
        comparable = ~(np.isnan(zero) | np.isnan(end))
        count = int(np.sum(comparable & (end < zero)))
        evidence["n_end_before_start"] = count
        if count:
            findings.append(f"{count:,} units have follow-up ending before time zero")
            affected.append(columns["time_zero"] or "")

    outcome_at = times.get("outcome_time")
    if outcome_at is not None:
        comparable = ~(np.isnan(outcome_at) | np.isnan(end))
        count = int(np.sum(comparable & (outcome_at > end)))
        evidence["n_outcome_after_end"] = count
        if count:
            findings.append(f"{count:,} units have an outcome dated after follow-up closed")
            affected.append(columns["outcome_time"] or "")

    passed = not findings
    return _issue(
        config,
        check_id,
        passed=passed,
        summary=("follow-up intervals are ordered" if passed else "; ".join(findings)),
        evidence=evidence,
        columns=[name for name in affected if name],
        impact=(
            "An interval that runs backwards, or an event outside the window it is counted "
            "in, means the rows do not describe the study they are being used for. Any "
            "person-time calculation over them is arithmetic on nothing."
        ),
        repair=(
            "Check the direction of the subtraction that produced the dates, and whether some "
            "rows carry a default date such as the epoch or the end of the extraction."
        ),
    )


def _insufficient_followup(
    config: dict[str, Any],
    spec: Spec,
    columns: dict[str, str | None],
    times: dict[str, np.ndarray | None],
) -> QualityIssue:
    """Units whose observation closes before the outcome window the question asks about.

    "28-day mortality" among units followed for ten days counts an administrative close as a
    survival. The horizon is taken in whatever unit the time columns already use, because
    converting it on the user's behalf is how 28 days becomes 28 hours.
    """
    check_id = "temporal_insufficient_followup"
    entry = spec.fields.get("outcome_horizon")
    horizon = None
    if entry is not None and entry.value is not None:
        try:
            horizon = float(entry.value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            horizon = None
    missing = [field for field in ("time_zero", "followup_end") if times.get(field) is None]
    if horizon is None:
        return _not_assessed(config, check_id, [*missing, "outcome_horizon"])
    if missing:
        return _not_assessed(config, check_id, missing)

    zero = times["time_zero"]
    end = times["followup_end"]
    assert zero is not None and end is not None
    comparable = ~(np.isnan(zero) | np.isnan(end))
    observed = np.where(comparable, end - zero, np.nan)
    # With a tolerance, because a window of exactly the horizon does not survive the
    # subtraction: an admission time rounded to two decimals plus 672 hours comes back as
    # 671.9999999999999, and without this the check fires on data that is exactly right.
    short = comparable & (observed < horizon) & ~np.isclose(observed, horizon, rtol=1e-9, atol=1e-9)

    # A unit that had the event does not need the rest of the window: the outcome is known.
    outcome_at = times.get("outcome_time")
    if outcome_at is not None:
        short = short & np.isnan(outcome_at)

    count = int(np.sum(short))
    total = int(np.sum(comparable))
    share = count / total if total else 0.0
    threshold = float(config.get(check_id, {}).get("max_short_share", 0.0))
    unit = spec.fields.get("time_unit")
    unit_label = f" {unit.value}" if unit is not None and unit.value is not None else ""
    return _issue(
        config,
        check_id,
        passed=share <= threshold,
        summary=(
            f"every unit without an event is followed for at least {horizon:g}{unit_label}"
            if share <= threshold
            else f"{count:,} units ({share:.1%}) have no event and less than "
            f"{horizon:g}{unit_label} of follow-up"
        ),
        evidence={
            "assessed": True,
            "outcome_horizon": horizon,
            "n_short_followup": count,
            "share_short_followup": round(share, 4),
            "max_short_share": threshold,
            # Reported as -1 rather than nan when nothing was comparable: an address the
            # report can print, and a value no follow-up duration can take.
            "median_followup": round(float(np.nanmedian(observed)), 4) if total else -1.0,
        },
        columns=[columns["time_zero"] or "", columns["followup_end"] or ""],
        impact=(
            "A unit whose observation closes before the window ends has an unknown outcome, "
            "not a negative one. Counting the close as survival biases the event rate down in "
            "whichever arm is followed for less time, which is usually the arm that leaves "
            "sooner."
        ),
        repair=(
            "Either shorten the outcome window to one the data supports, which changes the "
            "question and should be said out loud, or restrict the cohort to units with "
            "complete follow-up and report how many were dropped, or move to a design that "
            "handles censoring rather than ignoring it."
        ),
    )

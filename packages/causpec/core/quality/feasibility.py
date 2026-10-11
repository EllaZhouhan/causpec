"""The feasibility layer: is there enough here to answer the question that was asked?

Mirrors design.md 8.1. Two checks, both about counts rather than about structure: how many
units are in each arm, and how many of them had the outcome.

**Why these block when design.md 10.2 says not to gate on what an interval already says.**
That rule is right for the average effect. An arm of 200 against an arm of 3,000 produces a
wide interval, the reader sees it, and a gate would be paternalism. Heterogeneity is the case
the rule does not cover. A forest fitted to 25 events over seven covariates still returns a
per-point estimate for every patient, with an interval around each one, and those intervals
do not widen enough to say "this is noise". The number looks like an answer. So the counts
have to be reported and, below a floor, refused.

**Cross-sectional analyses only.** A panel's equivalent question is how many complete windows
each lag has, which depends on the lag structure, so `dynamic_lag_dml` computes it. When a
period column is declared, these checks say they do not apply rather than counting rows as
though they were units.

The event-count check applies only to a binary outcome. For a continuous one the arm sizes
are reported and the rest is left alone: there is no event to count, and the precision of a
mean is something the interval does say.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.quality import QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec
from causpec.core.quality.basic import _issue, _threshold, load_config

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# Columns whose count decides whether a covariate budget is affordable. The adjustment set and
# the effect modifiers both enter the nuisance models, so both are counted.
COVARIATE_FIELDS = ("effect_modifiers", "adjustment_set")


def _column(spec: Spec, data: pd.DataFrame, field: str) -> str | None:
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return None
    name = str(entry.value)
    return name if name in data.columns else None


def _covariate_count(spec: Spec, data: pd.DataFrame) -> int:
    names: set[str] = set()
    for field in COVARIATE_FIELDS:
        entry = spec.fields.get(field)
        if entry is None or entry.value is None:
            continue
        values = entry.value if isinstance(entry.value, (list, tuple)) else [entry.value]
        names.update(str(value) for value in values if str(value) in data.columns)
    return len(names)


def _is_binary(values: np.ndarray) -> bool:
    present = set(np.unique(values[~np.isnan(values)]).tolist())
    return present <= {0.0, 1.0} and len(present) == 2


def _not_applicable(config: dict[str, Any], check_id: str, reason: str) -> QualityIssue:
    return _issue(
        config,
        check_id,
        passed=True,
        summary=f"not applicable: {reason}",
        evidence={"assessed": False},
        impact="This check did not run; its absence is not evidence that the counts are ample.",
    )


def check_feasibility(
    data: pd.DataFrame, spec: Spec, config_path: Path | None = None
) -> QualityReport:
    """Arm sizes and event counts, for a cross-sectional analysis."""
    config = load_config(config_path)
    treatment_col = _column(spec, data, "treatment")
    outcome_col = _column(spec, data, "outcome")
    if treatment_col is None:
        return QualityReport(
            issues=[
                _not_applicable(config, "feasibility_arm_sizes", "no treatment column declared"),
                _not_applicable(config, "feasibility_event_counts", "no treatment column"),
            ]
        )
    if _column(spec, data, "period_index") is not None:
        reason = "the data is a panel, so the family counts windows per lag instead"
        return QualityReport(
            issues=[
                _not_applicable(config, "feasibility_arm_sizes", reason),
                _not_applicable(config, "feasibility_event_counts", reason),
            ]
        )

    treatment = np.asarray(data[treatment_col], dtype=float)
    issues = [_arm_sizes(treatment, treatment_col, config)]
    if outcome_col is None:
        issues.append(
            _not_applicable(config, "feasibility_event_counts", "no outcome column declared")
        )
        return QualityReport(issues=issues)
    outcome = np.asarray(data[outcome_col], dtype=float)
    issues.append(
        _event_counts(treatment, outcome, outcome_col, _covariate_count(spec, data), config)
    )
    return QualityReport(issues=issues)


def _arm_sizes(treatment: np.ndarray, column: str, config: dict[str, Any]) -> QualityIssue:
    minimum = int(_threshold(config, "feasibility_arm_sizes", "min_per_arm", 20))
    if not _is_binary(treatment):
        return _not_applicable(
            config, "feasibility_arm_sizes", f"{column} is not binary, so there are no two arms"
        )
    treated = int(np.nansum(treatment == 1.0))
    control = int(np.nansum(treatment == 0.0))
    smaller = min(treated, control)
    passed = smaller >= minimum
    return _issue(
        config,
        "feasibility_arm_sizes",
        passed=passed,
        summary=(
            f"{treated:,} treated and {control:,} control"
            if passed
            else f"the smaller arm has {smaller:,} units ({treated:,} treated, "
            f"{control:,} control), below the floor of {minimum:,}"
        ),
        evidence={
            "assessed": True,
            "n_treated": treated,
            "n_control": control,
            "n_smaller_arm": smaller,
            "min_per_arm": minimum,
            "treated_share": round(treated / (treated + control), 4) if treated + control else 0.0,
        },
        columns=[column],
        impact=(
            "Below this floor an arm cannot support a comparison, and it cannot support a "
            "comparison that varies by patient at all. The floor is deliberately low: a small "
            "arm that is merely imprecise is something the interval says for itself."
        ),
        repair=(
            "Widen the population if the filter was narrower than the question needed, or ask "
            "a question the data can carry: an average effect needs far less than a profile "
            "across patients."
        ),
    )


def _event_counts(
    treatment: np.ndarray,
    outcome: np.ndarray,
    outcome_column: str,
    n_covariates: int,
    config: dict[str, Any],
) -> QualityIssue:
    """Events per arm, and events per covariate in the smaller arm.

    The smaller arm is the binding constraint: a CATE needs the outcome model to be estimable
    in both arms, and it is the arm with fewer events that decides whether it is.
    """
    check_id = "feasibility_event_counts"
    if not _is_binary(outcome):
        return _not_applicable(
            config, check_id, f"{outcome_column} is not binary, so there are no events to count"
        )
    if not _is_binary(treatment):
        return _not_applicable(config, check_id, "the treatment is not binary")

    min_events = int(_threshold(config, check_id, "min_events_per_arm", 10))
    min_per_covariate = _threshold(config, check_id, "min_events_per_covariate", 5)
    treated_events = int(np.nansum((treatment == 1.0) & (outcome == 1.0)))
    control_events = int(np.nansum((treatment == 0.0) & (outcome == 1.0)))
    fewest = min(treated_events, control_events)
    per_covariate = fewest / n_covariates if n_covariates else float("inf")

    evidence: dict[str, float | int | str | bool] = {
        "assessed": True,
        "events_treated": treated_events,
        "events_control": control_events,
        "events_in_smaller_arm": fewest,
        "n_covariates": n_covariates,
        "events_per_covariate": round(per_covariate, 3) if np.isfinite(per_covariate) else -1.0,
        "min_events_per_arm": min_events,
        "min_events_per_covariate": min_per_covariate,
    }

    if fewest < min_events:
        return _issue(
            config,
            check_id,
            passed=False,
            summary=(
                f"{fewest:,} events in the smaller arm ({treated_events:,} treated, "
                f"{control_events:,} control), below the floor of {min_events:,}"
            ),
            evidence=evidence,
            columns=[outcome_column],
            impact=(
                "An outcome model fitted to this many events is fitting noise, and a forest "
                "does not say so: it returns a per-point estimate for every patient with an "
                "interval around each, and those intervals do not widen enough to make the "
                "problem visible. The number will look like an answer."
            ),
            repair=(
                "Ask for the average effect rather than who benefits more, which needs far "
                "fewer events. Or widen the population, or use a longer follow-up window if "
                "the outcome is time-bound, which changes the question and should be said."
            ),
        )

    thin = np.isfinite(per_covariate) and per_covariate < min_per_covariate
    thin_severity = Severity(config.get(check_id, {}).get("severity_thin_covariates", "warning"))
    return _issue(
        config,
        check_id,
        passed=not thin,
        severity=thin_severity,
        summary=(
            f"{treated_events:,} events in the treated arm and {control_events:,} in the "
            f"control arm, {per_covariate:.1f} per covariate in the smaller"
            if not thin
            else f"{fewest:,} events in the smaller arm against {n_covariates} covariates, "
            f"{per_covariate:.1f} per covariate (below {min_per_covariate:g})"
        ),
        evidence=evidence,
        columns=[outcome_column],
        impact=(
            "The classic rule for an outcome model is ten events per variable. A forest is less "
            "sharp about it, so this is a warning rather than a refusal, but a heterogeneity "
            "estimate on this budget is describing the covariates it happened to split on "
            "rather than the effect."
        ),
        repair=(
            "Narrow the covariate set to what the treatment decision actually used, which is "
            "usually far fewer columns than an extract contains, and report the average effect "
            "alongside any breakdown so a reader can see which one the data supports."
        ),
    )

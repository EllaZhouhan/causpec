"""dynamic_lag_dml's own quality checks.

Mirrors design.md 8.1 (the four layers) and 10.2 (blocking is reserved for what an
interval cannot express). Thresholds come from family.yaml, never from here.

Three of these have no counterpart in the cross-sectional families, because they are
about the shape of a trajectory rather than about a comparison:

- **Period gaps and duplicates.** The lag index counts rows. A unit missing period 3 has
  its lag-2 windows silently become lag-3 windows, and no error appears anywhere. This is
  the panel equivalent of a units mix-up: cheap to detect, impossible to detect later.
- **Continuation positivity.** The weight of a lag-kappa window multiplies kappa+1
  reciprocals of fitted continuation probabilities, so the same floor that is comfortable
  at lag 0 is not at lag 3. The check reports where the floor had to bind and how large a
  single window's weight became.
- **Lag relevance.** J is the denominator of the estimator, so a small J is the
  weak-instrument problem in another costume, and like instrument relevance it blocks.

Two of them deliberately do not block. Composition drift across lags is a caveat for the
reader, not a defect. And a state column that merely predicts the same period's treatment
is doing exactly what a confounder does; only a column that is nearly a copy of the
treatment is evidence of a post-treatment measurement, and the rest has to be confirmed
with the user.

The diagnostics come from one fit of the estimator's own stages, so the check and the
estimate cannot disagree about the weights or about J. The fit computed here is never
reported: ``check_panel`` returns a QualityReport and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


def _settings(config: dict[str, Any], check_id: str) -> tuple[Layer, Severity, bool]:
    entry = config.get(check_id, {})
    return (
        Layer(entry.get("layer", "basic")),
        Severity(entry.get("severity", "warning")),
        bool(entry.get("waivable", True)),
    )


def _threshold(config: dict[str, Any], check_id: str, key: str, default: float) -> float:
    return float(config.get(check_id, {}).get(key, default))


def _issue(
    config: dict[str, Any],
    check_id: str,
    passed: bool,
    summary: str,
    evidence: dict[str, float | int | str | bool],
    columns: list[str] | None = None,
    impact: str = "",
    repair: str = "",
    severity: Severity | None = None,
) -> QualityIssue:
    """Build one issue, honouring the QualityIssue invariant that a pass is INFO."""
    layer, declared, waivable = _settings(config, check_id)
    return QualityIssue(
        check_id=check_id,
        layer=layer,
        severity=Severity.INFO if passed else (severity or declared),
        waivable=waivable,
        summary=summary,
        evidence={**evidence, "passed": passed},
        affected_columns=columns or [],
        impact_on_analysis=impact,
        recommended_repair=repair,
    )


def _column_names(spec: Spec, field: str) -> list[str]:
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _one_column(spec: Spec, field: str) -> str:
    names = _column_names(spec, field)
    if not names:
        raise ValueError(f"dynamic_lag_dml requires spec.{field}")
    return names[0]


def check_panel(data: pd.DataFrame, spec: Spec, declaration: dict[str, Any]) -> QualityReport:
    """Every panel check, in the order a reader should meet them."""
    from causpec.families.dynamic_lag_dml.estimator import (
        DEFAULT_LAMBDA_FLOOR,
        DEFAULT_MAX_LAG,
        DynamicLagDmlFit,
        to_trajectories,
    )

    config = declaration.get("checks", {})
    unit = _one_column(spec, "unit_id")
    period = _one_column(spec, "period_index")
    treatment = _one_column(spec, "treatment")
    outcome = _one_column(spec, "outcome")
    state = _column_names(spec, "state")
    entry = spec.fields.get("max_lag")
    max_lag = int(entry.value) if entry is not None and entry.value is not None else DEFAULT_MAX_LAG
    lambda_floor = float(spec.param("lambda_floor", DEFAULT_LAMBDA_FLOOR))

    issues = [
        _horizon_declaration(data, config, spec, unit, period),
        _duplicate_periods(data, config, unit, period),
        _period_gaps(data, config, unit, period),
        _post_treatment_state(data, config, state, treatment),
    ]
    estimand = spec.fields.get("estimand")
    if estimand is not None and str(estimand.value) == "lag_cate":
        issues.append(
            _time_varying_modifier(
                data, config, _column_names(spec, "effect_modifiers"), unit, period, treatment
            )
        )

    prerequisites = {"horizon_declaration", "panel_duplicate_periods", "panel_period_gaps"}
    ready = all(
        issue.severity is not Severity.BLOCKING
        for issue in issues
        if issue.check_id in prerequisites
    )
    if not ready:
        # Everything below needs trajectories built on the declared horizon. A broken index
        # would mis-align the lags, and a wrong horizon would produce weight diagnostics for
        # a correction that does not apply. Stop with what is known; G3 still delivers it.
        return QualityReport(issues=issues)

    horizon_field = spec.fields.get("horizon")
    horizon = str(horizon_field.value).strip() if horizon_field is not None else "variable"
    termination = spec.fields.get("termination")
    termination_column = None
    if horizon == "variable" and termination is not None and termination.value is not None:
        name = str(termination.value).strip()
        termination_column = name if name in data.columns else None
    trajectories = to_trajectories(
        data, unit, period, state, treatment, outcome, termination=termination_column
    )
    fit = DynamicLagDmlFit(max_lag=max_lag, lambda_floor=lambda_floor, seed=0, horizon=horizon).fit(
        trajectories
    )

    issues.append(_window_counts(fit, config, max_lag))
    issues.append(_continuation_positivity(fit, config, lambda_floor))
    issues.append(_lag_relevance(fit, config))
    issues.append(_set_composition(fit, config, trajectories))
    return QualityReport(issues=issues)


# ---- temporal layer: the horizon the user declared, against the data ----


def _horizon_declaration(
    data: pd.DataFrame, config: dict[str, Any], spec: Spec, unit: str, period: str
) -> QualityIssue:
    """Does the declared horizon survive contact with the data?

    The horizon is a confirmed field rather than something inferred, because one pair of
    worlds is indistinguishable by shape: a panel where every unit has eight periods is
    either a genuinely fixed horizon, or a variable horizon whose data pull kept the first
    eight buckets of the units that lasted that long. The second is a cohort conditioned on
    surviving, which no weighting repairs. On the benchmark design, keeping the 3.5% of units
    that reach eight periods moves the lag-1 estimate from 4.22 to 2.87 against a truth of
    4.0, and a tool that guessed "fixed" would report that as a clean analysis.

    So this does not decide the horizon. It checks the declaration against the data and
    refuses the two combinations that cannot both be true.
    """
    check_id = "horizon_declaration"
    max_at_window = _threshold(config, check_id, "max_share_at_window_when_variable", 0.9)
    entry = spec.fields.get("horizon")
    declared = str(entry.value).strip() if entry is not None and entry.value is not None else ""
    lengths = np.asarray(data.groupby(unit)[period].max(), dtype=int) + 1
    window_end = int(lengths.max()) if len(lengths) else 0
    share_at_window = float(np.mean(lengths == window_end)) if len(lengths) else 0.0
    evidence: dict[str, float | int | str | bool] = {
        "declared_horizon": declared or "(missing)",
        "window_end": window_end,
        "shortest_trajectory": int(lengths.min()) if len(lengths) else 0,
        "share_reaching_the_window": round(share_at_window, 4),
        "max_share_at_window_when_variable": max_at_window,
    }

    if declared not in {"fixed", "variable"}:
        return _issue(
            config,
            check_id,
            passed=False,
            summary=(
                "spec.horizon is missing: say whether every unit is observed for the same "
                "number of periods (fixed) or trajectories end at different times (variable)"
            ),
            evidence=evidence,
            impact=(
                "The horizon decides whether the continuation weighting applies at all, and "
                "the data cannot settle it. Guessing is how a cohort truncated to a fixed "
                "length gets analysed as though nobody had ever left."
            ),
            repair=(
                "Ask the user. Fixed means the study observed every unit for the same number "
                "of periods. Variable means units left at different times, in which case also "
                "ask how leaving is identified in the data."
            ),
        )

    if declared == "fixed" and share_at_window < 1.0:
        return _issue(
            config,
            check_id,
            passed=False,
            summary=(
                f"declared a fixed horizon, but trajectories run from "
                f"{int(lengths.min())} to {window_end} periods"
            ),
            evidence=evidence,
            impact=(
                "Under a fixed horizon no weighting is applied, because nobody left early. If "
                "units do end at different times, those endings are unexplained and the "
                "windows that survive to a long lag are a selected sample."
            ),
            repair=(
                "Either the horizon is variable, in which case say how leaving is identified, "
                "or the short trajectories end for a reason that has nothing to do with "
                "leaving, such as missing rows, which is a different problem to fix first."
            ),
        )

    if declared == "variable" and share_at_window > max_at_window:
        return _issue(
            config,
            check_id,
            passed=False,
            summary=(
                f"declared a variable horizon, but {share_at_window:.0%} of units run exactly "
                f"to period {window_end - 1}, so almost nothing ended early"
            ),
            evidence=evidence,
            impact=(
                "This is the shape of a cohort truncated to a fixed length: the units kept are "
                "the ones that lasted, so the population is conditioned on surviving and the "
                "weights have nothing to correct because the evidence of leaving was dropped "
                "with the rows. No weighting repairs it."
            ),
            repair=(
                "If the data was cut at a fixed number of periods, go back to the untruncated "
                "panel. If every unit really was followed for the same length, the horizon is "
                "fixed. If leaving is recorded in a column rather than by the rows stopping, "
                "name that column in spec.termination."
            ),
        )

    return _issue(
        config,
        check_id,
        passed=True,
        summary=(
            f"the declared {declared} horizon matches the data"
            + (
                f": {share_at_window:.0%} of units reach the end of the window"
                if declared == "variable"
                else ""
            )
        ),
        evidence=evidence,
    )


# ---- basic layer: the shape of the index ----


def _duplicate_periods(
    data: pd.DataFrame, config: dict[str, Any], unit: str, period: str
) -> QualityIssue:
    duplicated = data.duplicated(subset=[unit, period]).sum()
    units = int(data.loc[data.duplicated(subset=[unit, period]), unit].nunique())
    return _issue(
        config,
        "panel_duplicate_periods",
        passed=duplicated == 0,
        summary=(
            f"{duplicated:,} rows repeat a unit and period, across {units:,} units"
            if duplicated
            else "one row per unit and period"
        ),
        evidence={"n_duplicate_rows": int(duplicated), "n_units_affected": units},
        columns=[unit, period],
        impact=(
            "Two rows for one period leave the state, the treatment and the outcome of "
            "that period ambiguous, and nothing downstream can choose between them."
        ),
        repair=(
            "Decide what a period means and aggregate to it before the analysis: one row "
            "per unit per period, with the state read at the start of it."
        ),
    )


def _period_gaps(
    data: pd.DataFrame, config: dict[str, Any], unit: str, period: str
) -> QualityIssue:
    """Every unit's periods must be consecutive integers from zero."""
    offenders: list[str] = []
    n_missing = 0
    for key, group in data.groupby(unit, sort=True):
        periods = np.sort(group[period].to_numpy())
        if len(periods) == 0:
            continue
        expected = np.arange(len(periods))
        if not np.array_equal(periods.astype(int), expected):
            missing = int(max(int(periods.max()) + 1 - len(periods), 0))
            n_missing += missing
            if len(offenders) < 5:
                offenders.append(str(key))
    passed = not offenders
    return _issue(
        config,
        "panel_period_gaps",
        passed=passed,
        summary=(
            "every unit's periods are consecutive from 0"
            if passed
            else f"{len(offenders)}+ units have gaps or do not start at 0, "
            f"for example {', '.join(offenders)}"
        ),
        evidence={"n_units_with_gaps": len(offenders), "n_missing_periods": n_missing},
        columns=[unit, period],
        impact=(
            "The lag index counts rows, so a missing period turns a lag-2 window into a "
            "lag-3 window with no error raised anywhere. Every lag past the gap would be "
            "attributed to the wrong distance in time."
        ),
        repair=(
            "Build the grid so that every period between a unit's first and last exists, "
            "treated or not, and renumber from 0. Do not impute the outcome of a period "
            "that was never observed: drop the trajectory after the gap instead."
        ),
    )


# ---- temporal layer: what the within-period order requires ----


def _post_treatment_state(
    data: pd.DataFrame, config: dict[str, Any], state: list[str], treatment: str
) -> QualityIssue:
    """Flag a state column that is nearly a copy of the same period's treatment.

    A confounder is *meant* to predict the treatment, so a moderate correlation is the
    design working rather than a defect. What no confounder does is separate the treated
    from the untreated almost perfectly. That pattern belongs to a column recorded during
    the period, a machine setting or a drug rate, which is post-treatment.
    """
    blocking_at = _threshold(config, "panel_post_treatment_state", "separation_blocking_above", 0.9)
    warning_at = _threshold(config, "panel_post_treatment_state", "separation_warning_above", 0.7)
    a = data[treatment].to_numpy(dtype=float)
    correlations: dict[str, float] = {}
    for column in state:
        values = data[column].to_numpy(dtype=float)
        if np.std(values) < 1e-12 or np.std(a) < 1e-12:
            continue
        correlations[column] = abs(float(np.corrcoef(values, a)[0, 1]))
    if not correlations:
        worst_column, worst = "", 0.0
    else:
        worst_column = max(correlations, key=lambda name: correlations[name])
        worst = correlations[worst_column]

    near_copies = sorted(name for name, value in correlations.items() if value >= blocking_at)
    suspicious = sorted(
        name for name, value in correlations.items() if warning_at <= value < blocking_at
    )
    if near_copies:
        severity, passed = Severity.BLOCKING, False
        summary = (
            f"{len(near_copies)} state columns almost reproduce the treatment of the same "
            f"period ({', '.join(near_copies)}); the strongest is |r| = {worst:.2f}"
        )
    elif suspicious:
        severity, passed = Severity.WARNING, False
        summary = (
            f"{len(suspicious)} state columns track the same period's treatment closely "
            f"(|r| up to {worst:.2f}); confirm with the user when each was measured"
        )
    else:
        severity, passed = Severity.INFO, True
        summary = (
            f"no state column reproduces the same period's treatment (largest |r| = {worst:.2f})"
        )
    return _issue(
        config,
        "panel_post_treatment_state",
        passed=passed,
        summary=summary,
        evidence={
            "max_abs_correlation": round(worst, 4),
            "max_correlation_column": worst_column,
            "n_near_copies": len(near_copies),
            "n_suspicious": len(suspicious),
        },
        columns=near_copies or suspicious,
        impact=(
            "A column recorded after the period's treatment began is on the path being "
            "estimated. Adjusting on it removes part of the effect and biases the lag "
            "profile in a direction that cannot be signed in advance."
        ),
        repair=(
            "Keep in the state only what was recorded before the period's treatment. "
            "Whether that holds cannot be read off the data: ask which of these columns "
            "were measured at the start of the period."
        ),
        severity=severity,
    )


def _time_varying_modifier(
    data: pd.DataFrame,
    config: dict[str, Any],
    modifiers: list[str],
    unit: str,
    period: str,
    treatment: str,
) -> QualityIssue:
    """For lag_cate only: a modifier the treatment moves leaves no profile to estimate.

    If the lag effect varies with something the treatment changes, the contribution of one
    treatment period to a later outcome becomes a function of the treatment in between, and
    the outcome no longer decomposes into a sum of lag effects. Fitting a profile anyway
    produces numbers that look plausible and are not any effect.

    Constant within every unit settles it, and that is checkable. A modifier that does vary
    is not automatically wrong, since a calendar effect or age would vary innocently, but
    the data cannot tell that apart from a modifier the treatment moves. So it blocks, and
    the user can waive it by saying why the treatment cannot move it.
    """
    check_id = "lag_cate_time_varying_modifier"
    max_varying = _threshold(config, check_id, "max_within_unit_variation_share", 0.0)
    flag_at = _threshold(config, check_id, "flag_lagged_treatment_correlation", 0.2)
    ordered = data.sort_values([unit, period], kind="stable")
    evidence: dict[str, float | int | str | bool] = {
        "max_within_unit_variation_share": max_varying,
        "n_modifiers": len(modifiers),
    }
    offenders: list[str] = []
    for column in modifiers:
        if column not in ordered.columns:
            continue
        spread = ordered.groupby(unit)[column].nunique()
        varying_share = float((spread > 1).mean())
        evidence[f"{column}_varying_share"] = round(varying_share, 4)
        if varying_share > max_varying:
            lagged = ordered.groupby(unit)[treatment].shift(1)
            usable = lagged.notna()
            correlation = 0.0
            if usable.sum() > 2:
                left = ordered.loc[usable, column].to_numpy(dtype=float)
                right = lagged[usable].to_numpy(dtype=float)
                if np.std(left) > 1e-12 and np.std(right) > 1e-12:
                    correlation = abs(float(np.corrcoef(left, right)[0, 1]))
            evidence[f"{column}_lagged_treatment_correlation"] = round(correlation, 4)
            hint = " and earlier treatment predicts it" if correlation >= flag_at else ""
            offenders.append(f"{column} varies within {varying_share:.0%} of units{hint}")
    passed = not offenders
    return _issue(
        config,
        check_id,
        passed=passed,
        summary=(
            "every effect modifier is constant within a unit, so the treatment cannot have moved it"
            if passed
            else "; ".join(offenders)
        ),
        evidence=evidence,
        columns=[name.split(" ")[0] for name in offenders],
        impact=(
            "A modifier the treatment moves destroys the additive decomposition the profile "
            "rests on: the contribution of one treatment period to a later outcome becomes a "
            "function of the treatment in between. What comes out is not a lag effect at all."
        ),
        repair=(
            "Use baseline variables as modifiers, measured before the first period. If the "
            "modifier genuinely varies for reasons outside the treatment, such as calendar "
            "time or age, say so and waive this check, because only you can know that."
        ),
    )


# ---- feasibility and identification, from the estimator's own stages ----


def _window_counts(fit: Any, config: dict[str, Any], max_lag: int) -> QualityIssue:
    min_windows = _threshold(config, "panel_too_short_for_the_lag", "min_windows_per_lag", 100)
    min_units = _threshold(config, "panel_too_short_for_the_lag", "min_units_per_lag", 50)
    evidence: dict[str, float | int | str | bool] = {}
    thin: list[str] = []
    by_lag = {lag_fit.lag: lag_fit for lag_fit in fit.fits_}
    for lag in range(max_lag + 1):
        lag_fit = by_lag.get(lag)
        windows = 0 if lag_fit is None else len(lag_fit.weight)
        units = 0 if lag_fit is None else int(len(np.unique(lag_fit.unit_index)))
        evidence[f"lag{lag}_windows"] = windows
        evidence[f"lag{lag}_units"] = units
        if windows < min_windows or units < min_units:
            thin.append(f"lag {lag} ({windows:,} windows, {units:,} units)")
    passed = not thin
    return _issue(
        config,
        "panel_too_short_for_the_lag",
        passed=passed,
        summary=(
            f"every lag up to {max_lag} has enough complete windows"
            if passed
            else f"too few complete windows at {', '.join(thin)}"
        ),
        evidence={
            **evidence,
            "min_windows_per_lag": min_windows,
            "min_units_per_lag": min_units,
        },
        impact=(
            "A lag-K window needs K+2 recorded periods, so the longest lag rests on the "
            "longest trajectories only. Below this many windows the estimate is not "
            "imprecise, it is arbitrary."
        ),
        repair=(
            "Lower max_lag to the longest lag the trajectories actually support, or use a "
            "longer period so that the same clock time costs fewer lags."
        ),
    )


def _continuation_positivity(fit: Any, config: dict[str, Any], floor: float) -> QualityIssue:
    """Whether the weights leave enough of the sample behind them.

    Two numbers, measuring the same assumption from two directions. How often the fitted
    continuation probability hit the floor, which is the data saying that continuation was
    near impossible somewhere and the weight had to be capped. And how many windows
    effectively carry each lag, which is what is left once a few enormous weights have
    taken over. The largest weight is reported but not thresholded: these weights are
    heavy-tailed even on the design the method was proved on.
    """
    min_effective = _threshold(config, "continuation_positivity", "min_effective_windows", 50)
    max_clipped = _threshold(config, "continuation_positivity", "max_clipped_share", 0.05)
    clipped = float(getattr(fit, "continuation_clipped_share_", float("nan")))
    smallest = float(getattr(fit, "continuation_min_", float("nan")))
    horizon = str(getattr(fit, "horizon_", "random"))
    if horizon == "fixed":
        # Every trajectory ran to the end of the observation window, so none of them left
        # early. There is no censoring to correct and no weights were applied, which is worth
        # saying rather than leaving the reader to notice that every weight equals one.
        return _issue(
            config,
            "continuation_positivity",
            passed=True,
            summary=(
                "the horizon is fixed: every unit is observed for the same number of periods, "
                "so no trajectory left early and no continuation weighting was applied"
            ),
            evidence={"horizon": horizon, "ipcw_applied": False},
            impact="",
            repair="",
        )
    evidence: dict[str, float | int | str | bool] = {
        "horizon": horizon,
        "ipcw_applied": True,
        "lambda_floor": floor,
        "continuation_min_fitted": round(smallest, 4) if np.isfinite(smallest) else "n/a",
        "clipped_share": round(clipped, 4) if np.isfinite(clipped) else "n/a",
        "min_effective_windows": min_effective,
        "max_clipped_share": max_clipped,
    }
    breaches: list[str] = []
    if np.isfinite(clipped) and clipped > max_clipped:
        breaches.append(
            f"the continuation model hit the floor on {clipped:.1%} of periods "
            f"(at most {max_clipped:.0%} allowed)"
        )
    worst_effective = float("inf")
    for lag_fit in fit.fits_:
        effective = lag_fit.effective_windows
        evidence[f"lag{lag_fit.lag}_weight_max"] = round(float(lag_fit.weight.max()), 2)
        evidence[f"lag{lag_fit.lag}_weight_mean"] = round(float(lag_fit.weight.mean()), 3)
        evidence[f"lag{lag_fit.lag}_effective_windows"] = round(effective, 1)
        evidence[f"lag{lag_fit.lag}_windows"] = int(len(lag_fit.weight))
        if lag_fit.lag > 0:
            worst_effective = min(worst_effective, effective)
        if lag_fit.lag > 0 and effective < min_effective:
            breaches.append(
                f"lag {lag_fit.lag} rests on {effective:.0f} effective windows out of "
                f"{len(lag_fit.weight):,}"
            )
    passed = not breaches
    return _issue(
        config,
        "continuation_positivity",
        passed=passed,
        summary=(
            f"the weights leave enough behind them (smallest effective size "
            f"{worst_effective:.0f} windows)"
            if passed
            else "; ".join(breaches)
        ),
        evidence=evidence,
        impact=(
            "A window whose continuation probability came close to zero carries a weight "
            "that dominates the moment, so the lag ends up decided by a handful of "
            "trajectories. The bound on the weight grows geometrically in the lag, which is "
            "why this fails at the far end of the profile first."
        ),
        repair=(
            "Report a shorter profile, or restrict the cohort to the region where leaving is "
            "not near certain, or collect more units. Raising the floor is not a repair: it "
            "caps the weight and biases the estimate towards the unweighted one, which is "
            "the bias the weighting exists to remove."
        ),
    )


def _lag_relevance(fit: Any, config: dict[str, Any]) -> QualityIssue:
    minimum = _threshold(config, "lag_relevance", "min_j_statistic", 0.01)
    evidence: dict[str, float | int | str | bool] = {"min_j_statistic": minimum}
    weak: list[str] = []
    for lag_fit in fit.fits_:
        evidence[f"lag{lag_fit.lag}_j"] = round(float(lag_fit.j_statistic), 5)
        if not np.isfinite(lag_fit.j_statistic) or lag_fit.j_statistic < minimum:
            weak.append(f"lag {lag_fit.lag} (J = {lag_fit.j_statistic:.4f})")
    passed = not weak
    return _issue(
        config,
        "lag_relevance",
        passed=passed,
        summary=(
            "the residualised treatment retains variation at every lag"
            if passed
            else f"too little residual treatment variation at {', '.join(weak)}"
        ),
        evidence=evidence,
        impact=(
            "J is the denominator of the estimator. When it is near zero the estimate is a "
            "ratio with almost nothing underneath, exactly as a weak instrument is: the "
            "point estimate moves a long way on a small change in the data."
        ),
        repair=(
            "This is a property of the design, not a setting. Either the treatment barely "
            "varies once the state is accounted for, in which case the question cannot be "
            "answered from this data, or the state is so rich that it predicts the "
            "treatment almost perfectly and should be narrowed to what clinicians use."
        ),
    )


def _set_composition(fit: Any, config: dict[str, Any], trajectories: list[Any]) -> QualityIssue:
    """The lag-K population is not the lag-0 population, and the report has to say so.

    Two things move together as the lag grows. The set shrinks, because a lag-K window
    needs K+2 periods. And its composition shifts, because the trajectories long enough to
    supply a long window are the ones with more sustained treatment: in the author's
    application the treated share of the windows rises from 12.1% at lag 0 to 17.1% at
    lag 3. Neither is a defect and neither can be fixed, so this never blocks; what it
    does is put the per-lag counts in front of the reader.
    """
    drift_at = _threshold(config, "lag_set_composition", "flag_treated_share_drift", 0.03)
    evidence: dict[str, float | int | str | bool] = {"flag_treated_share_drift": drift_at}
    units_per_lag: list[int] = []
    shares: list[float] = []
    for lag_fit in fit.fits_:
        lag = lag_fit.lag
        # The anchor of each window is its treatment period, so the treated share of the
        # anchors is what this lag's estimate is actually about.
        anchors = [
            float(trajectory.treatment[period - lag])
            for trajectory in trajectories
            for period in range(lag, trajectory.length - 1)
        ]
        share = float(np.mean(anchors)) if anchors else float("nan")
        units = int(len(np.unique(lag_fit.unit_index)))
        evidence[f"lag{lag}_units"] = units
        evidence[f"lag{lag}_windows"] = int(len(lag_fit.weight))
        evidence[f"lag{lag}_treated_share"] = round(share, 4)
        units_per_lag.append(units)
        shares.append(share)

    first_units, last_units = (units_per_lag[0], units_per_lag[-1]) if units_per_lag else (0, 0)
    retained = last_units / first_units if first_units else 0.0
    drift = abs(shares[-1] - shares[0]) if len(shares) > 1 else 0.0
    evidence["unit_retention_at_longest_lag"] = round(retained, 4)
    evidence["treated_share_drift"] = round(drift, 4)
    passed = drift <= drift_at
    return _issue(
        config,
        "lag_set_composition",
        passed=passed,
        summary=(
            f"the analysis set shrinks with the lag, keeping {retained:.0%} of the units at "
            f"the longest, with the treated share steady"
            if passed
            else f"the treated share moves by {drift:.1%} across the profile, from "
            f"{shares[0]:.1%} at lag 0 to {shares[-1]:.1%} at the longest lag, which keeps "
            f"{retained:.0%} of the units"
        ),
        evidence=evidence,
        impact=(
            "Longer trajectories carry more sustained treatment, so both the size and the "
            "composition of the analysis set change with the lag. The far end of the "
            "profile describes a different population from the near end."
        ),
        repair=(
            "Nothing to repair. Report the per-lag counts next to the profile so the "
            "reader can see which population each lag describes."
        ),
    )

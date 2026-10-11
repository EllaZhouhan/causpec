"""The population layer: what each exclusion costs.

Mirrors design.md 7.2's `population`. These checks run on the frame **before** the filters
are applied, because the people a filter removed are the only evidence about whether removing
them mattered, and after filtering they are gone.

Two questions, and the second is the one users will meet.

**Is the filter conditioning on something the treatment could have caused?** Selecting on a
consequence of treatment is selection bias, the same error as adjusting for a post-treatment
covariate and worse in one way: adjustment distorts an estimate, selection decides who is in
the study at all. Filtering on the outcome is the extreme case and is refused outright.

**Are the people it removed different from the people it kept?** This is the honest answer to
"can you just drop the patients with no creatinine". The tool will drop them. What it will
not do is let the report imply the remaining patients are a random subset: whether a test was
ordered is a clinical decision, so the excluded are usually the least sick or the sickest, and
the number that says which is the treatment rate and the event rate among them.

Neither check decides anything on its own. Both put the cost next to the decision, which is
what the user asked for when they asked to drop the rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.quality import QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec
from causpec.core.population import keep_mask
from causpec.core.quality.basic import _issue, _threshold, load_config

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


def _declared(spec: Spec, data: pd.DataFrame, field: str) -> str | None:
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return None
    name = str(entry.value)
    return name if name in data.columns else None


def _not_assessed(config: dict[str, Any], check_id: str, reason: str) -> QualityIssue:
    return _issue(
        config,
        check_id,
        passed=True,
        summary=f"not assessed: {reason}",
        evidence={"assessed": False},
        impact=(
            "This check did not run; its absence is not evidence that the population is "
            "the one the question is about."
        ),
    )


def check_population(
    data: pd.DataFrame, spec: Spec, config_path: Path | None = None
) -> QualityReport:
    """Both population checks, against the frame as it was before filtering."""
    config = load_config(config_path)
    filters = spec.population.filters
    if not filters:
        reason = "no population filters are declared, so the analysis is of every row supplied"
        return QualityReport(
            issues=[
                _not_assessed(config, "population_filter_variable", reason),
                _not_assessed(config, "population_exclusion_informative", reason),
            ]
        )
    treatment = _declared(spec, data, "treatment")
    outcome = _declared(spec, data, "outcome")
    return QualityReport(
        issues=[
            _filter_variable(data, spec, treatment, outcome, config),
            _exclusion_informative(data, spec, treatment, outcome, config),
        ]
    )


def _separation(data: pd.DataFrame, column: str, treatment: str | None) -> float:
    """|corr| between a filter column and the treatment, or 0 when it cannot be computed.

    A confounder is *meant* to predict the treatment, so a moderate correlation here is the
    design working. What no pre-treatment variable does is separate the arms almost perfectly;
    that pattern belongs to something recorded after the treatment started. The same criterion
    as `panel_post_treatment_state`, which is deliberate: it is the same error.
    """
    if treatment is None or column == treatment:
        return 0.0
    try:
        left = np.asarray(data[column], dtype=float)
        right = np.asarray(data[treatment], dtype=float)
    except (TypeError, ValueError):
        return 0.0
    usable = ~np.isnan(left) & ~np.isnan(right)
    if usable.sum() < 3 or np.std(left[usable]) < 1e-12 or np.std(right[usable]) < 1e-12:
        return 0.0
    return abs(float(np.corrcoef(left[usable], right[usable])[0, 1]))


def _filter_variable(
    data: pd.DataFrame,
    spec: Spec,
    treatment: str | None,
    outcome: str | None,
    config: dict[str, Any],
) -> QualityIssue:
    """Whether any filter conditions on the treatment, the outcome, or a consequence of them."""
    check_id = "population_filter_variable"
    blocking_at = _threshold(config, check_id, "separation_blocking_above", 0.9)
    warning_at = _threshold(config, check_id, "separation_warning_above", 0.7)

    on_outcome = [f.column for f in spec.population.filters if outcome and f.column == outcome]
    on_treatment = [
        f.column for f in spec.population.filters if treatment and f.column == treatment
    ]
    separations = {
        criterion.column: _separation(data, criterion.column, treatment)
        for criterion in spec.population.filters
        if criterion.column in data.columns
    }
    near_copies = sorted(name for name, value in separations.items() if value >= blocking_at)
    suspicious = sorted(
        name for name, value in separations.items() if warning_at <= value < blocking_at
    )
    worst = max(separations.values(), default=0.0)

    evidence: dict[str, float | int | str | bool] = {
        "assessed": True,
        "n_filters": len(spec.population.filters),
        "filters_on_outcome": ", ".join(on_outcome) or "none",
        "filters_on_treatment": ", ".join(on_treatment) or "none",
        "near_copies_of_treatment": ", ".join(near_copies) or "none",
        "suspicious": ", ".join(suspicious) or "none",
        "max_separation": round(worst, 4),
        "separation_blocking_above": blocking_at,
    }

    if on_outcome or on_treatment:
        named = ", ".join(on_outcome + on_treatment)
        return _issue(
            config,
            check_id,
            passed=False,
            summary=f"a population filter conditions on {named}",
            evidence=evidence,
            columns=on_outcome + on_treatment,
            impact=(
                "Selecting the population on the outcome makes the comparison circular: the "
                "survivors of one arm are being compared with the survivors of the other. "
                "Selecting it on the treatment defines away the contrast the question asks "
                "about. Neither is a wide interval; both are an answer to a different "
                "question that will read as an answer to this one."
            ),
            repair=(
                "If the question really is about a subgroup defined after treatment, it is a "
                "different question and needs a design that handles it, not a filter. If the "
                "intent was to restrict on a baseline characteristic, name the baseline "
                "column instead."
            ),
        )

    if near_copies:
        return _issue(
            config,
            check_id,
            passed=False,
            summary=(
                f"the filter column {near_copies[0]!r} separates the treatment arms almost "
                f"perfectly (|r| = {worst:.2f}), so it looks like a consequence of treatment"
            ),
            evidence=evidence,
            columns=near_copies,
            impact=(
                "Filtering on something the treatment caused selects a population defined "
                "partly by what happened after the decision. The estimate that follows "
                "describes whoever is left, and nothing in the interval says so."
            ),
            repair=(
                "Check when this column was measured. If its window starts after the "
                "treatment decision, filter on the baseline value instead, or state the "
                "population without this restriction."
            ),
        )

    passed = not suspicious
    return _issue(
        config,
        check_id,
        passed=passed,
        severity=Severity(config.get(check_id, {}).get("severity_suspicious", "warning")),
        summary=(
            f"{len(spec.population.filters)} filter(s), none on the treatment or the outcome"
            if passed
            else f"the filter column {suspicious[0]!r} is strongly associated with the "
            f"treatment (|r| = {separations[suspicious[0]]:.2f}); confirm it is measured "
            f"before the treatment decision"
        ),
        evidence=evidence,
        columns=suspicious,
        impact=(
            "A strong association is what a confounder looks like, so this is a question "
            "rather than a finding. It becomes an error only if the column is measured after "
            "the treatment started."
        ),
        repair=(
            "Confirm the measurement window of this column against time zero. The variable "
            "catalogue is where that belongs once it exists."
        ),
    )


def _rate(values: np.ndarray) -> float:
    usable = values[~np.isnan(values)]
    return float(np.mean(usable)) if usable.size else float("nan")


def _exclusion_informative(
    data: pd.DataFrame,
    spec: Spec,
    treatment: str | None,
    outcome: str | None,
    config: dict[str, Any],
) -> QualityIssue:
    """Whether the people each filter removed differ from the people it kept.

    Measured where it matters rather than across every column: the treatment rate and the
    event rate. An exclusion that is unbalanced on either is selecting on something related
    to the analysis, which is the difference between "we dropped 200 patients" and "we
    dropped 200 of the sickest patients".
    """
    check_id = "population_exclusion_informative"
    if treatment is None and outcome is None:
        return _not_assessed(
            config, check_id, "neither the treatment nor the outcome column is declared"
        )
    gap_at = _threshold(config, check_id, "rate_gap_above", 0.1)
    minimum = int(_threshold(config, check_id, "min_excluded_to_assess", 10))

    working = data
    worst_gap, worst_line, worst_detail = 0.0, "", ""
    total_removed = 0
    evidence: dict[str, float | int | str | bool] = {"assessed": True}
    for index, criterion in enumerate(spec.population.filters, start=1):
        mask = keep_mask(working, criterion)
        excluded, kept = working.loc[~mask], working.loc[mask]
        removed = len(excluded)
        total_removed += removed
        evidence[f"filter{index}_excluded"] = removed
        if removed < minimum or kept.empty:
            working = kept
            continue
        for role, column in (("treatment", treatment), ("outcome", outcome)):
            if column is None:
                continue
            try:
                inside = _rate(np.asarray(excluded[column], dtype=float))
                outside = _rate(np.asarray(kept[column], dtype=float))
            except (TypeError, ValueError):
                continue
            if np.isnan(inside) or np.isnan(outside):
                continue
            gap = abs(inside - outside)
            evidence[f"filter{index}_{role}_rate_excluded"] = round(inside, 4)
            evidence[f"filter{index}_{role}_rate_kept"] = round(outside, 4)
            if gap > worst_gap:
                worst_gap = gap
                worst_line = criterion.describe()
                worst_detail = (
                    f"the {role} rate is {inside:.1%} among the {removed:,} excluded "
                    f"against {outside:.1%} among the {len(kept):,} kept"
                )
        working = kept

    evidence["total_excluded"] = total_removed
    evidence["max_rate_gap"] = round(worst_gap, 4)
    evidence["rate_gap_above"] = gap_at
    informative = worst_gap > gap_at
    return _issue(
        config,
        check_id,
        passed=not informative,
        summary=(
            f"{total_removed:,} rows excluded, and the excluded look like the kept on the "
            f"treatment and event rates (largest gap {worst_gap:.1%})"
            if not informative
            else f"the exclusion {worst_line} is not neutral: {worst_detail}"
        ),
        evidence=evidence,
        impact=(
            "The analysis is now about the patients who remained, and they are not a random "
            "subset of the ones asked about. The estimate can still be the right answer for "
            "that population; what it cannot do is stand in for the population in the "
            "question without the exclusion being stated."
        ),
        repair=(
            "Keep the exclusion if it is what the question needs, and say in the report who "
            "was excluded and how they differed, which the exclusion ledger already shows. "
            "If the exclusion exists only to get past a missing column, consider leaving that "
            "column out of the covariate set instead, which keeps the patients."
        ),
    )

"""hte_backdoor's own quality checks: overlap, covariate balance, feasibility.

Mirrors design.md 8.1 (the identification and feasibility layers) and 10.2 (one of
the two blocking checks).

**This layer fits its own propensity model and does not depend on the estimator.**
G3 requires the quality report to be a deliverable even when the analysis cannot run,
and overlap bad enough to stop estimation is exactly when that report matters most.

Only overlap blocks. Following the trade-off of design.md 10.2 ("if the confidence
interval already says it, do not gate on it"), sample size and precision speak for
themselves through the interval. What an interval cannot express is systematic bias,
and under backdoor adjustment the main source of that is missing common support:
a group of people with no comparable controls, whose effect is extrapolated. The
interval will look narrow there, but narrow in a way that means nothing. SMD,
prevalence and ESS are computed, reported, and not gated on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:
    import pandas as pd

PROPENSITY_MODELS = ("gradient_boosting", "logistic")


def _threshold(config: dict[str, Any], check_id: str, key: str, default: float) -> float:
    return float(config.get(check_id, {}).get(key, default))


def _issue_settings(config: dict[str, Any], check_id: str) -> tuple[Layer, Severity, bool]:
    entry = config.get(check_id, {})
    return (
        Layer(entry.get("layer", "identification")),
        Severity(entry.get("severity", "warning")),
        bool(entry.get("waivable", True)),
    )


def _build_propensity_model(name: str, seed: int):
    if name == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    if name == "gradient_boosting":
        return GradientBoostingClassifier(random_state=seed)
    raise ValueError(f"propensity_model must be one of {', '.join(PROPENSITY_MODELS)}; got {name}")


def estimate_propensity(
    covariates: np.ndarray, treatment: np.ndarray, model_name: str, folds: int, seed: int
) -> np.ndarray:
    """Cross-fitted propensity scores.

    Cross-fitting is mandatory: fitting and predicting on the same data lets the model
    memorise individuals, pushing scores towards 0 and 1, so common support only
    *appears* to be missing, which would condemn perfectly good data.

    The default is gradient boosting rather than logistic regression: overlap asks
    whether there is a region where treatment is near-deterministic, and a too-narrow
    model can miss real separation. A false negative costs more than a false positive
    here, because it lets through an analysis that should have been blocked.
    """
    model = _build_propensity_model(model_name, seed)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    scores = cross_val_predict(model, covariates, treatment, cv=splitter, method="predict_proba")
    return np.asarray(scores, dtype=float)[:, 1]


def standardized_mean_difference(
    values: np.ndarray, treatment: np.ndarray, weights: np.ndarray | None = None
) -> float:
    """SMD: the treated-minus-control mean difference over the pooled standard deviation.

    The weighted variant checks balance after IPW. The denominator always uses the
    **unweighted** standard deviation, so the SMD before and after weighting are
    comparable, otherwise the weights move numerator and denominator together and any
    improvement is invisible.
    """
    treated, control = treatment == 1, treatment == 0
    pooled_sd = np.sqrt((np.var(values[treated]) + np.var(values[control])) / 2.0)
    if pooled_sd < 1e-12:
        return 0.0
    if weights is None:
        gap = values[treated].mean() - values[control].mean()
    else:
        gap = np.average(values[treated], weights=weights[treated]) - np.average(
            values[control], weights=weights[control]
        )
    return float(gap / pooled_sd)


def effective_sample_size(weights: np.ndarray) -> float:
    """Kish's effective sample size: (sum w)^2 / sum(w^2). Uneven weights shrink it."""
    total = float(np.sum(weights))
    if total <= 0:
        return 0.0
    return total**2 / float(np.sum(weights**2))


def _groups_declared(data: pd.DataFrame, spec: Spec, config: dict[str, Any]) -> QualityIssue:
    """The `gate` estimand needs groups, and the groups have to be formable from this data.

    Enforced here rather than in the gate's required-fields list because the requirement holds
    only for this estimand, and a flat `requires.spec_fields` cannot say "required only when".
    The family knows the condition and can state it, which is the same split the panel family
    uses for `termination` and `effect_modifiers`.
    """
    from causpec.core.grouping import GroupingError, group_masks

    check_id = "backdoor_effect_groups"
    layer, severity, waivable = _issue_settings(config, check_id)
    entry = spec.fields.get("estimand")
    estimand = str(entry.value) if entry is not None and entry.value is not None else ""

    if estimand == "cate":
        # Not a defect, so not a warning: `cate` is a declared estimand and a legitimate
        # request. But it is the one whose output a reader misreads by default, so the check
        # that would otherwise say "not applicable" says which question it answers instead.
        # In the report this sits beside the per-patient summary it is about.
        return QualityIssue(
            check_id=check_id,
            layer=layer,
            severity=Severity.INFO,
            waivable=waivable,
            summary=(
                "the estimand is cate, which reports a per-patient effect for every row and "
                "names no group"
            ),
            evidence={"assessed": False, "passed": True, "estimand": estimand},
            impact_on_analysis=(
                "A per-patient effect distribution says the effect varies and says of whom. "
                "The usual misreading is to take one patient's number as an estimate for that "
                "patient, which the interval around it does not support: these are fitted "
                "values from a forest, not individual effects."
            ),
            recommended_repair=(
                "If the question is who benefits more, ask for the `gate` estimand instead: "
                "read the importance table to see which covariates the effect varies along, "
                "then declare groups in effect_groups and get one effect and one interval per "
                "named group. `cate` stays the right request when the per-patient spread "
                "itself is the object of interest."
            ),
        )

    if estimand != "gate":
        return QualityIssue(
            check_id=check_id,
            layer=layer,
            severity=Severity.INFO,
            waivable=waivable,
            summary=f"not applicable: the estimand is {estimand or '(none)'}, not gate",
            evidence={"assessed": False, "passed": True},
        )

    if not spec.effect_groups:
        return QualityIssue(
            check_id=check_id,
            layer=layer,
            severity=severity,
            waivable=waivable,
            summary="the estimand is gate but no effect_groups are declared",
            evidence={"assessed": True, "passed": False, "n_groupings": 0},
            impact_on_analysis=(
                "A group effect is an effect for a named set of patients. With no groups "
                "declared there is nothing to name, and the per-patient effect cloud that "
                "would be reported instead says the effect varies and says of whom."
            ),
            recommended_repair=(
                "Report the average effect first, read the importance table to see which "
                "covariates the effect varies along, and ask the user which of them to split "
                "on and where. Their threshold, in their words."
            ),
        )

    problems: list[str] = []
    counts: dict[str, int] = {}
    for group in spec.effect_groups:
        try:
            masks = group_masks(data, group)
        except GroupingError as error:
            problems.append(str(error))
            continue
        for label, mask in masks:
            counts[f"{group.variable} {label}"] = int(mask.sum())

    if problems:
        return QualityIssue(
            check_id=check_id,
            layer=layer,
            severity=severity,
            waivable=waivable,
            summary="; ".join(problems),
            evidence={"assessed": True, "passed": False, "n_groupings": len(spec.effect_groups)},
            impact_on_analysis="A grouping that cannot be formed produces no rows to report.",
            recommended_repair="Name a column that is in the data, or choose different cuts.",
        )

    smallest = min(counts.values()) if counts else 0
    evidence: dict[str, float | int | str | bool] = {
        "assessed": True,
        "passed": True,
        "n_groupings": len(spec.effect_groups),
        "n_groups": len(counts),
        "smallest_group": smallest,
        **{f"n_{name.replace(' ', '_')}": size for name, size in counts.items()},
    }
    return QualityIssue(
        check_id=check_id,
        layer=layer,
        severity=Severity.INFO,
        waivable=waivable,
        summary=(
            f"{len(spec.effect_groups)} grouping(s) giving {len(counts)} groups, "
            f"the smallest holding {smallest:,} patients"
        ),
        evidence=evidence,
        impact_on_analysis=(
            "A small group gets a wide interval rather than a wrong answer, and the group "
            "table prints every group's size for that reason. No group is dropped or merged: "
            "a group of eleven patients with an interval four times the others is the finding."
        ),
    )


def _not_assessed_under_randomisation(
    check_id: str, config: dict[str, Any], what: str
) -> QualityIssue:
    """A balance check standing down because the design settles what it was asking.

    Overlap and covariate balance are diagnostics for an **adjustment**: they ask whether the
    covariates can carry the comparison. Under randomisation nothing is being carried by the
    covariates, so the question they answer is not the question in front of the analysis, and
    `assignment_mechanism` is a confirmed field with the user's own words in it. The user is
    the authority on how their treatment was assigned, and the arithmetic here is not.

    It reports rather than passing silently, because this layer's rule is that a check which
    did not run says so: a reader of the report has to be able to see that the balance
    diagnostics stood down, and on whose statement.

    What this gives up, stated here because it is the cost of the decision and not an
    argument against it: a file whose treatment column records what was received rather than
    which arm was assigned looks exactly like a randomised design to the spec and exactly
    like an observational one to the data, and these two checks were the only place that
    difference showed up.
    """
    layer, _, waivable = _issue_settings(config, check_id)
    return QualityIssue(
        check_id=check_id,
        layer=layer,
        severity=Severity.INFO,
        waivable=waivable,
        summary=(
            f"not assessed: the spec records that assignment was randomised, so {what} is "
            f"settled by the design rather than by the covariates"
        ),
        evidence={"assessed": False, "passed": True, "assignment_mechanism": "randomised"},
        impact_on_analysis=(
            "This check did not run. It asks whether the covariates can carry the comparison, "
            "which is a question about an adjustment, and under randomisation the design "
            "carries it. Its absence is not evidence about the covariates either way."
        ),
    )


def _was_randomised(spec: Spec) -> bool:
    """Whether the user said the treatment was assigned at random.

    Two checks read this, because what they found means something different depending on the
    answer, and getting it wrong means telling a user with a trial to do the opposite of what
    they should.
    """
    entry = spec.fields.get("assignment_mechanism")
    if entry is None or entry.value is None:
        return False
    return str(entry.value).startswith("randomised")


def check_backdoor(
    data: pd.DataFrame, spec: Spec, config: dict[str, Any] | None = None
) -> QualityReport:
    """Run every hte_backdoor check and return addressed issues."""
    from causpec.families.hte_backdoor.estimator import _column_names

    config = config or {}
    treatment_col = _column_names(spec, "treatment")[0]
    covariate_names = _column_names(spec, "effect_modifiers") + _column_names(
        spec, "adjustment_set"
    )
    if not covariate_names:
        raise ValueError(
            "hte_backdoor's quality checks require spec.effect_modifiers or adjustment_set"
        )

    treatment = data[treatment_col].to_numpy().astype(int)
    covariates = data[covariate_names].astype(float).to_numpy()
    # Read once: a failed overlap or balance check means something different depending on
    # how the treatment was assigned, and telling a trial's owner to restrict the population
    # is the opposite of what they should do.
    randomised = _was_randomised(spec)
    issues: list[QualityIssue] = []

    # ---- 1. treatment prevalence (feasibility) ----
    layer, severity, waivable = _issue_settings(config, "backdoor_treatment_prevalence")
    min_rate = _threshold(config, "backdoor_treatment_prevalence", "min_rate", 0.01)
    min_per_arm = int(_threshold(config, "backdoor_treatment_prevalence", "min_per_arm", 50))
    n_treated, n_control = int(treatment.sum()), int((1 - treatment).sum())
    rate = float(treatment.mean())
    passed = min_rate <= rate <= 1 - min_rate and min(n_treated, n_control) >= min_per_arm
    issues.append(
        QualityIssue(
            check_id="backdoor_treatment_prevalence",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=f"treated {rate:.1%} ({n_treated} treated, {n_control} control)",
            evidence={
                "treatment_rate": round(rate, 6),
                "n_treated": n_treated,
                "n_control": n_control,
                "min_per_arm": min_per_arm,
                "passed": passed,
            },
            affected_columns=[treatment_col],
            impact_on_analysis=(
                "With too few people in one arm the estimate carries a large variance, "
                "and subgroup analyses especially become unreliable."
            ),
            recommended_repair="Relax the population filter, or cut fewer subgroups.",
        )
    )
    if n_treated == 0 or n_control == 0:
        return QualityReport(issues=issues)  # one arm is empty; nothing else computes

    # After the arm check, so an empty arm still stops everything below it: with no comparison
    # to make, whether the groups are well formed is not the user's problem yet.
    issues.append(_groups_declared(data, spec, config))

    # ---- 2 and 3. overlap and covariate balance ----
    #
    # Both are diagnostics for an adjustment, so a declared randomised design stands them
    # down: see _not_assessed_under_randomisation for what that gives up. The propensity
    # model is still fitted, because section 4's weights come from it and that check still
    # says something, uniform weights being what randomisation produces.
    layer, severity, waivable = _issue_settings(config, "backdoor_overlap")
    low = _threshold(config, "backdoor_overlap", "propensity_low", 0.05)
    high = _threshold(config, "backdoor_overlap", "propensity_high", 0.95)
    max_extreme = _threshold(config, "backdoor_overlap", "max_extreme_fraction", 0.05)
    folds = int(_threshold(config, "backdoor_overlap", "cv_folds", 5))
    model_name = str(
        config.get("backdoor_overlap", {}).get("propensity_model", "gradient_boosting")
    )
    propensity = estimate_propensity(covariates, treatment, model_name, folds, seed=0)
    weights = np.where(
        treatment == 1, 1.0 / np.clip(propensity, 1e-6, 1), 1.0 / np.clip(1 - propensity, 1e-6, 1)
    )

    if randomised:
        issues.append(
            _not_assessed_under_randomisation(
                "backdoor_overlap", config, "whether the arms are comparable"
            )
        )
        issues.append(
            _not_assessed_under_randomisation(
                "backdoor_covariate_imbalance", config, "whether the arms are balanced"
            )
        )
    else:
        extreme = (propensity < low) | (propensity > high)
        extreme_fraction = float(extreme.mean())
        passed = extreme_fraction <= max_extreme
        issues.append(
            QualityIssue(
                check_id="backdoor_overlap",
                layer=layer,
                severity=severity if not passed else Severity.INFO,
                waivable=waivable,
                summary=(
                    f"{extreme_fraction:.1%} of the sample has a propensity score outside "
                    f"[{low:g}, {high:g}] (threshold {max_extreme:.0%})"
                ),
                evidence={
                    "extreme_fraction": round(extreme_fraction, 6),
                    "threshold": max_extreme,
                    "propensity_low": low,
                    "propensity_high": high,
                    "n_extreme": int(extreme.sum()),
                    "propensity_min": round(float(propensity.min()), 6),
                    "propensity_max": round(float(propensity.max()), 6),
                    "propensity_model": model_name,
                    "cv_folds": folds,
                    "passed": passed,
                },
                affected_columns=covariate_names,
                impact_on_analysis=(
                    "Some units have almost no comparable controls on these covariates, so "
                    "their effect is extrapolated rather than observed. The confidence "
                    "interval will look narrow, but narrow in a way that means nothing; the "
                    "conclusion may not be worded above associational."
                    if not passed
                    else "Common support is adequate."
                ),
                recommended_repair=(
                    "Restrict the population to the region with common support (and state in "
                    "the report that the estimand changes accordingly), or drop the "
                    "adjustment-set variables driving the separation. A waiver must state "
                    "its reason."
                    if not passed
                    else ""
                ),
            )
        )

        layer, severity, waivable = _issue_settings(config, "backdoor_covariate_imbalance")
        max_smd = _threshold(config, "backdoor_covariate_imbalance", "max_abs_smd", 0.10)
        before = {
            name: standardized_mean_difference(covariates[:, j], treatment)
            for j, name in enumerate(covariate_names)
        }
        after = {
            name: standardized_mean_difference(covariates[:, j], treatment, weights)
            for j, name in enumerate(covariate_names)
        }
        imbalanced = [name for name, smd in after.items() if abs(smd) > max_smd]
        passed = not imbalanced
        issues.append(
            QualityIssue(
                check_id="backdoor_covariate_imbalance",
                layer=layer,
                severity=severity if not passed else Severity.INFO,
                waivable=waivable,
                summary=(
                    f"after IPW, {len(imbalanced)}/{len(covariate_names)} covariates still "
                    f"have |SMD| > {max_smd:g}"
                ),
                evidence={
                    "n_covariates": len(covariate_names),
                    "n_imbalanced_after": len(imbalanced),
                    "max_abs_smd_before": round(max(abs(v) for v in before.values()), 6),
                    "max_abs_smd_after": round(max(abs(v) for v in after.values()), 6),
                    "threshold": max_smd,
                    "passed": passed,
                },
                affected_columns=imbalanced,
                impact_on_analysis=(
                    "Imbalance persisting after weighting means the propensity model did "
                    "not remove these between-group differences, so the adjustment may be "
                    "incomplete."
                ),
                recommended_repair=(
                    "Use a more flexible propensity model, or check whether these variables "
                    "simply lack common support."
                ),
            )
        )

    # ---- 4. extreme weights and effective sample size (feasibility) ----
    layer, severity, waivable = _issue_settings(config, "backdoor_extreme_weights")
    min_ess_ratio = _threshold(config, "backdoor_extreme_weights", "min_ess_ratio", 0.20)
    ess = effective_sample_size(weights)
    ratio = ess / len(weights)
    passed = ratio >= min_ess_ratio
    issues.append(
        QualityIssue(
            check_id="backdoor_extreme_weights",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=(
                f"IPW effective sample size {ess:.0f} of {len(weights)} "
                f"({ratio:.1%}, threshold {min_ess_ratio:.0%})"
            ),
            evidence={
                "effective_sample_size": round(ess, 2),
                "n": len(weights),
                "ess_ratio": round(ratio, 6),
                "threshold": min_ess_ratio,
                "max_weight": round(float(weights.max()), 4),
                "passed": passed,
            },
            affected_columns=[treatment_col],
            impact_on_analysis=(
                "A handful of individuals dominate the estimate, which is therefore very "
                "sensitive to those few."
            ),
            recommended_repair=(
                "Clip the extreme weights (and report the sensitivity to clipping), or "
                "restrict the population."
            ),
        )
    )

    return QualityReport(issues=issues)

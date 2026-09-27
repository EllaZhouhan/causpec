"""hte_backdoor: the CausalForestDML adapter and the overlap / SMD checks.

Mirrors design.md 8.1 (identification and feasibility layers) and 10.2 (one of the
two blocking checks).
"""

from __future__ import annotations

import numpy as np
import pytest
from dataset_a import config_for, generate, truth

from causpec.core import registry
from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.gates import GateError, check_all
from causpec.families.hte_backdoor.checks import (
    effective_sample_size,
    estimate_propensity,
    standardized_mean_difference,
)

COVARIATES = [
    "admission_age",
    "max_aki_stage_smoothed",
    "max_potassium",
    "min_bicarbonate",
    "max_creatinine",
    "sofa_total_24h",
    "min_GCS_Total",
    "noise_00",
    "noise_01",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="confirmed", status=Status.CONFIRMED)


def make_spec(params: dict[str, object] | None = None) -> Spec:
    return Spec(
        question="What is the average effect of dialysis on mortality?",
        family="hte_backdoor",
        estimation={"params": params or {"n_estimators": 100}},
        fields={
            "treatment": confirmed("isDialysisICU"),
            "outcome": confirmed("death"),
            "estimand": confirmed("ate"),
            "effect_modifiers": confirmed(COVARIATES),
        },
    )


@pytest.fixture(scope="module")
def data():
    return generate(config_for("high_power", seed=100, n=2000))


@pytest.fixture(scope="module")
def broken_overlap(data):
    """Destroy common support: above-median SOFA is almost certainly treated, below-median
    almost certainly not."""
    rng = np.random.default_rng(0)
    broken = data.copy()
    sofa = data["sofa_total_24h"].to_numpy()
    probability = np.where(sofa > np.median(sofa), 0.97, 0.03)
    broken["isDialysisICU"] = (rng.uniform(size=len(data)) < probability).astype(int)
    return broken


@pytest.fixture(scope="module")
def report(data):
    return registry.get("hte_backdoor").check(data, make_spec())


@pytest.fixture(scope="module")
def result(data):
    return registry.get("hte_backdoor").estimate(data, make_spec(), seed=42)


# ---- the statistics themselves ----


def test_smd_is_zero_when_groups_match() -> None:
    values = np.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0])
    treatment = np.array([1, 1, 1, 0, 0, 0])
    assert abs(standardized_mean_difference(values, treatment)) < 1e-12


def test_smd_scales_by_pooled_sd() -> None:
    """When the two group means differ by one pooled standard deviation, SMD is 1."""
    rng = np.random.default_rng(0)
    control = rng.normal(0, 1, 20000)
    treated = rng.normal(1, 1, 20000)
    values = np.concatenate([treated, control])
    treatment = np.concatenate([np.ones(20000, int), np.zeros(20000, int)])
    assert abs(standardized_mean_difference(values, treatment) - 1.0) < 0.05


def test_smd_handles_constant_column() -> None:
    values = np.ones(10)
    assert standardized_mean_difference(values, np.array([1] * 5 + [0] * 5)) == 0.0


def test_ess_equals_n_for_uniform_weights() -> None:
    assert abs(effective_sample_size(np.ones(100)) - 100.0) < 1e-9


def test_ess_collapses_for_extreme_weights() -> None:
    weights = np.concatenate([np.ones(99), [1000.0]])
    assert effective_sample_size(weights) < 5.0


def test_propensity_is_cross_fitted(data) -> None:
    """Cross-fitting is mandatory: fitting and predicting on the same data pushes the
    scores towards 0 and 1."""
    covariates = data[COVARIATES].astype(float).to_numpy()
    treatment = data["isDialysisICU"].to_numpy().astype(int)
    scores = estimate_propensity(covariates, treatment, "gradient_boosting", 5, seed=0)
    assert scores.shape == (len(data),)
    assert scores.min() >= 0.0 and scores.max() <= 1.0


def test_unknown_propensity_model_is_rejected(data) -> None:
    covariates = data[COVARIATES].astype(float).to_numpy()
    treatment = data["isDialysisICU"].to_numpy().astype(int)
    with pytest.raises(ValueError, match="gradient_boosting"):
        estimate_propensity(covariates, treatment, "magic", 5, seed=0)


# ---- overlap (the blocking check) ----


def test_good_overlap_passes(report) -> None:
    assert report.blocking == []
    assert report.get("backdoor_overlap").evidence["passed"] is True


def test_broken_overlap_blocks(broken_overlap) -> None:
    """Negative control: passing on good data alone says nothing about usefulness."""
    report = registry.get("hte_backdoor").check(broken_overlap, make_spec())
    issue = report.get("backdoor_overlap")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["passed"] is False
    assert float(issue.evidence["extreme_fraction"]) > 0.5
    assert "extrapolated" in issue.impact_on_analysis


def test_broken_overlap_also_wrecks_balance_and_ess(broken_overlap) -> None:
    """The three checks corroborate each other: without common support the IPW weights
    blow up and balance cannot be repaired either."""
    report = registry.get("hte_backdoor").check(broken_overlap, make_spec())
    assert report.get("backdoor_covariate_imbalance").evidence["passed"] is False
    assert float(report.get("backdoor_extreme_weights").evidence["ess_ratio"]) < 0.20


def test_ipw_improves_balance(report) -> None:
    evidence = report.get("backdoor_covariate_imbalance").evidence
    assert float(evidence["max_abs_smd_after"]) < float(evidence["max_abs_smd_before"])


def test_empty_arm_stops_further_checks(data) -> None:
    no_treated = data.copy()
    no_treated["isDialysisICU"] = 0
    report = registry.get("hte_backdoor").check(no_treated, make_spec())
    assert [i.check_id for i in report.issues] == ["backdoor_treatment_prevalence"]


def test_smd_is_a_warning_not_a_blocker() -> None:
    """design.md 10.2 explicitly lists adjusted SMD as report-but-do-not-gate."""
    checks = registry.load_declaration("hte_backdoor")["checks"]
    assert checks["backdoor_covariate_imbalance"]["severity"] == "warning"
    assert checks["backdoor_overlap"]["severity"] == "blocking"


def test_gate_blocks_on_broken_overlap(broken_overlap) -> None:
    report = registry.get("hte_backdoor").check(broken_overlap, make_spec())
    with pytest.raises(GateError) as excinfo:
        check_all(make_spec(), report)
    assert excinfo.value.details["blocking_checks"] == ["backdoor_overlap"]


# ---- the estimator ----


def test_intervals_come_from_blb_not_bootstrap(result) -> None:
    """CausalForestDML's final model is the forest, so the ATE interval is analytic too.

    Contrast hte_iv: NonParamDMLIV's final model is an arbitrary regressor, so it can
    only bootstrap.
    """
    assert result.values["res:cate.ci_method"] == "blb"
    assert result.values["res:primary.ate_ci_method"] == "blb"
    assert result.values["res:estimation.estimator"] == "causal_forest_dml"


def test_ate_interval_is_present_and_ordered(result) -> None:
    assert result.values["res:primary.ate_ci_lower"] < result.values["res:primary.ate_ci_upper"]


def test_every_value_is_addressed(result) -> None:
    prefixes = ("res:primary.", "res:cate.", "res:sample.", "res:design.", "res:estimation.")
    assert all(address.startswith(prefixes) for address in result.values)


def test_reproducible_under_same_seed(data) -> None:
    family = registry.get("hte_backdoor")
    spec = make_spec()
    assert family.estimate(data, spec, seed=7) == family.estimate(data, spec, seed=7)


def test_n_estimators_must_divide_subforest_size(data) -> None:
    with pytest.raises(ValueError, match="divisible"):
        registry.get("hte_backdoor").estimate(data, make_spec({"n_estimators": 50}), seed=42)


def test_missing_effect_modifiers_is_rejected(data) -> None:
    spec = make_spec()
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "effect_modifiers"}}
    )
    with pytest.raises(ValueError, match="effect_modifiers"):
        registry.get("hte_backdoor").estimate(data, spec, seed=42)


# ---- against ground truth ----


def test_backdoor_cannot_remove_unobserved_confounding() -> None:
    """Backdoor adjustment cannot remove unmeasured confounding, which is exactly why
    hte_iv exists.

    With unmeasured confounding turned up, the naive difference and the backdoor
    estimate should both be badly biased, by comparable amounts. This pins dataset A's
    design intent: it has to be data that **only** IV can identify, or every later
    demonstration of why IV is needed falls apart.
    """
    df = generate(
        config_for(
            "high_power",
            seed=300,
            n=3000,
            confounding_on_treatment=1.6,
            confounding_on_outcome=1.4,
        )
    )
    facts = truth(df)
    result = registry.get("hte_backdoor").estimate(df, make_spec(), seed=42)

    naive_bias = facts["naive_difference"] - facts["ate_true"]
    backdoor_bias = float(result.values["res:primary.ate"]) - facts["ate_true"]

    assert naive_bias > 0.10
    assert backdoor_bias > 0.10  # still badly biased after adjustment

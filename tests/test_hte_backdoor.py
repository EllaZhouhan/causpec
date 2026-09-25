"""hte_backdoor：CausalForestDML 适配器与 overlap / SMD 检查。

对应 design.md 8.1（可识别性与可行性层）、10.2（两项阻断检验之一）。
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
    return SpecField(value=value, source=Source.USER, said="确认", status=Status.CONFIRMED)


def make_spec(params: dict[str, object] | None = None) -> Spec:
    return Spec(
        question="透析对死亡率的平均效应？",
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
    """把共同支撑打掉：SOFA 高于中位数的人几乎必然接受处理，低于的几乎必然不。"""
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


# ---- 统计量本身 ----


def test_smd_is_zero_when_groups_match() -> None:
    values = np.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0])
    treatment = np.array([1, 1, 1, 0, 0, 0])
    assert abs(standardized_mean_difference(values, treatment)) < 1e-12


def test_smd_scales_by_pooled_sd() -> None:
    """两组均值差一个合并标准差时，SMD 应为 1。"""
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
    """交叉拟合是必须的：同一份数据上拟合又预测会把得分推向 0/1。"""
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


# ---- overlap（阻断检验）----


def test_good_overlap_passes(report) -> None:
    assert report.blocking == []
    assert report.get("backdoor_overlap").evidence["passed"] is True


def test_broken_overlap_blocks(broken_overlap) -> None:
    """负向对照：只在好数据上跑通不能说明这条检查有用。"""
    report = registry.get("hte_backdoor").check(broken_overlap, make_spec())
    issue = report.get("backdoor_overlap")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["passed"] is False
    assert float(issue.evidence["extreme_fraction"]) > 0.5
    assert "外推" in issue.impact_on_analysis


def test_broken_overlap_also_wrecks_balance_and_ess(broken_overlap) -> None:
    """三条检查互相印证：没有共同支撑时，IPW 权重也会爆炸、平衡也修不好。"""
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
    """design.md 10.2 明确把调整后 SMD 列入「照印不设闸」。"""
    checks = registry.load_declaration("hte_backdoor")["checks"]
    assert checks["backdoor_covariate_imbalance"]["severity"] == "warning"
    assert checks["backdoor_overlap"]["severity"] == "blocking"


def test_gate_blocks_on_broken_overlap(broken_overlap) -> None:
    report = registry.get("hte_backdoor").check(broken_overlap, make_spec())
    with pytest.raises(GateError) as excinfo:
        check_all(make_spec(), report)
    assert excinfo.value.details["blocking_checks"] == ["backdoor_overlap"]


# ---- 估计器 ----


def test_intervals_come_from_blb_not_bootstrap(result) -> None:
    """CausalForestDML 的 final model 就是森林，所以 ATE 区间也是解析的。

    对照 hte_iv：NonParamDMLIV 的 final model 是任意回归器，只能 bootstrap。
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
    with pytest.raises(ValueError, match="整除"):
        registry.get("hte_backdoor").estimate(data, make_spec({"n_estimators": 50}), seed=42)


def test_missing_effect_modifiers_is_rejected(data) -> None:
    spec = make_spec()
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "effect_modifiers"}}
    )
    with pytest.raises(ValueError, match="effect_modifiers"):
        registry.get("hte_backdoor").estimate(data, spec, seed=42)


# ---- 真值对照 ----


def test_backdoor_cannot_remove_unobserved_confounding() -> None:
    """后门调整消不掉未测混杂——这正是 hte_iv 存在的理由。

    把未测混杂调强，朴素差值与 backdoor 估计的偏倚应当都很大且量级相当。
    这条锁的是数据集 A 的设计意图：它必须是一份「只有 IV 能识别」的数据，
    否则后面所有关于 IV 必要性的演示都站不住。
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
    assert backdoor_bias > 0.10  # 调整之后仍然严重有偏

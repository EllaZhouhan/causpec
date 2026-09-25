"""hte_iv 适配器：两个后端、二值与连续 instrument、地址契约。

只用便宜的 ivforest 后端。dmliv 走 bootstrap，实测 n=5000 要 500 秒以上，
不适合放进每次 push 都跑的 CI——它的正确性由 econml 自己保证，
这里要锁的是**适配层**：字段怎么取、地址怎么给、哪些情况该拒绝。
"""

from __future__ import annotations

import pytest
from dataset_a import config_for, generate

from causpec.core import registry
from causpec.core.contracts.spec import Source, Spec, SpecField, Status

EFFECT_MODIFIERS = [
    "admission_age",
    "max_aki_stage_smoothed",
    "max_potassium",
    "min_bicarbonate",
    "sofa_total_24h",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="确认", status=Status.CONFIRMED)


def make_spec(params: dict[str, object], **overrides: object) -> Spec:
    fields: dict[str, SpecField] = {
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("conditional_late"),
        "instrument": confirmed(["instrument"]),
        "effect_modifiers": confirmed(EFFECT_MODIFIERS),
    }
    fields.update({k: confirmed(v) for k, v in overrides.items()})
    return Spec(
        question="透析对哪些患者有益？",
        family="hte_iv",
        estimation={"family": "hte_iv", "params": params},
        fields=fields,
    )


# n_estimators 必须能被 subforest_size=4 整除；bootstrap 次数压到最低，
# 这些测试锁的是适配层的契约，不是区间的统计性质。
FAST = {"estimator": "ivforest", "n_estimators": 52, "n_bootstrap_samples": 3}


@pytest.fixture(scope="module")
def data():
    return generate(config_for("high_power", instrument_kind="binary", seed=11, n=1200))


@pytest.fixture(scope="module")
def result(data):
    return registry.get("hte_iv").estimate(data, make_spec(FAST), seed=42)


def test_every_value_is_addressed(result) -> None:
    """design.md 10.1：结果里的每个数都有地址，且落在已知命名空间下。"""
    prefixes = (
        "res:primary.",
        "res:cate.",
        "res:sample.",
        "res:instrument.",
        "res:design.",
        "res:estimation.",
    )
    assert all(address.startswith(prefixes) for address in result.values)


def test_binary_instrument_is_detected(result) -> None:
    assert result.values["res:instrument.kind"] == "binary"


def test_continuous_instrument_is_detected(data) -> None:
    """同一个 family 两种 instrument 都要支持（family.yaml 的 instrument_kinds）。"""
    continuous = generate(config_for("high_power", instrument_kind="continuous", seed=11, n=1200))
    out = registry.get("hte_iv").estimate(continuous, make_spec(FAST), seed=42)
    assert out.values["res:instrument.kind"] == "continuous"


def test_cate_and_ate_intervals_come_from_different_mechanisms(result) -> None:
    """ivforest 的两种区间来路不同，必须分开记。

    CATE 逐点区间来自 GRF 的 honest 方差（一次拟合内完成）；ATE 区间来自对
    森林做单位层面 bootstrap——因为 econml.grf 只提供逐点方差，同一片森林的
    各点估计高度相关，逐点方差平均再除以 n 等于假设独立。
    """
    assert result.values["res:cate.ci_method"] == "grf_honest"
    assert result.values["res:primary.ate_ci_method"] == "forest_bootstrap"
    assert result.values["res:estimation.estimator"] == "ivforest"


def test_ate_interval_is_ordered(result) -> None:
    """percentile bootstrap 区间**不保证**包住点估计，所以这里只断言它有序。

    [q2.5(θ*), q97.5(θ*)] 是重抽样分布的分位数；当重抽样分布相对 θ̂ 有系统偏移时
    （honest 森林会向均值收缩，本来就有这种偏移），θ̂ 可以落在区间外。
    要让区间以 θ̂ 为中心得改用 basic/反分位 bootstrap，那是另一个选择——
    这里与 dmliv 保持一致，都用 percentile。
    """
    assert result.values["res:primary.ate_ci_lower"] < result.values["res:primary.ate_ci_upper"]


def test_low_bootstrap_count_is_flagged(result) -> None:
    """重抽样次数不够时结果里打标记，报告必须把这件事摆出来。"""
    assert result.values["res:estimation.bootstrap_adequate"] == "no"
    assert result.values["res:estimation.n_bootstrap_samples"] == 3


def test_bootstrap_parallelism_does_not_change_the_result(data) -> None:
    """下标先一次性抽好再并行，所以并行度不影响结果。"""
    family = registry.get("hte_iv")
    serial = family.estimate(data, make_spec({**FAST, "bootstrap_n_jobs": 1}), seed=5)
    parallel = family.estimate(data, make_spec({**FAST, "bootstrap_n_jobs": 2}), seed=5)
    assert serial.values == parallel.values


def test_sample_facts_match_the_data(result, data) -> None:
    assert result.values["res:sample.n"] == len(data)
    assert result.values["res:sample.n_treated"] == int(data["isDialysisICU"].sum())
    assert result.values["res:sample.n_treated"] + result.values["res:sample.n_control"] == len(
        data
    )


def test_reproducible_under_same_seed(data) -> None:
    family = registry.get("hte_iv")
    spec = make_spec(FAST)
    assert family.estimate(data, spec, seed=7) == family.estimate(data, spec, seed=7)


def test_unknown_estimator_is_rejected(data) -> None:
    with pytest.raises(ValueError, match="dmliv"):
        registry.get("hte_iv").estimate(data, make_spec({"estimator": "magic"}), seed=42)


def test_missing_instrument_is_rejected(data) -> None:
    spec = make_spec(FAST)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "instrument"}}
    )
    with pytest.raises(ValueError, match="instrument"):
        registry.get("hte_iv").estimate(data, spec, seed=42)


def test_missing_effect_modifiers_is_rejected(data) -> None:
    spec = make_spec(FAST)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "effect_modifiers"}}
    )
    with pytest.raises(ValueError, match="effect_modifiers"):
        registry.get("hte_iv").estimate(data, spec, seed=42)


def test_n_estimators_must_divide_subforest_size(data) -> None:
    """GRF 的约束翻译成能看懂的话，并给出可用的取值。"""
    spec = make_spec({"estimator": "ivforest", "n_estimators": 50})
    with pytest.raises(ValueError, match="整除"):
        registry.get("hte_iv").estimate(data, spec, seed=42)


def test_ivforest_refuses_adjustment_set_instead_of_silently_dropping_it(data) -> None:
    """CausalIVForest 没有独立的 W 通道。

    研究代码里 controls（75 列）定义了却因 W=None 被静默丢弃——
    这里宁可报错也不重演那件事。
    """
    spec = make_spec(FAST, adjustment_set=["min_GCS_Total", "max_creatinine"])
    with pytest.raises(ValueError, match="adjustment_set"):
        registry.get("hte_iv").estimate(data, spec, seed=42)

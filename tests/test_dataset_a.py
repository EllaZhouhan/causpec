"""合成数据集 A：真值自洽性与工具变量的有效性。

对应 design.md 第 15、16 节。这些测试锁的是**生成器本身对不对**——
如果 tau_true 不是真的真值，后面所有数值 evals 都建在沙子上。
"""

from __future__ import annotations

import numpy as np
import pytest
from dataset_a import PRESETS, DatasetAConfig, config_for, generate, truth


@pytest.fixture(scope="module")
def binary_data():
    return generate(config_for("high_power", instrument_kind="binary", seed=11, n=6000))


def test_same_seed_same_data() -> None:
    a = generate(DatasetAConfig(n=500, seed=3))
    b = generate(DatasetAConfig(n=500, seed=3))
    assert a.equals(b)


def test_different_seed_different_data() -> None:
    a = generate(DatasetAConfig(n=500, seed=3))
    b = generate(DatasetAConfig(n=500, seed=4))
    assert not a["death"].equals(b["death"])


def test_tau_true_equals_potential_outcome_difference(binary_data) -> None:
    """τ 必须由潜在结局概率直接算出。

    早先的版本把 τ 定义成风险差再 clip 到 [0,1]，在 4% 的基线死亡率下被大量截断，
    tau_true 记的就不再是真实效应——这个 bug 由真值验证抓出来，所以锁在这里。
    """
    expected = binary_data["p1_true"] - binary_data["p0_true"]
    assert np.allclose(binary_data["tau_true"], expected)


def test_potential_outcome_probabilities_are_valid(binary_data) -> None:
    for column in ("p0_true", "p1_true"):
        assert binary_data[column].between(0.0, 1.0).all()


def test_effect_is_heterogeneous_in_the_intended_direction(binary_data) -> None:
    """AKI 越重获益越多；AKI 0 期反而受害。"""
    by_stage = binary_data.groupby("max_aki_stage_smoothed")["tau_true"].mean()
    assert by_stage.loc[0] > 0 > by_stage.loc[3]
    assert by_stage.is_monotonic_decreasing


def test_confounding_makes_naive_estimate_wrong(binary_data) -> None:
    """未观测混杂必须真的把朴素差值带偏——否则这份数据证明不了任何事。"""
    facts = truth(binary_data)
    assert facts["ate_true"] < 0 < facts["naive_difference"]


def test_instrument_is_relevant(binary_data) -> None:
    z, t = binary_data["instrument"], binary_data["isDialysisICU"]
    first_stage = t[z == 1].mean() - t[z == 0].mean()
    assert first_stage > 0.05


def test_monotonicity_holds_by_construction(binary_data) -> None:
    """二值 instrument 下不存在 defier。"""
    assert set(binary_data["compliance_type"]) <= {"always_taker", "never_taker", "complier"}


def test_first_stage_equals_complier_share(binary_data) -> None:
    """单调性下 E[T|Z=1] - E[T|Z=0] 就是 complier 占比。"""
    z, t = binary_data["instrument"], binary_data["isDialysisICU"]
    first_stage = t[z == 1].mean() - t[z == 0].mean()
    complier_share = (binary_data["compliance_type"] == "complier").mean()
    assert abs(first_stage - complier_share) < 0.02


def test_exclusion_restriction_holds(binary_data) -> None:
    """Z 只通过 T 影响 Y：固定 compliance 类型后，Z 与潜在结局无关。

    always-taker 与 never-taker 的处理状态不随 Z 变化，所以他们的结局
    在 Z=0 与 Z=1 两组间不应有系统差异。
    """
    non_compliers = binary_data[binary_data["compliance_type"] != "complier"]
    z = non_compliers["instrument"]
    gap = non_compliers.loc[z == 1, "death"].mean() - non_compliers.loc[z == 0, "death"].mean()
    assert abs(gap) < 0.03


def test_wald_estimator_recovers_late_without_outcome_noise(binary_data) -> None:
    """用真实概率代替 0/1 结局，Wald 估计量应逼近真 LATE。

    这是 IV 识别的恒等式检验：去掉结局抽样噪声后，剩下的偏差只该是
    Z 分组的有限样本波动。
    """
    ct = binary_data["compliance_type"].to_numpy()
    z = binary_data["instrument"].to_numpy()
    p0, p1 = binary_data["p0_true"].to_numpy(), binary_data["p1_true"].to_numpy()

    t_at_observed_z = np.where(ct == "always_taker", 1, np.where(ct == "never_taker", 0, z))
    assert (t_at_observed_z == binary_data["isDialysisICU"].to_numpy()).all()

    p_y = np.where(t_at_observed_z == 1, p1, p0)
    reduced_form = p_y[z == 1].mean() - p_y[z == 0].mean()
    first_stage = t_at_observed_z[z == 1].mean() - t_at_observed_z[z == 0].mean()
    late_true = (p1 - p0)[ct == "complier"].mean()

    assert abs(reduced_form / first_stage - late_true) < 0.01


def test_continuous_instrument_first_stage_is_monotone() -> None:
    import pandas as pd

    df = generate(config_for("high_power", instrument_kind="continuous", seed=11, n=6000))
    bins = pd.qcut(df["instrument"], 5, labels=False, duplicates="drop")
    rates = np.asarray(df.groupby(bins)["isDialysisICU"].mean())
    assert np.all(np.diff(rates) > 0)
    # 连续 IV 下没有 always/never/complier 三分类
    assert set(df["compliance_type"].unique()) == {"unknown"}


def test_presets_hit_their_targets() -> None:
    for preset in PRESETS:
        cfg = config_for(preset, n=4000, seed=5)
        df = generate(cfg)
        assert abs(df["isDialysisICU"].mean() - cfg.target_treatment_rate) < 0.03
        assert abs(df["death"].mean() - cfg.target_death_rate) < 0.03


def test_realistic_preset_matches_the_real_study_scale() -> None:
    """realistic 预设要对得上真实 ICU 研究的量级（处理率约 9.5%、死亡率约 4%）。"""
    df = generate(config_for("realistic", n=8000, seed=5))
    assert 0.06 < df["isDialysisICU"].mean() < 0.13
    assert 0.02 < df["death"].mean() < 0.07


def test_unknown_preset_lists_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="realistic"):
        config_for("nonexistent")

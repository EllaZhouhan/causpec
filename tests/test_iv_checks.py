"""hte_iv 的 instrument 检查：相关性、外生性、BH 校正、门控联动。

对应 design.md 8.2（instrument relevance）、8.3（Issue schema）、
10.2（两项阻断检验之一）、11.2（门控第 2 条）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from dataset_a import config_for, generate

from causpec.core import registry
from causpec.core.contracts.quality import QualityReport, Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.gates import GateError, check_all, check_no_blocking_issues
from causpec.families.hte_iv.checks import benjamini_hochberg, check_instrument

COVARIATES = [
    "admission_age",
    "max_aki_stage_smoothed",
    "max_potassium",
    "min_bicarbonate",
    "max_creatinine",
    "sofa_total_24h",
    "min_GCS_Total",
    "max_uo_12h_ml",
    "noise_00",
    "noise_01",
    "noise_02",
    "noise_03",
    "noise_04",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="确认", status=Status.CONFIRMED)


SPEC = Spec(
    question="透析对哪些患者有益？",
    family="hte_iv",
    fields={
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("conditional_late"),
        "instrument": confirmed(["instrument"]),
        "effect_modifiers": confirmed(COVARIATES),
    },
)

CONFIG = registry.load_declaration("hte_iv")["checks"]


@pytest.fixture(scope="module")
def strong():
    return generate(config_for("high_power", instrument_kind="binary", seed=100, n=4000))


@pytest.fixture(scope="module")
def weak():
    return generate(
        config_for(
            "high_power", instrument_kind="binary", seed=100, n=4000, instrument_strength=0.06
        )
    )


@pytest.fixture(scope="module")
def strong_report(strong):
    return check_instrument(strong, SPEC, CONFIG)


# ---- Benjamini–Hochberg ----


def test_bh_controls_fdr_under_the_null() -> None:
    """全是真零假设时几乎不该有拒绝。"""
    rng = np.random.default_rng(7)
    assert benjamini_hochberg(rng.uniform(size=1000), 0.10).sum() <= 10


def test_bh_finds_true_signals() -> None:
    rng = np.random.default_rng(7)
    p = np.concatenate([rng.uniform(0, 1e-8, 50), rng.uniform(size=950)])
    rejected = benjamini_hochberg(p, 0.10)
    assert rejected[:50].all()
    assert rejected.sum() < 70  # 假发现受控


def test_bh_handles_empty_input() -> None:
    assert benjamini_hochberg(np.array([]), 0.10).shape == (0,)


def test_bh_is_less_conservative_than_bonferroni() -> None:
    p = np.array([0.001, 0.008, 0.02, 0.04, 0.5])
    assert benjamini_hochberg(p, 0.10).sum() >= (p < 0.10 / len(p)).sum()


# ---- 相关性（阻断检验）----


def test_strong_instrument_passes_all_checks(strong_report) -> None:
    assert strong_report.blocking == []
    assert strong_report.get("iv_weak_first_stage").evidence["passed"] is True


def test_weak_instrument_blocks(weak) -> None:
    report = check_instrument(weak, SPEC, CONFIG)
    issue = report.get("iv_weak_first_stage")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["passed"] is False
    assert float(issue.evidence["robust_f"]) < float(issue.evidence["robust_f_threshold"])
    assert issue.recommended_repair  # 结构化错误必须带修复建议


def test_first_stage_reports_both_linear_and_probit_diagnostics(strong_report) -> None:
    """design.md 8.2：诊断形式由 family 决定，不统一使用 first-stage F。

    treatment 是二值，所以线性稳健 F 与 Probit 的 LR 检验、McFadden 增量 R²
    一并报出，由读者判断。
    """
    evidence = strong_report.get("iv_weak_first_stage").evidence
    for key in ("robust_f", "partial_r2", "lr_statistic", "lr_p_value", "mcfadden_r2_increment"):
        assert key in evidence


def test_zero_variation_instrument_is_blocked_and_not_waivable(strong) -> None:
    degenerate = strong.copy()
    degenerate["instrument"] = 1
    report = check_instrument(degenerate, SPEC, CONFIG)
    issue = report.get("iv_zero_variation")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    # 没有变异就不必往下算，后面的检查不应出现
    assert [i.check_id for i in report.issues] == ["iv_zero_variation"]


# ---- 外生性 ----


def test_balanced_instrument_passes(strong_report) -> None:
    issue = strong_report.get("iv_covariate_imbalance")
    assert issue.evidence["passed"] is True
    assert issue.evidence["n_imbalanced"] == 0


def test_endogenous_instrument_is_detected(strong) -> None:
    """人为让 instrument 与病情严重度相关，检查必须抓到。

    这是这条检查的负向对照——只在外生数据上跑通不能说明它有用。
    """
    rng = np.random.default_rng(0)
    broken = strong.copy()
    severity = strong["sofa_total_24h"].to_numpy()
    probability = 1 / (1 + np.exp(-0.45 * (severity - severity.mean())))
    broken["instrument"] = (rng.uniform(size=len(strong)) < probability).astype(int)

    issue = check_instrument(broken, SPEC, CONFIG).get("iv_covariate_imbalance")
    assert issue.evidence["passed"] is False
    assert issue.severity is Severity.WARNING  # 不阻断：exclusion 本就无法检验
    assert "sofa_total_24h" in issue.affected_columns


def test_imbalance_is_a_warning_not_a_blocker(strong) -> None:
    """exclusion restriction 无法检验，失衡是坏信号但不是证明，因此不阻断。"""
    assert CONFIG["iv_covariate_imbalance"]["severity"] == "warning"


# ---- complier 占比 ----


def test_low_complier_share_warns(weak) -> None:
    issue = check_instrument(weak, SPEC, CONFIG).get("iv_low_complier_share")
    assert issue.evidence["passed"] is False
    assert issue.severity is Severity.WARNING
    # 估计对象只对 complier 成立这件事必须说出来（design.md 7.6）
    assert "complier" in issue.impact_on_analysis
    assert "适用人群" in issue.recommended_repair


def test_complier_share_skipped_for_continuous_instrument() -> None:
    """连续 instrument 下没有 complier 三分类，这条检查不适用。"""
    df = generate(config_for("high_power", instrument_kind="continuous", seed=100, n=3000))
    report = check_instrument(df, SPEC, CONFIG)
    with pytest.raises(KeyError):
        report.get("iv_low_complier_share")


# ---- 地址与门控 ----


def test_every_evidence_item_has_an_address(strong_report) -> None:
    addresses = strong_report.addresses()
    assert all(address.startswith("qc:") for address in addresses)
    assert "qc:iv_weak_first_stage.robust_f" in addresses


def test_boolean_evidence_renders_as_words(strong_report) -> None:
    """报告正文要能直接代入，所以布尔值转成 yes/no 而不是 True/False。"""
    assert strong_report.addresses()["qc:iv_weak_first_stage.passed"] == "yes"


def test_gate_blocks_on_blocking_issues(weak) -> None:
    report = check_instrument(weak, SPEC, CONFIG)
    with pytest.raises(GateError) as excinfo:
        check_all(SPEC, report)
    assert excinfo.value.code == "BLOCKING_QUALITY_ISSUES"
    assert excinfo.value.details["blocking_checks"] == ["iv_weak_first_stage"]


def test_waiver_with_reason_unblocks(weak) -> None:
    report = check_instrument(weak, SPEC, CONFIG)
    check_all(SPEC, report, waived={"iv_weak_first_stage": "预注册的敏感性分析，已在方案中说明"})


def test_waiver_without_reason_does_not_unblock(weak) -> None:
    """豁免必须附理由（design.md 第 12 节 record_waiver）。"""
    report = check_instrument(weak, SPEC, CONFIG)
    with pytest.raises(GateError):
        check_all(SPEC, report, waived={"iv_weak_first_stage": "   "})


def test_non_waivable_check_cannot_be_waived(strong) -> None:
    degenerate = strong.copy()
    degenerate["instrument"] = 1
    report = check_instrument(degenerate, SPEC, CONFIG)
    with pytest.raises(GateError) as excinfo:
        check_no_blocking_issues(report, waived={"iv_zero_variation": "无所谓"})
    assert excinfo.value.details["not_waivable"] == ["iv_zero_variation"]


def test_empty_report_passes_the_gate() -> None:
    check_all(SPEC, QualityReport())


def test_family_exposes_check_through_the_protocol(strong) -> None:
    """core 通过协议调 family 的检查，不认识 check_instrument 本身。"""
    report = registry.get("hte_iv").check(strong, SPEC)
    assert report.get("iv_weak_first_stage").evidence["passed"] is True


def test_hte_backdoor_check_is_empty_for_now(strong) -> None:
    assert registry.get("hte_backdoor").check(pd.DataFrame(), SPEC).issues == []

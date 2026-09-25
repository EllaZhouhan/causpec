"""措辞等级判定。

对应 design.md 10.2 与原则 5（措辞强度由代码决定，模型不能自行升级）。

这个文件锁的是两条最容易被"优化"掉的性质：
代码给不出 causal；豁免不改变诊断结论。
"""

from __future__ import annotations

import pytest

from causpec.core.contracts.quality import (
    Layer,
    QualityIssue,
    QualityReport,
    Severity,
)
from causpec.core.contracts.spec import (
    Assumption,
    AssumptionCategory,
    Source,
    Spec,
    SpecField,
    Status,
)
from causpec.core.reporting.claim_level import (
    CAUSAL_APPROVAL_FIELD,
    ClaimLevel,
    determine,
    load_rules,
    rules_hash,
)

UNTESTABLE = Assumption(
    id="unconfoundedness",
    category=AssumptionCategory.UNTESTABLE,
    statement="给定调整集后处理分配与潜在结局独立",
)
JUSTIFIED = UNTESTABLE.model_copy(
    update={
        "justification": "本院透析决策由固定方案驱动，方案变量已全部纳入调整集",
        "justified_by": Source.USER,
    }
)
EMPIRICAL = Assumption(
    id="positivity",
    category=AssumptionCategory.EMPIRICALLY_ASSESSED,
    statement="每个协变量取值下两种处理都有正概率",
)


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="确认", status=Status.CONFIRMED)


def make_spec(assumptions: list[Assumption], approved: bool = False) -> Spec:
    fields = {"treatment": confirmed("t"), "outcome": confirmed("y"), "estimand": confirmed("ate")}
    if approved:
        fields[CAUSAL_APPROVAL_FIELD] = confirmed(True)
    return Spec(question="q", family="hte_backdoor", assumptions=assumptions, fields=fields)


def issue(check_id: str, passed: bool, declared: Severity = Severity.BLOCKING) -> QualityIssue:
    """按 QualityIssue 的不变量构造：通过时 severity 降为 INFO。"""
    return QualityIssue(
        check_id=check_id,
        layer=Layer.IDENTIFICATION,
        severity=Severity.INFO if passed else declared,
        waivable=True,
        summary=f"{check_id} {'通过' if passed else '未通过'}",
        evidence={"passed": passed},
    )


PASSING = QualityReport(issues=[issue("backdoor_overlap", True)])
FAILING = QualityReport(issues=[issue("backdoor_overlap", False)])


# ---- 四级 ----


def test_gate_failure_gives_descriptive() -> None:
    decision = determine(make_spec([JUSTIFIED]), PASSING, gate_passed=False)
    assert decision.level is ClaimLevel.DESCRIPTIVE
    assert "门控未通过" in decision.reasons[0]


def test_failed_blocking_check_gives_associational() -> None:
    decision = determine(make_spec([JUSTIFIED], approved=True), FAILING, gate_passed=True)
    assert decision.level is ClaimLevel.ASSOCIATIONAL
    assert decision.failed_blocking_checks == ["backdoor_overlap"]


def test_all_checks_passed_gives_suggestive() -> None:
    decision = determine(make_spec([UNTESTABLE]), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE


def test_causal_requires_justification_and_approval() -> None:
    decision = determine(make_spec([JUSTIFIED], approved=True), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.CAUSAL


# ---- 代码只能降级，不能授予 causal ----


def test_code_cannot_grant_causal_without_user_justification() -> None:
    """诊断全过、用户也点头了，但假设没人论证——仍然只能到 suggestive。"""
    decision = determine(make_spec([UNTESTABLE], approved=True), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE
    assert decision.unjustified_assumptions == ["unconfoundedness"]


def test_model_justification_does_not_count() -> None:
    """模型论证自己的假设成立是循环的。"""
    by_model = UNTESTABLE.model_copy(
        update={"justification": "我认为成立", "justified_by": Source.MODEL}
    )
    decision = determine(make_spec([by_model], approved=True), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE
    assert decision.unjustified_assumptions == ["unconfoundedness"]


def test_empty_justification_does_not_count() -> None:
    blank = UNTESTABLE.model_copy(update={"justification": "   ", "justified_by": Source.USER})
    decision = determine(make_spec([blank], approved=True), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE


def test_causal_requires_explicit_user_approval() -> None:
    decision = determine(make_spec([JUSTIFIED]), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE
    assert any(CAUSAL_APPROVAL_FIELD in reason for reason in decision.reasons)


def test_only_untestable_assumptions_gate_causal() -> None:
    """经验可查的假设由质量检查负责，不需要用户额外论证。"""
    decision = determine(
        make_spec([JUSTIFIED, EMPIRICAL], approved=True), PASSING, gate_passed=True
    )
    assert decision.level is ClaimLevel.CAUSAL


def test_no_assumptions_declared_still_needs_approval() -> None:
    decision = determine(make_spec([]), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE


# ---- 豁免 ----


def test_waiver_does_not_change_the_diagnosis() -> None:
    """豁免让分析得以进行，但不会让问题消失。"""
    decision = determine(
        make_spec([JUSTIFIED], approved=True),
        FAILING,
        gate_passed=True,
        waived={"backdoor_overlap": "已限制到有共同支撑的子人群"},
    )
    assert decision.level is ClaimLevel.ASSOCIATIONAL
    assert decision.waived_blocking_checks == ["backdoor_overlap"]
    assert any("已豁免，但诊断结论不变" in reason for reason in decision.reasons)


def test_waived_analysis_cannot_reach_causal() -> None:
    """即使被豁免的那条检查与本次结论无关，豁免过的分析也不得用 causal 级措辞。"""
    report = QualityReport(issues=[issue("backdoor_overlap", True), issue("other_check", True)])
    decision = determine(
        make_spec([JUSTIFIED], approved=True),
        report,
        gate_passed=True,
        waived={"other_check": "与本次结论无关"},
    )
    assert decision.level is ClaimLevel.SUGGESTIVE
    assert any("豁免" in reason for reason in decision.reasons)


# ---- 规则与地址 ----


def test_rules_declare_the_code_maximum() -> None:
    assert load_rules()["code_maximum"] == "suggestive"


def test_rules_hash_is_stable_and_recorded() -> None:
    decision = determine(make_spec([JUSTIFIED], approved=True), PASSING, gate_passed=True)
    assert decision.rules_hash == rules_hash()
    assert len(decision.rules_hash) == 16


def test_addresses_are_namespaced() -> None:
    decision = determine(make_spec([JUSTIFIED], approved=True), PASSING, gate_passed=True)
    addresses = decision.addresses()
    assert all(address.startswith("claim:") for address in addresses)
    assert addresses["claim:level"] == "causal"


def test_every_downgrade_states_a_reason() -> None:
    """design.md 10.2：任何降级都要写明是哪项检验、实测值多少、线在哪。"""
    for report, gate in [(FAILING, True), (PASSING, True), (PASSING, False)]:
        decision = determine(make_spec([UNTESTABLE]), report, gate_passed=gate)
        if decision.level is not ClaimLevel.CAUSAL:
            assert decision.reasons


def test_at_most_compares_levels() -> None:
    decision = determine(make_spec([UNTESTABLE]), PASSING, gate_passed=True)
    assert decision.at_most(ClaimLevel.SUGGESTIVE)
    assert not decision.at_most(ClaimLevel.ASSOCIATIONAL)


def test_custom_rules_file_is_honoured(tmp_path) -> None:
    """规则可配——阈值与规则都不该写死在代码里。"""
    import yaml

    rules = load_rules()
    rules["rules"]["all_blocking_checks_passed"] = "associational"
    path = tmp_path / "claim_levels.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")

    decision = determine(make_spec([UNTESTABLE]), PASSING, gate_passed=True, rules_path=path)
    assert decision.level is ClaimLevel.ASSOCIATIONAL
    assert decision.rules_hash == rules_hash(path)


@pytest.mark.parametrize("level", list(ClaimLevel))
def test_every_level_has_wording_guidance(level: ClaimLevel) -> None:
    """skill 要照着这段写正文，四级都得有。"""
    assert load_rules()["wording"][level.value]

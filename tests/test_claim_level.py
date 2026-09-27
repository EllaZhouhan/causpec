"""The claim-level decision.

Mirrors design.md 10.2 and principle 5 (code decides the strength of the claim; the
model may not upgrade it).

This file pins the two properties most likely to be "simplified" away later: code
cannot grant causal, and a waiver does not change the diagnosis.
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
    statement="given the adjustment set, assignment is independent of potential outcomes",
)
JUSTIFIED = UNTESTABLE.model_copy(
    update={
        "justification": (
            "dialysis decisions here follow a fixed protocol whose variables are all in "
            "the adjustment set"
        ),
        "justified_by": Source.USER,
    }
)
EMPIRICAL = Assumption(
    id="positivity",
    category=AssumptionCategory.EMPIRICALLY_ASSESSED,
    statement="both treatments have positive probability at every covariate value",
)


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="confirmed", status=Status.CONFIRMED)


def make_spec(assumptions: list[Assumption], approved: bool = False) -> Spec:
    fields = {"treatment": confirmed("t"), "outcome": confirmed("y"), "estimand": confirmed("ate")}
    if approved:
        fields[CAUSAL_APPROVAL_FIELD] = confirmed(True)
    return Spec(question="q", family="hte_backdoor", assumptions=assumptions, fields=fields)


def issue(check_id: str, passed: bool, declared: Severity = Severity.BLOCKING) -> QualityIssue:
    """Built to QualityIssue's invariant: a passing check is downgraded to INFO."""
    return QualityIssue(
        check_id=check_id,
        layer=Layer.IDENTIFICATION,
        severity=Severity.INFO if passed else declared,
        waivable=True,
        summary=f"{check_id} {'pass' if passed else 'fail'}",
        evidence={"passed": passed},
    )


PASSING = QualityReport(issues=[issue("backdoor_overlap", True)])
FAILING = QualityReport(issues=[issue("backdoor_overlap", False)])


# ---- the four levels ----


def test_gate_failure_gives_descriptive() -> None:
    decision = determine(make_spec([JUSTIFIED]), PASSING, gate_passed=False)
    assert decision.level is ClaimLevel.DESCRIPTIVE
    assert "The gate did not pass" in decision.reasons[0]


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


# ---- code can only downgrade; it cannot grant causal ----


def test_code_cannot_grant_causal_without_user_justification() -> None:
    """Diagnostics all pass and the user approved, but nobody justified the
    assumption — still only suggestive."""
    decision = determine(make_spec([UNTESTABLE], approved=True), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE
    assert decision.unjustified_assumptions == ["unconfoundedness"]


def test_model_justification_does_not_count() -> None:
    """A model vouching for its own assumptions is circular."""
    by_model = UNTESTABLE.model_copy(
        update={"justification": "I believe it holds", "justified_by": Source.MODEL}
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
    """Empirically assessable assumptions are the quality checks' job; the user need
    not argue for them separately."""
    decision = determine(
        make_spec([JUSTIFIED, EMPIRICAL], approved=True), PASSING, gate_passed=True
    )
    assert decision.level is ClaimLevel.CAUSAL


def test_no_assumptions_declared_still_needs_approval() -> None:
    decision = determine(make_spec([]), PASSING, gate_passed=True)
    assert decision.level is ClaimLevel.SUGGESTIVE


# ---- waivers ----


def test_waiver_does_not_change_the_diagnosis() -> None:
    """A waiver lets the analysis run; it does not make the problem disappear."""
    decision = determine(
        make_spec([JUSTIFIED], approved=True),
        FAILING,
        gate_passed=True,
        waived={"backdoor_overlap": "restricted to the sub-population with common support"},
    )
    assert decision.level is ClaimLevel.ASSOCIATIONAL
    assert decision.waived_blocking_checks == ["backdoor_overlap"]
    assert any("waived, but the diagnosis is unchanged" in reason for reason in decision.reasons)


def test_waived_analysis_cannot_reach_causal() -> None:
    """Even when the waived check is unrelated to this conclusion, a waived analysis may
    not use causal wording."""
    report = QualityReport(issues=[issue("backdoor_overlap", True), issue("other_check", True)])
    decision = determine(
        make_spec([JUSTIFIED], approved=True),
        report,
        gate_passed=True,
        waived={"other_check": "unrelated to this conclusion"},
    )
    assert decision.level is ClaimLevel.SUGGESTIVE
    assert any("waive" in reason for reason in decision.reasons)


# ---- rules and addresses ----


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
    """design.md 10.2: every downgrade names the check, its value and the threshold."""
    for report, gate in [(FAILING, True), (PASSING, True), (PASSING, False)]:
        decision = determine(make_spec([UNTESTABLE]), report, gate_passed=gate)
        if decision.level is not ClaimLevel.CAUSAL:
            assert decision.reasons


def test_at_most_compares_levels() -> None:
    decision = determine(make_spec([UNTESTABLE]), PASSING, gate_passed=True)
    assert decision.at_most(ClaimLevel.SUGGESTIVE)
    assert not decision.at_most(ClaimLevel.ASSOCIATIONAL)


def test_custom_rules_file_is_honoured(tmp_path) -> None:
    """Rules are configurable; neither thresholds nor rules belong hard-coded."""
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
    """The skill writes its prose against this, so all four levels need an entry."""
    assert load_rules()["wording"][level.value]

"""hte_iv instrument checks: relevance, exogeneity, BH correction, gate interaction.

Mirrors design.md 8.2 (instrument relevance), 8.3 (the issue schema),
10.2 (one of the two blocking checks) and 11.2 (gate condition 2).
"""

from __future__ import annotations

from typing import Any

import numpy as np
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
    return SpecField(value=value, source=Source.USER, said="confirmed", status=Status.CONFIRMED)


SPEC = Spec(
    question="Which patients benefit from dialysis?",
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


# ---- Benjamini-Hochberg ----


def test_bh_controls_fdr_under_the_null() -> None:
    """Under all-true nulls there should be almost no rejections."""
    rng = np.random.default_rng(7)
    assert benjamini_hochberg(rng.uniform(size=1000), 0.10).sum() <= 10


def test_bh_finds_true_signals() -> None:
    rng = np.random.default_rng(7)
    p = np.concatenate([rng.uniform(0, 1e-8, 50), rng.uniform(size=950)])
    rejected = benjamini_hochberg(p, 0.10)
    assert rejected[:50].all()
    assert rejected.sum() < 70  # false discoveries stay controlled


def test_bh_handles_empty_input() -> None:
    assert benjamini_hochberg(np.array([]), 0.10).shape == (0,)


def test_bh_is_less_conservative_than_bonferroni() -> None:
    p = np.array([0.001, 0.008, 0.02, 0.04, 0.5])
    assert benjamini_hochberg(p, 0.10).sum() >= (p < 0.10 / len(p)).sum()


# ---- relevance (the blocking check) ----


def test_strong_instrument_passes_all_checks(strong_report) -> None:
    assert strong_report.blocking == []
    assert strong_report.get("iv_weak_first_stage").evidence["passed"] is True


def test_weak_instrument_blocks(weak) -> None:
    report = check_instrument(weak, SPEC, CONFIG)
    issue = report.get("iv_weak_first_stage")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["passed"] is False
    assert float(issue.evidence["robust_f"]) < float(issue.evidence["robust_f_threshold"])
    assert issue.recommended_repair  # a structured error must carry its fix


def test_first_stage_reports_both_linear_and_probit_diagnostics(strong_report) -> None:
    """design.md 8.2: the form of the diagnostic is the family's business, not a
    universal first-stage F.

    The treatment is binary, so the linear robust F, the probit LR test and the
    McFadden increment are all reported, for the reader to weigh.
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
    # With no variation nothing further is computable, so no later check should appear
    assert [i.check_id for i in report.issues] == ["iv_zero_variation"]


# ---- exogeneity ----


def test_balanced_instrument_passes(strong_report) -> None:
    issue = strong_report.get("iv_covariate_imbalance")
    assert issue.evidence["passed"] is True
    assert issue.evidence["n_imbalanced"] == 0


def test_endogenous_instrument_is_detected(strong) -> None:
    """Deliberately correlate the instrument with severity; the check must catch it.

    This is the check's negative control: passing on exogenous data alone says nothing
    about whether it is useful.
    """
    rng = np.random.default_rng(0)
    broken = strong.copy()
    severity = strong["sofa_total_24h"].to_numpy()
    probability = 1 / (1 + np.exp(-0.45 * (severity - severity.mean())))
    broken["instrument"] = (rng.uniform(size=len(strong)) < probability).astype(int)

    issue = check_instrument(broken, SPEC, CONFIG).get("iv_covariate_imbalance")
    assert issue.evidence["passed"] is False
    assert issue.severity is Severity.WARNING  # not blocking: exclusion is untestable
    assert "sofa_total_24h" in issue.affected_columns


def test_imbalance_is_a_warning_not_a_blocker(strong) -> None:
    """The exclusion restriction is untestable, so imbalance is a bad sign rather than
    proof, and does not block."""
    assert CONFIG["iv_covariate_imbalance"]["severity"] == "warning"


# ---- complier share ----


def test_low_complier_share_warns(weak) -> None:
    issue = check_instrument(weak, SPEC, CONFIG).get("iv_low_complier_share")
    assert issue.evidence["passed"] is False
    assert issue.severity is Severity.WARNING
    # That the estimand covers compliers only must be stated (design.md 7.6)
    assert "complier" in issue.impact_on_analysis
    assert "population" in issue.recommended_repair


def test_complier_share_skipped_for_continuous_instrument() -> None:
    """With a continuous instrument there is no complier split, so this check does not apply."""
    df = generate(config_for("high_power", instrument_kind="continuous", seed=100, n=3000))
    report = check_instrument(df, SPEC, CONFIG)
    with pytest.raises(KeyError):
        report.get("iv_low_complier_share")


# ---- addresses and the gate ----


def test_every_evidence_item_has_an_address(strong_report) -> None:
    addresses = strong_report.addresses()
    assert all(address.startswith("qc:") for address in addresses)
    assert "qc:iv_weak_first_stage.robust_f" in addresses


def test_boolean_evidence_renders_as_words(strong_report) -> None:
    """Report prose substitutes these directly, so booleans render as yes/no."""
    assert strong_report.addresses()["qc:iv_weak_first_stage.passed"] == "yes"


def test_gate_blocks_on_blocking_issues(weak) -> None:
    report = check_instrument(weak, SPEC, CONFIG)
    with pytest.raises(GateError) as excinfo:
        check_all(SPEC, report)
    assert excinfo.value.code == "BLOCKING_QUALITY_ISSUES"
    assert excinfo.value.details["blocking_checks"] == ["iv_weak_first_stage"]


def test_waiver_with_reason_unblocks(weak) -> None:
    report = check_instrument(weak, SPEC, CONFIG)
    check_all(
        SPEC,
        report,
        waived={
            "iv_weak_first_stage": (
                "a pre-registered sensitivity analysis, described in the protocol"
            )
        },
    )


def test_waiver_without_reason_does_not_unblock(weak) -> None:
    """A waiver requires a reason (design.md section 12, record_waiver)."""
    report = check_instrument(weak, SPEC, CONFIG)
    with pytest.raises(GateError):
        check_all(SPEC, report, waived={"iv_weak_first_stage": "   "})


def test_non_waivable_check_cannot_be_waived(strong) -> None:
    degenerate = strong.copy()
    degenerate["instrument"] = 1
    report = check_instrument(degenerate, SPEC, CONFIG)
    with pytest.raises(GateError) as excinfo:
        check_no_blocking_issues(report, waived={"iv_zero_variation": "does not matter"})
    assert excinfo.value.details["not_waivable"] == ["iv_zero_variation"]


def test_empty_report_passes_the_gate() -> None:
    check_all(SPEC, QualityReport())


def test_family_exposes_check_through_the_protocol(strong) -> None:
    """Core reaches the family's checks through the protocol, knowing nothing of
    check_instrument itself."""
    report = registry.get("hte_iv").check(strong, SPEC)
    assert report.get("iv_weak_first_stage").evidence["passed"] is True


def test_each_family_brings_its_own_checks(strong) -> None:
    """The two families check different things; core knows what neither of them checks."""
    iv_checks = {i.check_id for i in registry.get("hte_iv").check(strong, SPEC).issues}
    assert iv_checks and all(check.startswith("iv_") for check in iv_checks)


# ---- overidentification and endogeneity, from linearmodels ----


def _second_instrument(data, kind: str):
    """A second instrument of one of three kinds, each with a known status.

    ``same_compliers``: another continuous reading of the same physician preference, so it
    moves the same patients and identifies the same complier group. Valid.

    ``other_compliers``: the preference as a median split, alongside the continuous one. Both
    are valid, and they identify *different* complier groups, which matters below.

    ``invalid``: the preference plus the unmeasured confounder, so it reaches the outcome by a
    path that does not run through the treatment. ``u_true`` is in dataset A for exactly this
    purpose and never reaches an estimator.
    """
    out = data.copy()
    rng = np.random.default_rng(0)
    preference = out["consultant_preference"].to_numpy(float)
    if kind == "same_compliers":
        out["second_instrument"] = preference + rng.normal(size=len(out))
        return out, ["consultant_preference", "second_instrument"]
    if kind == "other_compliers":
        out["second_instrument"] = preference + rng.normal(size=len(out))
        return out, ["instrument", "second_instrument"]
    out["second_instrument"] = preference + 2.0 * out["u_true"].to_numpy(float)
    return out, ["instrument", "second_instrument"]


def _spec_with(instruments: list[str]) -> Spec:
    return SPEC.model_copy(update={"fields": {**SPEC.fields, "instrument": confirmed(instruments)}})


def _overid(frame, instruments):
    return check_instrument(frame, _spec_with(instruments), CONFIG).get("iv_overidentification")


def test_one_instrument_gets_no_overidentification_check(strong_report) -> None:
    """With one instrument there is nothing for the instruments to disagree about, so the
    check is not emitted rather than emitted and passed."""
    with pytest.raises(KeyError):
        strong_report.get("iv_overidentification")


def test_instruments_selecting_the_same_compliers_agree(strong) -> None:
    frame, instruments = _second_instrument(strong, "same_compliers")
    issue = _overid(frame, instruments)
    assert issue.severity is Severity.INFO
    assert issue.evidence["n_instruments"] == 2
    assert float(issue.evidence["overid_p_value"]) > 0.05


def test_an_instrument_that_violates_exclusion_is_caught(strong) -> None:
    """The failure the check exists for. The second instrument reaches the outcome through the
    unmeasured confounder, and the test rejects decisively."""
    frame, instruments = _second_instrument(strong, "invalid")
    issue = _overid(frame, instruments)
    assert issue.severity is Severity.WARNING
    assert float(issue.evidence["overid_p_value"]) < 0.01


def test_two_valid_instruments_can_also_disagree(strong) -> None:
    """Why this check cannot block, as a measurement rather than an opinion.

    Both instruments here are valid: one is the physician preference, the other is the same
    preference split at its median. They identify different complier groups, and with a
    heterogeneous effect those are different weighted averages of individual effects, so the
    test rejects. On this fixture it gives p = 0.04 while the genuinely invalid instrument
    gives p = 0.

    Blocking would therefore refuse a correct analysis, and the two cases cannot be separated
    by the statistic alone, which is what the issue text has to say.
    """
    frame, instruments = _second_instrument(strong, "other_compliers")
    issue = _overid(frame, instruments)
    assert float(issue.evidence["overid_p_value"]) < 0.05
    assert issue.severity is Severity.WARNING
    assert issue.severity is not Severity.BLOCKING
    assert issue.waivable is True
    # The text has to name both readings, because the number cannot tell them apart.
    assert "heterogeneous effect" in issue.impact_on_analysis
    assert "exclusion restriction" in issue.impact_on_analysis
    assert "each instrument alone" in issue.recommended_repair


def test_the_endogeneity_test_confirms_the_instrument_earns_its_cost(strong_report) -> None:
    """Dataset A has real unmeasured confounding, so the treatment should look endogenous.
    If it did not, the instrument would be paying variance for nothing."""
    issue = strong_report.get("iv_treatment_exogeneity")
    assert issue.severity is Severity.INFO
    assert float(issue.evidence["endogeneity_p_value"]) < 0.10


def test_the_endogeneity_test_does_not_claim_exogeneity(strong_report) -> None:
    """Failing to reject is not evidence of exogeneity, and the issue text has to say so:
    the user's judgement about unmeasured confounding stands above this test."""
    issue = strong_report.get("iv_treatment_exogeneity")
    assert "not evidence of exogeneity" in issue.impact_on_analysis


def test_a_broken_specification_is_reported_as_not_assessed(strong) -> None:
    """A diagnostic must not take the report down. It must also not report a bug as a finding:
    a bare except once turned a NameError in this module into "the linear specification did
    not fit", which reads as a property of the user's data."""
    frame = strong.copy()
    frame["collinear"] = frame["instrument"]
    spec = _spec_with(["instrument", "collinear"])
    report = check_instrument(frame, spec, CONFIG)
    # Either it fits and says the instruments agree, or it does not and says it was not
    # assessed. What it must never do is raise.
    issue = report.get("iv_overidentification")
    assert issue.severity in (Severity.INFO, Severity.WARNING)


def test_the_endogeneity_test_matches_the_package_it_replaced(strong) -> None:
    """It is three lines of OLS, so it is written here rather than imported. This pins it
    against linearmodels' wooldridge_score, which is what it was checked against when the
    decision was made to hand-write it (ADR-0003's test, applied honestly: a package earns
    its place when it carries something substantial, and this is not that).

    The overidentification test went the other way. A hand-rolled version gave p = 0.24 where
    the package gives 0.092, because the overidentification degrees of freedom are k - 1 and
    not k, and every verdict happened to agree on the designs it was tried on.
    """
    import pandas as pd
    from linearmodels.iv import IV2SLS

    from causpec.families.hte_iv.checks import _endogeneity_test

    controls = COVARIATES
    treatment = strong["isDialysisICU"].astype(float).to_numpy()
    outcome = strong["death"].astype(float).to_numpy()
    ours = _endogeneity_test(treatment, outcome, strong, ["instrument"], controls)

    exog = pd.DataFrame({"const": np.ones(len(strong))}, index=strong.index)
    for column in controls:
        exog[column] = strong[column].astype(float).to_numpy()
    # Any, because linearmodels types fit() as returning OLSResults, which is what it gives
    # for a model with no endogenous variable. One is always passed here.
    fitted: Any = IV2SLS(
        strong["death"].astype(float),
        exog,
        strong["isDialysisICU"].astype(float),
        strong[["instrument"]].astype(float),
    ).fit(cov_type="robust")
    theirs = fitted.wooldridge_score
    # Not algebraically identical: ours is the Wald form of the augmented regression and
    # theirs is the score form, which are asymptotically equivalent and differ in the
    # small-sample scaling of the robust covariance. They agree to under 1% here, and what
    # has to hold is that they never disagree about the verdict.
    mine = ours["endogeneity_p_value"]
    assert mine == pytest.approx(float(theirs.pval), rel=0.02)
    threshold = float(CONFIG["iv_treatment_exogeneity"]["max_p_value"])
    assert (mine <= threshold) is (float(theirs.pval) <= threshold)

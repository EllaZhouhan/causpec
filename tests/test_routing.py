"""Gate condition 3 and the routing check: does this family answer this question?

Mirrors design.md 7.6 and 11.2. Two failures that reached the user as something worse than a
refusal, and one that reached them as nothing at all.

**A missing required field** surfaced from inside a family's own code, as
`ValueError: hte_iv's quality checks require spec.instrument` with a traceback. It is a
precondition stated in family.yaml, so it belongs in the gate.

**An estimand the family cannot identify** did not surface. `estimand` is a label the
estimator never reads, so `conditional_late` on `hte_backdoor` ran to completion and the
report described an average over everyone in the words for an effect among compliers: a
different population and a different number.

**A family that does not match how the treatment was assigned** also did not surface. A user
who says "randomised, but uptake was about 60%" and an analysis routed to `hte_backdoor` gets
an average effect that treats non-compliance as though it never happened, with every other
check passing. That one is a warning rather than a refusal, because defensible analyses exist
on both sides; what is not defensible is silence.
"""

from __future__ import annotations

import pandas as pd
import pytest

from causpec.core import registry
from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.gates import GateError, check_family_supports_spec
from causpec.core.quality import check_routing

COVARIATES = ["max_creatinine", "max_potassium", "min_ArterialPressure"]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(family: str = "hte_backdoor", **fields: object) -> Spec:
    declared = {
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("ate"),
        "effect_modifiers": confirmed(COVARIATES),
    }
    declared.update({name: confirmed(value) for name, value in fields.items()})
    return Spec(question="q", family=family, fields=declared)


def frame(columns: list[str] | None = None) -> pd.DataFrame:
    names = columns or [*COVARIATES, "isDialysisICU", "death"]
    return pd.DataFrame({name: [0.0, 1.0] for name in names})


# ---- the estimand has to be one the family can identify ----


def test_an_estimand_from_another_family_is_refused() -> None:
    """The silent wrong answer this closes. Nothing else in the pipeline reads this field."""
    spec = make_spec(estimand="conditional_late")
    with pytest.raises(GateError) as caught:
        check_family_supports_spec(spec)
    assert caught.value.code == "ESTIMAND_NOT_SUPPORTED"
    # And the message points at the family that can answer it, so the user has somewhere to go.
    assert "hte_iv" in caught.value.reason


def test_an_estimand_no_family_declares_is_refused() -> None:
    spec = make_spec(estimand="total_effect_over_time")
    with pytest.raises(GateError, match="No family declares"):
        check_family_supports_spec(spec)


def test_each_declared_estimand_passes_its_own_family() -> None:
    """The declarations are the authority, so the test reads them rather than repeating them.
    A family that adds an estimand gets covered without this file changing."""
    for family in ("hte_backdoor", "hte_iv"):
        for estimand in registry.declared_estimands(family):
            spec = make_spec(family=family, estimand=estimand, instrument="bed_availability")
            check_family_supports_spec(spec)


def test_a_spec_without_an_estimand_is_left_to_the_confirmation_gate() -> None:
    """`estimand` is a critical field, so condition 1 already refuses a spec without one.
    Refusing it here as well would report the same problem twice in different words."""
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "treatment": confirmed("isDialysisICU"),
            "outcome": confirmed("death"),
            "effect_modifiers": confirmed(COVARIATES),
        },
    )
    check_family_supports_spec(spec)


# ---- the required fields have to be there ----


def test_a_missing_required_field_is_refused_by_name() -> None:
    spec = make_spec(family="hte_iv")
    with pytest.raises(GateError) as caught:
        check_family_supports_spec(spec)
    assert caught.value.code == "FAMILY_REQUIRES_FIELDS"
    assert caught.value.details["missing_fields"] == ["instrument"]


def test_a_field_present_but_empty_counts_as_missing() -> None:
    spec = make_spec(family="hte_iv", instrument=None)
    with pytest.raises(GateError, match="instrument"):
        check_family_supports_spec(spec)


def test_the_declarations_only_require_what_the_code_requires() -> None:
    """An overstated declaration refuses specs that run perfectly well, which is how this was
    found: hte_backdoor listed `time_zero`, read only by the optional temporal checks, and
    `adjustment_set`, which is optional because W=None is a valid analysis. The panel family
    listed a field name that does not exist (`instant_outcome`) and two that are conditional.
    """
    assert registry.required_spec_fields("hte_backdoor") == [
        "treatment",
        "outcome",
        "effect_modifiers",
    ]
    for family in ("hte_backdoor", "hte_iv"):
        required = registry.required_spec_fields(family)
        assert "time_zero" not in required
        assert "adjustment_set" not in required
    panel = registry.required_spec_fields("dynamic_lag_dml")
    assert "instant_outcome" not in panel
    assert "termination" not in panel  # only when the horizon is variable
    assert "effect_modifiers" not in panel  # only for lag_cate


def test_every_declared_requirement_is_a_real_spec_field_name() -> None:
    """A requirement nobody can satisfy refuses every spec. The names a family's code reads
    are the authority, and `instant_outcome` was in a declaration while the code read
    `outcome`."""
    known = {
        "treatment",
        "outcome",
        "estimand",
        "effect_modifiers",
        "adjustment_set",
        "instrument",
        "unit_id",
        "period_index",
        "period_length",
        "state",
        "horizon",
        "termination",
        "max_lag",
        "time_zero",
    }
    for family in registry.declared_families():
        for name in registry.required_spec_fields(family):
            assert name in known, f"{family} requires unknown field {name!r}"


# ---- the assumptions an estimand rests on are declared ----


def test_each_estimand_names_the_assumptions_it_rests_on() -> None:
    """So the agent writes them into the spec from the declaration rather than from memory."""
    assert registry.estimand_assumptions("hte_backdoor", "ate") == [
        "unconfoundedness",
        "positivity",
        "consistency",
    ]
    assert "exclusion_restriction" in registry.estimand_assumptions("hte_iv", "conditional_late")


# ---- routing: the data's shape ----


def test_a_panel_analysed_by_a_cross_sectional_family_warns() -> None:
    data = frame([*COVARIATES, "isDialysisICU", "death", "period"])
    spec = make_spec(period_index="period")
    issue = check_routing(data, spec).get("family_matches_the_question")
    assert issue.severity is Severity.WARNING
    assert "counted twenty times" in issue.impact_on_analysis


def test_a_cross_sectional_table_in_the_panel_family_warns() -> None:
    spec = make_spec(family="dynamic_lag_dml")
    issue = check_routing(frame(), spec).get("family_matches_the_question")
    assert issue.severity is Severity.WARNING
    assert "no periods to build a lag profile from" in issue.impact_on_analysis


# ---- routing: how the treatment was assigned ----


def test_noncompliance_routed_to_an_adjustment_family_warns() -> None:
    """The case nothing said a word about. Comparing by treatment received throws away the
    randomisation and compares people who chose differently."""
    spec = make_spec(assignment_mechanism="randomised_with_noncompliance")
    issue = check_routing(frame(), spec).get("family_matches_the_question")
    assert issue.severity is Severity.WARNING
    assert "points to hte_iv" in issue.summary
    assert "throws away the randomisation" in issue.impact_on_analysis


def test_a_trial_with_full_compliance_belongs_in_the_adjustment_family() -> None:
    spec = make_spec(assignment_mechanism="randomised")
    issue = check_routing(frame(), spec).get("family_matches_the_question")
    assert issue.severity is Severity.INFO


def test_a_decided_treatment_fits_either_family() -> None:
    """Which one depends on whether a credible instrument exists, which is an argument rather
    than a fact about the table."""
    for family in ("hte_backdoor", "hte_iv"):
        spec = make_spec(family=family, assignment_mechanism="decided")
        issue = check_routing(frame(), spec).get("family_matches_the_question")
        assert issue.severity is Severity.INFO


def test_a_consistent_route_is_not_claimed_to_be_a_correct_one() -> None:
    spec = make_spec(assignment_mechanism="randomised")
    issue = check_routing(frame(), spec).get("family_matches_the_question")
    assert "not a correct one" in issue.impact_on_analysis


def test_without_the_assignment_field_the_check_says_it_could_not_run() -> None:
    issue = check_routing(frame(), make_spec()).get("family_matches_the_question")
    assert issue.severity is Severity.INFO
    assert issue.evidence["assessed"] is False
    assert "not evidence that the right family was chosen" in issue.impact_on_analysis


def test_the_shape_is_checked_before_the_assignment() -> None:
    """A panel in the wrong family is the harder error: it answers a question about rows
    rather than about patients, whatever the assignment was."""
    data = frame([*COVARIATES, "isDialysisICU", "death", "period"])
    spec = make_spec(period_index="period", assignment_mechanism="randomised")
    issue = check_routing(data, spec).get("family_matches_the_question")
    assert issue.severity is Severity.WARNING
    assert "one row per unit per period" in issue.summary

"""The dynamic_lag_dml declaration.

The family is declared and not implemented, so what there is to test is the
declaration and its agreement with the document the skill reads. That is worth
testing rather than waiting: the previous declaration (`longitudinal_ipcw`, a
target-trial layout with event_roles) described a marginal structural model, which is
not the method this project has, and nothing caught it because nothing compared the
declaration against the method.

Mirrors design.md 7.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from causpec.core import registry

FAMILY = "dynamic_lag_dml"
REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "skill" / "causpec-analyst" / "references" / "dynamic-lag-dml.md"

ASSUMPTION_CATEGORIES = {"empirically_assessed", "requires_justification", "untestable"}


@pytest.fixture(scope="module")
def declaration() -> dict:
    return registry.load_declaration(FAMILY)


@pytest.fixture(scope="module")
def reference_text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def test_the_family_is_declared(declaration: dict) -> None:
    assert declaration["id"] == FAMILY
    assert declaration["status"] == "planned"
    assert declaration["analysis_type"] == "panel"


def test_reading_the_declaration_needs_no_dependency() -> None:
    """As for every family: a declaration is read from disk, never by importing.

    Here it also means the panel family can be described to a user who has installed
    nothing beyond core.
    """
    declaration = registry.load_declaration(FAMILY)
    assert declaration["requires_extra"] == "dynamic"


def test_the_declared_extra_exists_in_pyproject(declaration: dict) -> None:
    """The registry turns requires_extra into an install command, so it has to be real."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert f"\n{declaration['requires_extra']} = [" in text


def test_both_estimands_are_declared_with_their_assumptions(declaration: dict) -> None:
    estimands = {entry["id"]: entry for entry in declaration["estimands"]}
    assert set(estimands) == {"lag_profile", "lag_cate"}
    declared = {entry["id"] for entry in declaration["assumptions"]}
    for estimand in estimands.values():
        missing = set(estimand["requires_assumptions"]) - declared
        assert not missing, f"{estimand['id']} needs undeclared assumptions: {missing}"
        assert estimand["interpretation"].strip()


def test_every_assumption_carries_a_known_category(declaration: dict) -> None:
    for assumption in declaration["assumptions"]:
        assert assumption["category"] in ASSUMPTION_CATEGORIES, assumption["id"]
        assert assumption["statement"].strip()


def test_the_empirical_assumptions_say_what_the_evidence_is(declaration: dict) -> None:
    """An empirically_assessed assumption with no evidence is an untestable one in
    disguise, and the report would have nothing to print for it."""
    for assumption in declaration["assumptions"]:
        if assumption["category"] == "empirically_assessed":
            assert assumption.get("evidence", "").strip(), assumption["id"]


def test_the_heterogeneous_estimand_is_marked_as_going_beyond_the_paper(
    declaration: dict,
) -> None:
    """The paper proves the constant profile. lag_cate is this project's extension of
    the same moment, and the declaration has to say so, because the report's honesty
    about what is proved depends on it."""
    lag_cate = next(e for e in declaration["estimands"] if e["id"] == "lag_cate")
    assert lag_cate["extends_paper"] is True
    assert "linear_cate_projection" in lag_cate["requires_assumptions"]


def test_the_intervals_are_declared_exploratory(declaration: dict) -> None:
    """The one property that decides how every number from this family may be worded."""
    inference = declaration["inference"]
    assert inference["calibration"] == "exploratory"
    assert inference["primary"] == "patient_bootstrap_percentile"
    assert inference["bootstrap"]["resampling_unit"] == "unit"


def test_exploratory_is_a_calibration_the_claim_rules_know(declaration: dict) -> None:
    """The declaration and claim_levels.yaml have to use the same vocabulary, or the
    cap silently never applies."""
    from causpec.core.reporting.claim_level import load_rules

    calibrations = load_rules()["interval_calibration"]
    assert declaration["inference"]["calibration"] in calibrations


def test_cross_fitting_is_by_unit(declaration: dict) -> None:
    """Rows within a trajectory are dependent, so folds split patients, not rows."""
    assert declaration["estimator"]["recipe"]["cross_fitting"] == "by unit, not by row"


def test_the_two_expensive_lessons_are_written_down(declaration: dict) -> None:
    """Both were found by the author the hard way and both look like tidying-up.

    Stage-1 weighting: unweighted nuisances target the survivor-conditional mean, a
    different function, and the error once hid behind a compensating error in the
    continuation model. Continuation learner: the moment is not orthogonal in it, so
    its misspecification enters at first order and is magnified by the weight product.
    """
    estimator = declaration["estimator"]
    assert estimator["recipe"]["stage1_weighting"] == "ipcw"
    assert "unweighted" in estimator["note_stage1_weighting"]
    assert "orthogonal" in estimator["note_continuation_model"]


def test_the_refused_questions_are_named_in_the_declaration(declaration: dict) -> None:
    """Each is a question a user will ask in these words, and each needs a different
    design. Naming them here is what lets the skill refuse them specifically."""
    refused = {entry["id"] for entry in declaration["unsupported_questions"]}
    assert refused == {
        "strategy_contrast",
        "cumulative_effect",
        "survival_endpoint",
        "terminal_outcome",
    }
    for entry in declaration["unsupported_questions"]:
        assert entry["reason"].strip() and entry["example"].strip()


def test_the_panel_fields_the_declaration_requires_are_the_ones_design_md_lists(
    declaration: dict,
) -> None:
    design = (REPO / "docs" / "design.md").read_text(encoding="utf-8")
    for field in declaration["requires"]["spec_fields"]:
        assert field in design, f"{field} is required but design.md 7.3 does not list it"


# ---- the skill's reference agrees with the declaration ----


# What each refused question must sound like where the model will actually read it. The
# id set is pinned above, so adding a fifth refusal makes this list fail until it is
# written into the reference too.
REFUSAL_PHRASES = {
    "strategy_contrast": "start early or start late",
    "cumulative_effect": "three days on treatment",
    "survival_endpoint": "28-day mortality",
    "terminal_outcome": "score at discharge",
}


def test_the_reference_refuses_the_same_questions(declaration: dict, reference_text: str) -> None:
    """The model reads the reference, not family.yaml, so a question refused only in
    the declaration is not refused at all."""
    declared = {entry["id"] for entry in declaration["unsupported_questions"]}
    assert declared == set(REFUSAL_PHRASES), "a refusal was added without a phrase to say it in"
    for name, phrase in REFUSAL_PHRASES.items():
        assert phrase in reference_text, f"{name} is refused nowhere the model reads"


def test_the_reference_says_the_intervals_cannot_be_read_as_a_test(
    reference_text: str,
) -> None:
    assert "exploratory" in reference_text
    assert "significant" in reference_text


def test_the_reference_states_the_within_period_order(reference_text: str) -> None:
    """Everything the checks enforce follows from it, and a user has to be able to
    check their own data against it."""
    for token in ("active", "state", "treatment", "outcome"):
        assert token in reference_text
    assert "gap" in reference_text.lower()


def test_the_reference_does_not_promise_a_number(reference_text: str) -> None:
    """Declared and not implemented: describing the analysis is allowed, producing a
    number is not."""
    assert "not implemented" in reference_text.lower()


def test_yaml_is_not_accidentally_typed(declaration: dict) -> None:
    """A YAML file full of prose is one unquoted `yes` away from a boolean.

    This bit the project once already, in a test fixture where `said: yes, the
    population average effect` became True.
    """
    for entry in declaration["assumptions"]:
        assert isinstance(entry["statement"], str)
    for entry in declaration["estimands"]:
        assert isinstance(entry["interpretation"], str)


def test_the_declaration_round_trips(declaration: dict) -> None:
    """Guards against a duplicated key, which YAML resolves silently by keeping the last."""
    raw = (REPO / "packages" / "causpec" / "families" / FAMILY / "family.yaml").read_text(
        encoding="utf-8"
    )
    assert yaml.safe_load(raw) == declaration
    top_level = [
        line.split(":")[0]
        for line in raw.splitlines()
        if line and not line.startswith((" ", "#", "-"))
    ]
    assert len(top_level) == len(set(top_level)), "duplicate top-level key"

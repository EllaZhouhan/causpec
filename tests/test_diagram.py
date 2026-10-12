"""The variable-role diagram, derived from the declarations.

Mirrors design.md 7.5. The user is not asked to draw a DAG: over forty ICU covariates a full
diagram is a formality nobody reads. Roles are declared and the diagram is derived, and that
choice buys the thing a picture cannot give. The same declaration that produces the edges is
compared with the variables the analysis conditions on, so a diagram that contradicts the
analysis is a blocking error rather than a bad illustration.

The covariates are one node with a count and two examples. An honest diagram that fits on a
screen is worth more than a complete one that does not.
"""

from __future__ import annotations

import pandas as pd
import pytest

from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.quality import check_roles
from causpec.core.reporting import diagram

SEVEN = [
    "max_creatinine",
    "max_urea",
    "min_ArterialPressure",
    "sofa_total_24h",
    "admission_age",
    "max_potassium",
    "min_bicarbonate",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(
    roles: dict[str, str] | None = None,
    non_edges: list[str] | None = None,
    **fields: object,
) -> Spec:
    declared = {
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("ate"),
    }
    declared.update({name: confirmed(value) for name, value in fields.items()})
    return Spec(
        question="q",
        family="hte_backdoor",
        fields=declared,
        variable_roles=roles or {},
        key_non_edges=non_edges or [],
    )


def frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({name: [0.0, 1.0] for name in columns})


# ---- the group node, which is the readability decision ----


def test_seven_confounders_are_one_node_with_two_examples() -> None:
    """The alternative is seven boxes, which is where a derived diagram turns back into the
    formality design.md 7.5 refuses to ask for."""
    spec = make_spec({name: "confounder" for name in SEVEN}, adjustment_set=SEVEN)
    text = diagram.mermaid(spec)
    assert "7 confounders: max_creatinine, max_urea, ..." in text
    # The other five are not drawn, which is the point.
    for name in SEVEN[2:]:
        assert name not in text


def test_a_small_group_is_named_in_full() -> None:
    """Trailing off after two when there are only two would hide nothing and look like it
    was hiding something."""
    spec = make_spec({"max_creatinine": "confounder", "max_urea": "confounder"})
    assert "2 confounders: max_creatinine, max_urea" in diagram.mermaid(spec)
    assert "..." not in diagram.mermaid(spec)


def test_the_group_label_is_singular_for_one() -> None:
    assert "1 confounder: max_creatinine" in diagram.mermaid(
        make_spec({"max_creatinine": "confounder"})
    )


# ---- the edges follow from the role, with no freedom ----


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("confounder", ["N0 --> A", "N0 --> Y"]),
        ("instrument", ["N0 --> A"]),
        ("mediator", ["A --> N0", "N0 --> Y"]),
        ("suspected_collider", ["A --> N0", "Y --> N0"]),
        ("post_treatment", ["A --> N0"]),
    ],
)
def test_each_role_implies_its_edges(role: str, expected: list[str]) -> None:
    text = diagram.mermaid(make_spec({"some_column": role}))
    for edge in expected:
        assert edge in text, f"{role} should imply {edge}"


def test_a_collider_is_drawn_as_a_common_consequence() -> None:
    """Both arrows point in, which is what makes conditioning on it dangerous, and the
    picture is the quickest way to see it."""
    text = diagram.mermaid(make_spec({"icu_readmission": "suspected_collider"}))
    assert "A --> N0" in text and "Y --> N0" in text
    assert "N0 --> Y" not in text


def test_the_effect_modifiers_label_comes_from_the_field_the_estimator_uses() -> None:
    """Two places can say a variable modifies the effect. The field is what the estimator
    consumes, so the field decides the label."""
    spec = make_spec(
        {name: "confounder" for name in SEVEN},
        effect_modifiers=["admission_age", "sofa_total_24h"],
    )
    assert "varies by 2 effect modifiers: admission_age, sofa_total_24h" in diagram.mermaid(spec)


def test_a_modifier_declared_only_in_the_roles_is_still_drawn() -> None:
    """Something declared should not vanish from the picture."""
    spec = make_spec({"frailty_index": "effect_modifier"})
    assert "frailty_index" in diagram.mermaid(spec)


def test_no_modifiers_leaves_the_edge_bare() -> None:
    assert "A --> Y" in diagram.mermaid(make_spec({"max_creatinine": "confounder"}))


# ---- the one non-edge worth drawing ----


def test_the_exclusion_restriction_is_drawn_as_a_dashed_arrow() -> None:
    """It joins two nodes that are both on the diagram, so a reader can object to it. That is
    what distinguishes it from the free-text assumptions."""
    spec = make_spec(
        {"bed_availability": "instrument", "max_creatinine": "confounder"},
        instrument="bed_availability",
    )
    text = diagram.mermaid(spec)
    assert '-. "assumed absent" .-> Y' in text


def test_free_text_assumptions_are_not_drawn_as_arrows() -> None:
    """Drawn as an arrow from nowhere, an assumed-absent edge reads as an edge that exists,
    which is the opposite of what it means. They go in the list under the diagram."""
    spec = make_spec(
        {"max_creatinine": "confounder"},
        non_edges=["no unmeasured factor drives both the dialysis decision and death"],
    )
    text = diagram.mermaid(spec)
    assert "unmeasured factor" not in text


def test_no_instrument_means_no_dashed_arrow() -> None:
    assert "assumed absent" not in diagram.mermaid(make_spec({"max_creatinine": "confounder"}))


# ---- dot, which must agree with mermaid ----


def test_dot_draws_the_same_graph() -> None:
    spec = make_spec(
        {"bed_availability": "instrument", **{name: "confounder" for name in SEVEN}},
        instrument="bed_availability",
    )
    text = diagram.dot(spec)
    assert text.startswith("digraph roles {")
    assert text.rstrip().endswith("}")
    assert "7 confounders" in text
    assert "style=dashed" in text
    # Same group collapsing, so the two renderings cannot tell different stories.
    assert "min_bicarbonate" not in text


# ---- what makes the diagram more than an illustration ----


def test_adjusting_for_a_mediator_is_refused() -> None:
    """The error the picture exists to catch. Adjusting for a mediator removes the part of
    the effect that travels through it, and nothing in the interval says so."""
    spec = make_spec(
        {"post_dialysis_creatinine": "mediator"},
        adjustment_set=["post_dialysis_creatinine"],
    )
    issue = check_roles(frame(["post_dialysis_creatinine"]), spec).get("roles_match_adjustment")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert "shrinks towards zero" in issue.impact_on_analysis


def test_a_collider_in_the_effect_modifiers_is_refused_too() -> None:
    """The field name does not sound like adjustment, which is what makes this mistake easy:
    both fields are conditioned on, so both are subject to the rule."""
    spec = make_spec(
        {"icu_readmission": "suspected_collider"},
        effect_modifiers=["icu_readmission"],
    )
    issue = check_roles(frame(["icu_readmission"]), spec).get("roles_match_adjustment")
    assert issue.severity is Severity.BLOCKING
    assert "reverse the sign" in issue.impact_on_analysis


def test_adjusting_for_the_instrument_is_refused() -> None:
    spec = make_spec(
        {"bed_availability": "instrument"},
        instrument="bed_availability",
        adjustment_set=["bed_availability"],
    )
    issue = check_roles(frame(["bed_availability"]), spec).get("roles_match_adjustment")
    assert issue.severity is Severity.BLOCKING
    assert "the path the design relies on" in issue.impact_on_analysis


def test_an_unadjusted_confounder_warns_rather_than_blocks() -> None:
    """It may be a column this extract does not have, which is a limitation to report rather
    than an error to refuse."""
    spec = make_spec(
        {name: "confounder" for name in SEVEN},
        adjustment_set=SEVEN[:-1],
    )
    issue = check_roles(frame(SEVEN), spec).get("roles_match_adjustment")
    assert issue.severity is Severity.WARNING
    assert issue.evidence["confounders_not_adjusted"] == "min_bicarbonate"


def test_a_consistent_declaration_passes_and_says_what_it_checked() -> None:
    spec = make_spec({name: "confounder" for name in SEVEN}, adjustment_set=SEVEN)
    issue = check_roles(frame(SEVEN), spec).get("roles_match_adjustment")
    assert issue.severity is Severity.INFO
    assert issue.evidence["n_confounders"] == 7
    # And it says what it cannot settle, which is whether the roles themselves are right.
    assert "cannot speak to whether the roles themselves are right" in issue.impact_on_analysis


def test_a_post_treatment_variable_outside_the_adjustment_set_is_fine() -> None:
    """Declaring one is how a user records a column they deliberately left out, so declaring
    it must not be punished."""
    spec = make_spec(
        {"urine_output_day2": "post_treatment", "max_creatinine": "confounder"},
        adjustment_set=["max_creatinine"],
    )
    issue = check_roles(frame(["urine_output_day2", "max_creatinine"]), spec).get(
        "roles_match_adjustment"
    )
    assert issue.severity is Severity.INFO


def test_no_roles_declared_reports_that_it_could_not_run() -> None:
    issue = check_roles(frame(SEVEN), make_spec()).get("roles_match_adjustment")
    assert issue.severity is Severity.INFO
    assert issue.evidence["assessed"] is False
    assert "not evidence that the adjustment set is right" in issue.impact_on_analysis


def test_a_declared_variable_missing_from_the_data_is_reported() -> None:
    spec = make_spec({"frailty_index": "confounder"}, adjustment_set=["frailty_index"])
    issue = check_roles(frame(["max_creatinine"]), spec).get("roles_match_adjustment")
    assert issue.evidence["declared_but_absent_from_data"] == "frailty_index"


# ---- the closed surface ----


def test_an_undrawable_role_is_refused() -> None:
    """The edges are derived from the role, so a role nobody can draw means nothing."""
    with pytest.raises(ValueError, match="unknown variable role"):
        Spec(question="q", family="f", variable_roles={"x": "proxy_for_severity"})

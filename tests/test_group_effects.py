"""Group effects: the answer to "a conditional effect for whom".

Mirrors design.md 7.7. The `cate` estimand reports a per-patient effect for every row and
summarises the cloud. It says the effect varies and names nobody, which invites a reader to
pick a patient out of it. `gate` reports the average effect within groups the user declared,
with an interval each, which is a statement someone can act on or dispute.

The staged order is the point: the average effect first, then where the effect varies, then
the groups the user chooses along those dimensions. Choosing a dimension from the importance
ranking is the natural way to interpret a result and is not penalised here, because every
group of every declared grouping is printed: the striking group cannot be shown without the
dull ones beside it, so there is nothing to cherry-pick. What the report does say is that such
an interval is a little optimistic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core import registry
from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import EffectGroup, Source, Spec, SpecField, Status
from causpec.core.grouping import GroupingError, group_masks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

MODIFIERS = ["admission_age", "max_potassium", "sofa_total_24h", "max_creatinine"]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(estimand: str = "gate", groups: list[EffectGroup] | None = None) -> Spec:
    return Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "treatment": confirmed("isDialysisICU"),
            "outcome": confirmed("death"),
            "estimand": confirmed(estimand),
            "effect_modifiers": confirmed(MODIFIERS),
        },
        effect_groups=groups or [],
    )


def age_split() -> EffectGroup:
    return EffectGroup(
        variable="admission_age",
        cuts=[65],
        said="65 is where I would expect frailty to start mattering",
        chosen_from="clinical_knowledge",
    )


@pytest.fixture(scope="module")
def data() -> pd.DataFrame:
    return generate(config_for("high_power", n=1200, seed=7))


# ---- cutting a covariate ----


def test_a_threshold_gives_two_groups_labelled_as_a_reader_would_write_them() -> None:
    frame = pd.DataFrame({"admission_age": [40.0, 60.0, 70.0, 80.0]})
    assert [label for label, _ in group_masks(frame, age_split())] == ["< 65", ">= 65"]


def test_two_thresholds_give_three_bands() -> None:
    frame = pd.DataFrame({"x": [1.0, 15.0, 25.0]})
    group = EffectGroup(variable="x", cuts=[10, 20], said="three bands")
    assert [label for label, _ in group_masks(frame, group)] == [
        "< 10",
        "10 to < 20",
        ">= 20",
    ]


def test_quantiles_give_equal_sized_bins() -> None:
    """For a user with no threshold in mind. Equal bins at least cannot be chosen to flatter
    the result."""
    frame = pd.DataFrame({"x": list(range(300))})
    group = EffectGroup(variable="x", quantiles=3, said="split it in three")
    sizes = [int(mask.sum()) for _, mask in group_masks(frame, group)]
    assert sizes == [100, 100, 100]


def test_a_missing_value_joins_no_group() -> None:
    """A patient whose age is unknown is not known to be over 65 and not known to be under
    it, the same rule the population filters use."""
    frame = pd.DataFrame({"admission_age": [40.0, 70.0, np.nan]})
    sizes = [int(mask.sum()) for _, mask in group_masks(frame, age_split())]
    assert sizes == [1, 1]


def test_a_column_that_is_not_there_says_so() -> None:
    frame = pd.DataFrame({"other": [1.0]})
    with pytest.raises(GroupingError, match="not in the data"):
        group_masks(frame, age_split())


def test_a_constant_column_cannot_be_split_into_bins() -> None:
    frame = pd.DataFrame({"x": [5.0] * 50})
    group = EffectGroup(variable="x", quantiles=3, said="split it")
    with pytest.raises(GroupingError, match="quantiles coincide"):
        group_masks(frame, group)


# ---- the contract ----


def test_a_grouping_without_the_users_words_does_not_exist() -> None:
    with pytest.raises(ValueError, match="their judgement, not a default"):
        EffectGroup(variable="admission_age", cuts=[65], said="  ")


def test_exactly_one_way_to_cut_is_required() -> None:
    with pytest.raises(ValueError, match="not both and not neither"):
        EffectGroup(variable="x", cuts=[1], quantiles=2, said="both")
    with pytest.raises(ValueError, match="not both and not neither"):
        EffectGroup(variable="x", said="neither")


def test_cuts_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="increasing order"):
        EffectGroup(variable="x", cuts=[20, 10], said="backwards")


def test_the_origin_of_the_choice_is_recorded() -> None:
    """Not a penalty. An interval on a group chosen after seeing the ranking on the same data
    is a little optimistic, and the report says which it was rather than adjusting anything.
    """
    assert age_split().chosen_from == "clinical_knowledge"
    picked = EffectGroup(variable="x", cuts=[1], said="the ranking put this first")
    assert picked.chosen_from == "importance_ranking"
    with pytest.raises(ValueError, match="chosen_from must be one of"):
        EffectGroup(variable="x", cuts=[1], said="ok", chosen_from="a_hunch")


def test_groups_enter_the_spec_hash() -> None:
    assert make_spec().spec_hash() != make_spec(groups=[age_split()]).spec_hash()


# ---- the estimand is declared, and gate needs its groups ----


def test_gate_is_a_declared_estimand() -> None:
    assert "gate" in registry.declared_estimands("hte_backdoor")


def test_gate_without_groups_is_refused_by_the_family() -> None:
    """The requirement holds only for this estimand, so a flat `requires.spec_fields` cannot
    express it and the family's own check carries it.

    Through `Family.check`, not `check_backdoor` directly: the severities live in family.yaml
    and the family is what loads them, so calling the function with no config tests the
    fallback defaults rather than the declaration.
    """
    pytest.importorskip("econml")
    from causpec.families.hte_backdoor.estimator import HteBackdoor

    data = generate(config_for("high_power", n=300, seed=1))
    issue = HteBackdoor().check(data, make_spec()).get("backdoor_effect_groups")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert "says the effect varies and says of whom" in issue.impact_on_analysis


def test_another_estimand_does_not_need_groups() -> None:
    pytest.importorskip("econml")
    from causpec.families.hte_backdoor.estimator import HteBackdoor

    data = generate(config_for("high_power", n=300, seed=1))
    issue = HteBackdoor().check(data, make_spec(estimand="ate")).get("backdoor_effect_groups")
    assert issue.severity is Severity.INFO
    assert issue.evidence["assessed"] is False


def test_declared_groups_are_reported_with_their_sizes(data) -> None:
    pytest.importorskip("econml")
    from causpec.families.hte_backdoor.estimator import HteBackdoor

    issue = HteBackdoor().check(data, make_spec(groups=[age_split()])).get("backdoor_effect_groups")
    assert issue.severity is Severity.INFO
    assert issue.evidence["n_groups"] == 2
    assert "no group is dropped or merged" in issue.impact_on_analysis.lower()


# ---- what the estimator produces ----


@pytest.fixture(scope="module")
def result(data):
    pytest.importorskip("econml")
    from causpec.families.hte_backdoor.estimator import HteBackdoor

    groups = [
        age_split(),
        EffectGroup(variable="max_potassium", quantiles=2, said="high and low potassium"),
    ]
    return HteBackdoor().estimate(data, make_spec(groups=groups), seed=0)


def test_the_importance_ranking_is_ordered_and_covers_the_modifiers(result) -> None:
    values = result.values
    ranked = [
        str(values[f"res:importance.rank{rank}.variable"])
        for rank in range(int(values["res:importance.last_rank"]) + 1)
    ]
    assert sorted(ranked) == sorted(MODIFIERS)
    importances = [
        float(values[f"res:importance.rank{rank}.importance"]) for rank in range(len(ranked))
    ]
    assert importances == sorted(importances, reverse=True)


def test_the_importance_ranking_finds_a_real_modifier(result) -> None:
    """The generator makes the effect vary with potassium and AKI stage, so a ranking with any
    information in it should not put potassium last among four."""
    values = result.values
    ranked = [
        str(values[f"res:importance.rank{rank}.variable"])
        for rank in range(int(values["res:importance.last_rank"]) + 1)
    ]
    assert ranked.index("max_potassium") < len(ranked) - 1


def test_every_group_gets_an_effect_and_an_interval(result) -> None:
    values = result.values
    rows = int(values["res:gate.last_row"]) + 1
    assert rows == 4  # two from the age split, two from the potassium halves
    for row in range(rows):
        assert values[f"res:gate.row{row}.n"] > 0
        assert (
            float(values[f"res:gate.row{row}.ci_lower"])
            < float(values[f"res:gate.row{row}.effect"])
            < float(values[f"res:gate.row{row}.ci_upper"])
        )


def test_each_row_names_its_variable_and_group(result) -> None:
    values = result.values
    labels = {
        (str(values[f"res:gate.row{row}.variable"]), str(values[f"res:gate.row{row}.label"]))
        for row in range(int(values["res:gate.last_row"]) + 1)
    }
    assert ("admission_age", "< 65") in labels
    assert ("admission_age", ">= 65") in labels


def test_no_group_can_be_distinguished_from_the_average_here(result) -> None:
    """What a per-patient cloud hides, and the message this table exists to carry: every
    group's interval contains the overall average effect, so on this data no group is
    distinguishable from the average however different the point estimates look.

    The obvious claim, that a group's interval is always wider than the whole sample's, is
    false and was asserted here first. A group interval reflects both estimation noise and the
    spread of fitted effects inside the group, so a homogeneous group can come out tighter than
    the whole: one of these was 0.164 wide against 0.184 overall. The width is printed per
    group for that reason rather than summarised.
    """
    values = result.values
    overall = float(values["res:primary.ate"])
    for row in range(int(values["res:gate.last_row"]) + 1):
        lower = float(values[f"res:gate.row{row}.ci_lower"])
        upper = float(values[f"res:gate.row{row}.ci_upper"])
        assert lower <= overall <= upper, row


def test_the_origin_of_each_grouping_reaches_the_result(result) -> None:
    values = result.values
    assert values["res:gate.row0.chosen_from"] == "clinical_knowledge"
    assert values["res:gate.any_chosen_from_importance"] == "yes"


def test_no_groups_declared_produces_no_group_addresses(data) -> None:
    pytest.importorskip("econml")
    from causpec.families.hte_backdoor.estimator import HteBackdoor

    values = HteBackdoor().estimate(data, make_spec(estimand="ate"), seed=0).values
    assert not any(address.startswith("res:gate.") for address in values)
    # The importance ranking is produced regardless: it is what the user reads to choose.
    assert "res:importance.last_rank" in values

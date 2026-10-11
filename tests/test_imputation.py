"""Imputation: the user chooses, the tool fills, and the report says what it cost.

Mirrors design.md 6.4. Four fills exist, they run on the working copy like any other
preprocessing step, and none of them is the default for anything.

The property that keeps them honest is the price. Every single fill produces an interval
narrower than the evidence supports, because nothing downstream can tell a filled value from
a measured one, and the term that would correct it is the between-imputation variance that
only multiple imputation computes. So a spec containing any fill runs with
`interval_calibration: exploratory` and cannot claim significance. Charged automatically,
because the alternative is an interval that looks like every other interval.

The visible half of that price is in each step's own record: filling at the centre shrinks
the column's spread, and the amount it shrank is printed rather than argued about.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import (
    IMPUTATION_OPERATIONS,
    Assumption,
    AssumptionCategory,
    PreprocessingStep,
    Source,
    Spec,
    SpecField,
    Status,
)
from causpec.core.mapping import PreprocessingError
from causpec.core.mapping import apply as apply_steps
from causpec.core.quality import check_assumptions, check_basic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

COVARIATES = ["max_creatinine", "max_potassium", "max_urea", "min_ArterialPressure"]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(
    steps: list[PreprocessingStep] | None = None,
    assumptions: list[Assumption] | None = None,
    **extra: object,
) -> Spec:
    fields = {
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("cate"),
        "effect_modifiers": confirmed(COVARIATES),
    }
    fields.update({name: confirmed(value) for name, value in extra.items()})
    return Spec(
        question="q",
        family="hte_backdoor",
        fields=fields,
        preprocessing=steps or [],
        assumptions=assumptions or [],
    )


# The assumption check reads the spec only, so the frame it is handed is irrelevant to it.
EMPTY = pd.DataFrame({"x": [0.0]})

MAR = Assumption(
    id="missing_at_random",
    category=AssumptionCategory.UNTESTABLE,
    statement="Values are missing at random given the other analysis columns.",
)


def step(op: str, column: str = "max_creatinine", **kwargs: Any) -> PreprocessingStep:
    return PreprocessingStep(op=op, column=column, said="yes, fill it", **kwargs)


@pytest.fixture(scope="module")
def clean() -> pd.DataFrame:
    return generate(config_for("high_power", n=2000, seed=7))


@pytest.fixture
def gapped(clean: pd.DataFrame) -> pd.DataFrame:
    """200 patients whose creatinine was never drawn."""
    data = clean.copy()
    data.loc[data.index[:200], "max_creatinine"] = np.nan
    return data


# ---- the price, which is the point ----


def test_a_fill_does_not_touch_the_interval_calibration() -> None:
    """A design mistake, recorded so it does not come back.

    An earlier version made any fill force `exploratory`, so no result in such a run could be
    called significant. It was not defensible: excluding the units with a missing column
    distorts the estimate too, through selection rather than through variance, and it kept its
    calibrated interval. Penalising one and not the other pushed users towards the exclusion,
    which is not reliably the better choice, and it dressed a judgement up as arithmetic.

    What a fill introduces is an assumption, and this project already has a place for those.
    """
    from causpec.cli import _interval_calibration

    assert _interval_calibration(make_spec([step("impute_median")])) == "calibrated"
    assert _interval_calibration(make_spec()) == "calibrated"


def test_a_model_based_fill_needs_its_assumption_on_the_record() -> None:
    """The replacement. Filling from a model of the other columns assumes missing at random
    given those columns, which nothing can check and which is often false in exactly the way
    that matters: a test skipped because the patient looked fine is missing because of
    something related to the outcome."""
    issue = check_assumptions(EMPTY, make_spec([step("impute_median")])).get(
        "imputation_assumption_declared"
    )
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is True
    assert issue.evidence["filled_columns"] == "max_creatinine"
    assert "missing at random" in issue.impact_on_analysis


def test_declaring_the_assumption_is_enough_to_proceed() -> None:
    """Declared but unjustified does not block: it caps the claim level, which is how every
    untestable assumption is handled here. The user decides, with their name on it."""
    spec = make_spec([step("impute_median")], assumptions=[MAR])
    issue = check_assumptions(EMPTY, spec).get("imputation_assumption_declared")
    assert issue.severity is Severity.INFO
    assert "not yet justified" in issue.summary
    assert spec.unjustified_untestable_assumptions() == ["missing_at_random"]


def test_a_justified_assumption_leaves_the_ceiling_alone() -> None:
    justified = MAR.model_copy(
        update={
            "justification": "creatinine is ordered on a schedule here, not in response to "
            "how the patient looks",
            "justified_by": Source.USER,
        }
    )
    spec = make_spec([step("impute_median")], assumptions=[justified])
    assert spec.unjustified_untestable_assumptions() == []
    issue = check_assumptions(EMPTY, spec).get("imputation_assumption_declared")
    assert issue.severity is Severity.INFO
    assert "not yet justified" not in issue.summary


def test_a_mechanism_fill_needs_no_missingness_assumption() -> None:
    """A constant the user named and a value carried forward rest on an argument about the
    clinical process, which the report states, rather than on a pattern in the missingness.
    They are still fills and still printed with their counts."""
    for fill in (step("impute_constant", value=0.0), step("impute_locf", limit=1)):
        issue = check_assumptions(EMPTY, make_spec([fill])).get("imputation_assumption_declared")
        assert issue.severity is Severity.INFO, fill.op
        assert issue.evidence["mechanism_fills_only"] is True


def test_no_fill_means_no_assumption_to_ask_for() -> None:
    issue = check_assumptions(EMPTY, make_spec()).get("imputation_assumption_declared")
    assert issue.severity is Severity.INFO
    assert issue.evidence["assessed"] is False


def test_the_check_offers_the_assumption_to_declare() -> None:
    issue = check_assumptions(EMPTY, make_spec([step("impute_median")])).get(
        "imputation_assumption_declared"
    )
    suggestion = issue.suggestions[0]
    assert suggestion.kind == "assumption"
    assert suggestion.operation["id"] == "missing_at_random"
    assert suggestion.operation["category"] == "untestable"
    assert "max_creatinine" in suggestion.operation["statement"]


def test_a_recode_is_not_a_fill(gapped) -> None:
    """The distinction the whole module rests on. Recoding a sentinel changes how a value is
    written down; it adds nothing, so it costs nothing."""
    del gapped
    recode = PreprocessingStep(
        op="recode_null", column="max_creatinine", values=[-999], said="never ordered"
    )
    assert recode.imputes is False
    assert make_spec([recode]).imputed_columns() == []


def test_every_fill_declares_itself_as_one() -> None:
    required: dict[str, dict[str, Any]] = {
        "impute_constant": {"value": 0},
        "impute_locf": {"limit": 1},
    }
    for op in IMPUTATION_OPERATIONS:
        assert step(op, **required.get(op, {})).imputes is True


# ---- what each fill does, and what it costs ----


def test_the_median_fill_invents_the_spread_away_and_says_so(gapped) -> None:
    """The visible half of the price, and the statistic has to be the right one. The column's
    own spread does not reliably shrink: filling a right-skewed column at its median puts 200
    values away from the mean, which can widen it. What is unambiguous is the spread among the
    values written, which a median fill makes exactly zero."""
    out, records = apply_steps(gapped, [step("impute_median")], make_spec())
    assert records[0].rows_changed == 200
    assert not bool(np.asarray(out["max_creatinine"].isna(), dtype=bool).any())
    assert records[0].evidence["sd_filled"] == 0.0
    assert "every filled value identical" in records[0].describe()


def test_the_median_fill_puts_everyone_at_the_same_value(gapped) -> None:
    out, _ = apply_steps(gapped, [step("impute_median")], make_spec())
    filled = np.asarray(out["max_creatinine"], dtype=float)[:200]
    assert len(np.unique(filled)) == 1


def test_a_constant_fill_needs_the_user_to_name_the_value() -> None:
    """Sometimes exactly right, a missing infusion rate usually meaning no infusion, and worst
    of all when wrong, because a plausible number is indistinguishable from a real one."""
    with pytest.raises(ValueError, match="requires `value`"):
        PreprocessingStep(op="impute_constant", column="x", said="fill it")


def test_a_constant_fill_writes_what_was_asked_for(gapped) -> None:
    out, records = apply_steps(gapped, [step("impute_constant", value=0.0)], make_spec())
    assert float(np.asarray(out["max_creatinine"], dtype=float)[0]) == 0.0
    assert records[0].rows_changed == 200


def test_the_iterative_fill_uses_the_treatment_and_the_outcome(gapped) -> None:
    """The part everyone gets wrong. Imputing a covariate from the other covariates alone
    makes the filled values independent of the outcome given those covariates, which biases
    the association towards zero and weakens the adjustment the column was there to provide.
    It feels like cheating and it is the opposite."""
    _, records = apply_steps(gapped, [step("impute_iterative")], make_spec())
    detail = records[0].detail
    assert "isDialysisICU" in detail
    assert "death" in detail


def test_the_iterative_fill_keeps_variation_the_median_destroys() -> None:
    """Why it is worth offering at all: each filled value comes from that row's own predictors,
    so the filled values vary instead of sitting in one place.

    On a column the others genuinely predict. The next test is the other half of the story.
    """
    data = generate(config_for("high_power", n=2000, seed=7))
    rng = np.random.default_rng(11)
    urea = np.asarray(data["max_urea"], dtype=float)
    data["max_creatinine"] = 20 * urea + rng.normal(0, 5, size=len(data))
    data.loc[data.index[:200], "max_creatinine"] = np.nan

    _, median = apply_steps(data, [step("impute_median")], make_spec())
    _, iterative = apply_steps(data, [step("impute_iterative")], make_spec())
    assert median[0].evidence["sd_filled"] == 0.0
    assert iterative[0].evidence["sd_filled"] > 0.5 * median[0].evidence["sd_after"]


def test_on_independent_columns_the_iterative_fill_is_the_median_fill(gapped) -> None:
    """Measured rather than assumed, and it changes what is worth telling a user.

    This generator's covariates are independent by construction: the largest correlation
    among the four is 0.02. So the conditional mean of creatinine given the others is almost
    the unconditional mean, the filled values vary by 0.04 on a column whose spread is 108,
    and the iterative fill has done the median fill with extra steps and a worse story about
    itself. `sd_filled` is the number that says which case you are in, which is why the record
    prints it instead of claiming the fill preserved the distribution.
    """
    _, iterative = apply_steps(gapped, [step("impute_iterative")], make_spec())
    _, median = apply_steps(gapped, [step("impute_median")], make_spec())
    assert iterative[0].evidence["sd_filled"] < 0.01 * median[0].evidence["sd_before"]


def test_the_iterative_fill_refuses_with_nothing_to_predict_from(gapped) -> None:
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={"outcome": confirmed("max_creatinine")},
    )
    with pytest.raises(PreprocessingError, match="no other numeric analysis column"):
        apply_steps(gapped, [step("impute_iterative")], spec)


def test_a_column_with_no_observed_values_cannot_be_filled(clean) -> None:
    data = clean.copy()
    data["max_creatinine"] = np.nan
    with pytest.raises(PreprocessingError, match="no observed values"):
        apply_steps(data, [step("impute_median")], make_spec())


# ---- carry forward, the one with a mechanism behind it ----


def test_carry_forward_needs_a_limit() -> None:
    """Carrying a creatinine forward twelve hours and carrying it forward five days are
    different claims, and only one of them is usually defensible."""
    with pytest.raises(ValueError, match="requires `limit`"):
        PreprocessingStep(op="impute_locf", column="x", said="carry it")


def test_carry_forward_stays_inside_a_patient() -> None:
    """Carrying a value across patients would invent a trajectory nobody had."""
    panel = pd.DataFrame(
        {
            "pid": [1, 1, 1, 2, 2, 2],
            "t": [0, 1, 2, 0, 1, 2],
            "creat": [1.0, np.nan, np.nan, np.nan, 5.0, np.nan],
        }
    )
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={"unit_id": confirmed("pid"), "period_index": confirmed("t")},
    )
    out, records = apply_steps(panel, [step("impute_locf", "creat", limit=5)], spec)
    carried = np.asarray(out["creat"], dtype=float)
    assert carried[:3].tolist() == [1.0, 1.0, 1.0]
    # Patient 2's first period stays missing: the value after the gap is information the
    # clinician did not have.
    assert np.isnan(carried[3])
    assert carried[4:].tolist() == [5.0, 5.0]
    # Three filled, and the fourth gap reported as still open rather than counted as work.
    assert records[0].rows_changed == 3
    assert records[0].evidence["n_still_missing"] == 1.0
    assert "1 left missing" in records[0].detail


def test_carry_forward_stops_at_the_limit() -> None:
    panel = pd.DataFrame(
        {"pid": [1] * 4, "t": [0, 1, 2, 3], "creat": [1.0, np.nan, np.nan, np.nan]}
    )
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={"unit_id": confirmed("pid"), "period_index": confirmed("t")},
    )
    out, records = apply_steps(panel, [step("impute_locf", "creat", limit=1)], spec)
    carried = np.asarray(out["creat"], dtype=float)
    assert carried[1] == 1.0
    assert np.isnan(carried[2]) and np.isnan(carried[3])
    assert records[0].rows_changed == 1
    assert records[0].evidence["n_still_missing"] == 2.0


def test_carry_forward_refuses_without_a_unit_column(gapped) -> None:
    with pytest.raises(PreprocessingError, match="unit_id and period_index"):
        apply_steps(gapped, [step("impute_locf", limit=1)], make_spec())


# ---- the indicator, the only one that adds information ----


def test_the_indicator_records_that_the_test_was_ordered(gapped) -> None:
    out, records = apply_steps(gapped, [step("add_missing_indicator")], make_spec())
    flag = np.asarray(out["max_creatinine_was_measured"], dtype=float)
    assert flag[:200].tolist() == [0.0] * 200
    assert flag[200:].min() == 1.0
    assert records[0].rows_changed == 200


def test_the_indicator_says_it_does_nothing_until_the_spec_names_it(gapped) -> None:
    """The footgun it avoids: a user accepts the indicator, the column appears, nothing in the
    estimate changes, and nobody knows why."""
    _, records = apply_steps(gapped, [step("add_missing_indicator")], make_spec())
    assert "Add it to the covariate set" in records[0].detail


def test_the_indicator_is_not_a_fill(gapped) -> None:
    """It adds information rather than substituting it, so it carries no price. It also does
    not fix the missingness: the check still blocks."""
    out, _ = apply_steps(gapped, [step("add_missing_indicator")], make_spec())
    assert step("add_missing_indicator").imputes is False
    assert check_basic(out, make_spec()).get("basic_missing_values").evidence["passed"] is False


def test_the_indicator_has_to_come_before_the_fill(gapped) -> None:
    """Order is meaning, and this is the trap. Put the indicator after the fill and there are
    no gaps left to record: the column is 1 everywhere, it carries nothing, and nothing
    complains. Found by running the CLI with the steps in the wrong order."""
    with pytest.raises(PreprocessingError, match="move the indicator before it"):
        apply_steps(gapped, [step("impute_median"), step("add_missing_indicator")], make_spec())
    # The right way round works and keeps the information.
    _, records = apply_steps(
        gapped, [step("add_missing_indicator"), step("impute_median")], make_spec()
    )
    assert records[0].rows_changed == 200


def test_adding_the_indicator_twice_is_refused(gapped) -> None:
    with pytest.raises(PreprocessingError, match="added twice"):
        apply_steps(
            gapped, [step("add_missing_indicator"), step("add_missing_indicator")], make_spec()
        )


# ---- the menu the user chooses from ----


def test_the_missing_value_check_offers_the_whole_menu(gapped) -> None:
    """Not a default. Five ways forward, each with what it costs, in the order worth
    considering: exclusion first because it invents nothing, the fills next, dropping the
    column last."""
    issue = check_basic(gapped, make_spec()).get("basic_missing_values")
    kinds = [suggestion.kind for suggestion in issue.suggestions]
    operations = [suggestion.operation.get("op", "") for suggestion in issue.suggestions]
    assert kinds[0] == "population_filter"
    assert operations[1:4] == ["impute_median", "impute_iterative", "add_missing_indicator"]
    assert kinds[-1] == "spec_field"
    assert all(suggestion.cost for suggestion in issue.suggestions)


def test_every_fill_in_the_menu_states_what_it_assumes(gapped) -> None:
    """Said before they accept, not discovered in the report afterwards."""
    issue = check_basic(gapped, make_spec()).get("basic_missing_values")
    fills = [s for s in issue.suggestions if s.operation.get("op", "").startswith("impute_")]
    assert len(fills) == 2
    for suggestion in fills:
        assert "missing" in suggestion.cost and "random" in suggestion.cost


def test_the_suggested_fill_is_applicable_as_written(gapped) -> None:
    issue = check_basic(gapped, make_spec()).get("basic_missing_values")
    offered = next(s for s in issue.suggestions if s.operation.get("op") == "impute_median")
    accepted = PreprocessingStep(
        op=str(offered.operation["op"]),
        column=str(offered.operation["column"]),
        said="yes, use the median, I understand the interval",
    )
    _, records = apply_steps(gapped, [accepted], make_spec())
    assert records[0].rows_changed == 200

"""Population filters: the tool does the exclusion, and prices it.

Mirrors design.md 7.2. A filter is not a preprocessing step, and the difference is what these
tests are about: a step changes how a value is written down, a filter changes **who the answer
is about**. Excluding the patients with no creatinine redefines the population as "patients
who had a creatinine drawn", and whether a test was ordered is a clinical decision.

So the exclusion runs, and three things happen that make it visible: it is counted into a
ledger the report prints, the people it removed are compared with the people it kept, and a
filter on the treatment or the outcome is refused outright.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import (
    Population,
    PopulationFilter,
    PreprocessingStep,
    Source,
    Spec,
    SpecField,
    Status,
)
from causpec.core.mapping import apply as apply_steps
from causpec.core.population import PopulationError, apply_filters
from causpec.core.quality import check_basic, check_population

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

COVARIATES = ["max_creatinine", "max_potassium", "max_urea", "min_ArterialPressure"]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(*filters: PopulationFilter, description: str = "") -> Spec:
    return Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "treatment": confirmed("isDialysisICU"),
            "outcome": confirmed("death"),
            "estimand": confirmed("cate"),
            "effect_modifiers": confirmed(COVARIATES),
        },
        population=Population(description=description, filters=list(filters)),
    )


def drop_missing(column: str = "max_creatinine") -> PopulationFilter:
    return PopulationFilter(
        column=column,
        op="not_missing",
        said="yes, drop the ones with no creatinine and say so in the report",
        suggested_by="basic_missing_values",
    )


@pytest.fixture(scope="module")
def clean() -> pd.DataFrame:
    return generate(config_for("high_power", n=2000, seed=7))


@pytest.fixture
def unmeasured(clean: pd.DataFrame) -> pd.DataFrame:
    """200 patients whose creatinine was never drawn, arriving as a sentinel."""
    data = clean.copy()
    data.loc[data.index[:200], "max_creatinine"] = -999.0
    recoded, _ = apply_steps(
        data,
        [
            PreprocessingStep(
                op="recode_null",
                column="max_creatinine",
                values=[-999],
                said="yes, -999 means the test was never ordered",
            )
        ],
    )
    return recoded


# ---- the exclusion happens, and it is counted ----


def test_the_filter_runs_and_the_ledger_says_what_it_did(unmeasured) -> None:
    kept, ledger = apply_filters(unmeasured, make_spec(drop_missing()))
    assert len(kept) == 1800
    assert len(ledger) == 1
    assert (ledger[0].n_before, ledger[0].n_removed, ledger[0].n_after) == (2000, 200, 1800)
    assert "2,000 to 1,800" in ledger[0].describe()


def test_the_exclusion_is_what_unblocks_the_analysis(unmeasured) -> None:
    """The point of the whole path. Before: blocked on 200 missing creatinines. After: the
    analysis runs, on 1,800 patients, and the ledger says which 200 are not in it."""
    assert check_basic(unmeasured, make_spec()).get("basic_missing_values").severity is (
        Severity.BLOCKING
    )
    kept, _ = apply_filters(unmeasured, make_spec(drop_missing()))
    assert check_basic(kept, make_spec()).get("basic_missing_values").severity is Severity.INFO


def test_the_source_frame_is_not_filtered(unmeasured) -> None:
    apply_filters(unmeasured, make_spec(drop_missing()))
    assert len(unmeasured) == 2000


def test_filters_apply_in_order_and_each_gets_its_own_row(clean) -> None:
    spec = make_spec(
        PopulationFilter(column="admission_age", op="ge", value=18, said="adults only"),
        PopulationFilter(
            column="sofa_total_24h", op="ge", value=2, said="sick enough to be a candidate"
        ),
    )
    kept, ledger = apply_filters(clean, spec)
    assert [record.n_before for record in ledger] == [2000, ledger[0].n_after]
    assert ledger[-1].n_after == len(kept)


def test_an_empty_population_is_refused_with_the_ledger_so_far(clean) -> None:
    """Otherwise it surfaces as an unrelated failure inside an estimator."""
    spec = make_spec(
        PopulationFilter(column="admission_age", op="gt", value=200, said="a typo for 20")
    )
    with pytest.raises(PopulationError, match="leave no rows"):
        apply_filters(clean, spec)


def test_missing_values_never_satisfy_a_comparison(unmeasured) -> None:
    """A patient whose creatinine is unknown is not known to be above 300 and not known to be
    below it. Keeping them would silently read "unknown" as "qualifies"."""
    spec = make_spec(
        PopulationFilter(column="max_creatinine", op="ge", value=0, said="any real value")
    )
    kept, ledger = apply_filters(unmeasured, spec)
    assert ledger[0].n_removed == 200
    assert not bool(np.asarray(kept["max_creatinine"].isna(), dtype=bool).any())


# ---- what the exclusion costs ----


def test_a_neutral_exclusion_says_so_with_the_numbers(unmeasured) -> None:
    report = check_population(unmeasured, make_spec(drop_missing()))
    issue = report.get("population_exclusion_informative")
    assert issue.severity is Severity.INFO
    assert issue.evidence["total_excluded"] == 200
    assert "filter1_treatment_rate_excluded" in issue.evidence


def test_an_informative_exclusion_warns_and_names_the_gap(clean) -> None:
    """The case that matters: the unmeasured are the ones nobody expected to treat. Dropping
    them is still allowed, and the report has to say the remaining patients are not a random
    subset of the ones asked about."""
    data = clean.copy()
    treated = np.asarray(data["isDialysisICU"], dtype=float) == 1.0
    untreated_rows = np.flatnonzero(~treated)[:300]
    data.loc[data.index[untreated_rows], "max_creatinine"] = np.nan
    issue = check_population(data, make_spec(drop_missing())).get(
        "population_exclusion_informative"
    )
    assert issue.severity is Severity.WARNING
    assert float(issue.evidence["filter1_treatment_rate_excluded"]) == 0.0
    assert float(issue.evidence["max_rate_gap"]) > 0.1
    assert "not neutral" in issue.summary


def test_a_handful_of_excluded_rows_is_not_judged(clean) -> None:
    """Two excluded patients cannot support a rate comparison, and a gap computed from two
    would fire more often than one computed from two hundred."""
    data = clean.copy()
    data.loc[data.index[:2], "max_creatinine"] = np.nan
    issue = check_population(data, make_spec(drop_missing())).get(
        "population_exclusion_informative"
    )
    assert issue.severity is Severity.INFO
    assert issue.evidence["total_excluded"] == 2


# ---- what is refused ----


def test_filtering_on_the_outcome_is_refused(clean) -> None:
    """Comparing the survivors of one arm with the survivors of the other. Not waivable:
    there is no reading of the data under which those rows answer the question asked."""
    spec = make_spec(
        PopulationFilter(column="death", op="eq", value=0, said="only the ones who survived")
    )
    issue = check_population(clean, spec).get("population_filter_variable")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert issue.evidence["filters_on_outcome"] == "death"
    assert "circular" in issue.impact_on_analysis


def test_filtering_on_the_treatment_is_refused(clean) -> None:
    spec = make_spec(
        PopulationFilter(
            column="isDialysisICU", op="eq", value=1, said="just the dialysis patients"
        )
    )
    issue = check_population(clean, spec).get("population_filter_variable")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["filters_on_treatment"] == "isDialysisICU"


def test_filtering_on_a_consequence_of_treatment_is_refused(clean) -> None:
    """A column that separates the arms almost perfectly was recorded after the decision. The
    same criterion as panel_post_treatment_state, because it is the same error reached by
    selection instead of by adjustment."""
    data = clean.copy()
    treatment = np.asarray(data["isDialysisICU"], dtype=float)
    rng = np.random.default_rng(3)
    data["crrt_blood_flow"] = treatment * 150 + rng.normal(0, 4, size=len(data))
    spec = make_spec(
        PopulationFilter(
            column="crrt_blood_flow", op="ge", value=50, said="only ones with a real flow rate"
        )
    )
    issue = check_population(data, spec).get("population_filter_variable")
    assert issue.severity is Severity.BLOCKING
    assert float(issue.evidence["max_separation"]) > 0.9
    assert "crrt_blood_flow" in str(issue.evidence["near_copies_of_treatment"])


def test_a_confounder_is_not_mistaken_for_a_consequence(clean) -> None:
    """A confounder is *meant* to predict the treatment, so the ordinary case has to pass.
    Creatinine drives the dialysis decision in this generator and must not fire."""
    spec = make_spec(
        PopulationFilter(column="max_creatinine", op="ge", value=1, said="a plausible floor")
    )
    issue = check_population(clean, spec).get("population_filter_variable")
    assert issue.severity is Severity.INFO
    assert float(issue.evidence["max_separation"]) < 0.7


def test_no_filters_means_both_checks_report_that_they_did_not_run(clean) -> None:
    """An analysis of everyone in the extract is legitimate; a check that stays silent when it
    had nothing to read would make the report a clean bill of health."""
    report = check_population(clean, make_spec())
    for issue in report.issues:
        assert issue.severity is Severity.INFO
        assert issue.evidence["assessed"] is False


# ---- silence is not consent, here too ----


def test_a_filter_without_the_users_words_does_not_exist() -> None:
    with pytest.raises(ValueError, match="silence is not consent"):
        PopulationFilter(column="death", op="eq", value=0, said="  ")


def test_the_operator_surface_is_closed() -> None:
    with pytest.raises(ValueError, match="unknown filter operator"):
        PopulationFilter(column="x", op="regex_match", value="^a", said="go ahead")


def test_an_operator_needs_the_right_shape_of_value() -> None:
    with pytest.raises(ValueError, match="takes no value"):
        PopulationFilter(column="x", op="not_missing", value=3, said="ok")
    with pytest.raises(ValueError, match="requires a value"):
        PopulationFilter(column="x", op="ge", said="ok")
    with pytest.raises(ValueError, match="requires a list"):
        PopulationFilter(column="x", op="in", value="a", said="ok")


def test_filters_enter_the_spec_hash() -> None:
    assert make_spec().spec_hash() != make_spec(drop_missing()).spec_hash()


def test_a_column_that_is_not_there_says_so(clean) -> None:
    spec = make_spec(drop_missing("no_such_column"))
    with pytest.raises(PopulationError, match="not in the data"):
        apply_filters(clean, spec)


# ---- the suggestion channel ----


def test_the_missing_value_check_offers_the_exclusion(unmeasured) -> None:
    """The gap this closes: the refusal used to name a remedy in prose that no spec field
    could express, so the user went and filtered the CSV by hand, which is the silent
    exclusion the same sentence warned against."""
    issue = check_basic(unmeasured, make_spec()).get("basic_missing_values")
    exclusions = [s for s in issue.suggestions if s.kind == "population_filter"]
    assert len(exclusions) == 1
    # First in the menu, because it invents nothing. The fills follow it, each with its own
    # cost, and the user chooses: see test_imputation.py for what the fills cost.
    assert issue.suggestions[0] is exclusions[0]
    assert exclusions[0].operation == {"column": "max_creatinine", "op": "not_missing"}
    accepted = PopulationFilter(
        column=str(exclusions[0].operation["column"]),
        op=str(exclusions[0].operation["op"]),
        said="yes, drop them and note it",
    )
    _, ledger = apply_filters(unmeasured, make_spec(accepted))
    assert ledger[0].n_removed == 200


def test_several_affected_columns_offer_nothing(unmeasured) -> None:
    """Each exclusion compounds the last, so they are decided one at a time rather than
    bundled into one suggestion whose size nobody has seen."""
    data = unmeasured.copy()
    data.loc[data.index[500:600], "max_potassium"] = np.nan
    issue = check_basic(data, make_spec()).get("basic_missing_values")
    assert issue.suggestions == []
    assert "one at a time" in issue.recommended_repair

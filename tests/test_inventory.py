"""The column inventory: what the user chooses variable roles from.

This exists because of what the agent does without it. At the roles step it summarised the
file from its header, "age, sex, AKI stage and the 14 labs and vitals (creatinine, urea,
potassium and so on)", and then dropped twelve columns in one clause: "I'll leave out the
consultant columns, the noise_ columns and the patient ID." Nine columns were behind "and so
on" and twelve were never named at all, and those are precisely the ones the user would have
had something to say about.

Two properties carry it.

**Every column appears exactly once.** A column missing from the listing is a column the user
cannot ask about, so the renderer refuses a shape it has no group for rather than quietly
dropping it.

**Nothing crosses two columns.** Describing one column is a description of the file; relating
two is a diagnostic of the analysis, and diagnostics live in the checks, where a spec can
stand them down and a report can carry them. The inventory is what the agent reaches for
instead of improvising a propensity fit in a shell.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.inventory import GROUP_ORDER, ColumnFacts, describe_columns, render


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


@pytest.fixture
def frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 200
    return pd.DataFrame(
        {
            "unit_id": np.arange(n),
            "treated": rng.integers(0, 2, n),
            "death": rng.integers(0, 2, n),
            "aki_stage": rng.integers(0, 4, n),
            "creatinine": rng.normal(180, 40, n),
            "consultant_id": rng.integers(0, 40, n),
            "ward": rng.choice(["A", "B", "C"], n),
            "admitted_on": [f"2024-{1 + i % 12:02d}-0{1 + i % 9}" for i in range(n)],
            # Repeats on purpose: text with one value per row is indistinguishable from an
            # identifier, and the code calls it one.
            "note": [f"free text {i % 60}" for i in range(n)],
            "site": ["NUH"] * n,
            "never_recorded": [np.nan] * n,
        }
    )


def facts_of(data: pd.DataFrame, spec: Spec | None = None) -> dict[str, ColumnFacts]:
    return {fact.name: fact for fact in describe_columns(data, spec)}


# ---- the shapes, which is all the file can say ----


def test_each_column_lands_in_the_shape_it_has(frame) -> None:
    groups = {name: fact.group for name, fact in facts_of(frame).items()}
    assert groups == {
        "unit_id": "identifier",
        "treated": "binary",
        "death": "binary",
        "aki_stage": "scale",
        "creatinine": "measurement",
        "consultant_id": "code",
        "ward": "category",
        "admitted_on": "date",
        "note": "text",
        "site": "constant",
        "never_recorded": "empty",
    }


def test_a_continuous_column_with_no_repeats_is_not_an_identifier() -> None:
    """The bug this pins, found by running the command on this project's own test file: a
    measured quantity is all-distinct whenever the sample is small against its precision, and
    the first version filed two such columns under "cannot be a covariate". An identifier is a
    label, which means text or a whole number."""
    n = 50
    data = pd.DataFrame(
        {
            "bicarbonate": np.linspace(5.13, 39.28, n),  # all distinct, and a measurement
            "record_no": np.arange(n),  # all distinct, and a label
            "code": [f"x{i}" for i in range(n)],
        }
    )
    facts = facts_of(data)
    assert facts["bicarbonate"].group == "measurement"
    assert facts["record_no"].group == "identifier"
    assert facts["code"].group == "identifier"


def test_a_whole_number_column_with_many_levels_is_a_code_not_a_measurement(frame) -> None:
    """`consultant_id` holds 40 integers over 200 rows. Calling it a measurement invites it
    into the covariate set as though it were a lab value; calling it a code is what prompts
    the question the user should be asked about it."""
    assert facts_of(frame)["consultant_id"].summary.startswith("40 values, 0 to 39")


def test_the_levels_are_listed_while_they_are_few_and_summarised_when_not(frame) -> None:
    facts = facts_of(frame)
    assert facts["aki_stage"].summary == "0, 1, 2, 3"
    assert facts["ward"].summary == "A, B, C"
    assert "median" in facts["creatinine"].summary


def test_missingness_is_counted_per_column(frame) -> None:
    data = frame.copy()
    data.loc[data.index[:20], "creatinine"] = np.nan
    assert facts_of(data)["creatinine"].n_missing == 20
    assert facts_of(data)["never_recorded"].n_missing == len(data)


# ---- the spec's roles, so the listing shows what is still unassigned ----


def test_the_columns_a_spec_already_claims_are_marked(frame) -> None:
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "treatment": confirmed("treated"),
            "outcome": confirmed("death"),
            "unit_id": confirmed("unit_id"),
            "effect_modifiers": confirmed(["creatinine", "aki_stage"]),
        },
    )
    facts = facts_of(frame, spec)
    assert facts["treated"].role == "treatment"
    assert facts["death"].role == "outcome"
    assert facts["creatinine"].role == "effect_modifiers"
    assert facts["ward"].role is None


def test_no_spec_is_the_ordinary_case(frame) -> None:
    """The listing comes before the roles are decided, so it has to work with nothing."""
    assert all(fact.role is None for fact in describe_columns(frame))


# ---- the rendering, where a dropped column would hurt ----


def test_every_column_appears_in_the_listing(frame) -> None:
    text = render(describe_columns(frame), n_rows=len(frame), source="cohort.csv")
    for name in frame.columns:
        assert name in text, name
    assert "11 columns in cohort.csv, 200 rows" in text


def test_the_groups_that_cannot_be_covariates_say_so(frame) -> None:
    text = render(describe_columns(frame), n_rows=len(frame))
    assert "identifier (1): one value per row, so it cannot be a covariate" in text
    assert "constant (1): one value throughout, so it cannot be a covariate" in text


def test_a_shape_with_no_group_is_an_error_rather_than_a_silent_omission() -> None:
    fact = ColumnFacts(
        name="x", group="a shape nobody ordered", n_distinct=3, n_missing=0, summary=""
    )
    with pytest.raises(AssertionError, match="ungrouped"):
        render([fact], n_rows=3)


def test_every_group_the_code_can_produce_has_a_place_in_the_order() -> None:
    from causpec.core.inventory import GROUP_NOTES

    assert set(GROUP_NOTES) == set(GROUP_ORDER)


def test_an_empty_file_does_not_crash() -> None:
    data = pd.DataFrame({"a": pd.Series(dtype=float)})
    text = render(describe_columns(data), n_rows=0)
    assert "1 columns" in text and "a" in text

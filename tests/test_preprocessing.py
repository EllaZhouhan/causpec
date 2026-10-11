"""Preprocessing: suggested by a check, agreed by the user, applied to a working copy.

Mirrors design.md 6.4. Four properties carry this, and the first is the one that makes the
feature worth having rather than dangerous.

**A step reveals; it does not repair.** Recoding a sentinel to missing does not fix anything:
it converts a hidden problem into a visible one, and the missingness check then reports what
the placeholder was concealing. A preprocessing path that let a blocking check pass by
concealing what it reported would be worse than having none.

**The source is never modified.** Steps return a copy, because the read-only guarantee on a
data source is a safety boundary rather than a convenience (ADR-0002).

**Order is meaning.** Recode then cast is not cast then recode, and a lenient cast would do
the recode silently with no record that it happened.

**Silence is not consent.** A transformation changes the numbers, so a step without the
user's own words does not exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import PreprocessingStep, Source, Spec, SpecField, Status
from causpec.core.mapping import PreprocessingError
from causpec.core.mapping import apply as apply_steps
from causpec.core.quality import check_basic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

COVARIATES = ["max_creatinine", "max_potassium", "max_urea", "min_ArterialPressure"]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(steps: list[PreprocessingStep] | None = None) -> Spec:
    return Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "treatment": confirmed("isDialysisICU"),
            "outcome": confirmed("death"),
            "estimand": confirmed("ate"),
            "effect_modifiers": confirmed(COVARIATES),
        },
        preprocessing=steps or [],
    )


def recode(column: str, values: list[object]) -> PreprocessingStep:
    return PreprocessingStep(
        op="recode_null",
        column=column,
        values=values,
        said="yes, those mean the test was never ordered",
        suggested_by="basic_null_encoding",
    )


@pytest.fixture(scope="module")
def clean() -> pd.DataFrame:
    return generate(config_for("high_power", n=2000, seed=7))


@pytest.fixture
def sentinel(clean: pd.DataFrame) -> pd.DataFrame:
    data = clean.copy()
    data.loc[data.index[:200], "max_creatinine"] = -999.0
    return data


# ---- the property that makes this safe ----


def test_a_step_reveals_rather_than_repairs(sentinel) -> None:
    """The whole point. Before: a placeholder nobody can see is hiding 200 unmeasured
    creatinines. After: 200 missing creatinines, which still blocks. The analysis has not
    become possible, it has become honest about why it is not."""
    before = check_basic(sentinel, make_spec())
    assert before.get("basic_null_encoding").severity is Severity.BLOCKING
    assert before.get("basic_missing_values").severity is Severity.INFO

    data, _ = apply_steps(sentinel, [recode("max_creatinine", [-999])])
    after = check_basic(data, make_spec())
    assert after.get("basic_null_encoding").severity is Severity.INFO
    assert after.get("basic_missing_values").severity is Severity.BLOCKING
    assert after.get("basic_missing_values").evidence["max_creatinine_missing"] == 200


def test_the_source_frame_is_not_modified(sentinel) -> None:
    original = np.asarray(sentinel["max_creatinine"], dtype=float).copy()
    apply_steps(sentinel, [recode("max_creatinine", [-999])])
    assert np.array_equal(np.asarray(sentinel["max_creatinine"], dtype=float), original)
    assert int(np.sum(original == -999.0)) == 200


def test_what_each_step_did_is_recorded(sentinel) -> None:
    """A step that changed nothing is worth seeing too: it usually means the column was not
    what the user thought it was."""
    _, records = apply_steps(sentinel, [recode("max_creatinine", [-999])])
    assert len(records) == 1
    assert records[0].rows_changed == 200
    assert "recode_null on max_creatinine" in records[0].describe()

    _, none_matched = apply_steps(sentinel, [recode("max_potassium", [-999])])
    assert none_matched[0].rows_changed == 0


# ---- silence is not consent ----


def test_a_step_without_the_users_words_does_not_exist() -> None:
    with pytest.raises(ValueError, match="silence is not consent"):
        PreprocessingStep(op="recode_null", column="x", values=[-999], said="  ")


def test_an_unknown_operation_is_refused() -> None:
    """The surface is small on purpose: the steps are drafted by an agent and reviewed by a
    person, and a smaller surface is a reviewable one."""
    with pytest.raises(ValueError, match="unknown preprocessing operation"):
        PreprocessingStep(op="drop_outliers", column="x", said="go ahead")


def test_recode_null_needs_values_and_cast_needs_a_target() -> None:
    with pytest.raises(ValueError, match="requires the values"):
        PreprocessingStep(op="recode_null", column="x", said="ok")
    with pytest.raises(ValueError, match="cast requires"):
        PreprocessingStep(op="cast", column="x", said="ok")


def test_steps_enter_the_spec_hash(sentinel) -> None:
    """They change the numbers, so a run with them is not the same run. If they did not enter
    the hash, two different analyses would claim to be reproducible from one spec."""
    del sentinel
    assert make_spec().spec_hash() != make_spec([recode("max_creatinine", [-999])]).spec_hash()


# ---- order is meaning ----


def test_a_lenient_cast_is_not_available(clean) -> None:
    """The trap this avoids: `to_numeric(errors="coerce")` would turn "NA" into a missing
    value, performing a recode nobody declared and leaving no record of it. The strict cast
    refuses and the message says which values are in the way and what to do."""
    data = clean.copy()
    data["max_potassium"] = data["max_potassium"].astype(object)
    data.loc[data.index[:20], "max_potassium"] = "NA"
    step = PreprocessingStep(op="cast", column="max_potassium", to="number", said="yes, cast it")
    with pytest.raises(PreprocessingError, match="cannot convert"):
        apply_steps(data, [step])


def test_recode_then_cast_works_in_that_order(clean) -> None:
    data = clean.copy()
    data["max_potassium"] = data["max_potassium"].astype(object)
    data.loc[data.index[:20], "max_potassium"] = "NA"
    steps = [
        recode("max_potassium", ["NA"]),
        PreprocessingStep(op="cast", column="max_potassium", to="number", said="yes, cast it"),
    ]
    out, records = apply_steps(data, steps)
    assert records[0].rows_changed == 20
    assert pd.api.types.is_numeric_dtype(out["max_potassium"])
    assert int(np.asarray(out["max_potassium"].isna(), dtype=bool).sum()) == 20


def test_text_placeholders_match_whatever_their_spelling(clean) -> None:
    """ "NA", "na" and " NA " are the same placeholder, and asking the user to enumerate the
    spellings would be asking them to do the computer's work."""
    data = clean.copy()
    data["max_potassium"] = data["max_potassium"].astype(object)
    data.loc[data.index[0], "max_potassium"] = "NA"
    data.loc[data.index[1], "max_potassium"] = "na"
    data.loc[data.index[2], "max_potassium"] = " NA "
    out, records = apply_steps(data, [recode("max_potassium", ["NA"])])
    assert records[0].rows_changed == 3
    del out


def test_a_column_that_is_not_there_says_so(clean) -> None:
    with pytest.raises(PreprocessingError, match="not in the data"):
        apply_steps(clean, [recode("no_such_column", [-999])])


def test_a_cast_to_something_unimplemented_is_refused(clean) -> None:
    step = PreprocessingStep(op="cast", column="max_potassium", to="category", said="ok")
    with pytest.raises(PreprocessingError, match="cast supports"):
        apply_steps(clean, [step])


# ---- the suggestion channel ----


def test_the_check_suggests_the_exact_step(sentinel) -> None:
    """Machine-readable alongside the prose, so the agent offers the step it found rather than
    paraphrasing a sentence back into an operation."""
    issue = check_basic(sentinel, make_spec()).get("basic_null_encoding")
    suggestion = issue.suggested_operation
    assert suggestion == {"op": "recode_null", "column": "max_creatinine", "values": [-999.0]}
    assert suggestion is not None
    # And the suggestion is applicable as written, once the user has agreed to it. Field by
    # field rather than by unpacking, so that a suggestion growing a key the contract does not
    # accept fails here rather than at the call site in the agent's hands.
    step = PreprocessingStep(
        op=str(suggestion["op"]),
        column=str(suggestion["column"]),
        values=list(suggestion["values"]),
        said="yes, -999 means not ordered",
    )
    _, records = apply_steps(sentinel, [step])
    assert records[0].rows_changed == 200


def test_most_checks_suggest_nothing(sentinel) -> None:
    """There is no safe automatic answer to a duplicated join, a missing value or too few
    events. Offering one would invite the user to make a problem invisible instead of
    deciding about it."""
    data = pd.concat([sentinel, sentinel.iloc[:10]], ignore_index=True)
    report = check_basic(data, make_spec())
    for check_id in ("basic_duplicate_rows", "basic_missing_values", "basic_isolated_extremes"):
        assert report.get(check_id).suggested_operation is None, check_id

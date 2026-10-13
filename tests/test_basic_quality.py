"""The basic layer, on data with one defect injected at a time.

Mirrors design.md 8.1. Two properties matter more than the individual checks.

The layer has to stay quiet on data that is merely awkward. A urine output with 10% exact
zeros, a fluid balance that goes negative, a binary treatment: all normal, and a check that
fires on them is a check that gets switched off, after which it protects nothing.

And it has to fire on the defect that fails nowhere else. A missing value eventually reaches
a nuisance regression and complains; a sentinel does not. A creatinine column holding -999
for "not measured" is arithmetic all the way down, so every other check passes and the answer
becomes a statement about an export convention.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.quality import analysis_columns, check_basic, config_hash, load_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

STATE = [
    "max_creatinine",
    "max_potassium",
    "max_urea",
    "min_ArterialPressure",
    "min_netBodyBalancePerHour",
    "max_uo_12h_ml",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(**overrides: object) -> Spec:
    fields = {
        "unit_id": confirmed("unit_id"),
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "effect_modifiers": confirmed(STATE),
        "estimand": confirmed("ate"),
    }
    fields.update({name: confirmed(value) for name, value in overrides.items()})
    return Spec(question="q", family="hte_backdoor", fields=fields)


@pytest.fixture(scope="module")
def clean() -> pd.DataFrame:
    return generate(config_for("realistic", n=3000, seed=7))


@pytest.fixture(scope="module")
def clean_report(clean: pd.DataFrame):
    return check_basic(clean, make_spec())


def severity(report, check_id: str) -> Severity:
    return report.get(check_id).severity


# ---- quiet on data that is merely awkward ----


def test_real_data_passes_every_basic_check(clean_report) -> None:
    """Dataset A at the realistic preset: a binary treatment, a 4% outcome, a fluid balance
    that goes negative, and a urine output with genuine zeros."""
    offenders = [
        issue.check_id for issue in clean_report.issues if issue.severity is not Severity.INFO
    ]
    assert offenders == []


def test_a_column_with_real_zeros_is_not_flagged(clean, clean_report) -> None:
    """Urine output is exactly zero for about a tenth of these patients, and those zeros are
    measurements. What makes them real is that there are also values at 1 and 2."""
    zeros = float(np.mean(clean["max_uo_12h_ml"].to_numpy(dtype=float) == 0.0))
    assert zeros > 0.05, "the fixture should contain a column with real zeros"
    assert severity(clean_report, "basic_zero_spike") is Severity.INFO


def test_a_column_with_negative_values_is_left_alone(clean, clean_report) -> None:
    """Zero is in the middle of a fluid balance's range, so a spike there means nothing."""
    assert clean["min_netBodyBalancePerHour"].min() < 0
    assert severity(clean_report, "basic_zero_spike") is Severity.INFO


def test_only_the_columns_the_analysis_uses_are_checked(clean) -> None:
    """A sentinel in a column nobody reads is harmless, and flagging it trains the user to
    ignore this check."""
    data = clean.copy()
    data["noise_00"] = -999.0
    report = check_basic(data, make_spec())
    assert severity(report, "basic_null_encoding") is Severity.INFO


def test_the_analysis_columns_come_from_the_spec(clean) -> None:
    columns = analysis_columns(make_spec(), clean)
    assert columns[:3] == ["unit_id", "isDialysisICU", "death"]
    assert set(STATE) <= set(columns)
    # A field holding something that is not a column is skipped, not mistaken for one.
    assert "ate" not in columns


# ---- the one that fails nowhere else ----


def test_a_numeric_sentinel_blocks(clean) -> None:
    """The check that earns this layer. Nothing else in the pipeline notices -999: it is a
    number, so it averages, it fits and it predicts."""
    data = clean.copy()
    data.loc[data.index[:400], "max_creatinine"] = -999.0
    report = check_basic(data, make_spec())
    issue = report.get("basic_null_encoding")
    assert issue.severity is Severity.BLOCKING
    assert "max_creatinine" in issue.affected_columns
    assert issue.evidence["max_creatinine_sentinel_count"] == 400


def test_a_sentinel_is_waivable_because_only_the_user_knows(clean) -> None:
    """A value that looks out of band may be real in someone's data."""
    data = clean.copy()
    data.loc[data.index[:10], "max_urea"] = 999.0
    report = check_basic(data, make_spec())
    assert report.get("basic_null_encoding").waivable is True


def test_one_odd_value_is_not_an_encoding(clean) -> None:
    """A single -999 is more likely a typo, and the repair for a typo is not the repair for
    an encoding. The threshold is in the config, not here."""
    data = clean.copy()
    data.loc[data.index[0], "max_creatinine"] = -999.0
    report = check_basic(data, make_spec())
    assert severity(report, "basic_null_encoding") is Severity.INFO


def test_text_that_means_missing_is_found(clean) -> None:
    """How it usually arrives: one "NA" in an export makes the whole column text."""
    data = clean.copy()
    data["max_potassium"] = data["max_potassium"].astype(object)
    data.loc[data.index[:50], "max_potassium"] = "NA"
    report = check_basic(data, make_spec())
    assert severity(report, "basic_null_encoding") is Severity.BLOCKING
    # And the type check says the consequence: every value in that column is now text.
    assert severity(report, "basic_column_types") is Severity.BLOCKING


def test_zeros_with_nothing_above_them_are_flagged(clean) -> None:
    """Creatinine resumes at 30 with nothing between that and zero, so the zeros are a
    different population. A warning, not a refusal: whether zero is possible there is
    clinical knowledge."""
    data = clean.copy()
    data.loc[data.index[:300], "max_creatinine"] = 0.0
    report = check_basic(data, make_spec())
    issue = report.get("basic_zero_spike")
    assert issue.severity is Severity.WARNING
    assert float(issue.evidence["max_creatinine_smallest_nonzero"]) >= 30  # type: ignore[arg-type]
    assert "ask whether zero means zero" in issue.recommended_repair


# ---- the rest of the layer ----


def test_a_missing_value_blocks_and_cannot_be_waived(clean) -> None:
    data = clean.copy()
    data.loc[data.index[:30], "max_urea"] = np.nan
    report = check_basic(data, make_spec())
    issue = report.get("basic_missing_values")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert issue.evidence["max_urea_missing"] == 30


def test_a_duplicated_unit_blocks(clean) -> None:
    """Counted twice, which reweights the sample towards whoever was duplicated."""
    data = pd.concat([clean, clean.iloc[:120]], ignore_index=True)
    report = check_basic(data, make_spec())
    issue = report.get("basic_duplicate_rows")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["n_duplicate_rows"] == 120


def test_the_row_key_includes_the_period_when_there_is_one(clean) -> None:
    """On a panel the same unit appears many times legitimately, so the key is the pair."""
    panel = pd.concat([clean.assign(bucket=index) for index in range(3)], ignore_index=True)
    report = check_basic(panel, make_spec(period_index="bucket"))
    issue = report.get("basic_duplicate_rows")
    assert issue.severity is Severity.INFO
    assert issue.evidence["key"] == "unit_id, bucket"


def test_a_constant_column_warns_without_blocking(clean) -> None:
    data = clean.copy()
    data["max_potassium"] = 4.2
    report = check_basic(data, make_spec())
    assert severity(report, "basic_constant_column") is Severity.WARNING


def test_no_unit_column_is_not_an_error(clean) -> None:
    """Some data has no unit id, and the layer should say so rather than invent a key."""
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={"treatment": confirmed("isDialysisICU"), "outcome": confirmed("death")},
    )
    report = check_basic(clean, spec)
    assert severity(report, "basic_duplicate_rows") is Severity.INFO
    assert report.get("basic_duplicate_rows").evidence["key"] == "(none)"


# ---- the thresholds are configuration, not code ----


def test_every_check_is_declared_in_the_config(clean_report) -> None:
    """A check whose severity is not declared would silently default to a warning."""
    config = load_config()
    for issue in clean_report.issues:
        assert issue.check_id in config, issue.check_id
        assert "severity" in config[issue.check_id]


def test_a_custom_config_is_honoured(clean, tmp_path) -> None:
    """Where the line falls is a convention, and conventions have to be inspectable."""
    import yaml

    config = load_config()
    config["basic_null_encoding"]["min_occurrences"] = 1
    path = tmp_path / "basic_checks.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    data = clean.copy()
    data.loc[data.index[0], "max_creatinine"] = -999.0
    strict = check_basic(data, make_spec(), config_path=path)
    assert severity(strict, "basic_null_encoding") is Severity.BLOCKING


def test_the_config_hash_changes_with_the_config(tmp_path) -> None:
    """The manifest records it, so a report's thresholds can be reproduced later."""
    import yaml

    config = load_config()
    config["basic_null_encoding"]["min_occurrences"] = 99
    path = tmp_path / "basic_checks.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    assert config_hash(path) != config_hash()


def test_the_config_ships_with_the_package() -> None:
    """Read through importlib.resources, because in skill form causpec is imported out of a
    wheel where a filesystem path points at nothing."""
    assert load_config()["version"] == 1


# ---- isolated extremes: the gap is the statistic, not the distance ----


def test_a_z_score_rule_would_have_been_noise(clean) -> None:
    """Why the check measures a gap. On this data the largest |z| per column runs from 2.9 to
    4.2, so a rule at 3 or 4 fires on nearly every column, and a check that always fires is a
    check nobody reads. Lab values are right-skewed and a long tail is a long tail."""
    worst = 0.0
    for column in STATE:
        values = clean[column].to_numpy(dtype=float)
        worst = max(worst, float(np.abs((values - values.mean()) / values.std()).max()))
    assert worst > 2.5, "the fixture should have the heavy tails that defeat a z-score rule"


def test_a_clean_column_has_no_isolated_extreme(clean_report) -> None:
    assert clean_report.get("basic_isolated_extremes").severity is Severity.INFO


def test_a_decimal_slip_that_lands_outside_the_distribution_is_caught(clean) -> None:
    """The largest creatinine multiplied by ten sits 36 interquartile ranges from the next
    value, where clean columns sit between 0.007 and 0.31."""
    data = clean.copy()
    highest = float(clean["max_creatinine"].max())
    data.loc[data["max_creatinine"].idxmax(), "max_creatinine"] = highest * 10
    issue = check_basic(data, make_spec()).get("basic_isolated_extremes")
    assert issue.severity is Severity.WARNING
    assert "max_creatinine" in issue.affected_columns
    assert float(issue.evidence["max_creatinine_highest_gap_to_iqr"]) > 10


def test_a_slip_that_lands_inside_the_distribution_is_invisible(clean) -> None:
    """The limitation, stated rather than discovered later. A creatinine of 44 entered as 440
    is still an ordinary creatinine: it sits inside a distribution whose largest value is 632,
    so there is no gap, and nothing in the data distinguishes it from a real measurement.

    This check finds the slips that land outside. The ones that land inside need the
    measurement, not the table, and no statistic recovers them.
    """
    data = clean.copy()
    low = float(clean["max_creatinine"].min())
    data.loc[clean["max_creatinine"].idxmin(), "max_creatinine"] = low * 10
    assert low * 10 < float(clean["max_creatinine"].max())
    issue = check_basic(data, make_spec()).get("basic_isolated_extremes")
    assert issue.severity is Severity.INFO


def test_a_units_error_is_caught(clean) -> None:
    data = clean.copy()
    rows = data.index[:3]
    data.loc[rows, "max_potassium"] = data.loc[rows, "max_potassium"] * 1000
    issue = check_basic(data, make_spec()).get("basic_isolated_extremes")
    assert issue.severity is Severity.WARNING
    assert float(issue.evidence["max_potassium_highest_gap_to_iqr"]) > 10


def test_an_extreme_never_blocks(clean) -> None:
    """In an ICU a creatinine of 900 is real and matters. A check that encouraged deleting it
    would do more harm than the value does, so this reports and asks."""
    data = clean.copy()
    data.loc[data.index[0], "max_creatinine"] = 9000.0
    issue = check_basic(data, make_spec()).get("basic_isolated_extremes")
    assert issue.severity is not Severity.BLOCKING
    assert "Do not delete it" in issue.recommended_repair


def test_a_sentinel_is_not_reported_twice(clean) -> None:
    """A sentinel is an isolated extreme. Reporting it as both gives the user two findings for
    one defect, and the second one's repair is the wrong one."""
    data = clean.copy()
    data.loc[data.index[:400], "max_creatinine"] = -999.0
    report = check_basic(data, make_spec())
    assert report.get("basic_null_encoding").severity is Severity.BLOCKING
    assert report.get("basic_isolated_extremes").severity is Severity.INFO


# ---- impossible signs ----


def test_a_handful_of_negatives_in_a_positive_column_blocks(clean) -> None:
    data = clean.copy()
    data.loc[data.index[:5], "max_creatinine"] = -12.0
    issue = check_basic(data, make_spec()).get("basic_impossible_sign")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["max_creatinine_odd_sign_rows"] == 5


def test_a_genuinely_signed_column_is_left_alone(clean, clean_report) -> None:
    """The fluid balance in this data is 61% negative and 39% positive. A rule that fired on
    it would be unusable, which is why the rule requires a dominant sign."""
    balance = clean["min_netBodyBalancePerHour"].to_numpy(dtype=float)
    assert 0.2 < float(np.mean(balance < 0)) < 0.8
    assert clean_report.get("basic_impossible_sign").severity is Severity.INFO


# ---- structural columns are not measurements ----


def test_a_termination_marker_is_not_held_to_measurement_rules() -> None:
    """The bug that made the whole variable-horizon panel path unusable.

    Found by running it. `exit_reason` is a label and is empty on every row but a unit's
    last, which is what a termination marker is for, and the basic layer blocked twice on it:
    once for not being numeric, once for 9,511 missing values. Both are the column working as
    designed, and together they meant no panel with a variable horizon could be estimated
    through the CLI at all.
    """
    frame = pd.DataFrame(
        {
            "pid": [1, 1, 2, 2],
            "t": [0, 1, 0, 1],
            "on_rrt": [0.0, 1.0, 1.0, 0.0],
            "score": [1.5, 2.0, 3.0, 2.5],
            "exit_reason": [None, "discharged", None, "died"],
        }
    )
    spec = Spec(
        question="q",
        family="dynamic_lag_dml",
        fields={
            "unit_id": confirmed("pid"),
            "period_index": confirmed("t"),
            "treatment": confirmed("on_rrt"),
            "outcome": confirmed("score"),
            "termination": confirmed("exit_reason"),
        },
    )
    report = check_basic(frame, spec)
    assert report.get("basic_column_types").severity is Severity.INFO
    assert report.get("basic_missing_values").severity is Severity.INFO


def test_a_period_index_is_not_a_zero_spike() -> None:
    """Every unit has a period zero, so a third of the rows holding zero is the index working.

    The zero-spike check is about a measurement piling up at zero where its real values sit
    elsewhere, which is what a sentinel looks like. An index is not that.
    """
    frame = pd.DataFrame(
        {
            "pid": [1, 1, 1, 2, 2, 2],
            "t": [0, 1, 2, 0, 1, 2],
            "on_rrt": [0.0, 1.0, 1.0, 1.0, 0.0, 1.0],
            "score": [1.5, 2.0, 3.0, 2.5, 1.0, 2.2],
        }
    )
    spec = Spec(
        question="q",
        family="dynamic_lag_dml",
        fields={
            "unit_id": confirmed("pid"),
            "period_index": confirmed("t"),
            "treatment": confirmed("on_rrt"),
            "outcome": confirmed("score"),
        },
    )
    assert check_basic(frame, spec).get("basic_zero_spike").severity is Severity.INFO


def test_a_missing_unit_id_is_still_caught() -> None:
    """Missingness is the one rule a structural column keeps: a row with no unit is a row
    that cannot be analysed, and it is not the family's job to notice."""
    frame = pd.DataFrame(
        {
            "pid": [1.0, None, 2.0],
            "on_rrt": [0.0, 1.0, 1.0],
            "score": [1.5, 2.0, 3.0],
        }
    )
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "unit_id": confirmed("pid"),
            "treatment": confirmed("on_rrt"),
            "outcome": confirmed("score"),
        },
    )
    assert check_basic(frame, spec).get("basic_missing_values").severity is Severity.BLOCKING


def test_the_two_column_sets_differ_in_exactly_the_structural_columns() -> None:
    """So that a field added to one list is not silently added to the other."""
    from causpec.core.quality.basic import COLUMN_FIELDS, MEASUREMENT_FIELDS

    assert set(COLUMN_FIELDS) - set(MEASUREMENT_FIELDS) == {
        "unit_id",
        "period_index",
        "termination",
    }

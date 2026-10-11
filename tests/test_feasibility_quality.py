"""The feasibility layer: arm sizes and event counts.

Mirrors design.md 8.1. The interesting property is not the arithmetic, it is **why these
block at all** when design.md 10.2 says not to gate on what an interval already says.

That rule is right for an average effect: a small arm produces a wide interval and the reader
sees it. Heterogeneity is the case it does not cover. A forest fitted to 25 events over seven
covariates returns a per-point estimate for every patient with an interval around each, and
those intervals do not widen enough to say "this is noise". The number looks like an answer,
which is the definition of something an interval cannot express.

The thresholds are measured against this project's own data rather than invented: the
realistic preset gives 415 treated patients at a 3.8% event rate, so 25 events against seven
covariates, which is 3.6 per covariate where the classic rule for an outcome model is ten.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.quality import check_feasibility, load_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

COVARIATES = [
    "max_creatinine",
    "max_potassium",
    "max_urea",
    "min_ArterialPressure",
    "max_uo_12h_ml",
    "sofa_total_24h",
    "admission_age",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec(**overrides: object) -> Spec:
    fields = {
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("cate"),
        "effect_modifiers": confirmed(COVARIATES),
    }
    fields.update({name: confirmed(value) for name, value in overrides.items()})
    return Spec(question="q", family="hte_backdoor", fields=fields)


@pytest.fixture(scope="module")
def realistic() -> pd.DataFrame:
    """415 treated of 4,000, 3.8% events: the scale of the real ICU study."""
    return generate(config_for("realistic", n=4000, seed=7))


@pytest.fixture(scope="module")
def powered() -> pd.DataFrame:
    return generate(config_for("high_power", n=4000, seed=7))


def issue_of(data: pd.DataFrame, spec: Spec, check_id: str):
    return check_feasibility(data, spec).get(check_id)


# ---- what the counts actually are ----


def test_the_arms_are_reported_even_when_they_pass(realistic) -> None:
    """A reader comparing the report against the number of rows needs these, and a check that
    only speaks when something is wrong makes them hunt for them."""
    issue = issue_of(realistic, make_spec(), "feasibility_arm_sizes")
    assert issue.severity is Severity.INFO
    assert issue.evidence["n_treated"] == 415
    assert issue.evidence["n_control"] == 3585
    assert float(issue.evidence["treated_share"]) == pytest.approx(0.104, abs=0.001)


def test_a_thin_covariate_budget_warns_rather_than_blocks(realistic) -> None:
    """The realistic preset: 25 events in the smaller arm against seven covariates. Thin, not
    impossible, and the two severities come from the config rather than from the code."""
    issue = issue_of(realistic, make_spec(), "feasibility_event_counts")
    assert issue.severity is Severity.WARNING
    assert issue.evidence["events_in_smaller_arm"] == 25
    assert issue.evidence["n_covariates"] == 7
    assert float(issue.evidence["events_per_covariate"]) == pytest.approx(3.6, abs=0.1)


def test_a_well_powered_design_passes_both(powered) -> None:
    for check_id in ("feasibility_arm_sizes", "feasibility_event_counts"):
        assert issue_of(powered, make_spec(), check_id).severity is Severity.INFO


def test_too_few_events_blocks() -> None:
    """Two events in the smaller arm. A forest will still produce a per-patient estimate here,
    which is precisely why this refuses instead of leaving it to the interval."""
    small = generate(config_for("realistic", n=300, seed=7))
    issue = issue_of(small, make_spec(), "feasibility_event_counts")
    assert issue.severity is Severity.BLOCKING
    assert int(issue.evidence["events_in_smaller_arm"]) < 10  # type: ignore[arg-type]
    assert "will look like an answer" in issue.impact_on_analysis


def test_a_tiny_arm_blocks(realistic) -> None:
    data = realistic.copy()
    treated = np.asarray(data["isDialysisICU"], dtype=float) == 1.0
    keep_treated = np.flatnonzero(treated)[:5]
    keep = np.concatenate([keep_treated, np.flatnonzero(~treated)])
    issue = issue_of(data.iloc[keep], make_spec(), "feasibility_arm_sizes")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["n_smaller_arm"] == 5


def test_the_smaller_arm_is_the_one_that_counts(realistic) -> None:
    """A CATE needs the outcome model estimable in both arms, so the arm with fewer events
    decides. Reporting the total would hide a 25-against-128 split."""
    issue = issue_of(realistic, make_spec(), "feasibility_event_counts")
    assert issue.evidence["events_in_smaller_arm"] == min(
        int(issue.evidence["events_treated"]), int(issue.evidence["events_control"])
    )
    assert int(issue.evidence["events_treated"]) + int(issue.evidence["events_control"]) > 100


# ---- when the checks do not apply, they say so ----


def test_a_panel_is_left_to_its_own_family(realistic) -> None:
    """A panel's equivalent question is how many complete windows each lag has, which depends
    on the lag structure. Counting rows as though they were units would answer nothing."""
    data = realistic.copy()
    data["bucket"] = 0
    report = check_feasibility(data, make_spec(period_index="bucket"))
    for issue in report.issues:
        assert issue.severity is Severity.INFO
        assert issue.evidence["assessed"] is False
        assert "panel" in issue.summary


def test_a_continuous_outcome_has_no_events_to_count(realistic) -> None:
    """And says so rather than passing quietly: the precision of a mean is something the
    interval does say for itself."""
    data = realistic.copy()
    data["sofa_change"] = np.asarray(data["sofa_total_24h"], dtype=float)
    report = check_feasibility(data, make_spec(outcome="sofa_change"))
    events = report.get("feasibility_event_counts")
    assert events.evidence["assessed"] is False
    assert "no events to count" in events.summary
    # The arm sizes still apply and still run.
    assert report.get("feasibility_arm_sizes").evidence["assessed"] is True


def test_a_missing_treatment_column_is_not_an_error(realistic) -> None:
    spec = Spec(question="q", family="hte_backdoor", fields={"outcome": confirmed("death")})
    report = check_feasibility(realistic, spec)
    for issue in report.issues:
        assert issue.severity is Severity.INFO
        assert issue.evidence["assessed"] is False


def test_both_sub_cases_declare_their_severity() -> None:
    """Where the line falls stays in the config, including which sub-case refuses and which
    only warns."""
    entry = load_config()["feasibility_event_counts"]
    assert entry["severity"] == "blocking"
    assert entry["severity_thin_covariates"] == "warning"
    assert entry["min_events_per_arm"] == 10
    assert entry["min_events_per_covariate"] == 5

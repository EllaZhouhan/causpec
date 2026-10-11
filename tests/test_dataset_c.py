"""Dataset C: every injected defect reaches the check that is supposed to catch it.

Mirrors plan.md Phase 1 task 6. This is the test that keeps the check suite honest. Without
it, a suite drifts into one that reports reassuring things about data it does not understand,
and nothing fails.

Three properties, and the second is the one worth having:

1. The clean table passes everything, so a defect's effect is attributable to the defect.
2. Each defect fires **the check that names it**, at the declared severity. A defect caught
   by the wrong check is worse than one caught by none: the report would send the user to
   repair something that is not broken.
3. Each defect fires nothing else. A check that reacts to every disturbance carries no
   information, and the report becomes a list to scroll past.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from causpec.core.contracts.quality import QualityReport, Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.quality import check_basic, check_feasibility, check_temporal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_c import DEFECTS, Defect, clean_frame  # noqa: E402

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


def make_spec(timestamps: bool = True) -> Spec:
    fields = {
        "unit_id": confirmed("unit_id"),
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("ate"),
        "effect_modifiers": confirmed(STATE),
    }
    if timestamps:
        fields.update(
            {
                "time_zero": confirmed("admission_time"),
                "treatment_time": confirmed("rrt_start_time"),
                "outcome_time": confirmed("death_time"),
                "followup_end": confirmed("followup_end_time"),
                "outcome_horizon": confirmed(28 * 24),
                "time_unit": confirmed("hours"),
            }
        )
    return Spec(question="q", family="hte_backdoor", fields=fields)


def run_all(data, spec: Spec) -> QualityReport:
    """Every core layer, which is what the CLI runs before any family check."""
    return QualityReport(
        issues=[
            *check_basic(data, spec).issues,
            *check_temporal(data, spec).issues,
            *check_feasibility(data, spec).issues,
        ]
    )


@pytest.fixture(scope="module")
def clean():
    return clean_frame(n=1500, seed=11)


@pytest.fixture(scope="module")
def clean_report(clean):
    return run_all(clean, make_spec())


def not_passing(report: QualityReport) -> dict[str, Severity]:
    return {
        issue.check_id: issue.severity
        for issue in report.issues
        if issue.severity is not Severity.INFO
    }


# ---- the clean table ----


def test_the_clean_table_passes_every_check(clean_report) -> None:
    """Otherwise a defect's effect cannot be attributed to the defect."""
    assert not_passing(clean_report) == {}


def test_the_clean_table_actually_exercises_the_temporal_checks(clean_report) -> None:
    """Passing because there was nothing to read would make every temporal row below
    meaningless, so the clean run has to show the checks ran."""
    for check_id in (
        "temporal_treatment_before_time_zero",
        "temporal_outcome_before_treatment",
        "temporal_inversion",
        "temporal_insufficient_followup",
    ):
        assert clean_report.get(check_id).evidence["assessed"] is True, check_id


def test_without_time_fields_the_temporal_checks_say_so(clean) -> None:
    """The property that makes the layer honest: a check with nothing to read reports that,
    rather than passing into a report that then reads as a clean bill of health."""
    report = check_temporal(clean, make_spec(timestamps=False))
    for issue in report.issues:
        assert issue.severity is Severity.INFO
        assert issue.evidence["assessed"] is False
        assert "not assessed" in issue.summary
        assert "not evidence that the timing is sound" in issue.impact_on_analysis


# ---- every defect reaches its own check ----


@pytest.mark.parametrize("defect", DEFECTS, ids=lambda defect: defect.id)
def test_the_defect_fires_the_check_that_names_it(defect: Defect, clean) -> None:
    import numpy as np

    data = defect.inject(clean, np.random.default_rng(11))
    report = run_all(data, make_spec(timestamps=True))
    fired = not_passing(report)
    assert defect.expect_check in fired, (
        f"{defect.id} ({defect.description}) was caught by "
        f"{sorted(fired) or 'nothing'}, not by {defect.expect_check}"
    )
    assert fired[defect.expect_check].value == defect.expect_severity


@pytest.mark.parametrize("defect", DEFECTS, ids=lambda defect: defect.id)
def test_the_defect_does_not_fire_everything(defect: Defect, clean) -> None:
    """One defect, a small number of checks. A check that reacts to every disturbance carries
    no information, and the report becomes a list to scroll past.

    Three legitimate overlaps, all of them cases where both statements are true of the same
    rows. Text in a numeric column is both a type failure and a spelled null, and saying both
    is right: one names the cause, the other the consequence. Anchoring on the treatment moves
    time zero, which also shortens follow-up for the treated. And a follow-up end defaulted to
    the epoch is both an inverted interval and a window shorter than the horizon, since the
    observed duration comes out negative.
    """
    import numpy as np

    data = defect.inject(clean, np.random.default_rng(11))
    fired = set(not_passing(run_all(data, make_spec(timestamps=True))))
    allowed = {defect.expect_check} | {
        "text_null_potassium": {"basic_null_encoding"},
        "immortal_time": {"temporal_insufficient_followup"},
        "inverted_followup": {"temporal_insufficient_followup"},
        # Dropping to five treated patients drops their events with them, so the event count
        # goes thin at the same time. Both statements are true of the same rows.
        "tiny_treated_arm": {"feasibility_event_counts"},
    }.get(defect.id, set())
    assert fired <= allowed, f"{defect.id} also fired {sorted(fired - allowed)}"


# ---- the mapping is data, so it can be checked ----


def test_every_defect_declares_where_it_comes_from() -> None:
    """A random perturbation tests the checks against noise. These have to be mistakes that
    happen to real extracts, or the suite is being measured against the wrong thing."""
    for defect in DEFECTS:
        assert defect.provenance.strip(), defect.id
        assert defect.description.strip(), defect.id


def test_the_expected_checks_all_exist() -> None:
    """A defect pointing at a check_id that no check emits would pass by never being
    compared."""
    from causpec.core.quality.basic import load_config

    declared = set(load_config())
    for defect in DEFECTS:
        assert defect.expect_check in declared, defect.id


def test_every_core_layer_is_covered() -> None:
    """The set is meant to exercise the suite, so a layer with no defect aimed at it is a gap
    in the test, not in the checks. This went red when the feasibility layer arrived, which is
    what it is for."""
    aimed = {defect.expect_check.split("_")[0] for defect in DEFECTS}
    assert aimed == {"basic", "temporal", "feasibility"}

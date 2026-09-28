"""dynamic_lag_dml's quality checks, on data whose defects are injected on purpose.

Mirrors design.md 8.1 and 10.2. Each test breaks one thing and checks that the right check
notices, with the right severity. Two of these matter more than they look:

- The gap check has to fire **and** stop the rest of the run, because everything after it
  needs trajectories and building them on a broken index either raises or mis-aligns lags.
- The positivity check must NOT fire on the author's own benchmark design, where positivity
  holds by construction and the estimator is consistent. An earlier version thresholded the
  largest weight, which refused that design at 800 units; the threshold is on the effective
  number of windows for this reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core import registry
from causpec.core.contracts.quality import Severity
from causpec.core.contracts.spec import Source, Spec, SpecField, Status

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a_panel import (  # noqa: E402
    OUTCOME_COLUMN,
    PERIOD_COLUMN,
    TREATMENT_COLUMN,
    UNIT_COLUMN,
    baseline_columns,
    config_for,
    generate,
    state_columns,
)

FAMILY = "dynamic_lag_dml"


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def panel_spec(columns: list[str], **overrides: object) -> Spec:
    fields = {
        "unit_id": confirmed(UNIT_COLUMN),
        "period_index": confirmed(PERIOD_COLUMN),
        "period_length": confirmed(12),
        "treatment": confirmed(TREATMENT_COLUMN),
        "outcome": confirmed(OUTCOME_COLUMN),
        "state": confirmed(columns),
        "max_lag": confirmed(2),
        "estimand": confirmed("lag_profile"),
        # The generator's trajectories end where the unit leaves, and exit_reason marks it.
        "horizon": confirmed("variable"),
        "termination": confirmed("exit_reason"),
    }
    fields.update({name: confirmed(value) for name, value in overrides.items()})
    return Spec(question="q", family=FAMILY, fields=fields, estimation={"family": FAMILY})


def make_panel(n_units: int, seed: int = 4, preset: str = "paper_low_dim", **overrides):
    config = config_for(preset, n_units=n_units, seed=seed, **overrides)
    frame = generate(config)
    return config, frame, state_columns(config.p, config.n_baseline)


def run_checks(frame: pd.DataFrame, spec: Spec):
    return registry.get(FAMILY).check(frame, spec)


@pytest.fixture(scope="module")
def clean():
    """Enough units that every lag is comfortably supported."""
    return make_panel(n_units=2500, seed=7)


@pytest.fixture(scope="module")
def clean_report(clean):
    _, frame, columns = clean
    return run_checks(frame, panel_spec(columns))


def severity_of(report, check_id: str) -> Severity:
    return report.get(check_id).severity


# ---- a clean panel passes ----


def test_a_clean_panel_has_no_blocking_issue(clean_report) -> None:
    assert [issue.check_id for issue in clean_report.blocking] == []


def test_every_declared_check_runs(clean_report) -> None:
    """A check declared in family.yaml and never executed is a promise the report breaks.

    lag_cate_time_varying_modifier is the exception: it only applies to the other estimand.
    """
    declared = set(registry.load_declaration(FAMILY)["checks"])
    ran = {issue.check_id for issue in clean_report.issues}
    assert declared - ran == {"lag_cate_time_varying_modifier"}


def test_positivity_does_not_fire_on_the_design_the_method_was_proved_on(clean_report) -> None:
    """The weights here are heavy-tailed by construction, with single lag-2 weights in the
    hundreds. Blocking on that would refuse the paper's own benchmark."""
    issue = clean_report.get("continuation_positivity")
    assert issue.severity is Severity.INFO
    assert float(issue.evidence["lag2_weight_max"]) > 50


def test_the_report_carries_the_per_lag_numbers_a_reader_needs(clean_report) -> None:
    composition = clean_report.get("lag_set_composition")
    for lag in range(3):
        assert f"lag{lag}_units" in composition.evidence
        assert f"lag{lag}_treated_share" in composition.evidence
    assert "unit_retention_at_longest_lag" in composition.evidence


# ---- the index ----


def test_a_gap_blocks_and_stops_the_run(clean) -> None:
    """Dropping one middle period from one unit is enough: after it, every lag in that
    trajectory would refer to the wrong distance in time."""
    _, frame, columns = clean
    first_unit = frame[UNIT_COLUMN].iloc[0]
    dropped = (frame[UNIT_COLUMN] == first_unit) & (frame[PERIOD_COLUMN] == 1)
    broken = frame.drop(frame.index[dropped])
    report = run_checks(broken, panel_spec(columns))
    assert severity_of(report, "panel_period_gaps") is Severity.BLOCKING
    assert report.get("panel_period_gaps").waivable is False
    # Nothing that needs trajectories was attempted.
    assert "continuation_positivity" not in {issue.check_id for issue in report.issues}


def test_a_duplicated_period_blocks(clean) -> None:
    _, frame, columns = clean
    doubled = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    report = run_checks(doubled, panel_spec(columns))
    assert severity_of(report, "panel_duplicate_periods") is Severity.BLOCKING
    assert report.get("panel_duplicate_periods").evidence["n_duplicate_rows"] == 1


def test_the_gap_repair_does_not_suggest_imputing(clean) -> None:
    """An imputed period would put a fabricated outcome into the moment."""
    _, frame, columns = clean
    broken = frame[frame[PERIOD_COLUMN] != 1]
    report = run_checks(broken, panel_spec(columns))
    repair = report.get("panel_period_gaps").recommended_repair
    assert "Do not impute" in repair


# ---- the within-period order ----


def test_a_state_column_that_copies_the_treatment_blocks(clean) -> None:
    """The column a careless data pull adds: a machine setting recorded during the period.

    It is zero for the untreated and positive for the treated, so it separates them almost
    perfectly, which no confounder does.
    """
    _, frame, columns = clean
    frame = frame.copy()
    rng = __import__("numpy").random.default_rng(0)
    frame["rrt_blood_flow"] = frame[TREATMENT_COLUMN] * (200 + rng.normal(0, 5, len(frame)))
    report = run_checks(frame, panel_spec([*columns, "rrt_blood_flow"]))
    issue = report.get("panel_post_treatment_state")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert "rrt_blood_flow" in issue.affected_columns


def test_an_ordinary_confounder_does_not_block(clean_report) -> None:
    """A state column is supposed to predict the same period's treatment: that is
    confounding by indication, and the whole analysis exists to handle it."""
    issue = clean_report.get("panel_post_treatment_state")
    assert issue.severity is Severity.INFO
    assert float(issue.evidence["max_abs_correlation"]) > 0.2


def test_the_post_treatment_repair_says_the_data_cannot_settle_it(clean_report) -> None:
    assert "ask which" in clean_report.get("panel_post_treatment_state").recommended_repair


# ---- positivity and relevance ----


def test_too_few_effective_windows_blocks() -> None:
    """At 800 units the lag-2 effective size is about 8 windows out of 500, and the lag-2
    estimate is genuinely unusable there. The check blocks exactly that number."""
    _, frame, columns = make_panel(n_units=800, seed=5)
    report = run_checks(frame, panel_spec(columns))
    issue = report.get("continuation_positivity")
    assert issue.severity is Severity.BLOCKING
    assert float(issue.evidence["lag2_effective_windows"]) < 50


def test_the_positivity_repair_refuses_the_tempting_fix() -> None:
    """Raising the floor caps the weights and reintroduces the bias the weighting removes."""
    _, frame, columns = make_panel(n_units=800, seed=5)
    report = run_checks(frame, panel_spec(columns))
    assert "not a repair" in report.get("continuation_positivity").recommended_repair


def test_too_short_a_panel_blocks_the_longer_lags() -> None:
    """Trajectories of at most three periods cannot carry a lag-2 window at all."""
    _, frame, columns = make_panel(n_units=300, seed=2, max_periods=3)
    report = run_checks(frame, panel_spec(columns))
    issue = report.get("panel_too_short_for_the_lag")
    assert issue.severity is Severity.BLOCKING
    assert issue.evidence["lag2_windows"] == 0


def test_relevance_is_reported_per_lag(clean_report) -> None:
    issue = clean_report.get("lag_relevance")
    for lag in range(3):
        assert f"lag{lag}_j" in issue.evidence
    assert issue.severity is Severity.INFO


# ---- the modifier restriction, for lag_cate only ----


def test_a_baseline_modifier_passes() -> None:
    config, frame, columns = make_panel(n_units=1200, seed=11, preset="heterogeneous")
    modifier = baseline_columns(config.p, config.n_baseline)[0]
    spec = panel_spec(columns, estimand="lag_cate", effect_modifiers=[modifier])
    report = run_checks(frame, spec)
    assert severity_of(report, "lag_cate_time_varying_modifier") is Severity.INFO


def test_a_modifier_the_treatment_moves_blocks() -> None:
    """The failure this prevents is not imprecision. With a modifier the treatment moves,
    one treatment period's contribution to a later outcome depends on the treatment in
    between, so the outcome no longer decomposes into lag effects and there is no profile.
    """
    config, frame, columns = make_panel(n_units=800, seed=11, preset="heterogeneous")
    time_varying = columns[0]  # max_creatinine: the treatment moves it by construction
    spec = panel_spec(columns, estimand="lag_cate", effect_modifiers=[time_varying])
    report = run_checks(frame, spec)
    issue = report.get("lag_cate_time_varying_modifier")
    assert issue.severity is Severity.BLOCKING
    assert float(issue.evidence[f"{time_varying}_varying_share"]) > 0.5  # type: ignore[arg-type]
    assert "additive decomposition" in issue.impact_on_analysis
    del config


def test_the_modifier_check_is_skipped_for_the_constant_profile(clean_report) -> None:
    """It is about the varying estimand only; running it always would block analyses it has
    nothing to say about."""
    assert "lag_cate_time_varying_modifier" not in {i.check_id for i in clean_report.issues}


def test_the_modifier_check_is_waivable() -> None:
    """A modifier that varies for reasons outside the treatment, calendar time or age, is
    legitimate, and only the user can say so."""
    declaration = registry.load_declaration(FAMILY)
    assert declaration["checks"]["lag_cate_time_varying_modifier"]["waivable"] is True
    assert declaration["checks"]["panel_period_gaps"]["waivable"] is False


def test_a_fixed_horizon_is_reported_as_needing_no_weighting() -> None:
    """With every unit observed for the same number of periods there is no censoring to
    correct. The check has to say so: a reader who sees weights of exactly 1 and no
    explanation cannot tell that from a weighting step that was forgotten.
    """
    _, frame, columns = make_panel(n_units=400, seed=3, exit_ceiling=1e-9, max_periods=8)
    report = run_checks(frame, panel_spec(columns, horizon="fixed"))
    issue = report.get("continuation_positivity")
    assert issue.severity is Severity.INFO
    assert issue.evidence["horizon"] == "fixed"
    assert issue.evidence["ipcw_applied"] is False
    assert "no continuation weighting was applied" in issue.summary


def test_a_variable_horizon_still_reports_its_weight_diagnostics(clean_report) -> None:
    issue = clean_report.get("continuation_positivity")
    assert issue.evidence["horizon"] == "variable"
    assert issue.evidence["ipcw_applied"] is True
    assert "lag2_effective_windows" in issue.evidence


# ---- the horizon is declared, not inferred ----


def test_a_missing_horizon_blocks() -> None:
    """Not a default, because neither default is safe: assuming variable weights a panel
    that needs no weighting, and assuming fixed drops the correction a panel does need."""
    _, frame, columns = make_panel(n_units=400, seed=3)
    spec = panel_spec(columns)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "horizon"}}
    )
    report = run_checks(frame, spec)
    issue = report.get("horizon_declaration")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert "spec.horizon is missing" in issue.summary
    # Nothing that depends on the horizon was attempted.
    assert "continuation_positivity" not in {i.check_id for i in report.issues}


def test_declaring_fixed_when_trajectories_end_at_different_times_blocks() -> None:
    _, frame, columns = make_panel(n_units=400, seed=3)
    report = run_checks(frame, panel_spec(columns, horizon="fixed"))
    issue = report.get("horizon_declaration")
    assert issue.severity is Severity.BLOCKING
    assert "declared a fixed horizon" in issue.summary


def test_declaring_variable_on_a_cohort_truncated_to_a_fixed_length_blocks() -> None:
    """The trap the confirmed field exists for, and the reason the data cannot settle it.

    Keep only the units that lasted eight periods, and keep only their first eight. Every
    unit then has eight periods, exactly like a fixed horizon, but the cohort is conditioned
    on surviving that long and the evidence of anyone leaving was dropped with the rows. On
    the benchmark design that is 3.5% of units, and the lag-1 estimate moves from 4.22 to
    2.87 against a truth of 4.0. No weighting repairs it, so the check refuses rather than
    correcting.
    """
    _, frame, columns = make_panel(n_units=3000, seed=5)
    period = np.asarray(frame[PERIOD_COLUMN], dtype=int)
    last_period = np.asarray(frame.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max"), dtype=int)
    truncated = frame.loc[(last_period >= 7) & (period < 8)]
    kept = np.asarray(truncated.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max"), dtype=int)
    assert set(kept.tolist()) == {7}, "every kept unit should have exactly eight periods"

    report = run_checks(truncated, panel_spec(columns, horizon="variable"))
    issue = report.get("horizon_declaration")
    assert issue.severity is Severity.BLOCKING
    assert "truncated" in issue.impact_on_analysis
    assert "untruncated" in issue.recommended_repair


def test_a_matching_declaration_passes(clean_report) -> None:
    issue = clean_report.get("horizon_declaration")
    assert issue.severity is Severity.INFO
    assert issue.evidence["declared_horizon"] == "variable"


# ---- a missing value is refused, not imputed ----


def test_missing_values_block(clean) -> None:
    _, frame, columns = clean
    broken = frame.copy()
    broken.loc[broken.index[3], columns[1]] = np.nan
    report = run_checks(broken, panel_spec(columns))
    issue = report.get("panel_missing_values")
    assert issue.severity is Severity.BLOCKING
    assert issue.waivable is False
    assert columns[1] in issue.affected_columns
    # Nothing downstream ran: a NaN would otherwise reach a nuisance regression.
    assert "continuation_positivity" not in {i.check_id for i in report.issues}


def test_missing_values_only_on_final_periods_are_reported_as_such(clean) -> None:
    """Its own cause and its own fix: the outcome's measurement window runs past the end of
    data collection, so record one period fewer rather than leaving the last one blank."""
    _, frame, columns = clean
    broken = frame.copy()
    final = np.asarray(
        broken.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max") == broken[PERIOD_COLUMN],
        dtype=bool,
    )
    broken.loc[final, OUTCOME_COLUMN] = np.nan
    report = run_checks(broken, panel_spec(columns))
    issue = report.get("panel_missing_values")
    assert issue.severity is Severity.BLOCKING
    assert "all on final periods" in issue.summary
    assert "one period fewer" in issue.recommended_repair


def test_a_clean_panel_reports_no_missing_values(clean_report) -> None:
    issue = clean_report.get("panel_missing_values")
    assert issue.severity is Severity.INFO
    assert issue.evidence["n_missing"] == 0

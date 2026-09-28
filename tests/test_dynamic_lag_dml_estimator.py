"""The lag-profile estimator, against a world whose answer is known.

Mirrors design.md 7.3 and section 16. The numbers here are not decoration: the author's
paper reports that each ablation of the estimator keeps a bias that does not shrink with
the sample size, and that is the property these tests check. A benchmark whose error is the
same at every sample size has converged to the wrong quantity, and that is exactly what a
regression test can catch when someone later "simplifies" a stage away.

Everything runs on the panel part of dataset A, whose true profile is known in closed form.
The tests are sized to run in seconds, so the tolerances are loose; the tight numbers live
in the paper's own tables, reproduced by data/generators and the scratch experiments, not
here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from causpec.core import registry
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.families.dynamic_lag_dml.estimator import DynamicLagDmlFit, to_trajectories

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a_panel import (  # noqa: E402
    OUTCOME_COLUMN,
    PERIOD_COLUMN,
    TREATMENT_COLUMN,
    UNIT_COLUMN,
    PanelConfig,
    baseline_columns,
    config_for,
    generate,
    state_columns,
)

FAMILY = "dynamic_lag_dml"


def panel(n_units: int = 1500, seed: int = 4, preset: str = "paper_low_dim", **overrides):
    config = config_for(preset, n_units=n_units, seed=seed, **overrides)
    frame = generate(config)
    columns = state_columns(config.p, config.n_baseline)
    trajectories = to_trajectories(
        frame, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
    )
    return config, frame, columns, trajectories


@pytest.fixture(scope="module")
def benchmark():
    return panel()


@pytest.fixture(scope="module")
def estimated(benchmark):
    """One trip through the family interface, shared: the bootstrap is the expensive part."""
    config, frame, columns, _ = benchmark
    spec = panel_spec(columns)
    spec = spec.model_copy(
        update={"estimation": {"family": FAMILY, "params": {"n_bootstrap_samples": 6}}}
    )
    return config, registry.get(FAMILY).estimate(frame, spec, seed=1)


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
    return Spec(
        question="What does one period of treatment do, now and later?",
        family=FAMILY,
        fields=fields,
        estimation={
            "family": FAMILY,
            "params": {"n_bootstrap_samples": 20, "bootstrap_n_jobs": 1},
        },
    )


# ---- the profile is recovered ----


def test_lag_zero_is_recovered_almost_exactly(benchmark) -> None:
    """Lag 0 is the special case that needs no weighting, so it should be nearly exact.

    It is also the canary: every arm in the author's tables agrees at lag 0 except the two
    that skip state adjustment, so an error here means the residualisation is broken rather
    than the weighting.
    """
    config, _, _, trajectories = benchmark
    fit = DynamicLagDmlFit(max_lag=2, seed=1).fit(trajectories)
    assert fit.theta_[0] == pytest.approx(config.theta_0, abs=0.02)


def test_the_profile_is_recovered_on_the_paper_design(benchmark) -> None:
    config, _, _, trajectories = benchmark
    truth = config.constant_profile()
    fit = DynamicLagDmlFit(max_lag=2, seed=1).fit(trajectories)
    # Loose: at this size the paper's own Monte Carlo puts the lag-2 RMSE near 0.85.
    assert fit.theta_[1] == pytest.approx(truth[1], abs=1.2)
    assert fit.theta_[2] == pytest.approx(truth[2], abs=1.5)


def test_peeling_does_not_disturb_the_shorter_lags(benchmark) -> None:
    """The recursion runs upwards only: lag 0 is computed before lag 1 exists and must not
    change when a longer profile is requested."""
    _, _, _, trajectories = benchmark
    short = DynamicLagDmlFit(max_lag=0, seed=1).fit(trajectories)
    long = DynamicLagDmlFit(max_lag=2, seed=1).fit(trajectories)
    assert short.theta_[0] == pytest.approx(long.theta_[0], abs=1e-12)


def test_the_same_seed_gives_the_same_profile(benchmark) -> None:
    _, _, _, trajectories = benchmark
    first = DynamicLagDmlFit(max_lag=2, seed=3).fit(trajectories).theta_
    second = DynamicLagDmlFit(max_lag=2, seed=3).fit(trajectories).theta_
    assert np.allclose(first, second, equal_nan=True)


# ---- each ingredient earns its place ----


def test_dropping_the_continuation_weights_leaves_a_bias(benchmark) -> None:
    """The author's table: DML without IPCW sits near -0.68 at lag 1 and does not improve
    with n, because the complete windows are a selected sample."""
    config, _, _, trajectories = benchmark
    truth = config.constant_profile()
    weighted = DynamicLagDmlFit(max_lag=2, seed=1).fit(trajectories).theta_
    unweighted = DynamicLagDmlFit(max_lag=2, seed=1, use_weights=False).fit(trajectories).theta_
    assert abs(unweighted[1] - truth[1]) > abs(weighted[1] - truth[1])
    # And it is a real gap, not a coin flip.
    assert unweighted[1] < truth[1] - 0.3


def test_stage_one_nuisances_must_carry_the_weights(benchmark) -> None:
    """The expensive lesson from the author's own validation, kept as a test.

    The nuisances are anchor-conditional; fitted unweighted they estimate the
    survivor-conditional mean instead, which is a different function. On the author's design
    that error was worth about +0.20 at lags 1 and 2, and it went unnoticed for a while
    because a misspecified continuation model was contributing about -0.19 the other way.
    Two large errors cancelling is not a correct estimator.
    """
    config, _, _, trajectories = benchmark
    truth = config.constant_profile()
    weighted = DynamicLagDmlFit(max_lag=2, seed=1).fit(trajectories).theta_
    unweighted = DynamicLagDmlFit(max_lag=2, seed=1, weight_stage1=False).fit(trajectories).theta_
    assert abs(unweighted[1] - truth[1]) > abs(weighted[1] - truth[1])
    assert unweighted[1] > truth[1] + 0.3


def test_the_oracle_continuation_arm_is_at_least_as_good(benchmark) -> None:
    """The moment is not orthogonal in the continuation model, so knowing the truth there
    has to help. This is the arm that separates method error from nuisance error."""
    config, frame, columns, _ = benchmark
    truth = config.constant_profile()
    with_truth = to_trajectories(
        frame,
        UNIT_COLUMN,
        PERIOD_COLUMN,
        columns,
        TREATMENT_COLUMN,
        OUTCOME_COLUMN,
        continuation="lambda_true",
    )
    oracle = DynamicLagDmlFit(max_lag=2, seed=1, oracle_continuation=True).fit(with_truth)
    assert abs(oracle.theta_[1] - truth[1]) < 1.0


# ---- the varying profile ----


def test_a_varying_effect_is_recovered_at_lag_zero() -> None:
    """The projection at lag 0 is the cleanest case: no weights, no peeling.

    Truth here is theta_0(w) = -0.5 * (1 + 0.3 w), so the slope is -0.15.
    """
    config, _, columns, trajectories = panel(n_units=2000, seed=11, preset="heterogeneous")
    modifier = baseline_columns(config.p, config.n_baseline)[0]
    index = np.array([columns.index(modifier)])
    fit = DynamicLagDmlFit(max_lag=2, seed=2, heterogeneous=True, modifier_index=index).fit(
        trajectories
    )
    coefficients = fit.coefficients_[0]
    assert coefficients is not None
    intercept, slope = coefficients
    assert intercept == pytest.approx(config.theta_0, abs=0.05)
    assert slope == pytest.approx(config.theta_0 * config.hetero_outcome, abs=0.05)


def test_a_varying_effect_is_found_at_the_longer_lags() -> None:
    """Truth: theta_kappa(w) = rho^(kappa-1) * (mu'C) * (1 + 0.3 w), so the slope is
    positive at every lag and larger at the shorter one."""
    config, _, columns, trajectories = panel(n_units=2500, seed=11, preset="heterogeneous")
    modifier = baseline_columns(config.p, config.n_baseline)[0]
    index = np.array([columns.index(modifier)])
    fit = DynamicLagDmlFit(max_lag=2, seed=2, heterogeneous=True, modifier_index=index).fit(
        trajectories
    )
    constant = config.constant_profile()
    coefficients = fit.coefficients_[1]
    assert coefficients is not None
    intercept, slope = coefficients
    assert intercept == pytest.approx(constant[1], abs=1.0)
    assert slope == pytest.approx(constant[1] * config.hetero_propagation, abs=1.0)
    assert slope > 0


def test_the_analytic_standard_error_is_withheld_for_the_varying_profile() -> None:
    """With a coefficient vector per lag the recursion no longer reduces to one scalar, so
    reporting a number there would be inventing one. The bootstrap covers both cases."""
    config, _, columns, trajectories = panel(n_units=600, seed=11, preset="heterogeneous")
    index = np.array([columns.index(baseline_columns(config.p, config.n_baseline)[0])])
    fit = DynamicLagDmlFit(max_lag=1, seed=2, heterogeneous=True, modifier_index=index).fit(
        trajectories
    )
    assert np.all(np.isnan(fit.standard_error_))


# ---- the shape the estimand needs ----


def test_a_gap_in_the_periods_is_refused(benchmark) -> None:
    """The lag index counts rows, so a gap would silently relabel every later lag."""
    _, frame, columns, _ = benchmark
    first_unit = frame[UNIT_COLUMN].iloc[0]
    dropped = (frame[UNIT_COLUMN] == first_unit) & (frame[PERIOD_COLUMN] == 1)
    broken = frame.drop(frame.index[dropped])
    with pytest.raises(ValueError, match="consecutive integers"):
        to_trajectories(
            broken, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
        )


def test_a_duplicated_period_is_refused(benchmark) -> None:
    import pandas as pd

    _, frame, columns, _ = benchmark
    doubled = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate periods"):
        to_trajectories(
            doubled, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
        )


def test_a_missing_column_is_named(benchmark) -> None:
    _, frame, columns, _ = benchmark
    with pytest.raises(ValueError, match="not in the data"):
        to_trajectories(
            frame, UNIT_COLUMN, PERIOD_COLUMN, [*columns, "nope"], TREATMENT_COLUMN, OUTCOME_COLUMN
        )


# ---- the bootstrap ----


def test_the_bootstrap_resamples_units_not_rows(benchmark) -> None:
    """Rows inside a trajectory are dependent, so a row bootstrap would understate the
    spread. The profile spread should therefore be visible at all."""
    _, _, _, trajectories = benchmark
    fit = DynamicLagDmlFit(max_lag=1, seed=1).fit(trajectories[:250])
    interval = fit.bootstrap(trajectories[:250], replicates=8, seed=2)
    assert interval["profiles"].shape == (8, 2)
    assert interval["standard_error"][1] > 0
    assert interval["lower"][1] < interval["upper"][1]


def test_the_bootstrap_does_not_depend_on_the_number_of_workers(benchmark) -> None:
    """Indices are drawn up front for this reason: a result that changes with n_jobs is not
    reproducible, and the manifest would be recording a lie."""
    _, _, _, trajectories = benchmark
    fit = DynamicLagDmlFit(max_lag=1, seed=1).fit(trajectories[:200])
    serial = fit.bootstrap(trajectories[:200], replicates=6, seed=5, n_jobs=1)
    parallel = fit.bootstrap(trajectories[:200], replicates=6, seed=5, n_jobs=2)
    assert np.allclose(serial["profiles"], parallel["profiles"], equal_nan=True)


# ---- through the family interface ----


def test_the_family_returns_addressed_results(estimated) -> None:
    config, result = estimated
    truth = config.constant_profile()
    assert result.family == FAMILY
    for lag in range(3):
        assert f"res:profile.lag{lag}.theta" in result.values
        assert f"res:profile.lag{lag}.ci_lo" in result.values
        assert f"res:profile.lag{lag}.effective_windows" in result.values
    assert result.values["res:profile.lag0.theta"] == pytest.approx(truth[0], abs=0.05)
    # period_length turns a lag into the clock time a reader can use.
    assert result.values["res:profile.lag2.hours"] == 24.0


def test_the_result_declares_its_intervals_exploratory(estimated) -> None:
    """The claim-level decision reads this, and turns it into "nothing is significant"."""
    _, result = estimated
    assert result.values["res:profile.ci_calibration"] == "exploratory"
    assert result.values["res:profile.ci_method"] == "patient_bootstrap_percentile"


def test_an_unknown_estimand_is_refused(benchmark) -> None:
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns, estimand="lag_effect")
    with pytest.raises(ValueError, match="estimand must be one of"):
        registry.get(FAMILY).estimate(frame, spec, seed=1)


def test_the_varying_estimand_requires_modifiers(benchmark) -> None:
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns, estimand="lag_cate")
    with pytest.raises(ValueError, match="requires spec.effect_modifiers"):
        registry.get(FAMILY).estimate(frame, spec, seed=1)


def test_a_modifier_outside_the_state_is_refused(benchmark) -> None:
    """The projection is on the anchor state, so a modifier has to be part of it."""
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns, estimand="lag_cate", effect_modifiers=["exit_reason"])
    with pytest.raises(ValueError, match="must be part of the state"):
        registry.get(FAMILY).estimate(frame, spec, seed=1)


def test_the_unweighted_arm_is_reachable_from_the_spec(benchmark) -> None:
    """family.yaml declares the profile without IPCW as a sensitivity arm, so it has to be
    available without editing code."""
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns)
    spec = spec.model_copy(
        update={
            "estimation": {
                "family": FAMILY,
                "params": {"n_bootstrap_samples": 8, "use_ipcw": False},
            }
        }
    )
    result = registry.get(FAMILY).estimate(frame, spec, seed=1)
    assert result.values["res:estimation.use_ipcw"] == "False"
    assert result.values["res:profile.lag1.weight_max"] == 1.0


def test_the_generator_is_not_shipped_in_the_wheel() -> None:
    """data/generators is test scaffolding, not part of the package; if it ever became an
    import of causpec.* the wheel would carry synthetic-data code into production."""
    assert not (
        Path(registry.__file__).resolve().parents[1] / "families" / "dataset_a_panel.py"
    ).exists()


def test_a_short_trajectory_contributes_to_no_lag() -> None:
    """A unit with two periods can carry a lag-0 window and nothing longer. Off by one here
    would quietly borrow an outcome from a period that was never observed."""
    config = PanelConfig(n_units=60, seed=2, max_periods=3)
    frame = generate(config)
    columns = state_columns(config.p, config.n_baseline)
    trajectories = to_trajectories(
        frame, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
    )
    two_period = [t for t in trajectories if t.length == 2]
    assert two_period, "the design should produce some two-period trajectories"
    fit = DynamicLagDmlFit(max_lag=1, seed=1).fit(trajectories)
    by_lag = {lag_fit.lag: lag_fit for lag_fit in fit.fits_}
    # A two-period unit appears at lag 0 (one window: period 0) and at no longer lag.
    lag0_units = set(by_lag[0].unit_index.tolist())
    lag1_units = set(by_lag[1].unit_index.tolist()) if 1 in by_lag else set()
    short_indices = {i for i, t in enumerate(trajectories) if t.length == 2}
    assert short_indices <= lag0_units
    assert not (short_indices & lag1_units)


# ---- a fixed horizon needs no weights, and that is guaranteed rather than optional ----


def balanced_panel(periods: int = 8, n_units: int = 500, seed: int = 3):
    """Every unit observed for exactly ``periods`` periods: nobody leaves early.

    The hazard is switched off rather than turned down, so the true continuation probability
    is 1 everywhere and the correct weight is exactly 1.
    """
    return panel(n_units=n_units, seed=seed, exit_ceiling=1e-9, max_periods=periods)


def test_a_fixed_horizon_applies_no_weights_at_all() -> None:
    """The question this answers: with a fixed number of periods per unit there is no
    informative censoring, so is the weighting skipped, or only harmless?

    It is skipped. Before this was settled, the label rule treated the end of every
    trajectory as an exit, which asks the model to predict "is this the last period" from
    features that do not include the period index. On an eight-period balanced panel it
    returned continuation probabilities as low as 0.40 and weights up to 4.3, every one of
    which should have been 1.
    """
    config, _, _, trajectories = balanced_panel()
    assert len({t.length for t in trajectories}) == 1, "the panel should be balanced"
    fit = DynamicLagDmlFit(max_lag=2, seed=1, horizon="fixed").fit(trajectories)
    assert fit.horizon_ == "fixed"
    assert fit.ipcw_applied_ is False
    for lag_fit in fit.fits_:
        assert np.all(lag_fit.weight == 1.0)
    # No continuation model was fitted, so there is no diagnostic to report for one.
    assert np.isnan(fit.continuation_min_)
    del config


def test_on_a_fixed_horizon_the_weighting_contributes_nothing() -> None:
    """Not approximately: with the window convention held fixed, the two paths are the same
    computation, because every weight is 1.

    Switching the weighting off is not the same as declaring a fixed horizon, and that is the
    point of holding the convention fixed here: a fixed horizon also uses each trajectory's
    final period, which the sensitivity arm on a variable horizon does not.
    """
    _, _, _, trajectories = balanced_panel()
    weighted = DynamicLagDmlFit(max_lag=2, seed=1, horizon="fixed").fit(trajectories).theta_
    unweighted = (
        DynamicLagDmlFit(max_lag=2, seed=1, horizon="fixed", use_weights=False)
        .fit(trajectories)
        .theta_
    )
    assert np.allclose(weighted, unweighted, equal_nan=True)


def test_a_fixed_horizon_still_recovers_the_profile() -> None:
    config, _, _, trajectories = balanced_panel(periods=8, n_units=600)
    truth = config.constant_profile()
    fit = DynamicLagDmlFit(max_lag=2, seed=1, horizon="fixed").fit(trajectories)
    assert fit.theta_[0] == pytest.approx(truth[0], abs=0.02)
    assert fit.theta_[1] == pytest.approx(truth[1], abs=0.5)
    assert fit.theta_[2] == pytest.approx(truth[2], abs=0.5)


def test_a_variable_horizon_applies_the_weighting(benchmark) -> None:
    _, _, _, trajectories = benchmark
    fit = DynamicLagDmlFit(max_lag=1, seed=1).fit(trajectories)
    assert fit.horizon_ == "variable"
    assert fit.ipcw_applied_ is True
    assert any(lag_fit.weight.max() > 1.0 for lag_fit in fit.fits_)


def test_reaching_the_end_of_the_window_is_not_treated_as_leaving(benchmark) -> None:
    """The longest trajectory in a panel was cut off by the data, not by an exit, so it
    contributes no record saying it stopped continuing. Otherwise the model learns that
    whatever that unit looked like predicts leaving."""
    _, _, _, trajectories = benchmark
    window_end = max(t.length for t in trajectories)
    longest = [t for t in trajectories if t.length == window_end]
    assert longest, "some trajectory has to reach the window"
    fit = DynamicLagDmlFit(max_lag=1, seed=1).fit(trajectories)
    # Its final period keeps a continuation probability of 1, because no window's weight
    # ever reaches a unit's final period: the outcome period is at most the second to last.
    assert fit.horizon_ == "variable"


def test_the_result_says_whether_the_weighting_applied() -> None:
    """A report that shows weights of exactly 1 without saying why invites the reader to
    think the weighting was forgotten."""
    _, frame, columns, _ = balanced_panel(n_units=300)
    spec = panel_spec(columns, horizon="fixed").model_copy(
        update={"estimation": {"family": FAMILY, "params": {"n_bootstrap_samples": 4}}}
    )
    result = registry.get(FAMILY).estimate(frame, spec, seed=1)
    assert result.values["res:profile.horizon"] == "fixed"
    assert result.values["res:profile.ipcw_applied"] == "False"


def test_the_horizon_must_be_declared(benchmark) -> None:
    """The estimator refuses too, not only the checks: a spec that skipped the question
    cannot reach a number by going straight to estimation."""
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "horizon"}}
    )
    with pytest.raises(ValueError, match="requires spec.horizon"):
        registry.get(FAMILY).estimate(frame, spec, seed=1)


def test_a_variable_horizon_must_say_how_leaving_is_identified(benchmark) -> None:
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "termination"}}
    )
    with pytest.raises(ValueError, match="requires spec.termination"):
        registry.get(FAMILY).estimate(frame, spec, seed=1)


def test_a_termination_column_that_does_not_exist_is_named(benchmark) -> None:
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns, termination="discharge_flag")
    with pytest.raises(ValueError, match="not a column in the data"):
        registry.get(FAMILY).estimate(frame, spec, seed=1)


def test_the_rows_may_simply_stop_where_the_unit_left(benchmark) -> None:
    """The other of the two answers: no column marks the exit, the trajectory just ends."""
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns, termination="last_recorded_period").model_copy(
        update={"estimation": {"family": FAMILY, "params": {"n_bootstrap_samples": 4}}}
    )
    result = registry.get(FAMILY).estimate(frame, spec, seed=1)
    assert result.values["res:estimation.termination"] == "last_recorded_period"
    assert result.values["res:profile.ipcw_applied"] == "True"


def test_an_exit_column_decides_which_trajectories_ended_by_leaving(benchmark) -> None:
    """With a column, whether a trajectory left is read from it rather than from where its
    rows stop. The two differ for the longest trajectories, which reach the end of the
    observation window: those are cut off unless the column says they left."""
    _, frame, columns, _ = benchmark
    marked = to_trajectories(
        frame,
        UNIT_COLUMN,
        PERIOD_COLUMN,
        columns,
        TREATMENT_COLUMN,
        OUTCOME_COLUMN,
        termination="exit_reason",
    )
    unmarked = to_trajectories(
        frame, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
    )
    assert all(t.exited is not None for t in marked)
    assert all(t.exited is None for t in unmarked)
    # The generator's units leave, so nearly all of them are marked as having exited.
    assert sum(bool(t.exited) for t in marked) > 0.9 * len(marked)


def test_rows_recorded_after_a_unit_left_are_refused(benchmark) -> None:
    """A padded or carried-forward panel: the unit left at period 2 and the file still has
    rows for 3 and 4. Those are not observations of an active trajectory, and averaging over
    them would put made-up periods into the moment."""
    import pandas as pd

    _, frame, columns, _ = benchmark
    first_unit = frame[UNIT_COLUMN].iloc[0]
    rows = frame[frame[UNIT_COLUMN] == first_unit].copy()
    assert len(rows) >= 2
    padded = rows.copy()
    padded[PERIOD_COLUMN] = padded[PERIOD_COLUMN] + len(rows)
    padded["exit_reason"] = ""
    broken = pd.concat([rows, padded], ignore_index=True)
    with pytest.raises(ValueError, match="rows recorded after it left"):
        to_trajectories(
            broken,
            UNIT_COLUMN,
            PERIOD_COLUMN,
            columns,
            TREATMENT_COLUMN,
            OUTCOME_COLUMN,
            termination="exit_reason",
        )


def test_a_fixed_horizon_uses_the_final_period(benchmark) -> None:
    """Nobody leaves, so the last period's outcome is recorded like any other and the
    condition the paper's analysis set stands in for cannot fail. Excluding it would discard
    one window per unit per lag: on an eight-period panel, a sixth of the lag-2 windows.
    """
    del benchmark
    _, _, _, trajectories = balanced_panel(periods=8, n_units=200)
    relaxed = DynamicLagDmlFit(max_lag=2, seed=1, horizon="fixed").fit(trajectories)
    strict = DynamicLagDmlFit(max_lag=2, seed=1, horizon="variable").fit(trajectories)
    for lag in range(3):
        gained = len(relaxed.fits_[lag].weight)
        withheld = len(strict.fits_[lag].weight)
        assert gained == withheld + len(trajectories), f"lag {lag}"
    # 200 units, 8 periods: every unit contributes 8 - lag windows rather than 7 - lag.
    assert len(relaxed.fits_[2].weight) == 200 * 6


def test_a_variable_horizon_keeps_the_papers_window(benchmark) -> None:
    """Including trajectories the observation window cut off: their final outcome is
    recorded, but whether they would have continued is unknown, so the step the weight
    corrects for is unobservable rather than absent. One convention, conservatively."""
    _, _, _, trajectories = benchmark
    fit = DynamicLagDmlFit(max_lag=0, seed=1).fit(trajectories)
    expected = sum(t.length - 1 for t in trajectories)
    assert len(fit.fits_[0].weight) == expected


def test_the_result_says_which_window_convention_was_used(benchmark) -> None:
    _, frame, columns, _ = benchmark
    spec = panel_spec(columns).model_copy(
        update={"estimation": {"family": FAMILY, "params": {"n_bootstrap_samples": 4}}}
    )
    result = registry.get(FAMILY).estimate(frame, spec, seed=1)
    assert result.values["res:profile.final_period_included"] == "False"


def test_relaxing_the_window_does_not_move_the_estimate(benchmark) -> None:
    """More windows, same answer. If the extra period were biased, this is where it shows."""
    del benchmark
    config, _, _, trajectories = balanced_panel(periods=8, n_units=800, seed=11)
    truth = config.constant_profile()
    relaxed = DynamicLagDmlFit(max_lag=2, seed=1, horizon="fixed").fit(trajectories)
    assert relaxed.theta_[0] == pytest.approx(truth[0], abs=0.02)
    assert relaxed.theta_[1] == pytest.approx(truth[1], abs=0.4)
    assert relaxed.theta_[2] == pytest.approx(truth[2], abs=0.5)


# ---- a missing value is refused, not imputed ----


def test_a_missing_value_names_its_column(benchmark) -> None:
    """Left alone this surfaces as "Input y contains NaN" from inside a nuisance regression,
    which names neither the column nor the repair."""
    _, frame, columns, _ = benchmark
    broken = frame.copy()
    broken.loc[broken.index[5], columns[0]] = np.nan
    with pytest.raises(ValueError, match=f"missing values.*{columns[0]}"):
        to_trajectories(
            broken, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
        )


def test_missing_values_on_final_periods_get_their_own_explanation() -> None:
    """The pattern the relaxation makes more likely: the outcome's measurement window runs
    past the end of data collection, so the last period has a state and a treatment but no
    outcome. The fix is to record one period fewer, not to impute."""
    _, frame, columns, _ = balanced_panel(periods=6, n_units=100)
    broken = frame.copy()
    final = np.asarray(
        broken.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max") == broken[PERIOD_COLUMN],
        dtype=bool,
    )
    broken.loc[final, OUTCOME_COLUMN] = np.nan
    with pytest.raises(ValueError, match="all on final periods"):
        to_trajectories(
            broken, UNIT_COLUMN, PERIOD_COLUMN, columns, TREATMENT_COLUMN, OUTCOME_COLUMN
        )

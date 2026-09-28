"""The panel generator: is the truth it emits really the truth?

Mirrors design.md sections 15 and 16, and the lesson of test_dataset_a.py: if the emitted
ground truth is wrong, every numerical test built on it is sand. That has already happened
once in this project, when tau was defined as a risk difference and then clipped.

Two properties carry the rest. The closed-form profile has to agree with what the simulated
trajectories actually do, and positivity has to hold by construction rather than by luck.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a_panel import (  # noqa: E402
    OUTCOME_COLUMN,
    PERIOD_COLUMN,
    PRESETS,
    TREATMENT_COLUMN,
    UNIT_COLUMN,
    PanelConfig,
    baseline_columns,
    config_for,
    generate,
    state_columns,
    truth,
)


def test_the_same_seed_gives_the_same_panel() -> None:
    a = generate(PanelConfig(n_units=80, seed=3))
    b = generate(PanelConfig(n_units=80, seed=3))
    assert a.equals(b)


def test_a_different_seed_gives_a_different_panel() -> None:
    a = generate(PanelConfig(n_units=80, seed=3))
    b = generate(PanelConfig(n_units=80, seed=4))
    assert not a[OUTCOME_COLUMN].equals(b[OUTCOME_COLUMN])


def test_the_periods_are_consecutive_from_zero() -> None:
    """The estimand depends on it, and the checks refuse anything else, so the generator
    must not be the source of a violation."""
    frame = generate(PanelConfig(n_units=200, seed=1))
    for _, group in frame.groupby(UNIT_COLUMN):
        periods = np.sort(group[PERIOD_COLUMN].to_numpy())
        assert np.array_equal(periods, np.arange(len(periods)))


def test_positivity_holds_by_construction() -> None:
    """The exit probability is capped, so the continuation probability has a floor for every
    state. This is what lets the selection strength be turned up without breaking the
    assumption the estimator needs."""
    config = PanelConfig(n_units=400, seed=2)
    frame = generate(config)
    assert frame["lambda_true"].min() >= config.continuation_floor - 1e-9


def test_the_floor_moves_with_the_ceiling() -> None:
    config = PanelConfig(n_units=300, seed=2, exit_ceiling=0.5)
    frame = generate(config)
    assert config.continuation_floor == pytest.approx(0.5)
    assert frame["lambda_true"].min() >= 0.5 - 1e-9


def test_the_closed_form_profile_matches_the_paper() -> None:
    """The two designs the author reports: (-0.5, 4.0, 1.2) and (-0.5, 3.6, 1.08)."""
    low = config_for("paper_low_dim").constant_profile()
    high = config_for("paper_high_dim").constant_profile()
    assert low == pytest.approx([-0.5, 4.0, 1.2])
    assert high == pytest.approx([-0.5, 3.6, 1.08])


def test_the_emitted_truth_is_the_closed_form_truth() -> None:
    """With no heterogeneity every row carries the same profile, and it is the formula's."""
    config = PanelConfig(n_units=200, seed=5)
    frame = generate(config)
    expected = config.constant_profile()
    for lag in range(config.max_lag + 1):
        assert frame[f"theta{lag}_true"].nunique() == 1
        assert frame[f"theta{lag}_true"].iloc[0] == pytest.approx(expected[lag])


def test_the_outcome_equation_holds_row_by_row() -> None:
    """Y[t] = theta_0(row) * A[t] + mu' X[t] + noise, so removing the first two terms should
    leave nothing but noise of the declared size. This is the check that would have caught
    the clipping bug in dataset A."""
    config = PanelConfig(n_units=300, seed=6)
    frame = generate(config)
    columns = state_columns(config.p, config.n_baseline)
    mu = config.coefficients()["mu"]
    structural = (
        frame["theta0_true"].to_numpy() * frame[TREATMENT_COLUMN].to_numpy()
        + frame[columns].to_numpy() @ mu
    )
    residual = frame[OUTCOME_COLUMN].to_numpy() - structural
    assert abs(float(residual.mean())) < 0.01
    assert float(residual.std()) == pytest.approx(config.sigma_epsilon, rel=0.2)


def test_the_state_recursion_holds_between_consecutive_rows() -> None:
    """X[t+1] = C(row) * A[t] + rho * X[t] + noise for the time-varying coordinates."""
    config = PanelConfig(n_units=300, seed=6)
    frame = generate(config)
    columns = state_columns(config.p, config.n_baseline)
    c_vector = config.coefficients()["C"]
    errors = []
    for _, group in frame.groupby(UNIT_COLUMN):
        states = group[columns].to_numpy()
        treatment = group[TREATMENT_COLUMN].to_numpy()
        for period in range(len(group) - 1):
            predicted = c_vector * treatment[period] + config.rho * states[period]
            errors.append(states[period + 1] - predicted)
    residual = np.concatenate(errors)
    assert abs(float(residual.mean())) < 0.1
    assert float(residual.std()) == pytest.approx(config.sigma_eta, rel=0.2)


def test_the_paper_design_reproduces_its_reported_descriptives() -> None:
    """The author reports about 54% of periods treated and a mean of 2.9 observed periods."""
    config = PanelConfig(n_units=1500, seed=1)
    frame = generate(config)
    facts = truth(frame, config)
    assert facts["treated_fraction"] == pytest.approx(0.54, abs=0.04)
    assert facts["mean_periods"] == pytest.approx(2.9, abs=0.2)


def test_leaving_is_informative() -> None:
    """Sicker patients must leave earlier, or there is nothing for the weights to correct."""
    config = PanelConfig(n_units=600, seed=3)
    frame = generate(config)
    severity = frame[state_columns(config.p, config.n_baseline)[0]]
    last_row = frame.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max") == frame[PERIOD_COLUMN]
    assert severity[last_row].mean() > severity[~last_row].mean()


# ---- heterogeneity has to sit on a baseline covariate ----


def test_heterogeneity_without_a_baseline_covariate_is_refused() -> None:
    """A lag effect that varies with a state the treatment moves has no additive profile:
    the contribution of one treatment period then depends on the next period's treatment.
    The generator refuses to produce that world and call it ground truth.
    """
    with pytest.raises(ValueError, match="needs at least one baseline coordinate"):
        PanelConfig(n_units=10, hetero_propagation=0.3)


def test_a_baseline_covariate_never_changes_within_a_unit() -> None:
    config = config_for("heterogeneous", n_units=200, seed=8)
    frame = generate(config)
    for column in baseline_columns(config.p, config.n_baseline):
        assert (frame.groupby(UNIT_COLUMN)[column].nunique() == 1).all()


def test_the_varying_truth_is_constant_within_a_unit_and_varies_across_them() -> None:
    config = config_for("heterogeneous", n_units=200, seed=8)
    frame = generate(config)
    assert (frame.groupby(UNIT_COLUMN)["theta1_true"].nunique() == 1).all()
    assert frame["theta1_true"].nunique() > 50


def test_the_varying_truth_follows_the_stated_formula() -> None:
    """theta_0(w) = theta_0 * (1 + h_outcome * w) and
    theta_kappa(w) = rho^(kappa-1) * (mu'C) * (1 + h_propagation * w)."""
    config = config_for("heterogeneous", n_units=150, seed=9)
    frame = generate(config)
    modifier = baseline_columns(config.p, config.n_baseline)[0]
    w = frame[modifier].to_numpy()
    constant = config.constant_profile()
    assert frame["theta0_true"].to_numpy() == pytest.approx(
        config.theta_0 * (1.0 + config.hetero_outcome * w)
    )
    for lag in (1, 2):
        assert frame[f"theta{lag}_true"].to_numpy() == pytest.approx(
            constant[lag] * (1.0 + config.hetero_propagation * w)
        )


# ---- the presets and the reporting helpers ----


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_preset_generates_and_reports(preset: str) -> None:
    config = config_for(preset, n_units=60, seed=1)
    frame = generate(config)
    facts = truth(frame, config)
    assert len(frame) > 0
    assert facts["n_units"] == 60
    assert np.isfinite(facts["theta1_anchor_mean"])


def test_the_anchor_mean_is_reported_next_to_the_constant() -> None:
    """With heterogeneity the constant is no longer the target: what the estimator converges
    to is the average over the windows each lag actually has."""
    config = config_for("heterogeneous", n_units=400, seed=4)
    facts = truth(generate(config), config)
    assert facts["theta1_constant"] == pytest.approx(4.0)
    assert facts["theta1_anchor_mean"] != facts["theta1_constant"]


def test_the_exit_reason_is_only_on_the_last_row() -> None:
    """Cosmetic column, but a report says what share of endings were deaths, and that has to
    count endings rather than rows."""
    frame = generate(PanelConfig(n_units=150, seed=7))
    labelled = frame[frame["exit_reason"] != ""]
    last = frame.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max") == frame[PERIOD_COLUMN]
    assert set(labelled.index) <= set(frame.index[last])

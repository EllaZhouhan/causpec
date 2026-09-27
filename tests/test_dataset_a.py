"""Synthetic dataset A: ground-truth self-consistency and instrument validity.

Mirrors design.md sections 15 and 16. These tests pin whether **the generator itself**
is correct: if tau_true is not really the truth, every numerical eval built on it is sand.
"""

from __future__ import annotations

import numpy as np
import pytest
from dataset_a import PRESETS, DatasetAConfig, config_for, generate, truth


@pytest.fixture(scope="module")
def binary_data():
    return generate(config_for("high_power", instrument_kind="binary", seed=11, n=6000))


def test_same_seed_same_data() -> None:
    a = generate(DatasetAConfig(n=500, seed=3))
    b = generate(DatasetAConfig(n=500, seed=3))
    assert a.equals(b)


def test_different_seed_different_data() -> None:
    a = generate(DatasetAConfig(n=500, seed=3))
    b = generate(DatasetAConfig(n=500, seed=4))
    assert not a["death"].equals(b["death"])


def test_tau_true_equals_potential_outcome_difference(binary_data) -> None:
    """tau must be computed straight from the potential-outcome probabilities.

    An earlier version defined tau as a risk difference then clipped to [0,1], which at
    4% baseline mortality clipped heavily, so tau_true no longer held the real effect.
    The ground-truth check caught that bug, which is why it is pinned here.
    """
    expected = binary_data["p1_true"] - binary_data["p0_true"]
    assert np.allclose(binary_data["tau_true"], expected)


def test_potential_outcome_probabilities_are_valid(binary_data) -> None:
    for column in ("p0_true", "p1_true"):
        assert binary_data[column].between(0.0, 1.0).all()


def test_effect_is_heterogeneous_in_the_intended_direction(binary_data) -> None:
    """The sicker the AKI stage, the greater the benefit; stage 0 is harmed instead."""
    by_stage = binary_data.groupby("max_aki_stage_smoothed")["tau_true"].mean()
    assert by_stage.loc[0] > 0 > by_stage.loc[3]
    assert by_stage.is_monotonic_decreasing


def test_confounding_makes_naive_estimate_wrong(binary_data) -> None:
    """Unmeasured confounding must genuinely bias the naive difference, or this dataset
    proves nothing."""
    facts = truth(binary_data)
    assert facts["ate_true"] < 0 < facts["naive_difference"]


def test_instrument_is_relevant(binary_data) -> None:
    z, t = binary_data["instrument"], binary_data["isDialysisICU"]
    first_stage = t[z == 1].mean() - t[z == 0].mean()
    assert first_stage > 0.05


def test_monotonicity_holds_by_construction(binary_data) -> None:
    """With a binary instrument there are no defiers."""
    assert set(binary_data["compliance_type"]) <= {"always_taker", "never_taker", "complier"}


def test_first_stage_equals_complier_share(binary_data) -> None:
    """Under monotonicity, E[T|Z=1] - E[T|Z=0] is the complier share."""
    z, t = binary_data["instrument"], binary_data["isDialysisICU"]
    first_stage = t[z == 1].mean() - t[z == 0].mean()
    complier_share = (binary_data["compliance_type"] == "complier").mean()
    assert abs(first_stage - complier_share) < 0.02


def test_exclusion_restriction_holds(binary_data) -> None:
    """Z reaches Y only through T: holding compliance type fixed, Z is unrelated to the
    potential outcomes.

    Always-takers and never-takers do not change treatment with Z, so their outcomes
    should show no systematic difference between the Z=0 and Z=1 groups.
    """
    non_compliers = binary_data[binary_data["compliance_type"] != "complier"]
    z = non_compliers["instrument"]
    gap = non_compliers.loc[z == 1, "death"].mean() - non_compliers.loc[z == 0, "death"].mean()
    assert abs(gap) < 0.03


def test_wald_estimator_recovers_late_without_outcome_noise(binary_data) -> None:
    """Using true probabilities instead of 0/1 outcomes, the Wald estimator should
    approach the true LATE.

    This is the IV identification identity: with outcome sampling noise removed, the
    remaining discrepancy should be finite-sample variation in the Z split alone.
    """
    ct = binary_data["compliance_type"].to_numpy()
    z = binary_data["instrument"].to_numpy()
    p0, p1 = binary_data["p0_true"].to_numpy(), binary_data["p1_true"].to_numpy()

    t_at_observed_z = np.where(ct == "always_taker", 1, np.where(ct == "never_taker", 0, z))
    assert (t_at_observed_z == binary_data["isDialysisICU"].to_numpy()).all()

    p_y = np.where(t_at_observed_z == 1, p1, p0)
    reduced_form = p_y[z == 1].mean() - p_y[z == 0].mean()
    first_stage = t_at_observed_z[z == 1].mean() - t_at_observed_z[z == 0].mean()
    late_true = (p1 - p0)[ct == "complier"].mean()

    assert abs(reduced_form / first_stage - late_true) < 0.01


def test_continuous_instrument_first_stage_is_monotone() -> None:
    import pandas as pd

    df = generate(config_for("high_power", instrument_kind="continuous", seed=11, n=6000))
    bins = pd.qcut(df["instrument"], 5, labels=False, duplicates="drop")
    rates = np.asarray(df.groupby(bins)["isDialysisICU"].mean())
    assert np.all(np.diff(rates) > 0)
    # No always/never/complier split with a continuous instrument
    assert set(df["compliance_type"].unique()) == {"unknown"}


def test_presets_hit_their_targets() -> None:
    for preset in PRESETS:
        cfg = config_for(preset, n=4000, seed=5)
        df = generate(cfg)
        assert abs(df["isDialysisICU"].mean() - cfg.target_treatment_rate) < 0.03
        assert abs(df["death"].mean() - cfg.target_death_rate) < 0.03


def test_realistic_preset_matches_the_real_study_scale() -> None:
    """The realistic preset must match the real ICU study's scale (about 9.5% treated,
    about 4% mortality)."""
    df = generate(config_for("realistic", n=8000, seed=5))
    assert 0.06 < df["isDialysisICU"].mean() < 0.13
    assert 0.02 < df["death"].mean() < 0.07


def test_unknown_preset_lists_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="realistic"):
        config_for("nonexistent")

"""The hte_iv adapter: two backends, binary and continuous instruments, address contracts.

Only the cheap ivforest backend is exercised. dmliv bootstraps, measured at over 500
seconds at n=5000, which does not belong in CI on every push; its correctness is
econml's responsibility. What is pinned here is the **adapter**: which fields are read,
which addresses are emitted, and what must be refused.
"""

from __future__ import annotations

import pytest
from dataset_a import config_for, generate

from causpec.core import registry
from causpec.core.contracts.spec import Source, Spec, SpecField, Status

EFFECT_MODIFIERS = [
    "admission_age",
    "max_aki_stage_smoothed",
    "max_potassium",
    "min_bicarbonate",
    "sofa_total_24h",
]


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="confirmed", status=Status.CONFIRMED)


def make_spec(params: dict[str, object], **overrides: object) -> Spec:
    fields: dict[str, SpecField] = {
        "treatment": confirmed("isDialysisICU"),
        "outcome": confirmed("death"),
        "estimand": confirmed("conditional_late"),
        "instrument": confirmed(["instrument"]),
        "effect_modifiers": confirmed(EFFECT_MODIFIERS),
    }
    fields.update({k: confirmed(v) for k, v in overrides.items()})
    return Spec(
        question="Which patients benefit from dialysis?",
        family="hte_iv",
        estimation={"family": "hte_iv", "params": params},
        fields=fields,
    )


# n_estimators must be divisible by subforest_size=4; the bootstrap count is kept
# minimal, because these tests pin the adapter's contract, not the intervals' statistics.
FAST = {"estimator": "ivforest", "n_estimators": 52, "n_bootstrap_samples": 3}


@pytest.fixture(scope="module")
def data():
    return generate(config_for("high_power", instrument_kind="binary", seed=11, n=1200))


@pytest.fixture(scope="module")
def result(data):
    return registry.get("hte_iv").estimate(data, make_spec(FAST), seed=42)


def test_every_value_is_addressed(result) -> None:
    """design.md 10.1: every number in a Result has an address in a known namespace."""
    prefixes = (
        "res:primary.",
        "res:cate.",
        "res:sample.",
        "res:instrument.",
        "res:design.",
        "res:estimation.",
    )
    assert all(address.startswith(prefixes) for address in result.values)


def test_binary_instrument_is_detected(result) -> None:
    assert result.values["res:instrument.kind"] == "binary"


def test_continuous_instrument_is_detected(data) -> None:
    """One family supports both instrument kinds (family.yaml's instrument_kinds)."""
    continuous = generate(config_for("high_power", instrument_kind="continuous", seed=11, n=1200))
    out = registry.get("hte_iv").estimate(continuous, make_spec(FAST), seed=42)
    assert out.values["res:instrument.kind"] == "continuous"


def test_cate_and_ate_intervals_come_from_different_mechanisms(result) -> None:
    """ivforest's two intervals come from different mechanisms and are recorded separately.

    The pointwise CATE interval comes from GRF's honest variance, computed within one
    fit; the ATE interval comes from a unit-level bootstrap of the forest, because
    econml.grf exposes only pointwise variance and one forest's per-point estimates are
    highly correlated, so averaging them and dividing by n would assume independence.
    """
    assert result.values["res:cate.ci_method"] == "grf_honest"
    assert result.values["res:primary.ate_ci_method"] == "forest_bootstrap"
    assert result.values["res:estimation.estimator"] == "ivforest"


def test_ate_interval_is_ordered(result) -> None:
    """A percentile bootstrap interval is **not guaranteed** to bracket the point
    estimate, so this only asserts that it is ordered.

    [q2.5, q97.5] are quantiles of the resampling distribution; when that distribution
    sits systematically off the point estimate (an honest forest shrinks towards the
    mean, which does exactly that), the point estimate can fall outside.
    Centring on the point estimate means the basic (reverse-percentile) bootstrap,
    which is a different choice; this matches dmliv and uses percentile.
    """
    assert result.values["res:primary.ate_ci_lower"] < result.values["res:primary.ate_ci_upper"]


def test_low_bootstrap_count_is_flagged(result) -> None:
    """Too few replicates is flagged on the Result, and the report must surface it."""
    assert result.values["res:estimation.bootstrap_adequate"] == "no"
    assert result.values["res:estimation.n_bootstrap_samples"] == 3


def test_bootstrap_parallelism_does_not_change_the_result(data) -> None:
    """Indices are drawn up front, so parallelism cannot change the result."""
    family = registry.get("hte_iv")
    serial = family.estimate(data, make_spec({**FAST, "bootstrap_n_jobs": 1}), seed=5)
    parallel = family.estimate(data, make_spec({**FAST, "bootstrap_n_jobs": 2}), seed=5)
    assert serial.values == parallel.values


def test_sample_facts_match_the_data(result, data) -> None:
    assert result.values["res:sample.n"] == len(data)
    assert result.values["res:sample.n_treated"] == int(data["isDialysisICU"].sum())
    assert result.values["res:sample.n_treated"] + result.values["res:sample.n_control"] == len(
        data
    )


def test_reproducible_under_same_seed(data) -> None:
    family = registry.get("hte_iv")
    spec = make_spec(FAST)
    assert family.estimate(data, spec, seed=7) == family.estimate(data, spec, seed=7)


def test_unknown_estimator_is_rejected(data) -> None:
    with pytest.raises(ValueError, match="dmliv"):
        registry.get("hte_iv").estimate(data, make_spec({"estimator": "magic"}), seed=42)


def test_missing_instrument_is_rejected(data) -> None:
    spec = make_spec(FAST)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "instrument"}}
    )
    with pytest.raises(ValueError, match="instrument"):
        registry.get("hte_iv").estimate(data, spec, seed=42)


def test_missing_effect_modifiers_is_rejected(data) -> None:
    spec = make_spec(FAST)
    spec = spec.model_copy(
        update={"fields": {k: v for k, v in spec.fields.items() if k != "effect_modifiers"}}
    )
    with pytest.raises(ValueError, match="effect_modifiers"):
        registry.get("hte_iv").estimate(data, spec, seed=42)


def test_n_estimators_must_divide_subforest_size(data) -> None:
    """GRF's constraint, restated plainly, with usable values suggested."""
    spec = make_spec({"estimator": "ivforest", "n_estimators": 50})
    with pytest.raises(ValueError, match="divisible"):
        registry.get("hte_iv").estimate(data, spec, seed=42)


def test_ivforest_refuses_adjustment_set_instead_of_silently_dropping_it(data) -> None:
    """CausalIVForest has no separate W channel.

    The research code defined controls (75 columns) and then silently dropped them
    because W=None. Erroring is preferable to repeating that.
    """
    spec = make_spec(FAST, adjustment_set=["min_GCS_Total", "max_creatinine"])
    with pytest.raises(ValueError, match="adjustment_set"):
        registry.get("hte_iv").estimate(data, spec, seed=42)

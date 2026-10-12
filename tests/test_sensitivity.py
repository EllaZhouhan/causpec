"""Sensitivity and refutation: what it would take for the estimate to be wrong.

Mirrors design.md 10.1. Two things of different kinds.

The **E-value** is the only quantitative thing this project can say about unconfoundedness,
which is `untestable` and which no diagnostic will ever verify. It turns "could confounding
explain this?" into "could a confounder this strong exist?", which someone who knows the
setting can answer. Closed form, so it is written here under ADR-0004's rule and checked
against the published example.

The **refuters** perturb the data so that the right answer is known in advance, re-run the
family's own estimator, and check they get it. They are tested here against stub estimators
rather than real ones, because the question is whether the refuter notices a failure, and a
real estimator cannot be made to fail on demand. The stubs are what the `Estimator` protocol
is for.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.sensitivity import e_value, e_value_from_risks, run_refutations
from causpec.core.sensitivity.evalue import EValueUndefined

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402

COVARIATES = ["max_creatinine", "max_potassium", "max_urea", "min_ArterialPressure"]

# What `Honest`, a difference in proportions on 600 rows, would really report: its standard
# error is about 0.04, so a 95% half-width of roughly 0.08.
HONEST_WIDTH = 0.08

DECLARATION = {
    "sensitivity": {
        "primary_address": "res:primary.ate",
        "primary_ci_lower": "res:primary.ate_ci_lower",
        "primary_ci_upper": "res:primary.ate_ci_upper",
    }
}


def confirmed(value: object) -> SpecField:
    return SpecField(value=value, source=Source.USER, said="yes", status=Status.CONFIRMED)


def make_spec() -> Spec:
    return Spec(
        question="q",
        family="hte_backdoor",
        fields={
            "treatment": confirmed("isDialysisICU"),
            "outcome": confirmed("death"),
            "estimand": confirmed("ate"),
            "effect_modifiers": confirmed(COVARIATES),
        },
    )


def result_of(ate: float, half_width: float = 0.02) -> Result:
    return Result(
        family="hte_backdoor",
        seed=0,
        values={
            "res:primary.ate": ate,
            "res:primary.ate_ci_lower": ate - half_width,
            "res:primary.ate_ci_upper": ate + half_width,
        },
    )


class Constant:
    """An estimator that returns the same effect whatever the data.

    The failure mode the placebo test exists to catch, and the reason it is the one test that
    speaks to validity rather than stability: a pipeline that reports an effect from permuted
    data is reporting something other than an effect of the treatment.
    """

    def __init__(self, ate: float) -> None:
        self.ate = ate
        self.calls = 0

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        del data, spec, seed
        self.calls += 1
        return result_of(self.ate)


class Honest:
    """An estimator that reads the treatment, so permuting it destroys the effect."""

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        del seed
        treatment = np.asarray(data[str(spec.fields["treatment"].value)], dtype=float)
        outcome = np.asarray(data[str(spec.fields["outcome"].value)], dtype=float)
        treated = outcome[treatment == 1.0]
        control = outcome[treatment == 0.0]
        gap = float(treated.mean() - control.mean()) if treated.size and control.size else 0.0
        return result_of(gap)


@pytest.fixture(scope="module")
def data() -> pd.DataFrame:
    return generate(config_for("high_power", n=600, seed=7))


# ---- the E-value, against the published example ----


def test_the_published_example_reproduces() -> None:
    """VanderWeele and Ding (2017). Their headline pair: an observed risk ratio of 3.9 gives
    an E-value of 7.26, and a lower confidence limit of 1.8 gives 3.0."""
    assert e_value(3.9) == pytest.approx(7.26, abs=0.005)
    assert e_value(1.8) == pytest.approx(3.0, abs=0.005)


def test_no_association_needs_no_confounder() -> None:
    assert e_value(1.0) == pytest.approx(1.0)


def test_a_halving_and_a_doubling_need_the_same_confounder() -> None:
    """Otherwise the number would depend on which arm was called the treatment."""
    assert e_value(2.0) == pytest.approx(e_value(0.5))
    assert e_value(2.0) == pytest.approx(3.4142, abs=0.0001)


def test_an_impossible_ratio_is_refused() -> None:
    for ratio in (0.0, -1.0, float("inf")):
        with pytest.raises(EValueUndefined):
            e_value(ratio)


def test_the_ratio_is_formed_from_the_two_arm_risks() -> None:
    """Exact, given quantities the estimators already report, rather than one of the paper's
    approximate conversions from a risk difference."""
    computed = e_value_from_risks(control_risk=0.20, effect=0.10)
    assert computed.risk_ratio == pytest.approx(1.5)
    assert computed.point == pytest.approx(e_value(1.5))


def test_the_limit_nearest_the_null_is_the_one_used() -> None:
    """ "What would make this compatible with nothing" is a question about the edge of the
    interval closest to nothing, and it is the number a reader should take."""
    computed = e_value_from_risks(control_risk=0.20, effect=0.10, ci_lower=0.04, ci_upper=0.16)
    assert computed.limit_risk_ratio == pytest.approx(1.2)
    assert computed.limit is not None
    assert computed.limit == pytest.approx(e_value(1.2))
    assert computed.limit < computed.point
    assert computed.interval_includes_null is False


def test_an_interval_containing_the_null_needs_no_confounding_at_all() -> None:
    computed = e_value_from_risks(control_risk=0.20, effect=0.10, ci_lower=-0.02, ci_upper=0.22)
    assert computed.interval_includes_null is True
    assert computed.limit == pytest.approx(1.0)


def test_a_protective_effect_gives_a_ratio_above_one() -> None:
    computed = e_value_from_risks(control_risk=0.30, effect=-0.10)
    assert computed.risk_ratio == pytest.approx(2 / 3)
    assert computed.point > 1.0


def test_no_events_in_the_control_arm_means_no_e_value() -> None:
    with pytest.raises(EValueUndefined, match="no risk ratio to form"):
        e_value_from_risks(control_risk=0.0, effect=0.1)


def test_an_effect_implying_an_impossible_risk_is_refused() -> None:
    with pytest.raises(EValueUndefined, match="not a probability"):
        e_value_from_risks(control_risk=0.9, effect=0.3)


def test_the_addresses_are_rounded_and_complete() -> None:
    computed = e_value_from_risks(control_risk=0.2, effect=0.1, ci_lower=0.04, ci_upper=0.16)
    addresses = computed.addresses()
    assert addresses["res:sensitivity.e_value"] == pytest.approx(2.366, abs=0.001)
    assert addresses["res:sensitivity.interval_includes_null"] == "no"


# ---- the placebo test, which is the one that speaks to validity ----


def test_a_constant_estimator_fails_the_placebo_test(data) -> None:
    """The failure this exists to catch. The estimate survives permuting the treatment, so it
    is not an estimate of the treatment's effect, whatever else is right about the analysis.
    """
    family = Constant(0.30)
    report = run_refutations(family, data, make_spec(), result_of(0.30), DECLARATION, seed=1)
    placebo = next(f for f in report.findings if f.test_id == "placebo_treatment")
    assert placebo.passed is False
    assert "cannot be read as an effect of the treatment" in placebo.interpretation
    assert float(placebo.evidence["largest_absolute_estimate"]) == pytest.approx(0.30)


def test_an_honest_estimator_passes_the_placebo_test(data) -> None:
    """With an interval that matches its own precision. `Honest` is a difference in
    proportions on 600 rows, whose standard error is about 0.04, so HONEST_WIDTH is what it
    would really report."""
    family = Honest()
    observed = result_of(
        float(family.estimate(data, make_spec(), seed=0).values["res:primary.ate"]),
        half_width=HONEST_WIDTH,
    )
    report = run_refutations(family, data, make_spec(), observed, DECLARATION, seed=1)
    placebo = next(f for f in report.findings if f.test_id == "placebo_treatment")
    assert placebo.passed is True
    assert "not manufacturing an effect" in placebo.interpretation


def test_an_overconfident_interval_fails_the_placebo_test(data) -> None:
    """Found by writing the test above carelessly, and worth keeping. Pair the same honest
    estimator with an interval four times too narrow and the placebo test fails, because
    permuted estimates scatter by more than the interval admits. That is the right verdict:
    the complaint is not about the point estimate, it is that the reported precision is not
    real, and the placebo test is the thing that notices."""
    family = Honest()
    observed = result_of(
        float(family.estimate(data, make_spec(), seed=0).values["res:primary.ate"]),
        half_width=HONEST_WIDTH / 4,
    )
    report = run_refutations(family, data, make_spec(), observed, DECLARATION, seed=1)
    assert next(f for f in report.findings if f.test_id == "placebo_treatment").passed is False


def test_the_tolerance_is_the_analysis_own_precision(data) -> None:
    """A fixed threshold would fail a noisy-but-correct estimator and pass anything on a
    precise one. The interval half-width is the right scale: inside it, a placebo estimate is
    indistinguishable from nothing at the precision this analysis has."""
    family = Constant(0.05)
    tight = run_refutations(
        family, data, make_spec(), result_of(0.05, half_width=0.01), DECLARATION, seed=1
    )
    wide = run_refutations(
        family, data, make_spec(), result_of(0.05, half_width=0.50), DECLARATION, seed=1
    )
    assert next(f for f in tight.findings if f.test_id == "placebo_treatment").passed is False
    assert next(f for f in wide.findings if f.test_id == "placebo_treatment").passed is True


def test_the_placebo_test_refits_once_per_draw(data) -> None:
    family = Constant(0.0)
    run_refutations(family, data, make_spec(), result_of(0.0), DECLARATION, seed=1, placebo_draws=4)
    # Four placebo draws, one random-common-cause fit, three subset fits.
    assert family.calls == 8


# ---- the two stability tests ----


def test_a_noise_covariate_must_not_move_the_estimate(data) -> None:
    family = Honest()
    # `Honest` ignores the covariates entirely, so adding one cannot move it at all.
    observed = family.estimate(data, make_spec(), seed=0)
    report = run_refutations(family, data, make_spec(), observed, DECLARATION, seed=1)
    noise = next(f for f in report.findings if f.test_id == "random_common_cause")
    assert noise.passed is True
    assert float(noise.evidence["shift"]) == pytest.approx(0.0)


def test_the_noise_column_reaches_the_covariate_set(data) -> None:
    """A column in neither set would be ignored by construction and the test would pass
    without testing anything."""
    seen: list[list[str]] = []

    class Recording:
        def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
            del seed
            entry = spec.fields["effect_modifiers"].value
            seen.append([str(name) for name in entry])  # type: ignore[union-attr]
            assert all(name in data.columns for name in seen[-1])
            return result_of(0.0)

    run_refutations(Recording(), data, make_spec(), result_of(0.0), DECLARATION, seed=1)
    assert any("causpec_random_common_cause" in names for names in seen)


def test_subset_stability_widens_its_tolerance_for_the_smaller_sample(data) -> None:
    """A half-sample estimate is noisier than the full one. Comparing it against the full
    sample's interval without that correction would fail a sound estimator."""
    report = run_refutations(
        Constant(0.0), data, make_spec(), result_of(0.0, half_width=0.02), DECLARATION, seed=1
    )
    subset = next(f for f in report.findings if f.test_id == "subset_stability")
    assert float(subset.evidence["tolerance"]) > 0.02


def test_an_unstable_estimate_fails_subset_stability(data) -> None:
    FULL_SIZE = len(data)

    class Erratic:
        def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
            del spec
            return result_of(0.0 if len(data) == FULL_SIZE else 5.0)

    report = run_refutations(
        Erratic(), data, make_spec(), result_of(0.0, half_width=0.02), DECLARATION, seed=1
    )
    subset = next(f for f in report.findings if f.test_id == "subset_stability")
    assert subset.passed is False
    assert "less uncertainty than the data contains" in subset.interpretation


# ---- what it says when it cannot run ----


def test_a_family_declaring_no_primary_address_is_not_silently_skipped(data) -> None:
    report = run_refutations(Honest(), data, make_spec(), result_of(0.0), {}, seed=1)
    assert report.findings == []
    assert "not evidence that the estimate is stable" in report.skipped_because


def test_a_declared_address_the_run_did_not_produce_says_so(data) -> None:
    declaration = {"sensitivity": {"primary_address": "res:primary.nonexistent"}}
    report = run_refutations(Honest(), data, make_spec(), result_of(0.0), declaration, seed=1)
    assert "did not produce" in report.skipped_because


def test_a_missing_treatment_column_does_not_crash_the_placebo_test(data) -> None:
    spec = Spec(question="q", family="hte_backdoor", fields={"outcome": confirmed("death")})
    report = run_refutations(Constant(0.0), data, spec, result_of(0.0), DECLARATION, seed=1)
    placebo = next(f for f in report.findings if f.test_id == "placebo_treatment")
    assert placebo.evidence["assessed"] == "no"
    assert "absence is not evidence" in placebo.interpretation


def test_the_findings_become_addresses(data) -> None:
    report = run_refutations(Constant(0.0), data, make_spec(), result_of(0.0), DECLARATION, seed=1)
    addresses = report.addresses()
    assert addresses["res:refute.placebo_treatment.passed"] == "yes"
    assert addresses["res:refute.n_tests"] == 3
    assert addresses["res:refute.n_failed"] == 0

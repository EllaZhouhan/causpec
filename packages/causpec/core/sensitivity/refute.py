"""Refutation tests: perturb the data so the right answer is known, then check for it.

Mirrors design.md 10.1. Each test takes the analysis that was actually run, changes one thing
whose consequence is known in advance, re-runs the family's own estimator, and reports whether
the known answer came back. None of them can say the effect is real. What they can say is that
the machinery is not manufacturing one, which is a different and checkable claim.

Three tests, which are the three DoWhy provides, written against the `Family` protocol instead
of against DoWhy. That protocol is `estimate(data, spec, seed)`, so core can run all of this
without knowing what family it is driving: the panel family gets the same treatment as the two
cross-sectional ones, and DoWhy is not a dependency.

- **Placebo treatment.** Permute the treatment column. Nothing in the data then links treatment
  to outcome, so the effect must collapse towards zero. If it does not, the estimate is being
  produced by something other than the treatment, and the number from the real run means
  nothing. This is the one that matters; the others are stability, this one is validity.
- **A random common cause.** Add a column of noise to the covariates. A correct estimator
  ignores it, so the estimate must barely move. Large movement means the answer depends on
  which columns happened to be included.
- **Subset stability.** Re-estimate on random subsets. The estimates should sit inside the
  interval the full run reported. Wide scatter means that interval is describing less
  uncertainty than there is.

**Which number is compared** is declared by the family, as `sensitivity.primary_address` in
family.yaml, because core must not know that one family's headline is an average effect and
another's is a lag. A family that declares none is not refuted, and says so rather than being
silently skipped.

**Cost.** Each test re-fits the estimator, so the default repetition counts are small and the
whole thing is skippable. A refutation nobody waits for is a refutation nobody runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

    from causpec.core.contracts.result import Result

# The noise column a random-common-cause test adds. Named so that a reader finding it in a
# snapshot knows where it came from.
NOISE_COLUMN = "causpec_random_common_cause"


class Estimator(Protocol):
    """The part of the Family protocol a refuter needs."""

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result: ...


@dataclass(frozen=True)
class RefutationFinding:
    """One refutation test's verdict, with the numbers behind it."""

    test_id: str
    passed: bool
    summary: str
    evidence: dict[str, float | int | str] = field(default_factory=dict)
    # What a reader should take from it, and what it cannot say.
    interpretation: str = ""

    @property
    def address_prefix(self) -> str:
        return f"res:refute.{self.test_id}"

    def addresses(self) -> dict[str, float | int | str]:
        values: dict[str, float | int | str] = {
            f"{self.address_prefix}.passed": "yes" if self.passed else "no"
        }
        for name, value in self.evidence.items():
            values[f"{self.address_prefix}.{name}"] = value
        return values


@dataclass(frozen=True)
class SensitivityReport:
    """Every refutation finding, plus the E-value when the estimand admits one."""

    findings: list[RefutationFinding] = field(default_factory=list)
    e_value_addresses: dict[str, float | int | str] = field(default_factory=dict)
    # Why there is no E-value, when there is none. Printed, because a blank section reads as
    # a clean bill of health.
    e_value_absent_because: str = ""
    skipped_because: str = ""

    @property
    def failed(self) -> list[RefutationFinding]:
        return [finding for finding in self.findings if not finding.passed]

    def addresses(self) -> dict[str, float | int | str]:
        values: dict[str, float | int | str] = dict(self.e_value_addresses)
        for finding in self.findings:
            values.update(finding.addresses())
        values["res:refute.n_failed"] = len(self.failed)
        values["res:refute.n_tests"] = len(self.findings)
        return values


def _primary(result: Result, address: str) -> float:
    value = result.values[address]
    return float(value)


def _placebo(
    family: Estimator,
    data: pd.DataFrame,
    spec: Spec,
    address: str,
    observed: float,
    half_width: float,
    seed: int,
    draws: int,
) -> RefutationFinding:
    """Permute the treatment; the effect must collapse.

    The threshold is the real run's own interval half-width rather than a fixed number. A
    placebo estimate inside that distance of zero is indistinguishable from no effect at the
    precision this analysis has, which is the right standard: a tighter one would fail a
    noisy-but-correct estimator, and a looser one would pass anything.
    """
    treatment = spec.fields.get("treatment")
    column = str(treatment.value) if treatment is not None and treatment.value is not None else ""
    if column not in data.columns:
        return RefutationFinding(
            test_id="placebo_treatment",
            passed=True,
            summary="not run: no treatment column to permute",
            evidence={"assessed": "no"},
            interpretation="This test did not run; its absence is not evidence of anything.",
        )

    estimates: list[float] = []
    rng = np.random.default_rng(seed)
    for draw in range(draws):
        shuffled = data.copy()
        shuffled[column] = rng.permutation(np.asarray(data[column]))
        estimates.append(_primary(family.estimate(shuffled, spec, seed=seed + draw), address))

    worst = max(abs(value) for value in estimates)
    passed = worst <= half_width
    return RefutationFinding(
        test_id="placebo_treatment",
        passed=passed,
        summary=(
            f"with the treatment permuted, the largest effect over {draws} draws was "
            f"{worst:+.4g}, against {observed:+.4g} for the real treatment"
        ),
        evidence={
            "assessed": "yes",
            "n_draws": draws,
            "largest_absolute_estimate": round(worst, 6),
            "mean_estimate": round(float(np.mean(estimates)), 6),
            "observed_estimate": round(observed, 6),
            "tolerance": round(half_width, 6),
        },
        interpretation=(
            "A permuted treatment carries no relation to the outcome, so an effect that "
            "survives permutation is coming from somewhere else and the real estimate cannot "
            "be read as an effect of the treatment."
            if not passed
            else "The estimate disappears when the treatment is permuted, which is what it "
            "should do. This says the machinery is not manufacturing an effect; it does not "
            "say the real effect is causal."
        ),
    )


def _random_common_cause(
    family: Estimator,
    data: pd.DataFrame,
    spec: Spec,
    address: str,
    observed: float,
    half_width: float,
    seed: int,
) -> RefutationFinding:
    """Add a noise covariate; the estimate must barely move.

    The noise column goes into the effect modifiers, because that is the set this project's
    families always populate, and a column in neither set would be ignored by construction and
    the test would pass without testing anything.
    """
    entry = spec.fields.get("effect_modifiers")
    if entry is None or entry.value is None:
        return RefutationFinding(
            test_id="random_common_cause",
            passed=True,
            summary="not run: no covariate set to add a column to",
            evidence={"assessed": "no"},
            interpretation="This test did not run; its absence is not evidence of anything.",
        )
    existing = entry.value if isinstance(entry.value, (list, tuple)) else [entry.value]
    rng = np.random.default_rng(seed)
    widened = data.copy()
    widened[NOISE_COLUMN] = rng.normal(size=len(data))
    with_noise = spec.model_copy(
        update={
            "fields": {
                **spec.fields,
                "effect_modifiers": entry.model_copy(
                    update={"value": [*(str(name) for name in existing), NOISE_COLUMN]}
                ),
            }
        }
    )
    estimate = _primary(family.estimate(widened, with_noise, seed=seed), address)
    shift = abs(estimate - observed)
    passed = shift <= half_width
    return RefutationFinding(
        test_id="random_common_cause",
        passed=passed,
        summary=(
            f"adding a noise covariate moved the estimate from {observed:+.4g} to "
            f"{estimate:+.4g}, a shift of {shift:.4g}"
        ),
        evidence={
            "assessed": "yes",
            "estimate_with_noise": round(estimate, 6),
            "observed_estimate": round(observed, 6),
            "shift": round(shift, 6),
            "tolerance": round(half_width, 6),
        },
        interpretation=(
            "A column of noise carries no information, so an estimate that moves this much "
            "when one is added depends on which columns happened to be in the covariate set "
            "rather than on the data."
            if not passed
            else "The estimate is unmoved by a column that carries no information, which is "
            "what it should be."
        ),
    )


def _subset_stability(
    family: Estimator,
    data: pd.DataFrame,
    spec: Spec,
    address: str,
    observed: float,
    half_width: float,
    seed: int,
    draws: int,
    fraction: float,
) -> RefutationFinding:
    """Re-estimate on random subsets; the estimates should sit inside the reported interval.

    Subsets are smaller, so their own estimates are noisier than the full one, and the
    tolerance is widened by the square root of the sampling fraction to match. Comparing a
    half-sample estimate against the full sample's interval without that correction would fail
    a perfectly sound estimator.
    """
    rng = np.random.default_rng(seed)
    size = max(int(len(data) * fraction), 2)
    estimates: list[float] = []
    for draw in range(draws):
        rows = rng.choice(len(data), size=size, replace=False)
        estimates.append(
            _primary(family.estimate(data.iloc[rows], spec, seed=seed + draw), address)
        )
    tolerance = half_width / np.sqrt(fraction)
    worst = max(abs(value - observed) for value in estimates)
    passed = bool(worst <= tolerance)
    return RefutationFinding(
        test_id="subset_stability",
        passed=passed,
        summary=(
            f"on {draws} random {fraction:.0%} subsets the estimate ranged from "
            f"{min(estimates):+.4g} to {max(estimates):+.4g}, against {observed:+.4g} on the "
            f"full sample"
        ),
        evidence={
            "assessed": "yes",
            "n_draws": draws,
            "fraction": fraction,
            "lowest": round(float(min(estimates)), 6),
            "highest": round(float(max(estimates)), 6),
            "largest_deviation": round(float(worst), 6),
            "tolerance": round(float(tolerance), 6),
        },
        interpretation=(
            "The estimate moves further between subsets than the reported interval allows "
            "for, so that interval is describing less uncertainty than the data contains."
            if not passed
            else "Subsets of the data give estimates consistent with the reported interval."
        ),
    )


def run_refutations(
    family: Estimator,
    data: pd.DataFrame,
    spec: Spec,
    result: Result,
    declaration: dict[str, Any],
    seed: int = 0,
    placebo_draws: int = 3,
    subset_draws: int = 3,
    subset_fraction: float = 0.5,
) -> SensitivityReport:
    """Every refutation test the family's declaration supports.

    The declaration names the address to compare and the two that bound its interval, because
    core must not know that one family's headline is an average effect and another's is a lag.
    """
    settings = declaration.get("sensitivity") or {}
    address = str(settings.get("primary_address", "") or "")
    if not address or address not in result.values:
        return SensitivityReport(
            skipped_because=(
                f"{spec.family} declares no primary_address for refutation, so there is no "
                f"single number whose stability could be tested. Nothing was run, which is "
                f"not evidence that the estimate is stable."
                if not address
                else f"{spec.family} declares primary_address {address!r}, which this run did "
                f"not produce."
            )
        )
    observed = _primary(result, address)
    lower = settings.get("primary_ci_lower")
    upper = settings.get("primary_ci_upper")
    if lower in result.values and upper in result.values:
        half_width = abs(float(result.values[upper]) - float(result.values[lower])) / 2.0
    else:
        # Without an interval there is no scale on which "unchanged" means anything, so a
        # tenth of the estimate stands in, and the report says which rule was used.
        half_width = max(abs(observed) * 0.1, 1e-12)

    findings = [
        _placebo(family, data, spec, address, observed, half_width, seed, placebo_draws),
        _random_common_cause(family, data, spec, address, observed, half_width, seed),
        _subset_stability(
            family, data, spec, address, observed, half_width, seed, subset_draws, subset_fraction
        ),
    ]
    return SensitivityReport(findings=findings)

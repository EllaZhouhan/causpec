"""The E-value: how strong an unmeasured confounder would have to be.

VanderWeele and Ding (2017), "Sensitivity Analysis in Observational Research: Introducing the
E-Value", Annals of Internal Medicine 167(4):268-274.

Written here rather than taken from a package, under the rule of ADR-0004: a statistic earns
a dependency when it carries something substantial enough to get wrong, and this one is a
closed form with a published numerical example to check against. The whole of it is

    E = RR + sqrt(RR * (RR - 1))        for RR >= 1

with RR replaced by 1/RR when the estimate is protective, so the answer is always on one
scale and always at least 1.

**What it means.** An E-value of 7.26 says an unmeasured confounder would have to be
associated with both the treatment and the outcome by a risk ratio of 7.26 each, above and
beyond the measured covariates, to explain the observed association away. Whether any
plausible confounder is that strong is a question for someone who knows the field; the number
turns "could confounding explain this?" into "could a confounder this strong exist?", which is
answerable.

**Two numbers, and the second is the one to read.** The E-value for the point estimate says
what it would take to move the effect to nothing. The E-value for the confidence limit nearest
the null says what it would take to make the result compatible with nothing, which is the
weaker and more honest claim. A paper reporting only the first is reporting the flattering one.

**The scale.** The E-value is defined on a risk ratio. This project's binary-outcome families
estimate a risk difference, so the ratio is formed from the two arm risks, which the estimators
already report: RR = (p0 + ATE) / p0. That is exact given those quantities rather than one of
the paper's approximate conversions from an odds or hazard ratio. For a continuous outcome
there is no risk ratio and no E-value, and `e_value_from_risks` says so rather than inventing
a standardised effect size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class EValueUndefined(Exception):
    """The E-value does not apply to this estimate, with the reason."""


@dataclass(frozen=True)
class EValue:
    """An E-value for a point estimate, and for the confidence limit nearest the null."""

    risk_ratio: float
    point: float
    limit: float | None
    limit_risk_ratio: float | None
    # True when the interval already includes the null, where the E-value for the limit is 1:
    # no confounding at all is needed to make the result compatible with no effect.
    interval_includes_null: bool

    def addresses(self) -> dict[str, float | int | str]:
        """Addresses the report can cite, so the prose cannot restate them differently."""
        values: dict[str, float | int | str] = {
            "res:sensitivity.risk_ratio": round(self.risk_ratio, 4),
            "res:sensitivity.e_value": round(self.point, 4),
        }
        if self.limit is not None:
            values["res:sensitivity.e_value_limit"] = round(self.limit, 4)
        if self.limit_risk_ratio is not None:
            values["res:sensitivity.limit_risk_ratio"] = round(self.limit_risk_ratio, 4)
        values["res:sensitivity.interval_includes_null"] = (
            "yes" if self.interval_includes_null else "no"
        )
        return values


def e_value(risk_ratio: float) -> float:
    """The E-value for one risk ratio.

    A protective ratio is inverted first, because a halving and a doubling take the same
    strength of confounder to produce and reporting them differently would be an artefact of
    which arm was called the treatment.
    """
    if risk_ratio <= 0 or not math.isfinite(risk_ratio):
        raise EValueUndefined(
            f"a risk ratio of {risk_ratio} is not a ratio of two risks; the E-value is "
            f"defined for a positive, finite ratio"
        )
    ratio = risk_ratio if risk_ratio >= 1 else 1.0 / risk_ratio
    return ratio + math.sqrt(ratio * (ratio - 1.0))


def e_value_from_risks(
    control_risk: float,
    effect: float,
    ci_lower: float | None = None,
    ci_upper: float | None = None,
) -> EValue:
    """An E-value from a risk difference and the control-arm risk.

    `effect` is the risk difference, which is what these families estimate, and the ratio is
    formed from the two arm risks rather than through one of the paper's approximate
    conversions. The limit used is whichever confidence bound is nearer the null, since the
    question "what would make this compatible with nothing" is about the edge of the interval
    closest to nothing.
    """
    if not 0.0 < control_risk < 1.0:
        raise EValueUndefined(
            f"the control-arm risk is {control_risk:.4g}, so there is no risk ratio to form. "
            f"An E-value needs a binary outcome with events in the control arm."
        )
    treated_risk = control_risk + effect
    if not 0.0 < treated_risk < 1.0:
        raise EValueUndefined(
            f"the estimated effect implies a treated-arm risk of {treated_risk:.4g}, which is "
            f"not a probability. The E-value would describe an impossible comparison."
        )
    ratio = treated_risk / control_risk

    # The bound nearer the null, on the risk-difference scale, where the null is zero.
    limit_effect: float | None = None
    if ci_lower is not None and ci_upper is not None:
        if ci_lower <= 0.0 <= ci_upper:
            limit_effect = 0.0
        else:
            limit_effect = ci_lower if abs(ci_lower) < abs(ci_upper) else ci_upper

    limit_ratio: float | None = None
    limit: float | None = None
    includes_null = limit_effect == 0.0
    if limit_effect is not None:
        limit_risk = control_risk + limit_effect
        if 0.0 < limit_risk < 1.0:
            limit_ratio = limit_risk / control_risk
            limit = e_value(limit_ratio)

    return EValue(
        risk_ratio=ratio,
        point=e_value(ratio),
        limit=limit,
        limit_risk_ratio=limit_ratio,
        interval_includes_null=includes_null,
    )

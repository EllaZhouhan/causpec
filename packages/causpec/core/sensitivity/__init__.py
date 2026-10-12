"""Sensitivity and refutation: what the estimate would take to be wrong.

Mirrors design.md 10.1 and plan.md Phase 1 task 9. Two different things, and the division
matters because they answer questions of different kinds.

**The E-value** speaks to the assumption no diagnostic can check. Unconfoundedness is
`untestable`: no amount of data verifies it, so the claim level caps what code may say about
it. What the E-value adds is a quantity, how strong an unmeasured confounder would have to be
to explain the estimate away, which turns an argument about whether confounding remains into
an argument about how much. Closed form, no dependency, verified against a published example.

**The refuters** speak to the pipeline. Each perturbs the data in a way whose correct answer
is known in advance, re-runs the family's own estimator, and checks it gets that answer. They
cannot say the effect is real; they can say the machinery is not inventing one.

Both are run after estimation, so neither is a gate: the gate decides whether to estimate at
all. They feed the claim level and the report instead, which is where design.md 10.2 puts
them, since a failed refutation means causal wording is not available however clean the data
was.

What is deliberately not here: DoubleML's `sensitivity_analysis`, which plan.md named. It
bounds omitted-variable bias for a DML estimator, and this project's cross-sectional families
use EconML's causal forest rather than DoubleML, so using it would mean a second estimator
fitted to the same data and a second set of numbers to reconcile. DoWhy's refuters were also
named; the three implemented here are the three DoWhy provides, written against the Family
protocol in forty lines, which means they work for every family including the panel one
without DoWhy being a dependency at all.
"""

from causpec.core.sensitivity.evalue import EValue, e_value, e_value_from_risks
from causpec.core.sensitivity.refute import (
    RefutationFinding,
    SensitivityReport,
    run_refutations,
)

__all__ = [
    "EValue",
    "RefutationFinding",
    "SensitivityReport",
    "e_value",
    "e_value_from_risks",
    "run_refutations",
]

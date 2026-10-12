"""Estimation adapter for hte_backdoor: EconML CausalForestDML.

Reuses econml.dml.CausalForestDML (MIT).

One important difference from hte_iv: this class supports ``blb`` (bootstrap of
little bags, Athey-Tibshirani-Wager), so both the CATE and the ATE intervals come
from the forest's own variance estimate with **no refitting**. hte_iv's
NonParamDMLIV can only bootstrap, because its final model is an arbitrary regressor;
CausalForestDML's final model is the forest itself.

The identification strategy is backdoor adjustment, so results here rest on
unconfoundedness, an untestable assumption. All the code can do is check overlap
(see checks.py); it cannot establish the absence of confounding. The claim-level
ceiling is therefore suggestive (design.md 10.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from econml.dml import CausalForestDML

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.grouping import group_masks
from causpec.core.registry import register

if TYPE_CHECKING:
    import pandas as pd


def _column_names(spec: Spec, field: str) -> list[str]:
    """Read a list-of-column-names field from the spec; missing means empty."""
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _scalar(value: Any) -> float:
    return float(np.ravel(value)[0])


def _importance(estimator: Any, columns: list[str]) -> dict[str, float | int | str]:
    """Which covariates the forest split on to separate treatment effects, ranked.

    This is step two of the staged answer: the average effect first, then where the effect
    varies, then the groups the user asks for along those dimensions. Without it, choosing a
    dimension to report means guessing, and the per-patient effect cloud the forest produces
    names nobody.

    **What it is not.** A ranking of how strongly each covariate modifies the effect. It
    counts the splits a forest happened to make, so it favours continuous and high-cardinality
    columns over binary ones whatever their true importance, and a column correlated with a
    real modifier inherits some of its rank. It is a shortlist to choose from, which is
    exactly how the workflow uses it.
    """
    raw = getattr(estimator, "feature_importances_", None)
    if raw is None:
        return {}
    weights = np.ravel(np.asarray(raw, dtype=float))
    if weights.size != len(columns):
        # A shape this function cannot interpret is better reported as absent than attached to
        # the wrong column names.
        return {}
    order = np.argsort(-weights)
    values: dict[str, float | int | str] = {"res:importance.last_rank": int(len(order) - 1)}
    for rank, index in enumerate(order):
        values[f"res:importance.rank{rank}.variable"] = columns[int(index)]
        values[f"res:importance.rank{rank}.importance"] = float(weights[int(index)])
    return values


def _group_effects(
    estimator: Any, data: pd.DataFrame, spec: Spec, x: np.ndarray
) -> dict[str, float | int | str]:
    """The average effect within each declared group, with its own interval.

    `ate(X=subset)` averages the fitted effect over the patients in the group and
    `ate_interval` gives that average an interval, so each row is a statement about a named
    set of patients rather than about a cloud.

    Every group of every declared grouping is emitted, flattened into one numbered sequence so
    the report's declarative table mechanism can render a row count it learns from an address.
    Flattening is also what makes a grouping chosen after seeing the importance ranking safe to
    report: the striking group cannot appear without the dull ones beside it.
    """
    if not spec.effect_groups:
        return {}
    values: dict[str, float | int | str] = {}
    row = 0
    for group in spec.effect_groups:
        for label, mask in group_masks(data, group):
            prefix = f"res:gate.row{row}"
            values[f"{prefix}.variable"] = group.variable
            values[f"{prefix}.label"] = label
            values[f"{prefix}.n"] = int(mask.sum())
            values[f"{prefix}.chosen_from"] = group.chosen_from
            if mask.sum() == 0:
                # Emitted rather than skipped: an empty group means the cut fell outside the
                # data, which the user should see as a row of zeros rather than as a gap.
                values[f"{prefix}.effect"] = float("nan")
                values[f"{prefix}.ci_lower"] = float("nan")
                values[f"{prefix}.ci_upper"] = float("nan")
                row += 1
                continue
            subset = x[mask]
            lower, upper = estimator.ate_interval(X=subset, alpha=0.05)
            values[f"{prefix}.effect"] = _scalar(estimator.ate(X=subset))
            values[f"{prefix}.ci_lower"] = _scalar(lower)
            values[f"{prefix}.ci_upper"] = _scalar(upper)
            row += 1
    values["res:gate.last_row"] = int(row - 1)
    values["res:gate.n_groupings"] = len(spec.effect_groups)
    values["res:gate.any_chosen_from_importance"] = (
        "yes"
        if any(group.chosen_from == "importance_ranking" for group in spec.effect_groups)
        else "no"
    )
    return values


def _distribution(prefix: str, values: np.ndarray) -> dict[str, float]:
    q = np.percentile(values, [5, 25, 50, 75, 95])
    return {
        f"{prefix}.mean": float(np.mean(values)),
        f"{prefix}.std": float(np.std(values)),
        f"{prefix}.min": float(np.min(values)),
        f"{prefix}.q05": float(q[0]),
        f"{prefix}.q25": float(q[1]),
        f"{prefix}.median": float(q[2]),
        f"{prefix}.q75": float(q[3]),
        f"{prefix}.q95": float(q[4]),
        f"{prefix}.max": float(np.max(values)),
    }


class HteBackdoor:
    """Heterogeneous treatment effects under backdoor adjustment."""

    id = "hte_backdoor"

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        """Overlap, SMD and feasibility checks; thresholds from family.yaml."""
        from causpec.core.registry import load_declaration
        from causpec.families.hte_backdoor.checks import check_backdoor

        return check_backdoor(data, spec, load_declaration(self.id).get("checks", {}))

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        treatment = _column_names(spec, "treatment")[0]
        outcome = _column_names(spec, "outcome")[0]
        effect_modifiers = _column_names(spec, "effect_modifiers")
        adjustment_set = _column_names(spec, "adjustment_set")

        if not effect_modifiers:
            raise ValueError(
                "hte_backdoor requires spec.effect_modifiers (the CATE covariate set X)"
            )

        y = data[outcome].to_numpy().ravel().astype(int)
        t = data[treatment].to_numpy().ravel().astype(int)
        x = data[effect_modifiers].astype(float).to_numpy()
        w = data[adjustment_set].astype(float).to_numpy() if adjustment_set else None

        # subforest_size determines how blb groups; n_estimators must divide evenly
        # (the same constraint as in hte_iv).
        subforest_size = int(spec.param("subforest_size", 4))
        n_estimators = int(spec.param("n_estimators", 500))
        if n_estimators % subforest_size:
            raise ValueError(
                f"n_estimators ({n_estimators}) must be divisible by subforest_size "
                f"({subforest_size}), blb's variance estimate groups by sub-forest. "
                f"Use {n_estimators - n_estimators % subforest_size} or "
                f"{n_estimators + subforest_size - n_estimators % subforest_size}."
            )

        estimator = CausalForestDML(
            model_y="auto",
            model_t="auto",
            discrete_treatment=True,
            discrete_outcome=True,
            cv=spec.param("cv", 5),
            n_estimators=n_estimators,
            min_samples_leaf=spec.param("min_samples_leaf", 30),
            max_depth=spec.param("max_depth", None),
            honest=True,
            subforest_size=subforest_size,
            n_jobs=spec.param("model_n_jobs", 1),
            random_state=seed,
        )
        # blb = bootstrap of little bags: the forest's own variance estimate, computed
        # within one fit. No resampling is needed here; see the module docstring.
        estimator.fit(Y=y, T=t, X=x, W=w, inference="blb")

        cate = np.ravel(estimator.effect(X=x, T0=0, T1=1))
        interval = estimator.effect_interval(X=x, T0=0, T1=1, alpha=0.05)
        lower, upper = np.ravel(interval[0]), np.ravel(interval[1])
        ate_interval = estimator.ate_interval(X=x, alpha=0.05)

        values: dict[str, float | int | str] = {
            "res:primary.ate": _scalar(estimator.ate(X=x)),
            "res:primary.ate_ci_lower": _scalar(ate_interval[0]),
            "res:primary.ate_ci_upper": _scalar(ate_interval[1]),
            "res:cate.ci_method": "blb",
            "res:primary.ate_ci_method": "blb",
            "res:cate.n_significant_benefit": int(np.sum(upper < 0)),
            "res:cate.n_significant_harm": int(np.sum(lower > 0)),
            "res:cate.ci_width_median": float(np.median(upper - lower)),
            "res:sample.n": int(len(data)),
            "res:sample.n_treated": int(t.sum()),
            "res:sample.n_control": int(len(t) - t.sum()),
            "res:sample.treatment_rate": float(t.mean()),
            "res:sample.outcome_rate": float(y.mean()),
            # Per arm as well as overall, because the E-value needs a risk ratio and the
            # ratio is formed from these two rather than through one of the paper's
            # approximate conversions from a risk difference.
            "res:sample.outcome_rate_treated": float(y[t == 1].mean()) if (t == 1).any() else 0.0,
            "res:sample.outcome_rate_control": float(y[t == 0].mean()) if (t == 0).any() else 0.0,
            "res:design.n_effect_modifiers": len(effect_modifiers),
            "res:design.n_adjustment_covariates": len(adjustment_set),
            "res:estimation.estimator": "causal_forest_dml",
            "res:estimation.n_estimators": n_estimators,
        }
        values.update(_distribution("res:cate", cate))
        values.update(_importance(estimator, effect_modifiers))
        values.update(_group_effects(estimator, data, spec, x))
        return Result(family=self.id, seed=seed, values=values)


register(HteBackdoor())

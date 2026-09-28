"""The lag profile: cross-fitted sequential peeling with continuation weights.

Ports the author's estimator (Zhou 2026, Algorithm 1) behind CauSpec's family interface.
family.yaml is the declaration this follows; read it first, in particular the two notes
about Stage-1 weighting and about which nuisance needs a flexible learner.

For each lag kappa = 0 ... K, in that order:

**Stage 0, the continuation weights.** A classifier is cross-fitted by unit on the pooled
one-step records ``[state, treatment] -> continued``, giving lambda-hat, the probability
that a trajectory is still active one period on. The weight of a lag-kappa window is the
product of one reciprocal per continuation decision from the anchor period to the outcome
period, ``prod_{s=a}^{t} 1 / lambda-hat(X[s], A[s])``. At lag 0 no weight is applied: with
only the current shock left in the residual, one-step independence is enough, which is
what the paper's special case establishes.

**The peeled outcome.** The outcome of a period carries the effects of several earlier
treatment periods at once. Subtracting the already-estimated shorter lags leaves one
partially linear problem::

    peeled = Y[t] - sum over j < kappa of theta_j(X[t-j]) * A[t-j]

With a constant profile ``theta_j(x) = theta_j``. With a varying one the lower-lag effect
is evaluated at the state of **its own** treatment period, ``X[t-j]``, not at the anchor:
structurally ``theta_j`` is what one period of treatment in that state propagates, so the
state that matters is the one where that treatment was given. The author's earlier panel
code evaluated every lower lag at the anchor state; this is the corrected form, and it
matters as soon as the profile varies.

**Stage 1, residualisation.** The peeled outcome and the anchor treatment are regressed on
the anchor state, cross-fitted by unit, **carrying the continuation weights**. The
nuisances are anchor-conditional; fitted unweighted they target the survivor-conditional
mean, which is a different function. On the author's own design that error is worth about
+0.20 at lags 1 and 2, and it once looked harmless because a misspecified continuation
model contributed about -0.19 the other way. Two large errors cancelling is not a correct
estimator, so ``test_dynamic_lag_dml_estimator.py`` pins the weighting.

**Stage 2, the moment.** Constant profile: the weighted ratio of the residual cross-moment
to the residual second moment. Varying profile: a weighted least squares of the residual
outcome on the residual treatment interacted with the modifiers, which is the same moment
projected onto a linear model for theta_kappa(x).

**Stage 3, uncertainty.** A bootstrap that resamples whole units and re-runs every stage,
including the continuation model and all the peeling. Rows inside a trajectory are
dependent and each lag inherits the lower-lag estimates it was peeled with, so the unit is
the only defensible resampling unit. A recursive influence function also gives an analytic
standard error for the constant profile; it treats the fitted continuation model as fixed,
so it omits that model's first-order contribution and is reported alongside, never instead.

**Neither interval is calibrated.** The theory proves consistency of the whole profile and
gives no limiting distribution. Results carry ``res:profile.ci_calibration =
"exploratory"``, which the claim-level decision turns into "no result may be called
significant".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

import numpy as np
from joblib import Parallel, delayed
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LinearRegression

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.registry import register

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

DEFAULT_MAX_LAG = 2
DEFAULT_BOOTSTRAP_SAMPLES = 200
DEFAULT_N_FOLDS = 2
# Chosen without knowledge of the true positivity bound, so it is a fixed constant rather
# than anything read off the data. The author's application uses the same value.
DEFAULT_LAMBDA_FLOOR = 0.05
ESTIMANDS = ("lag_profile", "lag_cate")

_Model = TypeVar("_Model")


def _clone(model: _Model) -> _Model:
    """sklearn's clone returns the union of everything it can clone; keep the type."""
    return cast(_Model, clone(model))


@dataclass(frozen=True)
class Trajectory:
    """One unit's whole recorded history, in period order.

    ``state``, ``treatment`` and ``outcome`` are aligned row by row: row t holds the state
    at the start of period t, the treatment over period t, and the outcome realised after
    that treatment. ``length`` is the number of recorded periods, the paper's T_i.
    """

    unit: Any
    state: np.ndarray
    treatment: np.ndarray
    outcome: np.ndarray
    continuation: np.ndarray | None = None  # true lambda, for the oracle arm in tests

    @property
    def length(self) -> int:
        return len(self.treatment)


def _column_names(spec: Spec, field: str) -> list[str]:
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _one_column(spec: Spec, field: str) -> str:
    names = _column_names(spec, field)
    if not names:
        raise ValueError(f"dynamic_lag_dml requires spec.{field}")
    if len(names) > 1:
        raise ValueError(f"spec.{field} must name one column; got {names}")
    return names[0]


def _field_value(spec: Spec, field: str, default: Any) -> Any:
    entry = spec.fields.get(field)
    return default if entry is None or entry.value is None else entry.value


def to_trajectories(
    data: pd.DataFrame,
    unit: str,
    period: str,
    state: list[str],
    treatment: str,
    outcome: str,
    continuation: str | None = None,
) -> list[Trajectory]:
    """Split a long panel into trajectories, refusing a shape the estimand cannot carry.

    The lag index counts rows, so a gap in the period index silently turns a lag-2 window
    into a lag-3 one. That is not something to impute; it is something to refuse. The
    quality checks report the same problems with a repair suggestion, and this is the
    backstop for a caller that skipped them.
    """
    missing = [c for c in [unit, period, treatment, outcome, *state] if c not in data.columns]
    if missing:
        raise ValueError(f"columns not in the data: {missing}")

    ordered = data.sort_values([unit, period], kind="stable")
    trajectories: list[Trajectory] = []
    for key, group in ordered.groupby(unit, sort=True):
        periods = group[period].to_numpy()
        if len(set(periods.tolist())) != len(periods):
            raise ValueError(f"unit {key!r} has duplicate periods")
        expected = np.arange(len(periods))
        if not np.array_equal(periods.astype(int), expected):
            raise ValueError(
                f"unit {key!r} has periods {periods.tolist()[:6]}...; they must be "
                f"consecutive integers from 0, because the lag index counts rows"
            )
        trajectories.append(
            Trajectory(
                unit=key,
                state=group[state].to_numpy(dtype=float),
                treatment=group[treatment].to_numpy(dtype=float),
                outcome=group[outcome].to_numpy(dtype=float),
                continuation=(group[continuation].to_numpy(dtype=float) if continuation else None),
            )
        )
    return trajectories


@dataclass
class _LagFit:
    """What one lag produced, kept for the influence function and the report."""

    lag: int
    unit_index: np.ndarray
    weight: np.ndarray
    residual_treatment: np.ndarray  # one column per tau <= lag
    score_residual: np.ndarray
    theta: float
    coefficients: np.ndarray | None  # the linear projection, for lag_cate
    j_statistic: float

    @property
    def effective_windows(self) -> float:
        """Kish's effective sample size of the continuation weights.

        How many windows the lag is effectively built from. The weights of this estimator
        are heavy-tailed by construction, so their maximum says little on its own; what
        decides whether a lag is estimated or invented is how many windows carry it.
        """
        total = float(np.sum(self.weight))
        squared = float(np.sum(self.weight**2))
        return total**2 / squared if squared > 0 else 0.0


class DynamicLagDmlFit:
    """One fit of the whole profile. Stateless once fitted."""

    def __init__(
        self,
        max_lag: int = DEFAULT_MAX_LAG,
        heterogeneous: bool = False,
        n_folds: int = DEFAULT_N_FOLDS,
        lambda_floor: float = DEFAULT_LAMBDA_FLOOR,
        seed: int = 0,
        use_weights: bool = True,
        weight_stage1: bool = True,
        oracle_continuation: bool = False,
        continuation_model: Any = None,
        nuisance_model: Any = None,
        modifier_index: np.ndarray | None = None,
    ) -> None:
        self.max_lag = max_lag
        self.heterogeneous = heterogeneous
        self.n_folds = n_folds
        self.lambda_floor = lambda_floor
        self.seed = seed
        # use_weights=False is the declared sensitivity arm, the profile without IPCW.
        # weight_stage1=False exists only so a test can show the weighting matters; it is
        # not reachable from a spec.
        self.use_weights = use_weights
        self.weight_stage1 = weight_stage1
        self.oracle_continuation = oracle_continuation
        self.continuation_model: Any = continuation_model or HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05
        )
        self.nuisance_model: Any = nuisance_model or LinearRegression()
        self.modifier_index = modifier_index

    # ---- Stage 0 ----

    def _continuation(self, trajectories: list[Trajectory], folds: np.ndarray) -> list[np.ndarray]:
        """Cross-fitted one-step continuation probability per unit and period."""
        self.continuation_min_ = float("nan")
        self.continuation_clipped_share_ = float("nan")
        if not self.use_weights:
            return [np.ones(t.length) for t in trajectories]
        if self.oracle_continuation:
            return [
                np.clip(np.asarray(t.continuation, dtype=float), self.lambda_floor, 1 - 1e-9)
                for t in trajectories
            ]

        features: list[np.ndarray] = []
        labels: list[float] = []
        owner: list[int] = []
        for index, trajectory in enumerate(trajectories):
            for period in range(trajectory.length):
                features.append(np.append(trajectory.state[period], trajectory.treatment[period]))
                labels.append(1.0 if period + 1 < trajectory.length else 0.0)
                owner.append(index)
        design = np.asarray(features, dtype=float)
        label = np.asarray(labels, dtype=float)
        # Explicitly integer: it indexes the fold array, and a float index is not indexing.
        unit_of_row = np.asarray(owner, dtype=int)

        fitted = np.ones(len(label))
        for fold in range(self.n_folds):
            train = folds[unit_of_row] != fold
            test = folds[unit_of_row] == fold
            if not train.any() or not test.any():
                continue
            fitted[test] = self._predict_continuation(design[train], label[train], design[test])
        # Before clipping, so the diagnostic says what the model actually predicted. A
        # floor that has to bind often is the data saying continuation is near impossible
        # somewhere, which caps the weight and pulls the estimate towards the unweighted one.
        self.continuation_min_ = float(fitted.min())
        self.continuation_clipped_share_ = float(np.mean(fitted <= self.lambda_floor))
        fitted = np.clip(fitted, self.lambda_floor, 1 - 1e-9)

        out, cursor = [], 0
        for trajectory in trajectories:
            out.append(fitted[cursor : cursor + trajectory.length])
            cursor += trajectory.length
        return out

    def _predict_continuation(
        self, train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray
    ) -> np.ndarray:
        classes = np.unique(train_y)
        if classes.size < 2:
            # A fold where every trajectory continued, or none did. The constant is the
            # honest prediction; the floor keeps the weight finite.
            return np.full(len(test_x), float(classes[0]))
        model = _clone(self.continuation_model)
        model.fit(train_x, train_y)
        probability = model.predict_proba(test_x)
        return probability[:, list(model.classes_).index(1)]

    # ---- Stage 1 ----

    def _residualise(
        self,
        target: np.ndarray,
        design: np.ndarray,
        unit_index: np.ndarray,
        folds: np.ndarray,
        weight: np.ndarray,
    ) -> np.ndarray:
        """Cross-fitted residual of ``target`` on the anchor state, weighted by IPCW."""
        residual = target.astype(float).copy()
        for fold in range(self.n_folds):
            train = folds[unit_index] != fold
            test = folds[unit_index] == fold
            if not train.any() or not test.any():
                continue
            prediction = self._fit_predict(
                design[train],
                target[train],
                design[test],
                weight[train] if self.weight_stage1 else None,
            )
            residual[test] = target[test] - prediction
        return residual

    def _fit_predict(
        self,
        train_x: np.ndarray,
        train_y: np.ndarray,
        test_x: np.ndarray,
        weight: np.ndarray | None,
    ) -> np.ndarray:
        if np.std(train_y) < 1e-12:
            mean = np.average(train_y, weights=weight) if weight is not None else train_y.mean()
            return np.full(len(test_x), float(mean))
        model = _clone(self.nuisance_model)
        try:
            model.fit(train_x, train_y, sample_weight=weight)
        except TypeError:
            model.fit(train_x, train_y)
        return np.asarray(model.predict(test_x)).ravel()

    # ---- the profile ----

    def fit(self, trajectories: list[Trajectory]) -> DynamicLagDmlFit:
        rng = np.random.default_rng(self.seed)
        n_units = len(trajectories)
        folds = rng.integers(0, self.n_folds, size=n_units)
        continuation = self._continuation(trajectories, folds)

        self.n_units_ = n_units
        self.theta_ = np.full(self.max_lag + 1, np.nan)
        self.coefficients_: list[np.ndarray | None] = [None] * (self.max_lag + 1)
        self.fits_: list[_LagFit] = []

        for lag in range(self.max_lag + 1):
            rows = self._build_rows(trajectories, continuation, lag)
            if rows is None:
                continue
            self._fit_one_lag(rows, folds, lag)

        self.standard_error_ = self._influence_standard_errors()
        return self

    def _build_rows(
        self, trajectories: list[Trajectory], continuation: list[np.ndarray], lag: int
    ) -> dict[str, np.ndarray] | None:
        """Every usable lag-``lag`` window, with its weight, anchor state and peeled outcome.

        A window is usable when the outcome period is recorded **and** the trajectory was
        still active one period after it, which is the convention the paper's analysis set
        uses: the outcome of period t is realised before period t+1, so observing it means
        surviving that step, and the weight includes it.
        """
        unit_index: list[int] = []
        weights: list[float] = []
        peeled: list[float] = []
        anchors: list[np.ndarray] = []
        treatments: list[list[float]] = []
        for index, trajectory in enumerate(trajectories):
            last_usable = trajectory.length - 1  # t <= length - 2
            for outcome_period in range(lag, last_usable):
                anchor = outcome_period - lag
                if self.use_weights and lag > 0:
                    factors = continuation[index][anchor : outcome_period + 1]
                    weight = float(np.prod(1.0 / factors))
                elif self.use_weights:
                    # Lag 0 needs no weight: one-step independence is enough there.
                    weight = 1.0
                else:
                    weight = 1.0
                value = float(trajectory.outcome[outcome_period])
                for shorter in range(lag):
                    period = outcome_period - shorter
                    value -= self._theta_at(shorter, trajectory.state[period]) * float(
                        trajectory.treatment[period]
                    )
                unit_index.append(index)
                weights.append(weight)
                peeled.append(value)
                anchors.append(trajectory.state[anchor])
                treatments.append(
                    [float(trajectory.treatment[outcome_period - tau]) for tau in range(lag + 1)]
                )
        if not unit_index:
            return None
        return {
            "unit_index": np.asarray(unit_index, dtype=int),
            "weight": np.asarray(weights, dtype=float),
            "peeled": np.asarray(peeled, dtype=float),
            "anchor": np.asarray(anchors, dtype=float),
            "treatment": np.asarray(treatments, dtype=float),
        }

    def _theta_at(self, lag: int, state: np.ndarray) -> float:
        """The already-estimated lag-``lag`` effect for a treatment given in ``state``."""
        coefficients = self.coefficients_[lag]
        if coefficients is None:
            return float(self.theta_[lag])
        return float(coefficients[0] + coefficients[1:] @ self._modifiers(state[None, :])[0])

    def _modifiers(self, anchor: np.ndarray) -> np.ndarray:
        if self.modifier_index is None:
            return anchor
        return anchor[:, self.modifier_index]

    def _fit_one_lag(self, rows: dict[str, np.ndarray], folds: np.ndarray, lag: int) -> None:
        unit_index = rows["unit_index"]
        weight = rows["weight"]
        anchor = rows["anchor"]
        residual_outcome = self._residualise(rows["peeled"], anchor, unit_index, folds, weight)
        residual_treatment = np.column_stack(
            [
                self._residualise(rows["treatment"][:, tau], anchor, unit_index, folds, weight)
                for tau in range(lag + 1)
            ]
        )
        anchor_treatment = residual_treatment[:, lag]
        denominator = float(np.sum(weight * anchor_treatment**2))
        j_statistic = denominator / self.n_units_

        if self.heterogeneous:
            design = self._interaction(anchor_treatment, anchor)
            coefficients = self._weighted_least_squares(design, residual_outcome, weight)
            self.coefficients_[lag] = coefficients
            prediction = design @ coefficients
            # The reported scalar is the projection averaged over the anchor windows, which
            # is what this lag's population actually experienced.
            theta = float(
                np.average(
                    coefficients[0] + self._modifiers(anchor) @ coefficients[1:], weights=weight
                )
            )
            score_residual = residual_outcome - prediction
        else:
            numerator = float(np.sum(weight * residual_outcome * anchor_treatment))
            theta = numerator / denominator if denominator > 1e-12 else float("nan")
            score_residual = residual_outcome - theta * anchor_treatment

        self.theta_[lag] = theta
        self.fits_.append(
            _LagFit(
                lag=lag,
                unit_index=unit_index,
                weight=weight,
                residual_treatment=residual_treatment,
                score_residual=score_residual,
                theta=theta,
                coefficients=self.coefficients_[lag],
                j_statistic=j_statistic,
            )
        )

    def _interaction(self, residual_treatment: np.ndarray, anchor: np.ndarray) -> np.ndarray:
        """``[1, modifiers] * residual treatment``: the linear model for theta_kappa(x)."""
        modifiers = self._modifiers(anchor)
        with_intercept = np.column_stack([np.ones(len(modifiers)), modifiers])
        return with_intercept * residual_treatment[:, None]

    @staticmethod
    def _weighted_least_squares(
        design: np.ndarray, target: np.ndarray, weight: np.ndarray
    ) -> np.ndarray:
        root = np.sqrt(weight)[:, None]
        solution, *_ = np.linalg.lstsq(design * root, target * np.sqrt(weight), rcond=None)
        return np.asarray(solution).ravel()

    def _influence_standard_errors(self) -> np.ndarray:
        """The recursive influence function of the paper's Theorem, clustered by unit.

        Only for the constant profile: with a varying profile the target is a coefficient
        vector per lag and the recursion no longer reduces to one scalar per lag. The
        bootstrap covers both.
        """
        errors = np.full(self.max_lag + 1, np.nan)
        if self.heterogeneous:
            return errors
        influence: dict[int, np.ndarray] = {}
        for fit in self.fits_:
            anchor_treatment = fit.residual_treatment[:, fit.lag]
            j_statistic = fit.j_statistic
            if not np.isfinite(j_statistic) or j_statistic <= 1e-12:
                continue
            per_row = fit.weight * fit.score_residual * anchor_treatment
            per_unit = np.zeros(self.n_units_)
            np.add.at(per_unit, fit.unit_index, per_row)
            current = per_unit / j_statistic
            # Each shorter lag was estimated first and its error propagates through the
            # peeling; this is that correction.
            for shorter in range(fit.lag):
                if shorter not in influence:
                    continue
                cross = (
                    float(
                        np.sum(fit.weight * fit.residual_treatment[:, shorter] * anchor_treatment)
                    )
                    / self.n_units_
                )
                current = current - (cross / j_statistic) * influence[shorter]
            influence[fit.lag] = current
            errors[fit.lag] = float(np.sqrt(np.mean(current**2) / self.n_units_))
        return errors

    # ---- Stage 3 ----

    def bootstrap(
        self,
        trajectories: list[Trajectory],
        replicates: int = DEFAULT_BOOTSTRAP_SAMPLES,
        seed: int = 0,
        n_jobs: int = 1,
        alpha: float = 0.05,
    ) -> dict[str, np.ndarray]:
        """Resample units, re-run every stage, take percentiles of the whole profile."""
        rng = np.random.default_rng(seed)
        n_units = len(trajectories)
        # Indices are drawn up front so the result cannot depend on the number of workers.
        draws = [rng.integers(0, n_units, size=n_units) for _ in range(replicates)]
        seeds = rng.integers(0, 2**31 - 1, size=replicates)

        def one(index: int) -> np.ndarray:
            resampled = [trajectories[j] for j in draws[index]]
            replica = DynamicLagDmlFit(
                max_lag=self.max_lag,
                heterogeneous=self.heterogeneous,
                n_folds=self.n_folds,
                lambda_floor=self.lambda_floor,
                seed=int(seeds[index]),
                use_weights=self.use_weights,
                weight_stage1=self.weight_stage1,
                oracle_continuation=self.oracle_continuation,
                continuation_model=_clone(self.continuation_model),
                nuisance_model=_clone(self.nuisance_model),
                modifier_index=self.modifier_index,
            )
            return replica.fit(resampled).theta_

        profiles: list[np.ndarray]
        if n_jobs != 1:
            profiles = cast(
                "list[np.ndarray]",
                Parallel(n_jobs=n_jobs)(delayed(one)(b) for b in range(replicates)),
            )
        else:
            profiles = [one(b) for b in range(replicates)]
        stacked = np.vstack(profiles)
        return {
            "profiles": stacked,
            "lower": np.nanpercentile(stacked, 100 * alpha / 2, axis=0),
            "upper": np.nanpercentile(stacked, 100 * (1 - alpha / 2), axis=0),
            "standard_error": np.nanstd(stacked, axis=0, ddof=1),
        }


class DynamicLagDml:
    """The lag profile of one treatment period, on panel data with an informative horizon."""

    id = "dynamic_lag_dml"

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        from causpec.core.registry import load_declaration
        from causpec.families.dynamic_lag_dml.checks import check_panel

        return check_panel(data, spec, load_declaration(self.id))

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        estimand = str(_field_value(spec, "estimand", "lag_profile"))
        if estimand not in ESTIMANDS:
            raise ValueError(f"estimand must be one of {', '.join(ESTIMANDS)}; got {estimand}")
        heterogeneous = estimand == "lag_cate"

        unit = _one_column(spec, "unit_id")
        period = _one_column(spec, "period_index")
        treatment = _one_column(spec, "treatment")
        outcome = _one_column(spec, "outcome")
        state = _column_names(spec, "state")
        if not state:
            raise ValueError("dynamic_lag_dml requires spec.state (the covariates X)")
        modifiers = _column_names(spec, "effect_modifiers")
        if heterogeneous and not modifiers:
            raise ValueError("estimand lag_cate requires spec.effect_modifiers")
        unknown = [name for name in modifiers if name not in state]
        if unknown:
            raise ValueError(
                f"effect_modifiers must be part of the state: {unknown} are not in spec.state"
            )

        max_lag = int(_field_value(spec, "max_lag", spec.param("max_lag", DEFAULT_MAX_LAG)))
        period_hours = _field_value(spec, "period_length", None)
        replicates = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        n_jobs = int(spec.param("bootstrap_n_jobs", 1))
        lambda_floor = float(spec.param("lambda_floor", DEFAULT_LAMBDA_FLOOR))
        n_folds = int(spec.param("n_folds", DEFAULT_N_FOLDS))
        use_weights = bool(spec.param("use_ipcw", True))

        trajectories = to_trajectories(data, unit, period, state, treatment, outcome)
        modifier_index = (
            np.array([state.index(name) for name in modifiers], dtype=int) if modifiers else None
        )

        fit = DynamicLagDmlFit(
            max_lag=max_lag,
            heterogeneous=heterogeneous,
            n_folds=n_folds,
            lambda_floor=lambda_floor,
            seed=seed,
            use_weights=use_weights,
            modifier_index=modifier_index,
        ).fit(trajectories)
        interval = fit.bootstrap(trajectories, replicates=replicates, seed=seed + 1, n_jobs=n_jobs)

        values = self._profile_addresses(fit, interval, period_hours, modifiers)
        lengths = np.array([t.length for t in trajectories])
        values.update(
            {
                "res:sample.n_units": int(len(trajectories)),
                "res:sample.n_rows": int(len(data)),
                "res:sample.mean_periods": float(lengths.mean()),
                "res:sample.max_periods": int(lengths.max()),
                "res:sample.treatment_rate": float(
                    np.mean(np.concatenate([t.treatment for t in trajectories]))
                ),
                "res:design.n_state_columns": len(state),
                "res:design.n_effect_modifiers": len(modifiers),
                "res:estimation.estimand": estimand,
                "res:estimation.max_lag": max_lag,
                "res:estimation.continuation_model": type(fit.continuation_model).__name__,
                "res:estimation.nuisance_model": type(fit.nuisance_model).__name__,
                "res:estimation.lambda_floor": lambda_floor,
                "res:estimation.use_ipcw": str(use_weights),
                "res:estimation.n_bootstrap_samples": replicates,
                "res:estimation.bootstrap_adequate": str(
                    replicates >= int(spec.param("bootstrap_adequate_threshold", 100))
                ),
            }
        )
        return Result(family=self.id, seed=seed, values=values)

    @staticmethod
    def _profile_addresses(
        fit: DynamicLagDmlFit,
        interval: dict[str, np.ndarray],
        period_hours: Any,
        modifiers: list[str],
    ) -> dict[str, float | int | str]:
        values: dict[str, float | int | str] = {
            "res:profile.max_lag": fit.max_lag,
            "res:profile.ci_method": "patient_bootstrap_percentile",
            # Read by the claim-level decision: consistency is proved, a limiting
            # distribution is not, so no lag may be called significant.
            "res:profile.ci_calibration": "exploratory",
            "res:profile.continuation_min": float(fit.continuation_min_),
            "res:profile.continuation_clipped_share": float(fit.continuation_clipped_share_),
        }
        by_lag = {lag_fit.lag: lag_fit for lag_fit in fit.fits_}
        for lag in range(fit.max_lag + 1):
            prefix = f"res:profile.lag{lag}"
            values[f"{prefix}.theta"] = float(fit.theta_[lag])
            values[f"{prefix}.ci_lo"] = float(interval["lower"][lag])
            values[f"{prefix}.ci_hi"] = float(interval["upper"][lag])
            values[f"{prefix}.se_bootstrap"] = float(interval["standard_error"][lag])
            values[f"{prefix}.se_influence"] = float(fit.standard_error_[lag])
            if period_hours is not None:
                values[f"{prefix}.hours"] = float(lag) * float(period_hours)
            lag_fit = by_lag.get(lag)
            if lag_fit is None:
                values[f"{prefix}.n_windows"] = 0
                continue
            weight = lag_fit.weight
            values[f"{prefix}.n_windows"] = int(len(weight))
            values[f"{prefix}.n_units"] = int(len(np.unique(lag_fit.unit_index)))
            values[f"{prefix}.j_statistic"] = float(lag_fit.j_statistic)
            values[f"{prefix}.weight_max"] = float(weight.max())
            values[f"{prefix}.weight_mean"] = float(weight.mean())
            values[f"{prefix}.effective_windows"] = float(lag_fit.effective_windows)
            if lag_fit.coefficients is not None:
                values[f"{prefix}.coef.intercept"] = float(lag_fit.coefficients[0])
                for name, coefficient in zip(modifiers, lag_fit.coefficients[1:], strict=True):
                    values[f"{prefix}.coef.{name}"] = float(coefficient)
        return values


register(DynamicLagDml())

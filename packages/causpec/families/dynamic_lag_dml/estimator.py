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
what the paper's special case establishes. And when the horizon is fixed, meaning every unit
is observed for the same number of periods, no model is fitted, every weight is exactly one,
and each unit's final period contributes a window: see ``_continuation`` and ``_build_rows``.
The horizon is a confirmed spec field rather than an inference, because a panel truncated to a
fixed length has the same shape as a fixed horizon and a very different meaning.

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
HORIZONS = ("fixed", "variable")
# The value of spec.termination when a trajectory simply stops: the rows end where the unit
# left, with no column marking it. A real column of this name wins, which is resolved against
# the data rather than assumed.
ROWS_END_AT_EXIT = "last_recorded_period"

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
    # Whether this trajectory ended because the unit left, as opposed to because the
    # observation window ran out. None means the caller did not say, and the fit then
    # reads it from the declared horizon. Only an exit is evidence about continuing.
    exited: bool | None = None

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
    termination: str | None = None,
) -> list[Trajectory]:
    """Split a long panel into trajectories, refusing a shape the estimand cannot carry.

    The lag index counts rows, so a gap in the period index silently turns a lag-2 window
    into a lag-3 one. That is not something to impute; it is something to refuse. The
    quality checks report the same problems with a repair suggestion, and this is the
    backstop for a caller that skipped them.

    ``termination`` names a column that marks the period a unit left, if the data has one.
    Then whether a trajectory ended by leaving is read from that column instead of being
    guessed from where its rows stop, and rows recorded after a unit left are refused: they
    are not observations of an active trajectory.
    """
    wanted = [unit, period, treatment, outcome, *state]
    if termination is not None:
        wanted.append(termination)
    missing = [c for c in wanted if c not in data.columns]
    if missing:
        raise ValueError(f"columns not in the data: {missing}")

    ordered = data.sort_values([unit, period], kind="stable")
    _refuse_missing_values(ordered, unit, period, [treatment, outcome, *state])
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
        exited: bool | None = None
        if termination is not None:
            marked = _exit_marks(np.asarray(group[termination]))
            if marked.any():
                where = int(np.flatnonzero(marked)[-1])
                if where != len(marked) - 1:
                    raise ValueError(
                        f"unit {key!r} has {len(marked) - 1 - where} rows recorded after it "
                        f"left (period {where}); rows after a unit leaves are not "
                        f"observations of an active trajectory"
                    )
                exited = True
            else:
                exited = False
        trajectories.append(
            Trajectory(
                unit=key,
                state=group[state].to_numpy(dtype=float),
                treatment=group[treatment].to_numpy(dtype=float),
                outcome=group[outcome].to_numpy(dtype=float),
                continuation=(group[continuation].to_numpy(dtype=float) if continuation else None),
                exited=exited,
            )
        )
    return trajectories


def _refuse_missing_values(
    ordered: pd.DataFrame, unit: str, period: str, columns: list[str]
) -> None:
    """Refuse a missing value in any column that enters the estimation.

    Left to itself this surfaces as ``Input y contains NaN`` from inside a nuisance
    regression, which names neither the column nor the repair. A missing value here is not
    something to impute either: the state, the treatment and the outcome of a period are the
    period, and a guess at one of them is a guess at the effect.

    The final-period pattern is called out separately because it has its own cause and its
    own fix. A fixed-horizon panel now uses the last period's outcome, and that outcome is
    the one most likely to be absent, since its measurement window can run past the end of
    data collection.
    """
    offenders: list[str] = []
    final_only: list[str] = []
    is_final = np.asarray(
        ordered.groupby(unit)[period].transform("max") == ordered[period], dtype=bool
    )
    for column in columns:
        missing = np.asarray(ordered[column].isna(), dtype=bool)
        if not missing.any():
            continue
        count = int(missing.sum())
        if bool((missing == (missing & is_final)).all()):
            final_only.append(f"{column} ({count}, all on final periods)")
        else:
            offenders.append(f"{column} ({count})")
    if not offenders and not final_only:
        return
    detail = ", ".join(offenders + final_only)
    hint = ""
    if final_only and not offenders:
        hint = (
            " Missing only on final periods usually means the outcome's measurement window "
            "runs past the end of data collection: record one period fewer per unit rather "
            "than leaving the last one blank."
        )
    raise ValueError(
        f"missing values in columns the estimation uses: {detail}. The state, the treatment "
        f"and the outcome of a period are the period, so these cannot be imputed."
        f"{hint}"
    )


def _exit_marks(values: np.ndarray) -> np.ndarray:
    """Which periods the termination column marks as the unit leaving.

    Left deliberately permissive about how a dataset says "left here": a flag of 1, a
    non-empty reason, a date. What all of them share is that the marked period is the one
    the unit left in, and everything else is blank, zero or missing.
    """
    marked = np.zeros(len(values), dtype=bool)
    for index, value in enumerate(values):
        if value is None:
            continue
        if isinstance(value, float) and np.isnan(value):
            continue
        if isinstance(value, str):
            marked[index] = value.strip() != ""
        elif isinstance(value, (bool, np.bool_)):
            marked[index] = bool(value)
        elif isinstance(value, (int, float, np.integer, np.floating)):
            marked[index] = float(value) != 0.0
        else:
            marked[index] = True
    return marked


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
        horizon: str = "variable",
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
        # What the user confirmed about the horizon, not what the data looks like. The two
        # are cross-checked by the quality checks, because the shape of the data cannot tell
        # a fixed horizon from a cohort that was truncated to a fixed length: see
        # _continuation.
        if horizon not in HORIZONS:
            raise ValueError(f"horizon must be one of {', '.join(HORIZONS)}; got {horizon!r}")
        self.horizon = horizon
        self.continuation_model: Any = continuation_model or HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05
        )
        self.nuisance_model: Any = nuisance_model or LinearRegression()
        self.modifier_index = modifier_index

    # ---- Stage 0 ----

    def _continuation(self, trajectories: list[Trajectory], folds: np.ndarray) -> list[np.ndarray]:
        """Cross-fitted one-step continuation probability per unit and period.

        **A fixed horizon needs no weights, and the user says which it is.** With
        ``horizon="fixed"`` nobody left early, there is nothing to correct, no model is
        fitted, and every weight is exactly one.

        This is not inferred from the data, and the reason is a specific trap. A panel whose
        units all have eight periods can be either of two worlds: a genuinely fixed horizon,
        or a variable horizon whose data pull kept the first eight buckets of the units that
        lasted that long. The second is a cohort conditioned on surviving, which no weighting
        repairs, and the two are indistinguishable by shape. On the benchmark design,
        truncating to the 3.5% of units that reach eight periods moves the lag-1 estimate
        from 4.22 to 2.87 against a truth of 4.0, and a tool that guessed "fixed" would report
        that as a clean analysis. So the horizon is a confirmed spec field, and a quality
        check compares it with the data and refuses a contradiction.

        Within a variable horizon, reaching the end of the observation window is not leaving:
        nothing is known about whether such a trajectory would have continued, so its final
        period contributes no record. Where the data marks exits with a column, that column
        decides; otherwise a trajectory that stops before the window is read as having left.

        The labelling matters. Treating the end of every trajectory as an exit asks the model
        to predict "is this the last period", which the state and the treatment cannot say,
        and on an eight-period balanced panel it fitted continuation probabilities as low as
        0.40 and weights up to 4.3 where all of them were 1.
        """
        self.continuation_min_ = float("nan")
        self.continuation_clipped_share_ = float("nan")
        lengths = [trajectory.length for trajectory in trajectories]
        window_end = max(lengths)
        self.horizon_ = self.horizon
        self.ipcw_applied_ = self.use_weights and self.horizon_ == "variable"
        if not self.ipcw_applied_:
            return [np.ones(length) for length in lengths]
        if self.oracle_continuation:
            return [
                np.clip(np.asarray(t.continuation, dtype=float), self.lambda_floor, 1 - 1e-9)
                for t in trajectories
            ]

        features: list[np.ndarray] = []
        labels: list[float] = []
        owner: list[int] = []
        at_period: list[int] = []
        for index, trajectory in enumerate(trajectories):
            # An explicit termination column wins; without one, a trajectory that stops
            # before the window is read as having left, and one that reaches the window as
            # having been cut off.
            censored = (
                trajectory.length == window_end
                if trajectory.exited is None
                else not trajectory.exited
            )
            for period in range(trajectory.length):
                continued = period + 1 < trajectory.length
                if not continued and censored:
                    continue  # cut off by the window; nothing is known about continuing
                features.append(np.append(trajectory.state[period], trajectory.treatment[period]))
                labels.append(1.0 if continued else 0.0)
                owner.append(index)
                at_period.append(period)

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

        # Scattered back by (unit, period) rather than by position: a censored trajectory
        # contributes one record fewer than it has periods, so the rows and the periods no
        # longer line up. Anything with no record keeps 1, and a window's weight never
        # reaches a unit's final period anyway, since the outcome period is at most the
        # second to last.
        out = [np.ones(length) for length in lengths]
        for row, (index, period) in enumerate(zip(owner, at_period, strict=True)):
            out[index][period] = fitted[row]
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

        Under a variable horizon a window is usable when the outcome period is recorded
        **and** the trajectory was still active one period after it, which is the paper's
        analysis set: the outcome of period t is realised before period t+1, so observing it
        means surviving that step, and the weight includes that step.

        **Under a fixed horizon the final period is usable too.** Nobody leaves, so the
        outcome of the last period is recorded like any other and the condition it was
        standing in for cannot fail. Excluding it would discard one window per unit per lag
        for a reason that does not apply: on an eight-period panel that is a sixth of the
        lag-2 windows. The relaxation is keyed on the declared horizon and not on whether
        weights happen to be 1, because under a variable horizon with weighting switched off
        the outcome genuinely may be unobserved.

        A mixed panel keeps the paper's convention throughout. A trajectory cut off by the
        window does have its final outcome recorded, but whether it would have continued is
        unknown, so the step the weight corrects for is unobservable rather than absent. One
        convention for that case, conservatively.
        """
        unit_index: list[int] = []
        weights: list[float] = []
        peeled: list[float] = []
        anchors: list[np.ndarray] = []
        treatments: list[list[float]] = []
        include_final = self.horizon == "fixed"
        for index, trajectory in enumerate(trajectories):
            # t <= length - 2 normally; t <= length - 1 when nobody leaves.
            last_usable = trajectory.length if include_final else trajectory.length - 1
            for outcome_period in range(lag, last_usable):
                anchor = outcome_period - lag
                if self.use_weights and lag > 0:
                    # One factor per continuation decision from the anchor through the step
                    # that makes the outcome observable. Capped at the recorded periods,
                    # which only binds when the final period is included and the weights are
                    # all 1 anyway.
                    end = min(outcome_period + 1, trajectory.length)
                    factors = continuation[index][anchor:end]
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
                horizon=self.horizon,
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

        horizon = str(_field_value(spec, "horizon", "")).strip()
        if horizon not in HORIZONS:
            raise ValueError(
                f"dynamic_lag_dml requires spec.horizon, one of {', '.join(HORIZONS)}. The "
                f"data cannot settle it: a panel where every unit has the same number of "
                f"periods is either a fixed horizon or a cohort truncated to a fixed length, "
                f"and the second is conditioned on surviving. Ask the user."
            )
        termination = self._termination_column(spec, data, horizon)

        max_lag = int(_field_value(spec, "max_lag", spec.param("max_lag", DEFAULT_MAX_LAG)))
        period_hours = _field_value(spec, "period_length", None)
        replicates = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        n_jobs = int(spec.param("bootstrap_n_jobs", 1))
        lambda_floor = float(spec.param("lambda_floor", DEFAULT_LAMBDA_FLOOR))
        n_folds = int(spec.param("n_folds", DEFAULT_N_FOLDS))
        use_weights = bool(spec.param("use_ipcw", True))

        trajectories = to_trajectories(
            data, unit, period, state, treatment, outcome, termination=termination
        )
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
            horizon=horizon,
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
                "res:estimation.termination": termination or ROWS_END_AT_EXIT,
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
    def _termination_column(spec: Spec, data: pd.DataFrame, horizon: str) -> str | None:
        """Which column marks a unit leaving, if any.

        A variable horizon has to say how an exit is identified, and there are only two
        answers: the rows stop where the unit left, or a column marks it. The sentinel for
        the first is ``last_recorded_period``; a real column of that name wins, which is why
        this resolves against the data rather than against the string alone.
        """
        declared = _field_value(spec, "termination", None)
        if horizon == "fixed":
            return None
        if declared is None or not str(declared).strip():
            raise ValueError(
                f"a variable horizon requires spec.termination: either the name of the "
                f"column that marks the period a unit left, or {ROWS_END_AT_EXIT!r} when the "
                f"rows simply stop there. Which it is decides what counts as evidence that a "
                f"trajectory could have continued."
            )
        name = str(declared).strip()
        if name in data.columns:
            return name
        if name == ROWS_END_AT_EXIT:
            return None
        raise ValueError(
            f"spec.termination names {name!r}, which is not a column in the data. Use "
            f"{ROWS_END_AT_EXIT!r} if the rows simply stop where the unit left."
        )

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
            # Whether any trajectory ended before the end of the observation window. A fixed
            # horizon has nothing to weight, and the report should say the weighting was
            # skipped rather than leave the reader to infer it from weights of exactly 1.
            "res:profile.horizon": str(fit.horizon_),
            "res:profile.ipcw_applied": str(fit.ipcw_applied_),
            # Whether the last period of each trajectory contributed a window. It can only
            # when nobody leaves, and it is worth saying because it changes the counts a
            # reader compares against the number of rows.
            "res:profile.final_period_included": str(fit.horizon_ == "fixed"),
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
                # The period length in its own right. Without it, a sentence about "a
                # 12-hour period" has no address to cite and lit: is refused, because 12
                # also happens to be the lag-1 effect's 12 hours.
                values["res:profile.period_hours"] = float(period_hours)
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

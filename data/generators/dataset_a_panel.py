"""Dataset A, panel part: an episodic trajectory with a known lag profile.

Mirrors design.md sections 7.3 and 15, and ports the data-generating process of the
author's dynamic-treatment-effect paper (the low-dimensional benchmark and the
high-dimensional nonlinear design). What dataset A is to `hte_iv`, this is to
`dynamic_lag_dml`: a world where the answer is known, so an estimator can be checked
rather than admired.

**The generated data is never committed**, only this generator is.

The world
---------
A patient is in the unit for a random number of 12-hour periods. Within each period the
order is fixed, and the whole estimand depends on it::

    active  ->  state X[t]  ->  treatment A[t]  ->  outcome Y[t]  ->  next period

    X[t+1] = C * A[t] + B * X[t] + eta[t+1]          B = rho * I
    Y[t]   = theta_0 * A[t] + mu' * X[t] + eps[t+1]
    Pr(A[t] = 1 | X[t], A[t-1]) = sigmoid(g0 + gx' X[t] + gd * A[t-1])
    Pr(leaving before t+1 | X[t], A[t]) = exit_ceiling * sigmoid(a_e + tau * A[t] + b_e' X[t])

Four properties make it the right test bed:

1. **The treatment is confounded by the state and persistent in itself.** `gx` makes the
   sicker patient more likely to be treated, `gd` makes yesterday's decision predict
   today's, so a regression of the outcome on the treatment lags is biased in a way that
   does not shrink with the sample size.
2. **Leaving is informative.** `b_e` makes sicker patients leave earlier, so the windows
   long enough to carry a lag-2 outcome are a selected sample. This is what the
   continuation weights correct, and dropping them leaves a bias that also does not
   shrink.
3. **Continuation positivity holds by construction.** The exit probability is capped at
   `exit_ceiling`, so the one-step continuation probability is at least
   ``1 - exit_ceiling`` for every state. That decouples positivity from the strength of
   the selection, which can then be turned up without breaking the assumption.
4. **The lag profile is known in closed form.** Because the state and outcome equations
   are linear, ``theta_kappa = mu' B^(kappa-1) C``, and with ``B = rho * I`` that is
   ``rho^(kappa-1) * (mu' C)``.

Where heterogeneity may live
----------------------------
Heterogeneity is driven by **baseline coordinates**, drawn once per unit and never
updated, and never by the time-varying state. That is not a simplification, it is the only
place it can go.

Suppose the propagation varied with the time-varying state, ``C(X[t])``. Then the effect of
the treatment at t on the outcome at t+2 runs through two paths: ``rho * mu' C(X[t])``, and
``mu' C * h * delta' C(X[t]) * A[t+1]`` through ``C(X[t+1])``, because ``X[t+1]`` depends on
``A[t]``. The second is multiplied by the treatment of the *next* period, so it is an
interaction between two treatment periods, and the additive decomposition of one outcome
into a sum of lag effects no longer holds. There is then no lag profile to estimate, and an
estimator that assumes one returns something that looks plausible and is not any effect: on
an earlier version of this generator the constant lag-2 estimate came out at +4.7 where the
nominal truth was +1.2.

A baseline covariate leaves the second path at zero, because the treatment cannot move it.
So ``theta_0(w) = theta_0 * (1 + h_outcome * w)`` and ``theta_kappa(w) = rho^(kappa-1) *
(mu' C) * (1 + h_propagation * w)``, both known per unit, and the decomposition stays
additive. The same restriction is why ``family.yaml`` requires the effect modifiers of
``lag_cate`` to be variables the treatment does not move.

Why the outcome is continuous
-----------------------------
The paper's application reads a binary outcome through the same linear conditional mean,
where ``theta_kappa`` is a risk difference. A generator cannot honestly do that: a linear
probability in an unbounded state leaves [0, 1], and clipping it would make the emitted
truth a lie. Dataset A already taught this project that lesson once, when tau was defined
as a risk difference and then clipped at 4% baseline mortality. So the outcome here is
continuous, and the binary reading stays a documented property of the estimand rather
than something pretended in synthetic data.

Truth columns
-------------
``theta0_true`` ... ``thetaK_true``  the true lag-kappa effect of **this row's**
                    treatment, that is of a period whose starting state is this row's.
                    With no heterogeneity they are constant down the column.
``lambda_true``     the true one-step continuation probability for this row, used by the
                    oracle-continuation arm that separates method error from
                    continuation-model error.
``exit_reason``     death or discharge for the last row of a trajectory, empty otherwise.
                    Cosmetic: the estimator treats both identically, and the column
                    exists so a report can say what share of the endings were deaths,
                    which is the caveat a clinician needs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# The first six state columns are named after the real ICU variables, so the real data
# drops into the same pipeline. Beyond six the names are generic.
NAMED_STATE_COLUMNS: tuple[str, ...] = (
    "max_creatinine",
    "max_potassium",
    "max_urea",
    "max_lactate",
    "min_ArterialPressure",
    "min_urine_output",
)

# Baseline coordinates come last, are drawn once per unit and never change. They are part of
# the state, so they are adjusted on like any other covariate; what makes them different is
# that the treatment cannot move them, which is what lets the lag effect vary with them.
NAMED_BASELINE_COLUMNS: tuple[str, ...] = ("aki_stage_admission", "admission_age")

UNIT_COLUMN = "patient_id"
PERIOD_COLUMN = "bucket"
TREATMENT_COLUMN = "on_rrt"
OUTCOME_COLUMN = "instability_score"


def state_columns(p: int, n_baseline: int = 0) -> list[str]:
    """Every state column in order, the time-varying ones first, the baseline ones last."""
    varying = p - n_baseline
    named = list(NAMED_STATE_COLUMNS[:varying])
    names = named + [f"state_{index:03d}" for index in range(len(named), varying)]
    baseline = list(NAMED_BASELINE_COLUMNS[:n_baseline])
    baseline += [f"baseline_{index:03d}" for index in range(len(baseline), n_baseline)]
    return names + baseline


def baseline_columns(p: int, n_baseline: int) -> list[str]:
    return state_columns(p, n_baseline)[p - n_baseline :] if n_baseline else []


@dataclass(frozen=True)
class PanelConfig:
    """One world. Every field that changes a number is here, so the seed reproduces it."""

    n_units: int = 1000
    seed: int = 0
    max_lag: int = 2
    period_hours: int = 12

    # State: X[t+1] = C * A[t] + B * X[t] + eta, with B = rho * I.
    p: int = 6
    s: int = 1  # active coordinates; the rest are noise the nuisances must see through
    rho: float = 0.3
    sigma_eta: float = 1.8
    c_value: float = 2.0  # each active coordinate of C
    mu_value: float = 2.0  # each active coordinate of mu

    # Outcome: Y[t] = theta_0 * A[t] + mu' X[t] + eps.
    theta_0: float = -0.5
    sigma_epsilon: float = 0.05

    # Treatment: sigmoid(g0 + gx' X[t] + gd * A[t-1]).
    g0: float = -0.3
    gx_value: float = 0.8  # confounding by indication
    gd: float = 1.2  # persistence of the decision

    # Exit: exit_ceiling * sigmoid(a_e + tau * A[t] + b_e' X[t]).
    a_exit: float = -1.0
    tau_exit: float = 0.0
    b_exit_value: float = 1.0  # informative: the sicker leave earlier
    exit_ceiling: float = 0.85  # continuation probability is at least 1 - this
    max_periods: int = 40

    # Baseline coordinates: the last n_baseline of the p state columns. Drawn once per unit
    # and never updated, so the treatment cannot move them.
    n_baseline: int = 0
    mu_baseline: float = 0.5  # how much a baseline coordinate moves the outcome directly

    # Heterogeneity, both off by default, and both driven by the FIRST baseline coordinate.
    # It has to be a baseline one: heterogeneity in the propagation of a time-varying state
    # makes the effect of one period's treatment depend on the next period's, and then there
    # is no additive lag profile to estimate. See the module docstring.
    #   theta_0(w)     = theta_0 * (1 + hetero_outcome * w)
    #   theta_kappa(w) = rho^(kappa-1) * (mu' C) * (1 + hetero_propagation * w),  kappa >= 1
    hetero_outcome: float = 0.0
    hetero_propagation: float = 0.0

    # Nonlinear nuisances: a bounded pairwise interaction added to the treatment and exit
    # sigmoid arguments only, never to the outcome or the state, so the closed-form
    # profile survives while a linear nuisance model becomes misspecified.
    nonlinear_nuisance: bool = False
    nl_strength: float = 0.0

    def __post_init__(self) -> None:
        if self.s > self.p:
            raise ValueError(f"s={self.s} active coordinates but only p={self.p} state columns")
        if self.n_baseline + self.s > self.p:
            raise ValueError(
                f"s={self.s} time-varying active coordinates plus n_baseline="
                f"{self.n_baseline} baseline ones exceed p={self.p}"
            )
        if (self.hetero_outcome or self.hetero_propagation) and not self.n_baseline:
            raise ValueError(
                "heterogeneity needs at least one baseline coordinate: a lag effect that "
                "varies with a state the treatment moves has no additive profile"
            )
        if not 0.0 < self.exit_ceiling <= 1.0:
            raise ValueError("exit_ceiling must be in (0, 1]")
        if self.max_lag < 0:
            raise ValueError("max_lag must be at least 0")

    @property
    def continuation_floor(self) -> float:
        """The positivity bound the design guarantees, c_lambda in the paper."""
        return 1.0 - self.exit_ceiling

    def coefficients(self) -> dict[str, np.ndarray]:
        c = np.zeros(self.p)
        c[: self.s] = self.c_value
        mu = np.zeros(self.p)
        mu[: self.s] = self.mu_value
        gx = np.zeros(self.p)
        gx[: self.s] = self.gx_value
        b_exit = np.zeros(self.p)
        b_exit[: self.s] = self.b_exit_value
        # The baseline block affects the outcome but nothing propagates into it: C is zero
        # there, which is what "the treatment cannot move it" means in this model.
        if self.n_baseline:
            mu[self.p - self.n_baseline :] = self.mu_baseline
        delta = np.zeros(self.p)
        if self.n_baseline:
            delta[self.p - self.n_baseline] = 1.0  # the first baseline coordinate
        return {"C": c, "mu": mu, "gx": gx, "b_exit": b_exit, "delta": delta}

    def constant_profile(self) -> np.ndarray:
        """theta_kappa with no heterogeneity: (theta_0, mu'C, rho * mu'C, ...)."""
        coefficients = self.coefficients()
        mu_c = float(coefficients["mu"] @ coefficients["C"])
        profile = np.empty(self.max_lag + 1)
        profile[0] = self.theta_0
        for lag in range(1, self.max_lag + 1):
            profile[lag] = (self.rho ** (lag - 1)) * mu_c
        return profile


PRESETS: dict[str, dict[str, object]] = {
    # The paper's low-dimensional benchmark: true profile (-0.5, 4.0, 1.2).
    "paper_low_dim": {},
    # The paper's high-dimensional nonlinear design: true profile (-0.5, 3.6, 1.08).
    # Linear nuisances are misspecified here, which is the point: the moment is not
    # orthogonal in the continuation model, so that one has to be flexible.
    "paper_high_dim": {
        "p": 100,
        "s": 10,
        "sigma_eta": 1.2,
        "c_value": 0.6,
        "mu_value": 0.6,
        "a_exit": -1.2,
        "b_exit_value": 0.2,
        "gx_value": 0.15,
        "exit_ceiling": 0.6,
        "nonlinear_nuisance": True,
        "nl_strength": 0.7,
    },
    # Heterogeneous propagation: the same period of treatment moves a sicker patient's
    # trajectory further, so lag_cate has a truth to be checked against.
    # The modifier is severity at admission, a baseline coordinate, because it has to be
    # one: see the module docstring on where heterogeneity may live.
    "heterogeneous": {"n_baseline": 1, "hetero_outcome": 0.3, "hetero_propagation": 0.3},
}


def config_for(preset: str, **overrides: object) -> PanelConfig:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; available: {sorted(PRESETS)}")
    values = dict(PRESETS[preset])
    values.update(overrides)
    return PanelConfig(**values)  # type: ignore[arg-type]


def _sigmoid(z: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-z))


def _nonlinear_term(x: np.ndarray, s: int, strength: float) -> float:
    """A bounded pairwise interaction on the active coordinates.

    Each tanh term is in (-1, 1), so the whole term is bounded and the state cannot be
    driven out of the region where the exit cap keeps positivity. No linear model can
    represent it, which is the whole purpose.
    """
    if strength == 0.0 or s < 2:
        return 0.0
    total = 0.0
    for index in range(0, s - 1, 2):
        total += float(np.tanh(x[index] * x[index + 1]))
    return strength * total


@dataclass
class _Row:
    unit: int
    period: int
    state: np.ndarray
    treatment: float
    outcome: float
    continuation: float
    theta: np.ndarray
    last: bool = False
    exit_reason: str = ""


def generate(config: PanelConfig | None = None) -> pd.DataFrame:
    """One row per unit and period, in order, with the truth attached to each row."""
    config = config or PanelConfig()
    rng = np.random.default_rng(config.seed)
    coefficients = config.coefficients()
    c_vector = coefficients["C"]
    mu = coefficients["mu"]
    gx = coefficients["gx"]
    b_exit = coefficients["b_exit"]
    delta = coefficients["delta"]
    mu_c = float(mu @ c_vector)
    rows: list[_Row] = []

    def draw_treatment(state: np.ndarray, previous: float) -> float:
        z = config.g0 + float(gx @ state) + config.gd * previous
        if config.nonlinear_nuisance:
            z += _nonlinear_term(state, config.s, config.nl_strength)
        return float(rng.uniform() < _sigmoid(z))

    def row_profile(state: np.ndarray) -> np.ndarray:
        """This row's true lag profile: theta_kappa for a treatment given in this state.

        Constant within a unit, because the modifier is a baseline coordinate.
        """
        outcome_scale = 1.0 + config.hetero_outcome * float(delta @ state)
        propagation_scale = 1.0 + config.hetero_propagation * float(delta @ state)
        profile = np.empty(config.max_lag + 1)
        profile[0] = config.theta_0 * outcome_scale
        for lag in range(1, config.max_lag + 1):
            profile[lag] = (config.rho ** (lag - 1)) * mu_c * propagation_scale
        return profile

    n_varying = config.p - config.n_baseline
    for unit in range(config.n_units):
        state = rng.normal(0.0, 1.0, size=config.p)
        # Drawn once and carried unchanged: this unit's baseline covariates.
        baseline_block = state[n_varying:].copy()
        previous_treatment = 0.0
        treatment = draw_treatment(state, previous_treatment)

        for period in range(config.max_periods):
            profile = row_profile(state)
            outcome = (
                profile[0] * treatment
                + float(mu @ state)
                + float(rng.normal(0.0, config.sigma_epsilon))
            )

            exit_argument = config.a_exit + config.tau_exit * treatment + float(b_exit @ state)
            if config.nonlinear_nuisance:
                exit_argument += _nonlinear_term(state, config.s, config.nl_strength)
            exit_probability = config.exit_ceiling * float(_sigmoid(exit_argument))
            leaving = rng.uniform() < exit_probability
            reason = ""
            if leaving:
                # Cosmetic only: the estimator treats death and discharge identically.
                # Severity at the moment of leaving decides which label it gets.
                severity = float(mu @ state)
                death_probability = float(_sigmoid(0.4 * severity - 3.0))
                reason = "death" if rng.uniform() < death_probability else "discharge"

            rows.append(
                _Row(
                    unit=unit,
                    period=period,
                    state=state.copy(),
                    treatment=treatment,
                    outcome=outcome,
                    continuation=1.0 - exit_probability,
                    theta=profile,
                    last=leaving or period == config.max_periods - 1,
                    exit_reason=reason,
                )
            )
            if leaving:
                break

            propagation = c_vector * (1.0 + config.hetero_propagation * float(delta @ state))
            state = (
                propagation * treatment
                + config.rho * state
                + rng.normal(0.0, config.sigma_eta, size=config.p)
            )
            # The baseline block is not part of the recursion: put it back untouched.
            state[n_varying:] = baseline_block
            previous_treatment, treatment = treatment, draw_treatment(state, previous_treatment)

    # Assembled in one go: a hundred columns added one at a time fragments the frame.
    names = state_columns(config.p, config.n_baseline)
    states = np.vstack([row.state for row in rows])
    thetas = np.vstack([row.theta for row in rows])
    columns: dict[str, object] = {
        UNIT_COLUMN: [row.unit for row in rows],
        PERIOD_COLUMN: [row.period for row in rows],
    }
    columns.update({name: states[:, index] for index, name in enumerate(names)})
    columns[TREATMENT_COLUMN] = [row.treatment for row in rows]
    columns[OUTCOME_COLUMN] = [row.outcome for row in rows]
    columns.update({f"theta{lag}_true": thetas[:, lag] for lag in range(config.max_lag + 1)})
    columns["lambda_true"] = [row.continuation for row in rows]
    columns["exit_reason"] = [row.exit_reason for row in rows]
    return pd.DataFrame(columns)


def truth(frame: pd.DataFrame, config: PanelConfig) -> dict[str, float]:
    """The profile the estimator should recover, plus what shaped the sample.

    With heterogeneity the constant profile is no longer the target: what the estimator
    converges to is the average over the anchor risk set, and that average shifts with
    the lag because the trajectories long enough to carry a lag-K outcome are not the
    same trajectories as those carrying a lag-0 one. Both are reported.
    """
    # Everything below works on arrays rather than on grouped Series: the per-row trajectory
    # length is what every window rule needs, and pandas' types for a grouped max are loose.
    period = frame[PERIOD_COLUMN].to_numpy(dtype=int)
    length_of_row = (
        np.asarray(frame.groupby(UNIT_COLUMN)[PERIOD_COLUMN].transform("max"), dtype=int) + 1
    )
    per_unit_length = np.asarray(frame.groupby(UNIT_COLUMN)[PERIOD_COLUMN].max(), dtype=int) + 1
    out: dict[str, float] = {}
    constant = config.constant_profile()
    for lag in range(config.max_lag + 1):
        out[f"theta{lag}_constant"] = float(constant[lag])
        # The anchor of a lag-kappa window is the treatment period; the window needs the
        # outcome one period past its end, so the anchor must satisfy
        # period <= length - 2 - lag.
        in_set = period <= length_of_row - 2 - lag
        truths = frame[f"theta{lag}_true"].to_numpy(dtype=float)
        out[f"theta{lag}_anchor_mean"] = (
            float(truths[in_set].mean()) if in_set.any() else float("nan")
        )
        out[f"lag{lag}_anchor_windows"] = float(in_set.sum())
    out["n_units"] = float(len(per_unit_length))
    out["n_rows"] = float(len(frame))
    out["mean_periods"] = float(per_unit_length.mean())
    out["treated_fraction"] = float(frame[TREATMENT_COLUMN].to_numpy(dtype=float).mean())
    out["min_continuation"] = float(frame["lambda_true"].to_numpy(dtype=float).min())
    out["continuation_floor"] = config.continuation_floor
    endings = np.asarray(frame["exit_reason"], dtype=object)
    labelled = endings[endings != ""]
    out["death_share_of_endings"] = float((labelled == "death").mean()) if len(labelled) else 0.0
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the panel part of dataset A, with a known lag profile."
    )
    parser.add_argument("--out", type=Path, required=True, help="output CSV path (never committed)")
    parser.add_argument("--n", type=int, default=PanelConfig.n_units)
    parser.add_argument("--seed", type=int, default=PanelConfig.seed)
    parser.add_argument("--max-lag", type=int, default=PanelConfig.max_lag)
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="paper_low_dim",
        help=(
            "paper_low_dim = the paper's benchmark, true profile (-0.5, 4.0, 1.2); "
            "paper_high_dim = p=100 with nonlinear nuisances; "
            "heterogeneous = the lag effect varies with the state"
        ),
    )
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {"seed": args.seed, "max_lag": args.max_lag}
    if args.n != PanelConfig.n_units:
        overrides["n_units"] = args.n
    config = config_for(args.preset, **overrides)
    frame = generate(config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)

    print(f"wrote {args.out}: {len(frame):,} rows x {frame.shape[1]} columns")
    for key, value in truth(frame, config).items():
        print(f"  {key:24} {value: .4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

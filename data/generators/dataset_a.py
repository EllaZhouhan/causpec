"""Synthetic dataset A: an HTE-IV structural causal model with known ground truth.

Mirrors design.md section 15. Its shape follows the real ICU dialysis study (about a
9.5% treatment rate, about 4% mortality, a consultant-level physician-preference
instrument), but every individual's true treatment effect is emitted alongside, so
evals can measure coverage.

**The generated data is never committed**, only this generator is.

Structure
---------
    U ---------------+            U: unmeasured severity
    |                v
    X -----------> T -----------> Y
    ^                ^
    |                |
  consultant ------> Z            Z: the consultant's historical dialysis tendency

Key properties:

1. **U affects both T and Y**, so the naive difference *and* backdoor adjustment are
   both biased; only IV identifies. This is dataset A's main purpose: to check that
   the tool can tell when adjustment is not enough.
2. **Z affects Y only through T** (the exclusion restriction holds) and its effect on
   T is monotone (monotonicity holds).
3. **The effect is heterogeneous**: tau(X) grows with AKI stage and potassium, the
   sicker the patient, the greater the benefit.
4. Z can be continuous (the preference itself) or binary (preference above the
   median), controlled by ``instrument_kind``, the hte_iv family supports both.

Truth columns
-------------
``tau_true``        each individual's true treatment effect (the risk difference
                    p1 - p0, computed from the potential-outcome probabilities)
``beta_true``       the effect on the logit scale
``u_true``          the unmeasured confounder (diagnostics only; never given to an estimator)
``compliance_type`` only when instrument_kind="binary": always/never/complier
``p0_true``/``p1_true``  the two potential-outcome probabilities
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# Continuous covariates, named after the real data so real data drops into the same pipeline.
CONTINUOUS_COVARIATES: dict[str, tuple[float, float, float, float]] = {
    # name: (mean, sd, low, high)
    "admission_age": (61.0, 15.0, 18.0, 95.0),
    "min_bicarbonate": (21.0, 4.5, 5.0, 40.0),
    "max_creatinine": (180.0, 120.0, 30.0, 900.0),
    "max_potassium": (4.6, 0.8, 2.5, 8.0),
    "min_pH": (7.33, 0.09, 6.90, 7.60),
    "max_urea": (12.0, 8.0, 1.0, 60.0),
    "min_ArterialPressure": (68.0, 13.0, 30.0, 120.0),
    "max_heartRate": (98.0, 20.0, 40.0, 180.0),
    "min_O2Saturation": (93.0, 5.0, 60.0, 100.0),
    "min_GCS_Total": (12.0, 3.5, 3.0, 15.0),
    "max_WBC": (14.0, 7.0, 1.0, 60.0),
    "min_platelet": (180.0, 90.0, 5.0, 600.0),
    "min_hemoglobin": (9.5, 2.0, 4.0, 18.0),
    "max_uo_12h_ml": (450.0, 350.0, 0.0, 3000.0),
    "min_netBodyBalancePerHour": (-20.0, 80.0, -500.0, 400.0),
}

NOISE_COVARIATES = 10  # unrelated to T and Y; checks whether the tool is led astray by noise


@dataclass
class DatasetAConfig:
    """Generation parameters for dataset A. Change these, not the code."""

    n: int = 10_000
    n_consultants: int = 400
    seed: int = 20260925

    instrument_kind: str = "continuous"  # continuous | binary

    # ---- target marginals (the generator calibrates close to these) ----
    target_treatment_rate: float = 0.095
    target_death_rate: float = 0.041

    # ---- effect structure ----
    # The effect is defined on the **logit scale**: logit(p1) = logit(p0) + beta(X).
    # Not as a risk difference: baseline mortality is only about 4%, so a risk
    # difference can reach at most -0.04, and specifying one directly gets clipped,
    # at which point tau_true is no longer the truth. (This bug was caught by the
    # ground-truth check.)
    #   beta(X) = base + aki * aki_stage + k * (potassium - 4.5)
    # Negative lowers mortality risk. A positive base means dialysis is harmful for
    # patients at AKI stage 0 with normal potassium.
    effect_base: float = 0.45
    effect_per_aki_stage: float = -0.40
    effect_per_potassium: float = -0.55

    # ---- strength of unmeasured confounding ----
    confounding_on_treatment: float = 1.10  # U → T
    confounding_on_outcome: float = 0.90  # U → Y

    # ---- instrument strength: how dispersed consultant preferences are ----
    preference_sd: float = 0.9  # sd of the consultant random effect (logit scale)
    instrument_strength: float = 1.30  # coefficient of Z on T

    # Whether the effect varies by compliance type. With False the conditional LATE
    # equals the CATE, so tau_true validates an IV estimate directly; with True they
    # differ and the tool must make clear that the estimand covers compliers only
    # (design.md 7.6).
    effect_varies_by_compliance: bool = False
    compliance_effect_shift: float = -0.35  # logit scale

    noise_covariates: int = NOISE_COVARIATES
    covariates: dict[str, tuple[float, float, float, float]] = field(
        default_factory=lambda: dict(CONTINUOUS_COVARIATES)
    )


# Two presets. `realistic` matches the scale of the real ICU study and is what demos
# and quality checks use; but at that scale an IV analysis has almost no statistical
# power (compliers around 8%, mortality around 4%, and the Wald standard error larger
# than the truth itself), so numerical regression tests drown in noise. `high_power`
# raises the complier share and the event rate for numerical evals, it is not
# realistic, but it gives "is the estimator correct?" a determinate answer.
PRESETS: dict[str, dict[str, object]] = {
    "realistic": {},
    "high_power": {
        "n": 40_000,
        "target_treatment_rate": 0.30,
        "target_death_rate": 0.25,
        "instrument_strength": 2.20,
        "preference_sd": 1.30,
        "confounding_on_treatment": 0.80,
        "confounding_on_outcome": 0.70,
    },
}


def config_for(preset: str, **overrides: object) -> DatasetAConfig:
    """Build a config from a preset name; overrides win."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset}; choose from: {', '.join(PRESETS)}")
    return DatasetAConfig(**{**PRESETS[preset], **overrides})  # type: ignore[arg-type]


def _truncated_normal(rng, mean, sd, low, high, n):
    """Truncated normal: clinical variables have physiological bounds."""
    out = rng.normal(mean, sd, n)
    return np.clip(out, low, high)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _solve_intercept(linear, target_rate, lo=-30.0, hi=30.0, tol=1e-10):
    """Bisect for the intercept that makes mean(sigmoid(intercept + linear)) == target_rate."""
    for _ in range(200):
        mid = (lo + hi) / 2
        rate = float(_sigmoid(mid + linear).mean())
        if abs(rate - target_rate) < tol:
            return mid
        if rate < target_rate:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def generate(config: DatasetAConfig | None = None) -> pd.DataFrame:
    """Generate dataset A. The same seed always yields the same data."""
    cfg = config or DatasetAConfig()
    if cfg.instrument_kind not in ("continuous", "binary"):
        raise ValueError(f"instrument_kind must be continuous or binary; got {cfg.instrument_kind}")
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n

    # ---- 1. observed covariates ----
    data: dict[str, np.ndarray] = {}
    for name, (mean, sd, low, high) in cfg.covariates.items():
        data[name] = _truncated_normal(rng, mean, sd, low, high, n)
    for j in range(cfg.noise_covariates):
        data[f"noise_{j:02d}"] = rng.normal(0.0, 1.0, n)

    data["gender_Male"] = rng.binomial(1, 0.58, n)
    data["admitType_EM"] = rng.binomial(1, 0.62, n)

    # AKI stage follows creatinine and urine output, both a confounder and an effect modifier
    aki_linear = (
        0.010 * (data["max_creatinine"] - 180.0)
        - 0.0022 * (data["max_uo_12h_ml"] - 450.0)
        + rng.normal(0, 1.0, n)
    )
    data["max_aki_stage_smoothed"] = np.clip(
        np.digitize(aki_linear, [-0.6, 0.7, 1.9]), 0, 3
    ).astype(int)

    data["sofa_total_24h"] = np.clip(
        np.round(
            6.0
            + 1.4 * data["max_aki_stage_smoothed"]
            - 0.05 * (data["min_ArterialPressure"] - 68.0)
            - 0.25 * (data["min_GCS_Total"] - 12.0)
            + rng.normal(0, 2.0, n)
        ),
        0,
        24,
    ).astype(int)

    df = pd.DataFrame(data)

    # ---- 2. unmeasured confounding: the part of severity nobody wrote down ----
    u = rng.normal(0.0, 1.0, n)

    # ---- 3. consultants and the physician-preference instrument ----
    # Patients are assigned to consultants at random, which is what makes the exclusion
    # restriction hold: assignment is unrelated to patient characteristics, so a
    # consultant's preference cannot reach the outcome by any other route.
    consultant = rng.integers(0, cfg.n_consultants, n)
    consultant_effect = rng.normal(0.0, cfg.preference_sd, cfg.n_consultants)
    df["consultant_id"] = consultant

    # The observed preference is the consultant's dialysis rate among their other
    # patients (leave-one-out), which is how the real data was built, so it is built
    # that way here too: a random effect plus measurement noise.
    n_per_consultant = np.bincount(consultant, minlength=cfg.n_consultants)
    measurement_noise = rng.normal(
        0.0, 1.0 / np.sqrt(np.maximum(n_per_consultant[consultant], 1)), n
    )
    preference_logit = consultant_effect[consultant]
    df["consultant_preference"] = _sigmoid(preference_logit - 2.2 + 0.35 * measurement_noise)

    if cfg.instrument_kind == "binary":
        z = (df["consultant_preference"] > df["consultant_preference"].median()).astype(int)
        z_for_treatment = z.to_numpy().astype(float)
    else:
        z = df["consultant_preference"]
        # Standardised before entering the treatment equation, so instrument_strength
        # keeps a stable scale
        z_for_treatment = ((z - z.mean()) / z.std()).to_numpy()
    df["instrument"] = z

    # ---- 4. treatment assignment: U matters (confounding), Z matters monotonically ----
    treatment_linear = (
        0.55 * df["max_aki_stage_smoothed"]
        + 0.085 * (df["sofa_total_24h"] - 6.0)
        + 0.45 * (df["max_potassium"] - 4.6)
        - 0.085 * (df["min_bicarbonate"] - 21.0)
        + 0.0022 * (df["max_creatinine"] - 180.0)
        - 0.0009 * (df["max_uo_12h_ml"] - 450.0)
        + cfg.confounding_on_treatment * u
    ).to_numpy()

    base_linear = treatment_linear + cfg.instrument_strength * z_for_treatment
    intercept_t = _solve_intercept(base_linear, cfg.target_treatment_rate)
    p_treat = _sigmoid(intercept_t + base_linear)

    # One uniform draw decides "would this unit take treatment at each value of Z",
    # so monotonicity holds by construction and the compliance type is readable directly.
    uniform = rng.uniform(0, 1, n)
    df["isDialysisICU"] = (uniform < p_treat).astype(int)

    if cfg.instrument_kind == "binary":
        p_if_z0 = _sigmoid(intercept_t + treatment_linear + cfg.instrument_strength * 0.0)
        p_if_z1 = _sigmoid(intercept_t + treatment_linear + cfg.instrument_strength * 1.0)
        t_if_z0 = (uniform < p_if_z0).astype(int)
        t_if_z1 = (uniform < p_if_z1).astype(int)
        compliance = np.where(
            (t_if_z0 == 1) & (t_if_z1 == 1),
            "always_taker",
            np.where((t_if_z0 == 0) & (t_if_z1 == 0), "never_taker", "complier"),
        )
        df["compliance_type"] = compliance
        is_complier = compliance == "complier"
    else:
        df["compliance_type"] = "unknown"  # no three-way split with a continuous instrument
        is_complier = np.zeros(n, dtype=bool)

    # ---- 5. treatment effect: on the logit scale, heterogeneous, depending on observed X ----
    beta = (
        cfg.effect_base
        + cfg.effect_per_aki_stage * df["max_aki_stage_smoothed"].to_numpy()
        + cfg.effect_per_potassium * (df["max_potassium"].to_numpy() - 4.5)
    )
    if cfg.effect_varies_by_compliance:
        beta = beta + cfg.compliance_effect_shift * is_complier
    df["beta_true"] = beta

    # ---- 6. potential and observed outcomes ----
    outcome_linear = (
        0.30 * df["max_aki_stage_smoothed"]
        + 0.075 * (df["sofa_total_24h"] - 6.0)
        - 0.16 * (df["min_GCS_Total"] - 12.0)
        - 0.030 * (df["min_ArterialPressure"] - 68.0)
        + 0.020 * (df["max_urea"] - 12.0)
        + cfg.confounding_on_outcome * u
    ).to_numpy()
    intercept_y = _solve_intercept(outcome_linear, cfg.target_death_rate)
    logit_p0 = intercept_y + outcome_linear
    p0 = _sigmoid(logit_p0)
    p1 = _sigmoid(logit_p0 + beta)  # additive on the logit scale, so (0,1) by construction
    df["p0_true"] = p0
    df["p1_true"] = p1
    # tau is the risk difference, computed straight from the potential-outcome
    # probabilities, true by construction, and never clipped.
    df["tau_true"] = p1 - p0

    uniform_y = rng.uniform(0, 1, n)
    y0 = (uniform_y < p0).astype(int)
    y1 = (uniform_y < p1).astype(int)
    df["death"] = np.where(df["isDialysisICU"] == 1, y1, y0)

    df["u_true"] = u  # the confounder's true value: for diagnostics only, never an estimator
    df.insert(0, "unit_id", np.arange(1, n + 1))
    return df


def truth(df: pd.DataFrame) -> dict[str, float]:
    """Ground-truth summary for this dataset, for evals to compare against."""
    tau = df["tau_true"].to_numpy()
    treated = df["isDialysisICU"].to_numpy().astype(bool)
    death = df["death"].to_numpy()
    out = {
        "ate_true": float(np.mean(tau)),
        "att_true": float(np.mean(tau[treated])),
        "treatment_rate": float(np.mean(treated)),
        "death_rate": float(np.mean(death)),
        "naive_difference": float(np.mean(death[treated]) - np.mean(death[~treated])),
    }
    compliers = (df["compliance_type"] == "complier").to_numpy()
    if compliers.any():
        out["late_true"] = float(np.mean(tau[compliers]))
        out["complier_share"] = float(np.mean(compliers))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic dataset A with ground truth.")
    parser.add_argument("--out", type=Path, required=True, help="output CSV path (never committed)")
    parser.add_argument("--n", type=int, default=DatasetAConfig.n)
    parser.add_argument("--seed", type=int, default=DatasetAConfig.seed)
    parser.add_argument("--instrument-kind", choices=["continuous", "binary"], default="continuous")
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="realistic",
        help=(
            "realistic = the real study's scale (for demos); "
            "high_power = enough power (for numerical evals)"
        ),
    )
    parser.add_argument(
        "--vary-effect-by-compliance",
        action="store_true",
        help=(
            "let the effect vary by compliance type, so the conditional LATE differs from the CATE"
        ),
    )
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {
        "seed": args.seed,
        "instrument_kind": args.instrument_kind,
        "effect_varies_by_compliance": args.vary_effect_by_compliance,
    }
    if args.n != DatasetAConfig.n:  # only override the preset's n when asked explicitly
        overrides["n"] = args.n
    df = generate(config_for(args.preset, **overrides))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    print(f"wrote {args.out}: {len(df):,} rows x {df.shape[1]} columns")
    for key, value in truth(df).items():
        print(f"  {key:20} {value: .4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

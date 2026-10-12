"""Estimation adapter for hte_iv.

Reuses two EconML (MIT) IV estimators. This file only adapts: read fields from the
spec, infer from the data whether the instrument is discrete, run the estimator, and
turn the output into an addressed Result.

Two backends, selected through ``spec.estimation.params.estimator``:

|               | ``ivforest`` (default)              | ``dmliv``                       |
|---------------|-------------------------------------|---------------------------------|
| estimator     | ``econml.grf.CausalIVForest``       | ``econml.iv.dml.NonParamDMLIV`` |
| CATE interval | GRF honest variance, within one fit | **bootstrap only**              |
| ATE interval  | unit-level bootstrap of the forest  | bootstrap                       |
| cost          | low (about 6s at n=5000)            | high (about 9 min, 20 replicates) |

``NonParamDMLIV``'s final model is an arbitrary regressor, so EconML can derive no
variance for it: ``_get_inference_options()`` lists ``bootstrap`` and nothing else.
That is not a choice, it is the only option. ``CausalIVForest`` uses the
Athey-Tibshirani-Wager honest forest variance and needs no resampling.

**Why the default is ivforest.** The research code's final version uses ``dmliv``,
but the out-of-the-box default should be the one that stands up: a trustworthy
percentile interval needs hundreds of replicates at roughly 26 seconds each, so 200
replicates is an hour and a half. Lowering the count is faster but distorts the
interval, on the same data, 20 replicates and the GRF analytic interval differed by
two orders of magnitude in the count of individuals with a significant benefit (416
against 3). Rather than ship a default that is both slow and untrustworthy, the
analytic interval is the default and ``dmliv`` is kept for a confirmatory run that
matches the paper. How each interval was built is recorded in
``res:cate.ci_method`` and ``res:primary.ate_ci_method``, for the report to show the
reader rather than for the tool to decide on their behalf.

Three differences from the research code (plan.md Phase 0 task 3, "strip the I/O"):

1. **No file writes.** The original called ``joblib.dump(model, f"{model_name}.pkl")``
   inside the function; artefacts now go through core/runtime's atomic writer.
2. **No printing.** The statistics the original printed under ``verbose`` become
   addresses on the Result.
3. **X and W are separate.** The original defined ``controls`` (75 columns) and
   ``features`` (60 columns) but passed only ``features`` as X with ``W=None``,
   silently dropping the difference. In the spec, ``effect_modifiers`` (-> X) and
   ``adjustment_set`` (-> W) are two fields, each confirmed on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

# Imported at module level rather than inside estimate(): a missing dependency then
# surfaces at registry.get(), so the user does not walk the whole spec-confirmation
# flow before discovering the run is impossible. The registry turns the ImportError
# into a structured error carrying the install command.
from econml.grf import CausalIVForest
from econml.inference import BootstrapInference
from econml.iv.dml import NonParamDMLIV
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestRegressor

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.registry import register

if TYPE_CHECKING:
    import pandas as pd

ESTIMATORS = ("dmliv", "ivforest")

# A percentile bootstrap interval needs enough replicates to be trustworthy: on the
# same data, 20 replicates and the GRF analytic interval differed by two orders of
# magnitude in the count of individuals with a significant benefit. Shared by both
# backends; overridable from spec.estimation.params.
DEFAULT_BOOTSTRAP_SAMPLES = 200

# An instrument whose values lie in {0, 1} is treated as binary.
_BINARY_VALUES = frozenset({0, 1})


def _column_names(spec: Spec, field: str) -> list[str]:
    """Read a list-of-column-names field from the spec; missing means empty."""
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _is_binary(series: Any) -> bool:
    return set(series.dropna().unique().tolist()) <= _BINARY_VALUES


def _scalar(value: Any) -> float:
    """EconML's ate / ate_interval return an array over treatment dimensions; with a
    binary treatment, take the first element."""
    return float(np.ravel(value)[0])


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


class HteIv:
    """Heterogeneous treatment effects under an IV design.

    Binary and continuous instruments are both supported: ``discrete_instrument`` is
    inferred from the data and recorded on the Result, because it determines how the
    estimand is to be read (see family.yaml).
    """

    id = "hte_iv"

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        """Instrument relevance and exogeneity checks; thresholds from family.yaml."""
        from causpec.core.registry import load_declaration
        from causpec.families.hte_iv.checks import check_instrument

        return check_instrument(data, spec, load_declaration(self.id).get("checks", {}))

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        backend = str(spec.param("estimator", "ivforest"))
        if backend not in ESTIMATORS:
            raise ValueError(f"estimator must be one of {', '.join(ESTIMATORS)}; got {backend}")

        treatment = _column_names(spec, "treatment")[0]
        outcome = _column_names(spec, "outcome")[0]
        instruments = _column_names(spec, "instrument")
        effect_modifiers = _column_names(spec, "effect_modifiers")
        adjustment_set = _column_names(spec, "adjustment_set")

        if not instruments:
            raise ValueError("hte_iv requires spec.instrument")
        if not effect_modifiers:
            raise ValueError("hte_iv requires spec.effect_modifiers (the CATE covariate set X)")

        y = data[outcome].to_numpy().ravel().astype(int)
        t = data[treatment].to_numpy().ravel().astype(int)
        z = data[instruments]
        x = data[effect_modifiers].astype(float).to_numpy()
        w = data[adjustment_set].astype(float).to_numpy() if adjustment_set else None

        discrete_instrument = all(_is_binary(z.loc[:, column]) for column in z.columns)

        if backend == "dmliv":
            values = self._fit_dmliv(y, t, z, x, w, spec, seed, discrete_instrument)
        else:
            values = self._fit_ivforest(y, t, z, x, w, spec, seed, adjustment_set)

        values.update(
            {
                "res:sample.n": int(len(data)),
                "res:sample.n_treated": int(t.sum()),
                "res:sample.n_control": int(len(t) - t.sum()),
                "res:sample.treatment_rate": float(t.mean()),
                "res:sample.outcome_rate": float(y.mean()),
                # Per arm as well as overall, because the E-value needs a risk ratio and the
                # ratio is formed from these two rather than through one of the paper's
                # approximate conversions from a risk difference.
                "res:sample.outcome_rate_treated": float(y[t == 1].mean())
                if (t == 1).any()
                else 0.0,
                "res:sample.outcome_rate_control": float(y[t == 0].mean())
                if (t == 0).any()
                else 0.0,
                "res:instrument.kind": "binary" if discrete_instrument else "continuous",
                "res:instrument.n_columns": len(instruments),
                "res:design.n_effect_modifiers": len(effect_modifiers),
                "res:design.n_adjustment_covariates": len(adjustment_set),
                "res:estimation.estimator": backend,
            }
        )
        return Result(family=self.id, seed=seed, values=values)

    # ---- backend one: NonParamDMLIV (matches the research code's final version) ----

    def _fit_dmliv(self, y, t, z, x, w, spec: Spec, seed: int, discrete_instrument: bool):
        # Hyper-parameters come from spec.estimation.params: they change the result, so
        # they must enter spec_hash and the manifest rather than being hard-coded here
        # (design.md 7.2, G5). Defaults follow the research code's final version.
        model_final = RandomForestRegressor(
            n_estimators=spec.param("n_estimators", 300),
            max_depth=spec.param("max_depth", 5),
            min_samples_leaf=spec.param("min_samples_leaf", 30),
            max_features=spec.param("max_features", "sqrt"),
            n_jobs=spec.param("model_n_jobs", 1),
            random_state=seed,
        )
        estimator = NonParamDMLIV(
            model_y_xw="auto",
            model_t_xw="auto",
            model_t_xwz="auto",
            model_final=model_final,
            discrete_outcome=True,
            discrete_treatment=True,
            discrete_instrument=discrete_instrument,
            cv=spec.param("cv", 5),
            random_state=seed,
        )
        # Bootstrap's default of 100 replicates at n_jobs=-1 exhausts memory (observed:
        # SIGKILL). Set the replicate count and parallelism explicitly; both are
        # overridable from the spec.
        n_bootstrap = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        estimator.fit(
            Y=y,
            T=t,
            Z=z,
            X=x,
            W=w,
            inference=BootstrapInference(
                n_bootstrap_samples=n_bootstrap,
                n_jobs=spec.param("bootstrap_n_jobs", 1),
            ),
        )

        cate = estimator.effect(X=x, T0=0, T1=1).ravel()
        lower, upper = estimator.effect_interval(X=x, T0=0, T1=1, alpha=0.05)
        ate_lower, ate_upper = estimator.ate_interval(X=x, alpha=0.05)

        values: dict[str, float | int | str] = {
            "res:primary.ate": _scalar(estimator.ate(X=x)),
            "res:primary.ate_ci_lower": _scalar(ate_lower),
            "res:primary.ate_ci_upper": _scalar(ate_upper),
            "res:cate.ci_method": "bootstrap",
            "res:primary.ate_ci_method": "bootstrap",
            "res:estimation.n_bootstrap_samples": n_bootstrap,
            "res:estimation.bootstrap_adequate": "yes" if n_bootstrap >= 100 else "no",
            "res:estimation.n_estimators": int(spec.param("n_estimators", 300)),
        }
        values.update(self._cate_addresses(cate, np.ravel(lower), np.ravel(upper)))
        return values

    # ---- backend two: CausalIVForest (analytic CATE interval, cheap) ----

    @staticmethod
    def _build_forest(spec: Spec, seed: int, n_estimators: int, subforest_size: int):
        return CausalIVForest(
            n_estimators=n_estimators,
            criterion=spec.param("criterion", "het"),
            min_samples_leaf=spec.param("min_samples_leaf", 10),
            min_var_fraction_leaf=spec.param("min_var_fraction_leaf", 0.05),
            honest=True,
            inference=True,
            subforest_size=subforest_size,
            n_jobs=spec.param("model_n_jobs", 1),
            random_state=seed,
        )

    def _bootstrap_ate_interval(
        self, x, t, y, z_values, spec: Spec, seed: int, n_estimators: int, subforest_size: int
    ) -> tuple[float, float]:
        """Percentile interval for the ATE, from a unit-level bootstrap.

        Each replicate resamples observations, refits the forest, then predicts on the
        **original X** and averages, so the estimand stays the ATE over the original
        sample's covariate distribution.

        Why not the forest's own variance: ``predict_and_var``, ``prediction_stderr``
        and the rest are all **pointwise** (the covariance matrix from
        ``predict_and_var`` is across output dimensions at a single x, not across
        different x). The per-point estimates from one forest are highly correlated, so
        averaging pointwise variances and dividing by n would assume independence,
        which is wrong. econml.grf exposes nothing for the variance of a sample average.

        ``n_bootstrap_samples`` sets the replicate count (shared with dmliv) and
        ``bootstrap_n_jobs`` the parallelism. All resample indices are drawn up front,
        so parallelism cannot change the result and a fixed seed reproduces it.
        """
        n_bootstrap = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        rng = np.random.default_rng(seed)
        n = len(y)
        indices = [rng.integers(0, n, n) for _ in range(n_bootstrap)]

        def one_replicate(rep: int, idx: np.ndarray) -> float:
            forest = self._build_forest(spec, seed + rep + 1, n_estimators, subforest_size)
            forest.fit(X=x[idx], T=t[idx], y=y[idx], Z=z_values[idx])
            return float(np.mean(np.ravel(forest.predict(x))))

        # joblib cannot type Parallel's return; collect it explicitly.
        ates = np.asarray(
            Parallel(n_jobs=spec.param("bootstrap_n_jobs", 1))(
                delayed(one_replicate)(rep, idx) for rep, idx in enumerate(indices)
            ),
            dtype=float,
        )
        # Percentile method, matching dmliv (EconML's BootstrapInference). Note it is
        # **not guaranteed** to bracket the point estimate: an honest forest shrinks
        # towards the mean, so the resampling distribution can sit systematically off
        # theta-hat. Centring on theta-hat means the basic (reverse-percentile) method,
        # which is a different choice, expose it through the spec if wanted, rather
        # than switching silently here.
        lower, upper = np.percentile(ates, [2.5, 97.5])
        return float(lower), float(upper)

    def _fit_ivforest(self, y, t, z, x, w, spec: Spec, seed: int, adjustment_set: list[str]):
        if adjustment_set:
            raise ValueError(
                "the ivforest backend does not accept adjustment_set: CausalIVForest has "
                "no separate W channel and adjusts on X only. Either fold these variables "
                "into effect_modifiers and confirm that change, or switch to "
                "estimator=dmliv."
            )
        if z.shape[1] != 1:
            raise ValueError(f"the ivforest backend supports a single instrument; got {z.shape[1]}")

        # GRF's honest variance splits the forest into sub-forests of subforest_size, so
        # n_estimators must divide evenly. Say so plainly rather than passing econml's
        # own message straight through.
        subforest_size = int(spec.param("subforest_size", 4))
        n_estimators = int(spec.param("n_estimators", 300))
        if n_estimators % subforest_size:
            raise ValueError(
                f"ivforest's n_estimators ({n_estimators}) must be divisible by "
                f"subforest_size ({subforest_size}), GRF's variance estimate groups by "
                f"sub-forest. Use {n_estimators - n_estimators % subforest_size} or "
                f"{n_estimators + subforest_size - n_estimators % subforest_size}."
            )

        z_values = z.to_numpy().ravel()
        forest = self._build_forest(spec, seed, n_estimators, subforest_size)
        forest.fit(X=x, T=t, y=y, Z=z_values)

        cate = np.ravel(forest.predict(x))
        interval = forest.predict_interval(x, alpha=0.05)
        lower, upper = np.ravel(interval[0]), np.ravel(interval[1])

        n_bootstrap = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        ate_lower, ate_upper = self._bootstrap_ate_interval(
            x, t, y, z_values, spec, seed, n_estimators, subforest_size
        )

        values: dict[str, float | int | str] = {
            "res:primary.ate": float(np.mean(cate)),
            "res:primary.ate_ci_lower": ate_lower,
            "res:primary.ate_ci_upper": ate_upper,
            # The CATE and ATE intervals come from different mechanisms; record them
            # separately so the report can explain each.
            "res:cate.ci_method": "grf_honest",
            "res:primary.ate_ci_method": "forest_bootstrap",
            "res:estimation.n_bootstrap_samples": n_bootstrap,
            "res:estimation.bootstrap_adequate": "yes" if n_bootstrap >= 100 else "no",
            "res:estimation.n_estimators": n_estimators,
        }
        values.update(self._cate_addresses(cate, lower, upper))
        return values

    # ---- shared ----

    @staticmethod
    def _cate_addresses(cate, lower, upper) -> dict[str, float | int | str]:
        values: dict[str, float | int | str] = dict(_distribution("res:cate", cate))
        # Individual-level significance: the whole interval on one side of zero. This is
        # the addressed version of the research code's "significant beneficial patients".
        values["res:cate.n_significant_benefit"] = int(np.sum(upper < 0))
        values["res:cate.n_significant_harm"] = int(np.sum(lower > 0))
        values["res:cate.ci_width_median"] = float(np.median(upper - lower))
        return values


register(HteIv())

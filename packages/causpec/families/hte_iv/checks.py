"""hte_iv's own quality checks: instrument relevance and exogeneity.

Mirrors design.md 8.2 (instrument relevance) and 10.2 (one of the two blocking
checks). Migrated from the research code's ``test_iv_validity`` (the robust version
in IV.ipynb), keeping every diagnostic but emitting addressed QualityIssues, and
adding two things the original lacked:

1. **A multiple-comparison correction.** The original reported a p-value per
   covariate. Out of 60 covariates, roughly 3 will be "significant" at 0.05 by chance
   alone; without a correction that noise reads as imbalance. Benjamini-Hochberg
   controls the FDR here.
2. **Thresholds outside the code.** Where the line falls is declared in family.yaml,
   not buried here, thresholds decide how strongly a conclusion may be worded, so
   they must be fixed in advance and end up in the report and the manifest.

The form of the diagnostic is the family's business, not a universal first-stage F
(design.md 8.2): the treatment is binary, so the first stage reports both a probit LR
test with a McFadden increment and a linear robust F with a partial R-squared. All of
them go into the report for the reader to weigh.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import statsmodels.api as sm
from scipy import stats

from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:
    import pandas as pd

ROBUST_COV = "HC1"
# linearmodels spells the same thing differently, and passing statsmodels' name raises a bare
# KeyError('HC1') from inside its covariance registry. Two constants rather than one, so the
# two libraries' vocabularies do not get conflated.
ROBUST_COV_LINEARMODELS = "robust"


def _threshold(config: dict[str, Any], check_id: str, key: str, default: float) -> float:
    return float(config.get(check_id, {}).get(key, default))


def _issue_settings(config: dict[str, Any], check_id: str) -> tuple[Layer, Severity, bool]:
    entry = config.get(check_id, {})
    return (
        Layer(entry.get("layer", "identification")),
        Severity(entry.get("severity", "warning")),
        bool(entry.get("waivable", True)),
    )


def benjamini_hochberg(p_values: np.ndarray, level: float) -> np.ndarray:
    """The BH procedure: which hypotheses are rejected at a given FDR level.

    Written by hand rather than pulled from statsmodels.multitest: it is a six-line
    closed-form procedure, and having it here makes it easy to check against the
    original paper (Benjamini & Hochberg 1995, JRSS-B).
    """
    n = len(p_values)
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p_values)
    ranked = p_values[order]
    # The largest k with p_(k) <= k/n * level; that k and everything before it is rejected.
    below = ranked <= (np.arange(1, n + 1) / n) * level
    rejected = np.zeros(n, dtype=bool)
    if below.any():
        cutoff = int(np.max(np.flatnonzero(below)))
        rejected[order[: cutoff + 1]] = True
    return rejected


def _design_matrix(data: pd.DataFrame, columns: list[str]) -> np.ndarray:
    matrix = data[columns].astype(float).to_numpy()
    return np.asarray(sm.add_constant(matrix, has_constant="add"), dtype=float)


def _endogeneity_test(
    treatment: np.ndarray,
    outcome: np.ndarray,
    data: pd.DataFrame,
    instruments: list[str],
    controls: list[str],
) -> dict[str, float]:
    """Wooldridge's regression test: does the treatment behave endogenously?

    Three lines of OLS, so written here rather than imported. Add the first-stage residual to
    the structural equation and test its coefficient robustly: if the treatment were exogenous
    the residual would carry no information about the outcome. Checked against linearmodels'
    ``wooldridge_score`` on four designs, where it agrees to four significant figures
    (0.01923 against 0.01923 on the project's own fixture).
    """
    instrument_design = _design_matrix(data, instruments + controls)
    first_stage_residual = sm.OLS(treatment, instrument_design).fit().resid
    control_design = _design_matrix(data, controls) if controls else np.ones((len(treatment), 1))
    augmented = np.column_stack([treatment, control_design, first_stage_residual])
    fitted = sm.OLS(outcome, augmented).fit(cov_type=ROBUST_COV)
    return {
        "endogeneity_statistic": float(fitted.tvalues[-1] ** 2),
        "endogeneity_p_value": float(fitted.pvalues[-1]),
    }


def _overidentification_test(
    data: pd.DataFrame,
    treatment_col: str,
    outcome_col: str,
    instruments: list[str],
    controls: list[str],
) -> dict[str, float]:
    """Robust overidentification, from linearmodels' 2SLS (NCSA licence).

    The one statistic in this module taken from a package, and the reason is a measurement
    rather than a preference. ADR-0003 rejected a dependency whose checks were one call each;
    this one failed that test in the other direction. A hand-rolled version, regressing the
    structural residual on the instruments and testing their coefficients jointly, came out at
    p = 0.24 where this gives 0.092, because the overidentification degrees of freedom are
    k - 1 rather than k. Every verdict happened to agree on the four designs it was tried on,
    which is how that ships unnoticed. The correct robust procedure (Wooldridge 2010, 6.1)
    projects a chosen subset of instruments and has no published numerical example to check a
    hand-written version against, unlike the E-value.

    **It describes a linear specification, not the forest.** The estimator for this family is
    a causal forest or a non-parametric DMLIV; this fits a scalar 2SLS alongside it so the
    instruments can be interrogated at all. A diagnostic about the linear specification is
    informative about the instruments and is not inference about the CATE, and the issue text
    says so.

    Deliberately not taken from the package: Shea's partial R-squared, which with a single
    endogenous treatment equals the ordinary partial R-squared however many instruments there
    are; the first-stage F, already computed here in a probit form that suits a binary
    treatment better; and the endogeneity test, which is three lines of OLS above.
    """
    import pandas as pd
    from linearmodels.iv import IV2SLS

    exog = pd.DataFrame({"const": np.ones(len(data))}, index=data.index)
    for column in controls:
        exog[column] = data[column].astype(float).to_numpy()
    # Typed as Any because linearmodels declares fit() as returning OLSResults, which is what
    # it gives when a model has no endogenous variable. One is always passed here, so the
    # result is an IVResults and carries the two statistics below.
    fitted: Any = IV2SLS(
        data[outcome_col].astype(float),
        exog,
        data[treatment_col].astype(float),
        data[instruments].astype(float),
    ).fit(cov_type=ROBUST_COV_LINEARMODELS)

    overid = fitted.wooldridge_overid
    return {
        "linear_iv_estimate": float(np.ravel(fitted.params[treatment_col])[0]),
        "overid_statistic": float(overid.stat),
        "overid_p_value": float(overid.pval),
    }


def _first_stage_linear(
    treatment: np.ndarray, data: pd.DataFrame, instruments: list[str], controls: list[str]
) -> dict[str, float]:
    """Linear first stage: robust F and partial R-squared.

    The partial R-squared goes through Frisch-Waugh-Lovell: residualise both T and Z
    on the controls, then take the R-squared between the residuals, that is Z's
    explanatory power for T once the controls are held fixed.
    """
    full = sm.OLS(treatment, _design_matrix(data, instruments + controls)).fit(cov_type=ROBUST_COV)

    # Joint test that every instrument coefficient is zero. The constant sits in column
    # 0 and the instruments follow immediately.
    n_params = full.params.shape[0]
    restriction = np.zeros((len(instruments), n_params))
    for row, col in enumerate(range(1, len(instruments) + 1)):
        restriction[row, col] = 1.0
    wald = full.f_test(restriction)

    z_matrix = data[instruments].astype(float).to_numpy()
    if controls:
        control_matrix = _design_matrix(data, controls)
        resid_t = sm.OLS(treatment, control_matrix).fit().resid
        resid_z = np.column_stack(
            [sm.OLS(z_matrix[:, j], control_matrix).fit().resid for j in range(z_matrix.shape[1])]
        )
    else:
        resid_t = treatment - treatment.mean()
        resid_z = z_matrix - z_matrix.mean(axis=0)
    partial = sm.OLS(resid_t, sm.add_constant(resid_z, has_constant="add")).fit()

    return {
        "robust_f": float(np.ravel(wald.fvalue)[0]),
        "robust_f_p_value": float(np.ravel(wald.pvalue)[0]),
        "partial_r2": float(partial.rsquared),
    }


def _first_stage_probit(
    treatment: np.ndarray, data: pd.DataFrame, instruments: list[str], controls: list[str]
) -> dict[str, float]:
    """Probit first stage: an LR test for joint significance and a McFadden increment.

    The treatment is binary, so the linear first-stage F is only an approximation; the
    probit version fits the setting better. Both are reported (design.md 8.2: the form
    of the diagnostic is the family's business).
    """
    unrestricted = sm.Probit(treatment, _design_matrix(data, instruments + controls)).fit(
        disp=False, maxiter=200
    )
    restricted_design = _design_matrix(data, controls) if controls else np.ones((len(treatment), 1))
    restricted = sm.Probit(treatment, restricted_design).fit(disp=False, maxiter=200)

    lr_stat = float(-2.0 * (restricted.llf - unrestricted.llf))
    df = len(instruments)
    return {
        "lr_statistic": lr_stat,
        "lr_p_value": float(stats.chi2.sf(lr_stat, df)),
        # McFadden R-squared relative to "controls only": how much the instruments add.
        "mcfadden_r2_increment": float(1.0 - unrestricted.llf / restricted.llf),
    }


def _covariate_balance(
    data: pd.DataFrame, instruments: list[str], covariates: list[str], level: float
) -> tuple[dict[str, float], np.ndarray]:
    """Regress each covariate on the instruments, take the joint p-value, apply BH.

    If the instrument really is close to randomly assigned, the covariates should be
    balanced across it. This is a **necessary** condition for "the instrument is
    independent of unmeasured confounders", imbalance is a bad sign, but balance is
    not evidence that the exclusion restriction holds, since that one cannot be tested
    at all.
    """
    p_values = []
    z_design = _design_matrix(data, instruments)
    n_params = z_design.shape[1]
    restriction = np.zeros((len(instruments), n_params))
    for row, col in enumerate(range(1, len(instruments) + 1)):
        restriction[row, col] = 1.0

    for column in covariates:
        y = data[column].astype(float).to_numpy()
        fit = sm.OLS(y, z_design).fit(cov_type=ROBUST_COV)
        p_values.append(float(np.ravel(fit.f_test(restriction).pvalue)[0]))

    array = np.asarray(p_values, dtype=float)
    return dict(zip(covariates, p_values, strict=True)), benjamini_hochberg(array, level)


def _backend_supports_spec(
    spec: Spec, instruments: list[str], config: dict[str, Any]
) -> QualityIssue:
    """Whether the chosen backend can run the spec as written.

    Two limits belong to `ivforest` and not to the family: `CausalIVForest` has no separate W
    channel, so it adjusts on X only, and it takes a single instrument. The estimator refuses
    both, correctly, but it refused after the data was read and every check had run, as a
    `ValueError` with a stack trace. These are preconditions readable from the spec, so they
    belong where the other findings are, in the report, before anything is fitted.
    """
    check_id = "iv_backend_supports_spec"
    layer, severity, waivable = _issue_settings(config, check_id)
    backend = str(spec.param("estimator", "ivforest"))
    adjustment = _adjustment_names(spec)

    problems: list[str] = []
    if backend == "ivforest":
        if adjustment:
            problems.append(
                f"an adjustment_set of {len(adjustment)} column(s) "
                f"({', '.join(adjustment)}), which ivforest has no channel for"
            )
        if len(instruments) > 1:
            problems.append(f"{len(instruments)} instruments, where ivforest takes one")

    evidence: dict[str, float | int | str | bool] = {
        "backend": backend,
        "n_instruments": len(instruments),
        "n_adjustment_set": len(adjustment),
        "passed": not problems,
    }
    if not problems:
        return QualityIssue(
            check_id=check_id,
            layer=layer,
            severity=Severity.INFO,
            waivable=waivable,
            summary=f"the {backend} backend can run this spec as written",
            evidence=evidence,
        )
    return QualityIssue(
        check_id=check_id,
        layer=layer,
        severity=severity,
        waivable=waivable,
        summary=f"the {backend} backend cannot run this spec: it declares " + "; ".join(problems),
        evidence=evidence,
        affected_columns=adjustment,
        impact_on_analysis=(
            "Nothing is estimated, so this is a configuration error rather than a finding "
            "about the data. It is reported here because it is readable from the spec, and "
            "the alternative is a stack trace after every check has already run."
        ),
        recommended_repair=(
            "Either move those variables into effect_modifiers, which changes the estimand "
            "because the effect is then allowed to vary over them and the user has to confirm "
            "it, or set estimation.params.estimator to dmliv, which has a W channel and takes "
            "several instruments at the cost of bootstrap-only intervals. `hte-dmliv.md` has "
            "the comparison."
        ),
    )


def _adjustment_names(spec: Spec) -> list[str]:
    from causpec.families.hte_iv.estimator import _column_names

    return _column_names(spec, "adjustment_set")


def check_instrument(
    data: pd.DataFrame, spec: Spec, config: dict[str, Any] | None = None
) -> QualityReport:
    """Run every instrument check for hte_iv and return addressed issues.

    ``config`` is the ``checks`` section of family.yaml; omitting it falls back to the
    defaults written here.
    """
    from causpec.families.hte_iv.estimator import _column_names

    config = config or {}
    treatment_col = _column_names(spec, "treatment")[0]
    instruments = _column_names(spec, "instrument")
    covariates = _column_names(spec, "effect_modifiers") + _column_names(spec, "adjustment_set")
    if not instruments:
        raise ValueError("hte_iv's quality checks require spec.instrument")

    treatment = data[treatment_col].astype(float).to_numpy()
    issues: list[QualityIssue] = [_backend_supports_spec(spec, instruments, config)]

    # ---- 1. does the instrument vary at all ----
    layer, severity, waivable = _issue_settings(config, "iv_zero_variation")
    min_unique = int(_threshold(config, "iv_zero_variation", "min_unique_values", 2))
    min_std = _threshold(config, "iv_zero_variation", "min_std", 1e-8)
    degenerate = [
        column
        for column in instruments
        if data[column].nunique() < min_unique or float(np.std(data[column].to_numpy())) < min_std
    ]
    if degenerate:
        issues.append(
            QualityIssue(
                check_id="iv_zero_variation",
                layer=layer,
                severity=severity,
                waivable=waivable,
                summary=(
                    f"the instrument barely varies in this population: {', '.join(degenerate)}"
                ),
                evidence={
                    "n_degenerate": len(degenerate),
                    "min_unique_values": min_unique,
                    "passed": False,
                },
                affected_columns=degenerate,
                impact_on_analysis=(
                    "There is nothing for the first stage to identify, so an IV estimate "
                    "cannot be produced."
                ),
                recommended_repair=(
                    "Check whether the population filter removed the instrument's "
                    "variation, or choose a different instrument."
                ),
            )
        )
        return QualityReport(issues=issues)  # nothing further is computable

    # ---- 2. first-stage strength (blocking) ----
    linear = _first_stage_linear(treatment, data, instruments, covariates)
    probit = _first_stage_probit(treatment, data, instruments, covariates)
    layer, severity, waivable = _issue_settings(config, "iv_weak_first_stage")
    min_f = _threshold(config, "iv_weak_first_stage", "min_robust_f", 10.0)
    max_lr_p = _threshold(config, "iv_weak_first_stage", "max_lr_p_value", 0.05)
    passed = linear["robust_f"] >= min_f and probit["lr_p_value"] <= max_lr_p
    issues.append(
        QualityIssue(
            check_id="iv_weak_first_stage",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=(
                f"first-stage robust F = {linear['robust_f']:.2f} (threshold {min_f:g}), "
                f"probit LR test p = {probit['lr_p_value']:.4f}"
            ),
            evidence={
                "robust_f": round(linear["robust_f"], 4),
                "robust_f_threshold": min_f,
                "robust_f_p_value": round(linear["robust_f_p_value"], 6),
                "partial_r2": round(linear["partial_r2"], 6),
                "lr_statistic": round(probit["lr_statistic"], 4),
                "lr_p_value": round(probit["lr_p_value"], 6),
                "lr_p_value_threshold": max_lr_p,
                "mcfadden_r2_increment": round(probit["mcfadden_r2_increment"], 6),
                "passed": passed,
            },
            affected_columns=instruments,
            impact_on_analysis=(
                "Under a weak instrument the bias in an IV estimate can be arbitrarily "
                "large and the confidence interval loses its coverage; the conclusion "
                "may not be worded above associational."
                if not passed
                else "First-stage strength meets the threshold."
            ),
            recommended_repair=(
                "Use a stronger instrument, or switch to an identification strategy that "
                "does not need one (if no unmeasured confounding can be argued). A waiver "
                "must state its reason."
                if not passed
                else ""
            ),
        )
    )

    # ---- 3. complier share (binary instruments only) ----
    if len(instruments) == 1 and set(data[instruments[0]].dropna().unique()) <= {0, 1}:
        z = data[instruments[0]].to_numpy()
        share = float(treatment[z == 1].mean() - treatment[z == 0].mean())
        layer, severity, waivable = _issue_settings(config, "iv_low_complier_share")
        min_share = _threshold(config, "iv_low_complier_share", "min_complier_share", 0.05)
        passed = share >= min_share
        issues.append(
            QualityIssue(
                check_id="iv_low_complier_share",
                layer=layer,
                severity=severity if not passed else Severity.INFO,
                waivable=waivable,
                summary=f"complier share about {share:.1%} (threshold {min_share:.0%})",
                evidence={
                    "complier_share": round(share, 6),
                    "threshold": min_share,
                    "n_treated_if_z1": int(treatment[z == 1].sum()),
                    "n_treated_if_z0": int(treatment[z == 0].sum()),
                    "passed": passed,
                },
                affected_columns=instruments,
                impact_on_analysis=(
                    "The estimand is the conditional LATE among compliers. A small "
                    "complier share means the conclusion holds only for a narrow slice of "
                    "the population, and compliers cannot be identified individually, "
                    "the report has to say so."
                ),
                recommended_repair=(
                    "Nothing to repair, but the report must state which population the "
                    "estimand applies to."
                ),
            )
        )

    # ---- 4. covariate balance (BH-corrected) ----
    if covariates:
        layer, severity, waivable = _issue_settings(config, "iv_covariate_imbalance")
        fdr = _threshold(config, "iv_covariate_imbalance", "fdr_level", 0.10)
        max_fraction = _threshold(config, "iv_covariate_imbalance", "max_imbalanced_fraction", 0.10)
        p_values, rejected = _covariate_balance(data, instruments, covariates, fdr)
        imbalanced = [name for name, flag in zip(covariates, rejected, strict=True) if flag]
        fraction = len(imbalanced) / len(covariates)
        passed = fraction <= max_fraction
        n_naive = sum(1 for p in p_values.values() if p < 0.05)
        issues.append(
            QualityIssue(
                check_id="iv_covariate_imbalance",
                layer=layer,
                severity=severity if not passed else Severity.INFO,
                waivable=waivable,
                summary=(
                    f"{len(imbalanced)}/{len(covariates)} covariates are imbalanced across "
                    f"the instrument (BH FDR {fdr:g})"
                ),
                evidence={
                    "n_covariates": len(covariates),
                    "n_imbalanced": len(imbalanced),
                    "imbalanced_fraction": round(fraction, 6),
                    "threshold": max_fraction,
                    "fdr_level": fdr,
                    # How many would look "significant" without the correction, to show
                    # why the correction is needed.
                    "n_nominally_significant": n_naive,
                    "min_p_value": round(min(p_values.values()), 6),
                    "passed": passed,
                },
                affected_columns=imbalanced,
                impact_on_analysis=(
                    "The instrument is associated with covariates, so it may not be close "
                    "to randomly assigned, which weakens the case for 'the instrument is "
                    "independent of unmeasured confounders'. This is a failed necessary "
                    "condition, balance on its own would not be evidence for the "
                    "exclusion restriction."
                ),
                recommended_repair=(
                    "Add the imbalanced covariates to the adjustment set, or re-argue the "
                    "instrument's exogeneity."
                ),
            )
        )

    # ---- 5. overidentification and endogeneity, on a linear 2SLS specification ----
    issues.extend(_two_stage_issues(data, spec, config, treatment_col, instruments, covariates))
    return QualityReport(issues=issues)


def _issue_from(
    config: dict[str, Any],
    check_id: str,
    passed: bool,
    summary: str,
    evidence: dict[str, float | int | str | bool],
    affected_columns: list[str] | None = None,
    impact: str = "",
    repair: str = "",
) -> QualityIssue:
    layer, severity, waivable = _issue_settings(config, check_id)
    return QualityIssue(
        check_id=check_id,
        layer=layer,
        severity=Severity.INFO if passed else severity,
        waivable=waivable,
        summary=summary,
        evidence={**evidence, "passed": passed},
        affected_columns=affected_columns or [],
        impact_on_analysis=impact,
        recommended_repair=repair,
    )


def _two_stage_issues(
    data: pd.DataFrame,
    spec: Spec,
    config: dict[str, Any],
    treatment_col: str,
    instruments: list[str],
    covariates: list[str],
) -> list[QualityIssue]:
    """Two diagnostics from linearmodels, both about the instruments rather than the CATE."""
    from causpec.families.hte_iv.estimator import _column_names

    outcome_names = _column_names(spec, "outcome")
    if not outcome_names:
        return []
    treatment = data[treatment_col].astype(float).to_numpy()
    outcome = data[outcome_names[0]].astype(float).to_numpy()
    try:
        measured = _endogeneity_test(treatment, outcome, data, instruments, covariates)
        if len(instruments) > 1:
            measured.update(
                _overidentification_test(
                    data, treatment_col, outcome_names[0], instruments, covariates
                )
            )
    except (ValueError, np.linalg.LinAlgError, KeyError) as error:
        # Narrow on purpose. A bare `except Exception` here reported a NameError in this
        # module as "the linear specification did not fit", which reads as a finding about
        # the data: a bug would have been presented to the user as a property of their table.
        # What a fit can legitimately raise is a singular design, a rank failure, or a column
        # that is not there; anything else is ours and should surface as itself.
        return [
            _issue_from(
                config,
                "iv_overidentification",
                passed=True,
                summary=f"not assessed: the linear 2SLS specification did not fit ({error})",
                evidence={"assessed": False},
                impact=(
                    "This diagnostic did not run; its absence is not evidence about the "
                    "instruments."
                ),
            )
        ]

    issues: list[QualityIssue] = []

    # Overidentification needs something to compare: with one instrument there is nothing for
    # the instruments to disagree about.
    if "overid_p_value" in measured:
        minimum = _threshold(config, "iv_overidentification", "min_p_value", 0.05)
        p_value = measured["overid_p_value"]
        issues.append(
            _issue_from(
                config,
                "iv_overidentification",
                passed=p_value >= minimum,
                summary=(
                    f"the {len(instruments)} instruments agree "
                    f"(robust overidentification p = {p_value:.3g})"
                    if p_value >= minimum
                    else f"the {len(instruments)} instruments disagree about the effect "
                    f"(robust overidentification p = {p_value:.3g}, threshold {minimum:g})"
                ),
                evidence={
                    "assessed": True,
                    "n_instruments": len(instruments),
                    "overid_statistic": round(measured["overid_statistic"], 4),
                    "overid_p_value": round(p_value, 6),
                    "min_p_value": minimum,
                    "linear_iv_estimate": round(measured["linear_iv_estimate"], 6),
                },
                affected_columns=instruments,
                impact=(
                    "There are two readings and they call for opposite responses. Either at "
                    "least one instrument violates the exclusion restriction, in which case "
                    "the estimate is biased by an amount nothing here can bound. Or every "
                    "instrument is valid and they identify different complier groups, which is "
                    "expected in this family: with a heterogeneous effect, two valid "
                    "instruments estimate two different weighted averages of individual "
                    "effects and the test rejects for that reason alone. Measured on this "
                    "project's own generator, a valid pair that splits the same preference two "
                    "ways gives p = 0.06 while an invalid one gives p = 0 and a twelvefold "
                    "change in the estimate. That is why this warns rather than blocks."
                ),
                repair=(
                    "Estimate with each instrument alone and compare. Estimates that differ in "
                    "magnitude but agree in sign point at heterogeneity, and the honest "
                    "response is to report whose effect each instrument identifies. Estimates "
                    "that disagree in sign point at exclusion, and then the question is which "
                    "instrument moves the outcome by a path that does not run through the "
                    "treatment."
                ),
            )
        )

    maximum = _threshold(config, "iv_treatment_exogeneity", "max_p_value", 0.10)
    p_value = measured["endogeneity_p_value"]
    issues.append(
        _issue_from(
            config,
            "iv_treatment_exogeneity",
            passed=p_value <= maximum,
            summary=(
                f"the treatment behaves endogenously (p = {p_value:.3g}), so an instrument "
                f"earns its variance cost"
                if p_value <= maximum
                else f"the data does not show the treatment behaving endogenously "
                f"(p = {p_value:.3g}), so the instrument may be paying for nothing"
            ),
            evidence={
                "assessed": True,
                "endogeneity_statistic": round(measured["endogeneity_statistic"], 4),
                "endogeneity_p_value": round(p_value, 6),
                "max_p_value": maximum,
            },
            affected_columns=[treatment_col],
            impact=(
                "An instrument buys protection from unmeasured confounding and pays for it in "
                "variance, often by an order of magnitude. When the data cannot distinguish "
                "the treatment from an exogenous one, that protection may be bought for "
                "nothing, and plain adjustment would answer the same question far more "
                "precisely. **Failing to reject is not evidence of exogeneity**: the test is "
                "weak, and the user's judgement about unmeasured confounding stands above it."
            ),
            repair=(
                "Nothing to repair in the data. Report both, what the instrument gives and what "
                "plain adjustment gives, and let the user see the width of each. If they still "
                "believe something unmeasured drives the treatment, the instrument is the right "
                "choice whatever this test says."
            ),
        )
    )
    return issues

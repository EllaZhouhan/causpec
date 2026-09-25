"""hte_iv 的专属质量检查：instrument 的相关性与外生性。

对应 design.md 8.2（instrument relevance）与 10.2（两项阻断检验之一）。
迁自研究代码的 ``test_iv_validity``（IV.ipynb 的 robust 版本），保留全部诊断量，
输出改为带地址的 QualityIssue，并补上两处：

1. **多重比较校正。** 原代码逐个协变量报 p 值。60 个协变量里平均有 3 个会在
   0.05 下"显著"纯属偶然，不校正就会把噪声读成失衡。这里用 Benjamini–Hochberg
   控制 FDR。
2. **阈值外置。** 通过或不通过的线写在 family.yaml 里，不埋在代码中——
   它们决定结论能用多强的措辞，必须事先定死、进报告、进 manifest。

诊断形式由 family 决定，不统一使用 first-stage F（design.md 8.2）：treatment 是
二值，所以一阶段同时给出 Probit 的 LR 检验与 McFadden 增量 R²，以及线性一阶段的
稳健 F 与 partial R²。三者一并进报告，由读者判断。
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
    """BH 过程：返回哪些假设在给定 FDR 水平下被拒绝。

    自写而非引入 statsmodels.multitest，因为这是六行的闭式过程，
    自己写便于对照原文（Benjamini & Hochberg 1995, JRSS-B）。
    """
    n = len(p_values)
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p_values)
    ranked = p_values[order]
    # 最大的 k 使得 p_(k) <= k/n * level；该 k 及之前全部拒绝
    below = ranked <= (np.arange(1, n + 1) / n) * level
    rejected = np.zeros(n, dtype=bool)
    if below.any():
        cutoff = int(np.max(np.flatnonzero(below)))
        rejected[order[: cutoff + 1]] = True
    return rejected


def _design_matrix(data: pd.DataFrame, columns: list[str]) -> np.ndarray:
    matrix = data[columns].astype(float).to_numpy()
    return np.asarray(sm.add_constant(matrix, has_constant="add"), dtype=float)


def _first_stage_linear(
    treatment: np.ndarray, data: pd.DataFrame, instruments: list[str], controls: list[str]
) -> dict[str, float]:
    """线性一阶段：稳健 F、partial R²。

    partial R² 走 Frisch–Waugh–Lovell：把 T 和 Z 都对 controls 回归取残差，
    再看残差之间的 R²——这就是控制住 controls 之后 Z 对 T 的解释力。
    """
    full = sm.OLS(treatment, _design_matrix(data, instruments + controls)).fit(cov_type=ROBUST_COV)

    # 联合检验 instrument 的系数全为零。常数项在第 0 列，instrument 紧随其后。
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
    """Probit 一阶段：LR 联合显著性检验与 McFadden 增量 R²。

    treatment 是二值，线性一阶段的 F 只是近似；Probit 版本更贴合设定，
    两者都报出来（design.md 8.2：诊断形式由 family 决定）。
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
        # 相对「只有 controls」的增量 McFadden R²：加入 instrument 多解释了多少
        "mcfadden_r2_increment": float(1.0 - unrestricted.llf / restricted.llf),
    }


def _covariate_balance(
    data: pd.DataFrame, instruments: list[str], covariates: list[str], level: float
) -> tuple[dict[str, float], np.ndarray]:
    """逐个协变量对 instrument 回归，取 instrument 的联合 p 值，再做 BH 校正。

    instrument 若真的近似随机分配，协变量在它上面应当是平衡的。这是
    「instrument 与未测混杂无关」的**必要条件**——不平衡是坏信号，
    平衡不构成 exclusion restriction 成立的证据（那一条本就无法检验）。
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


def check_instrument(
    data: pd.DataFrame, spec: Spec, config: dict[str, Any] | None = None
) -> QualityReport:
    """跑 hte_iv 的全部 instrument 检查，返回带地址的 issue 列表。

    ``config`` 是 family.yaml 的 ``checks`` 段；不给则用代码里的默认阈值。
    """
    from causpec.families.hte_iv.estimator import _column_names

    config = config or {}
    treatment_col = _column_names(spec, "treatment")[0]
    instruments = _column_names(spec, "instrument")
    covariates = _column_names(spec, "effect_modifiers") + _column_names(spec, "adjustment_set")
    if not instruments:
        raise ValueError("hte_iv 的质量检查需要 spec.instrument")

    treatment = data[treatment_col].astype(float).to_numpy()
    issues: list[QualityIssue] = []

    # ---- 1. instrument 有没有变异 ----
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
                summary=f"instrument 在本人群中几乎没有变异：{'、'.join(degenerate)}",
                evidence={
                    "n_degenerate": len(degenerate),
                    "min_unique_values": min_unique,
                    "passed": False,
                },
                affected_columns=degenerate,
                impact_on_analysis="一阶段无从识别，IV 估计不可进行。",
                recommended_repair=(
                    "检查人群过滤是否把 instrument 的变异筛掉了，或改用其他 instrument。"
                ),
            )
        )
        return QualityReport(issues=issues)  # 没有变异就不必往下算了

    # ---- 2. 一阶段强度（阻断）----
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
                f"一阶段稳健 F = {linear['robust_f']:.2f}"
                f"（线 {min_f:g}），Probit LR 检验 p = {probit['lr_p_value']:.4f}"
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
                "弱工具下 IV 估计的偏倚可以任意大，置信区间的覆盖率失效；"
                "结论措辞不得超过 associational 级。"
                if not passed
                else "一阶段强度达到设定的线。"
            ),
            recommended_repair=(
                "改用更强的 instrument，或改用不依赖 instrument 的识别策略"
                "（若可论证无未测混杂）。豁免须写明理由。"
                if not passed
                else ""
            ),
        )
    )

    # ---- 3. complier 占比（仅二值 instrument）----
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
                summary=f"complier 占比约 {share:.1%}（线 {min_share:.0%}）",
                evidence={
                    "complier_share": round(share, 6),
                    "threshold": min_share,
                    "n_treated_if_z1": int(treatment[z == 1].sum()),
                    "n_treated_if_z0": int(treatment[z == 0].sum()),
                    "passed": passed,
                },
                affected_columns=instruments,
                impact_on_analysis=(
                    "估计对象是 complier 的条件 LATE。complier 占比小意味着结论只对"
                    "人群中很窄的一部分成立，且无法识别到个体——报告必须写明这一点。"
                ),
                recommended_repair="不必修复，但报告中须明确 estimand 的适用人群。",
            )
        )

    # ---- 4. 协变量平衡（BH 校正）----
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
                    f"{len(imbalanced)}/{len(covariates)} 个协变量在 instrument 上失衡"
                    f"（BH FDR {fdr:g}）"
                ),
                evidence={
                    "n_covariates": len(covariates),
                    "n_imbalanced": len(imbalanced),
                    "imbalanced_fraction": round(fraction, 6),
                    "threshold": max_fraction,
                    "fdr_level": fdr,
                    # 不校正时会「显著」的个数，用来说明校正的必要性
                    "n_nominally_significant": n_naive,
                    "min_p_value": round(min(p_values.values()), 6),
                    "passed": passed,
                },
                affected_columns=imbalanced,
                impact_on_analysis=(
                    "instrument 与协变量相关，说明它未必接近随机分配，"
                    "「instrument 与未测混杂无关」这条假设的可信度下降。"
                    "这是必要条件不成立的信号——平衡本身不构成 exclusion restriction 的证据。"
                ),
                recommended_repair="把失衡的协变量纳入调整集，或重新论证 instrument 的外生性。",
            )
        )

    return QualityReport(issues=issues)

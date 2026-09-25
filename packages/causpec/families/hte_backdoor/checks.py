"""hte_backdoor 的专属质量检查：overlap、协变量平衡、可行性。

对应 design.md 8.1（可识别性层与可行性层）与 10.2（两项阻断检验之一）。

**这一层自己拟合倾向得分，不依赖估计器。** G3 要求即使分析不能运行，
质量报告本身也是交付物——overlap 差到不能估计时，恰恰是最需要这份报告的时候。

阻断的只有 overlap 一项。按 design.md 10.2 的取舍原则「置信区间已经表达的，
不再设闸」：样本量、精度 CI 自己会说；CI 说不了的是系统性偏倚，而后门调整
设定下偏倚的主要来源就是缺乏共同支撑——有一批人根本没有对照，估计是外推出来的，
这时 CI 会很窄，但窄得没有意义。SMD、流行率、ESS 照算照印，不设闸。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:
    import pandas as pd

PROPENSITY_MODELS = ("gradient_boosting", "logistic")


def _threshold(config: dict[str, Any], check_id: str, key: str, default: float) -> float:
    return float(config.get(check_id, {}).get(key, default))


def _issue_settings(config: dict[str, Any], check_id: str) -> tuple[Layer, Severity, bool]:
    entry = config.get(check_id, {})
    return (
        Layer(entry.get("layer", "identification")),
        Severity(entry.get("severity", "warning")),
        bool(entry.get("waivable", True)),
    )


def _build_propensity_model(name: str, seed: int):
    if name == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    if name == "gradient_boosting":
        return GradientBoostingClassifier(random_state=seed)
    raise ValueError(f"propensity_model 只能是 {'、'.join(PROPENSITY_MODELS)}，收到 {name}")


def estimate_propensity(
    covariates: np.ndarray, treatment: np.ndarray, model_name: str, folds: int, seed: int
) -> np.ndarray:
    """交叉拟合的倾向得分 ê(X)。

    必须交叉拟合：同一份数据上拟合又预测，模型会记住个体，得分被推向 0/1，
    于是**看上去**没有共同支撑——这会把一个好数据判成坏数据。

    默认用梯度提升而非 logistic：overlap 检查问的是「有没有一片区域里处理几乎
    是确定的」，设定过窄的模型可能看不出真实的分离。在这里漏报比误报代价更大，
    因为漏报会放行一个本该阻断的分析。
    """
    model = _build_propensity_model(model_name, seed)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    scores = cross_val_predict(model, covariates, treatment, cv=splitter, method="predict_proba")
    return np.asarray(scores, dtype=float)[:, 1]


def standardized_mean_difference(
    values: np.ndarray, treatment: np.ndarray, weights: np.ndarray | None = None
) -> float:
    """SMD：处理组与对照组的均值差，除以两组标准差的合并值。

    加权版用于检查 IPW 之后是否平衡。分母始终用**未加权**的标准差，
    这样加权前后的 SMD 可比——否则权重会同时改变分子和分母，看不出改善。
    """
    treated, control = treatment == 1, treatment == 0
    pooled_sd = np.sqrt((np.var(values[treated]) + np.var(values[control])) / 2.0)
    if pooled_sd < 1e-12:
        return 0.0
    if weights is None:
        gap = values[treated].mean() - values[control].mean()
    else:
        gap = np.average(values[treated], weights=weights[treated]) - np.average(
            values[control], weights=weights[control]
        )
    return float(gap / pooled_sd)


def effective_sample_size(weights: np.ndarray) -> float:
    """Kish 的有效样本量：(Σw)² / Σw²。权重越不均，ESS 越小于实际样本量。"""
    total = float(np.sum(weights))
    if total <= 0:
        return 0.0
    return total**2 / float(np.sum(weights**2))


def check_backdoor(
    data: pd.DataFrame, spec: Spec, config: dict[str, Any] | None = None
) -> QualityReport:
    """跑 hte_backdoor 的全部检查，返回带地址的 issue 列表。"""
    from causpec.families.hte_backdoor.estimator import _column_names

    config = config or {}
    treatment_col = _column_names(spec, "treatment")[0]
    covariate_names = _column_names(spec, "effect_modifiers") + _column_names(
        spec, "adjustment_set"
    )
    if not covariate_names:
        raise ValueError("hte_backdoor 的质量检查需要 spec.effect_modifiers 或 adjustment_set")

    treatment = data[treatment_col].to_numpy().astype(int)
    covariates = data[covariate_names].astype(float).to_numpy()
    issues: list[QualityIssue] = []

    # ---- 1. 处理流行率（可行性）----
    layer, severity, waivable = _issue_settings(config, "backdoor_treatment_prevalence")
    min_rate = _threshold(config, "backdoor_treatment_prevalence", "min_rate", 0.01)
    min_per_arm = int(_threshold(config, "backdoor_treatment_prevalence", "min_per_arm", 50))
    n_treated, n_control = int(treatment.sum()), int((1 - treatment).sum())
    rate = float(treatment.mean())
    passed = min_rate <= rate <= 1 - min_rate and min(n_treated, n_control) >= min_per_arm
    issues.append(
        QualityIssue(
            check_id="backdoor_treatment_prevalence",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=f"处理率 {rate:.1%}（处理组 {n_treated}，对照组 {n_control}）",
            evidence={
                "treatment_rate": round(rate, 6),
                "n_treated": n_treated,
                "n_control": n_control,
                "min_per_arm": min_per_arm,
                "passed": passed,
            },
            affected_columns=[treatment_col],
            impact_on_analysis="某一组样本过少时估计的方差很大，子组分析尤其不可靠。",
            recommended_repair="放宽人群过滤条件，或减少子组切分。",
        )
    )
    if n_treated == 0 or n_control == 0:
        return QualityReport(issues=issues)  # 有一组是空的，后面算不了

    # ---- 2. Overlap / positivity（阻断）----
    layer, severity, waivable = _issue_settings(config, "backdoor_overlap")
    low = _threshold(config, "backdoor_overlap", "propensity_low", 0.05)
    high = _threshold(config, "backdoor_overlap", "propensity_high", 0.95)
    max_extreme = _threshold(config, "backdoor_overlap", "max_extreme_fraction", 0.05)
    folds = int(_threshold(config, "backdoor_overlap", "cv_folds", 5))
    model_name = str(
        config.get("backdoor_overlap", {}).get("propensity_model", "gradient_boosting")
    )

    propensity = estimate_propensity(covariates, treatment, model_name, folds, seed=0)
    extreme = (propensity < low) | (propensity > high)
    extreme_fraction = float(extreme.mean())
    passed = extreme_fraction <= max_extreme
    issues.append(
        QualityIssue(
            check_id="backdoor_overlap",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=(
                f"{extreme_fraction:.1%} 的样本倾向得分落在 [{low:g}, {high:g}] 之外"
                f"（线 {max_extreme:.0%}）"
            ),
            evidence={
                "extreme_fraction": round(extreme_fraction, 6),
                "threshold": max_extreme,
                "propensity_low": low,
                "propensity_high": high,
                "n_extreme": int(extreme.sum()),
                "propensity_min": round(float(propensity.min()), 6),
                "propensity_max": round(float(propensity.max()), 6),
                "propensity_model": model_name,
                "cv_folds": folds,
                "passed": passed,
            },
            affected_columns=covariate_names,
            impact_on_analysis=(
                "有一批人在协变量上几乎没有对照，对他们的效应是外推出来的。"
                "此时置信区间会很窄，但窄得没有意义——结论措辞不得超过 associational 级。"
                if not passed
                else "共同支撑充分。"
            ),
            recommended_repair=(
                "把人群限制到有共同支撑的区域（并在报告中写明 estimand 随之改变），"
                "或减少调整集中导致分离的变量。豁免须写明理由。"
                if not passed
                else ""
            ),
        )
    )

    # ---- 3. 协变量平衡：IPW 前后的 SMD ----
    weights = np.where(
        treatment == 1, 1.0 / np.clip(propensity, 1e-6, 1), 1.0 / np.clip(1 - propensity, 1e-6, 1)
    )
    layer, severity, waivable = _issue_settings(config, "backdoor_covariate_imbalance")
    max_smd = _threshold(config, "backdoor_covariate_imbalance", "max_abs_smd", 0.10)
    before = {
        name: standardized_mean_difference(covariates[:, j], treatment)
        for j, name in enumerate(covariate_names)
    }
    after = {
        name: standardized_mean_difference(covariates[:, j], treatment, weights)
        for j, name in enumerate(covariate_names)
    }
    imbalanced = [name for name, smd in after.items() if abs(smd) > max_smd]
    passed = not imbalanced
    issues.append(
        QualityIssue(
            check_id="backdoor_covariate_imbalance",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=(
                f"IPW 后 {len(imbalanced)}/{len(covariate_names)} 个协变量 |SMD| > {max_smd:g}"
            ),
            evidence={
                "n_covariates": len(covariate_names),
                "n_imbalanced_after": len(imbalanced),
                "max_abs_smd_before": round(max(abs(v) for v in before.values()), 6),
                "max_abs_smd_after": round(max(abs(v) for v in after.values()), 6),
                "threshold": max_smd,
                "passed": passed,
            },
            affected_columns=imbalanced,
            impact_on_analysis=(
                "加权后仍不平衡，说明倾向得分模型没能把这些变量的组间差异消掉，调整可能不充分。"
            ),
            recommended_repair="换更灵活的倾向得分模型，或检查这些变量是否本就难以共同支撑。",
        )
    )

    # ---- 4. 极端权重与有效样本量（可行性）----
    layer, severity, waivable = _issue_settings(config, "backdoor_extreme_weights")
    min_ess_ratio = _threshold(config, "backdoor_extreme_weights", "min_ess_ratio", 0.20)
    ess = effective_sample_size(weights)
    ratio = ess / len(weights)
    passed = ratio >= min_ess_ratio
    issues.append(
        QualityIssue(
            check_id="backdoor_extreme_weights",
            layer=layer,
            severity=severity if not passed else Severity.INFO,
            waivable=waivable,
            summary=(
                f"IPW 有效样本量 {ess:.0f} / {len(weights)}（{ratio:.1%}，线 {min_ess_ratio:.0%}）"
            ),
            evidence={
                "effective_sample_size": round(ess, 2),
                "n": len(weights),
                "ess_ratio": round(ratio, 6),
                "threshold": min_ess_ratio,
                "max_weight": round(float(weights.max()), 4),
                "passed": passed,
            },
            affected_columns=[treatment_col],
            impact_on_analysis="少数个体的权重主导了估计，结果对这几个人非常敏感。",
            recommended_repair="截断极端权重（并报告截断前后的敏感性），或限制人群。",
        )
    )

    return QualityReport(issues=issues)

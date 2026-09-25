"""hte_backdoor 的估计适配器：EconML CausalForestDML。

【复用】econml.dml.CausalForestDML（MIT）。

与 hte_iv 的一处重要差别：这个类支持 ``blb``（bootstrap of little bags，
Athey–Tibshirani–Wager），CATE 与 ATE 的区间都由森林自己的方差估计给出，
**不需要重抽样重拟合**。hte_iv 的 NonParamDMLIV 只能 bootstrap，因为它的
final model 是任意回归器；CausalForestDML 的 final model 就是森林本身。

识别策略是后门调整，所以这个 family 的结果依赖 unconfoundedness——
一条 untestable 假设。代码能做的只有查 overlap（见 checks.py），
证明不了无混杂。措辞等级的上限因此是 suggestive（design.md 10.2）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from econml.dml import CausalForestDML

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.registry import register

if TYPE_CHECKING:
    import pandas as pd


def _column_names(spec: Spec, field: str) -> list[str]:
    """从 spec 取一个列名列表字段。缺失返回空列表。"""
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _scalar(value: Any) -> float:
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


class HteBackdoor:
    """后门调整下的异质处理效应。"""

    id = "hte_backdoor"

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        """overlap、SMD、可行性检查，阈值取自 family.yaml。"""
        from causpec.core.registry import load_declaration
        from causpec.families.hte_backdoor.checks import check_backdoor

        return check_backdoor(data, spec, load_declaration(self.id).get("checks", {}))

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        treatment = _column_names(spec, "treatment")[0]
        outcome = _column_names(spec, "outcome")[0]
        effect_modifiers = _column_names(spec, "effect_modifiers")
        adjustment_set = _column_names(spec, "adjustment_set")

        if not effect_modifiers:
            raise ValueError("hte_backdoor 需要 spec.effect_modifiers（CATE 的协变量集 X）")

        y = data[outcome].to_numpy().ravel().astype(int)
        t = data[treatment].to_numpy().ravel().astype(int)
        x = data[effect_modifiers].astype(float).to_numpy()
        w = data[adjustment_set].astype(float).to_numpy() if adjustment_set else None

        # subforest_size 决定 blb 怎么分组，n_estimators 必须整除（与 hte_iv 同一约束）。
        subforest_size = int(spec.param("subforest_size", 4))
        n_estimators = int(spec.param("n_estimators", 500))
        if n_estimators % subforest_size:
            raise ValueError(
                f"n_estimators（{n_estimators}）必须能被 subforest_size"
                f"（{subforest_size}）整除——blb 的方差估计按子森林分组。"
                f"改成 {n_estimators - n_estimators % subforest_size}"
                f" 或 {n_estimators + subforest_size - n_estimators % subforest_size}。"
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
        # blb = bootstrap of little bags：森林自己的方差估计，一次拟合内完成。
        # 不用 bootstrap——这个 family 不需要，见模块文档。
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
            "res:design.n_effect_modifiers": len(effect_modifiers),
            "res:design.n_adjustment_covariates": len(adjustment_set),
            "res:estimation.estimator": "causal_forest_dml",
            "res:estimation.n_estimators": n_estimators,
        }
        values.update(_distribution("res:cate", cate))
        return Result(family=self.id, seed=seed, values=values)


register(HteBackdoor())

"""hte_backdoor 的估计适配器。

垂直切片版本：只做组均值差，**不是**最终估计器。
Phase 1 任务 7 换成 EconML 的 CausalForestDML（MIT）。

这里存在的意义是验证 core ↔ family 的接口方向：
本文件 import core，core 不 import 本文件。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.registry import register

if TYPE_CHECKING:
    import pandas as pd


class HteBackdoor:
    """后门调整下的处理效应。切片版本 = 朴素组均值差。"""

    id = "hte_backdoor"

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        """尚未实现专属检查（overlap、SMD 见 design.md 8.1，Phase 1 任务 5）。"""
        return QualityReport()

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        treatment_col = str(spec.fields["treatment"].value)
        outcome_col = str(spec.fields["outcome"].value)

        treated = data.loc[data[treatment_col] == 1, outcome_col].astype(float)
        control = data.loc[data[treatment_col] == 0, outcome_col].astype(float)
        if treated.empty or control.empty:
            raise ValueError("处理组或对照组为空，无法估计")

        return Result(
            family=self.id,
            seed=seed,
            values={
                "res:primary.estimate": round(float(treated.mean() - control.mean()), 4),
                "res:primary.n": int(len(data)),
                "res:primary.n_treated": int(len(treated)),
                "res:primary.n_control": int(len(control)),
                "res:primary.mean_treated": round(float(treated.mean()), 4),
                "res:primary.mean_control": round(float(control.mean()), 4),
            },
        )


register(HteBackdoor())

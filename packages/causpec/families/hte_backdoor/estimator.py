"""hte_backdoor 的估计适配器。

垂直切片版本：只做组均值差，**不是**最终估计器。
Phase 1 任务 7 换成 EconML 的 CausalForestDML（MIT）。

这里存在的意义是验证 core ↔ family 的接口方向：
本文件 import core，core 不 import 本文件。
"""

from __future__ import annotations

from statistics import fmean

from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.registry import register


class HteBackdoor:
    """后门调整下的处理效应。切片版本 = 朴素组均值差。"""

    id = "hte_backdoor"

    def estimate(self, rows: list[dict[str, str]], spec: Spec, seed: int) -> Result:
        treatment_col = str(spec.fields["treatment"].value)
        outcome_col = str(spec.fields["outcome"].value)

        treated = [float(r[outcome_col]) for r in rows if r[treatment_col] == "1"]
        control = [float(r[outcome_col]) for r in rows if r[treatment_col] == "0"]
        if not treated or not control:
            raise ValueError("处理组或对照组为空，无法估计")

        return Result(
            family=self.id,
            seed=seed,
            values={
                "res:primary.estimate": round(fmean(treated) - fmean(control), 4),
                "res:primary.n": len(rows),
                "res:primary.n_treated": len(treated),
                "res:primary.n_control": len(control),
                "res:primary.mean_treated": round(fmean(treated), 4),
                "res:primary.mean_control": round(fmean(control), 4),
            },
        )


register(HteBackdoor())

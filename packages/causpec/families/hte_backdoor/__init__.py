"""hte_backdoor：后门调整下的异质处理效应，作为 baseline。

估计器复用 EconML 的 ``CausalForestDML``（MIT）。
HTE 校准复用 EconML 的 ``econml.validate.DRTester``（MIT）。

当前是垂直切片的占位实现（组均值差），Phase 1 任务 7、8 替换。
"""

from causpec.families.hte_backdoor.estimator import HteBackdoor

__all__ = ["HteBackdoor"]

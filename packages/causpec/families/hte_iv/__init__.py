"""hte_iv：IV 设定下的异质处理效应。

估计器【复用】EconML 的 ``NonParamDMLIV``（MIT）。instrument 二值与连续都支持。

HTE 校准需要注意：EconML 的 ``DRTester`` 基于无混杂假设下的 doubly robust
得分，**不能直接用于 IV 设定**，需改用 IV 版本的得分自写（design.md 第 9 节 TODO）。
"""

from causpec.families.hte_iv.estimator import HteIv

__all__ = ["HteIv"]

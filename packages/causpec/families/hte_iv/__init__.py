"""hte_iv：IV 设定下的异质处理效应，主方法 DMLIV。

估计器是作者自己的研究代码，迁入时剥离 I/O 并配数值回归测试。
识别的 estimand 取决于假设，见 family.yaml。

HTE 校准需要注意：EconML 的 ``DRTester`` 基于无混杂假设下的 doubly robust
得分，**不能直接用于 IV 设定**，需改用 IV 版本的得分自写（design.md 第 9 节 TODO）。

Phase 0 任务 3、Phase 1 任务 8。
"""

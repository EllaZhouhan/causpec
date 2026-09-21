"""分析 family 插件。

每个 family 目录包含（design.md 第 5 节）：
family.yaml、spec 扩展、专属检查、估计适配器、图、evals、tests。

- ``hte_iv``             IV 设定下的异质处理效应（DMLIV，作者自己的方法）
- ``hte_backdoor``       后门调整下的 HTE（EconML CausalForestDML，baseline）
- ``longitudinal_ipcw``  纵向处理效应（IPCW，作者自己的方法）
"""

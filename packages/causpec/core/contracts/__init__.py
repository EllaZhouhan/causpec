"""Pydantic contracts：系统里所有跨层传递的数据结构。

对应 design.md 7.2（Spec 结构）、8.3（Issue schema）、14（Manifest）。

计划定义：
- ``Field``        字段级 value/source/said/turn/status（design.md 7.1）
- ``Spec``         population、causal_design、estimation、analysis_plan
- ``QualityIssue`` check_id、layer、severity、waivable、evidence、地址
- ``Result``       带地址的估计结果（design.md 10.1）
- ``Manifest``     execution_mode、git_sha、包版本、指纹、checksum

Phase 0 任务 2。
"""

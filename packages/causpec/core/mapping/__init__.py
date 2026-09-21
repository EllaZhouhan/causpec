"""轻量 mapping：把数据源的列映射到 canonical schema。

对应 design.md 6.4。只支持 rename、cast、recode_null、map_categories、
unit_convert、按窗口聚合六种操作，**不接受任意表达式**——
mapping 由 agent 起草、用户确认，能力越小越可审阅。

同时维护变量目录（design.md 6.2）：来源列、单位、相对 time zero 的
测量窗口、聚合方式。没有时间信息的变量，post-treatment 检查只能给 suspected。

Phase 1 任务 2。
"""

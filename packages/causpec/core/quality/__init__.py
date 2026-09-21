"""数据质量与可识别性检查。

对应 design.md 第 8 节的四层：

| 层       | 检查 |
|----------|------|
| 基础     | 类型、范围、唯一性、缺失、NULL 编码变体 |
| 时间一致性 | treatment 早于 time zero、outcome 早于 treatment、follow-up 不足 |
| 可识别性 | 流行率、overlap、SMD、suspected post-treatment、instrument relevance |
| 可行性   | 各组样本量、事件数、子组最小 n、极端权重与 ESS |

每个检查有地址 ``qc:<check_id>``，供报告引用。修复只作用于派生快照。

Phase 1 任务 4、5。
"""

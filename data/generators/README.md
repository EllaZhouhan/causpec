# data/generators/

合成数据生成器。**生成器入库，生成出来的数据不入库。**

对应 design.md 第 15 节：

| 数据集 | 内容 | 何时建 |
|---|---|---|
| **A** | 结构因果模型生成，带真值：异质效应、instrument、informative censoring、变长轨迹 | Phase 0 任务 4（HTE 部分）、Phase 4 任务 3（纵向部分） |
| **B** | A 的三种口径：宽表、长事件表、关系型（关系型装入 Postgres demo） | Phase 3 任务 4 |
| **C** | 在 A 上注入问题，每个问题对应预期的 `check_id` | Phase 1 任务 6 |
| **D** | 商业场景：带 non-compliance 的 A/B test、用户留存 | Phase 5 任务 1 |

每个生成器固定 seed，并把真值一并输出，供 evals 计算覆盖率。

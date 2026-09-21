# data/

**生成的数据不入库。** 这个目录只放生成器（`generators/`），运行后产出的 CSV/Parquet/DuckDB 文件由 `.gitignore` 和 pre-commit 钩子双重拦截。

任何真实数据都不得放进这个仓库。

合成数据集（见 docs/design.md 第 15 节）：

- **A**：结构因果模型生成，带真值，包含异质效应、instrument、informative censoring、变长轨迹
- **B**：A 的三种口径（宽表、长事件表、关系型）
- **C**：在 A 上注入问题，每个问题对应预期的 `check_id`
- **D**：商业场景（带 non-compliance 的 A/B test、用户留存）

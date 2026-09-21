# CauSpec

把自然语言的因果问题，转成一份逐字段经用户确认的分析规格（spec），先评估数据能否支撑这个问题，再用确定性代码执行估计，最后产出数字全部可追溯到计算结果的报告。全程对数据源只读。

> 状态：早期开发中（v0.0）。当前仓库为 private，v0.3 后转公开。

## 它解决什么

在观测数据上做因果分析，失败通常发生在估计之前：treatment、outcome、time zero 定义含糊；存在 post-treatment 变量或 positivity 问题却没被发现；数据口径不统一；数字无法复现。而"LLM + 代码"类工具还会引入另一种失败：模型自己算数或编数。

CauSpec 的四条原则：

1. **代码计算事实，模型做判断，框架设闸。**
2. **spec 的每个关键字段都有来源（用户 / 模型 / 数据）和状态（草拟 / 确认）**，关键字段全部确认前不执行估计。
3. **数字只由代码产生**，报告正文只能用占位符引用地址，渲染器代入；出现未占位的数字则渲染失败。
4. **结论措辞等级由代码根据诊断结果判定**（causal / suggestive / associational / descriptive），模型不能自行升级。

## 支持的分析

| family | 说明 |
|---|---|
| `hte_iv` | IV 设定下的异质处理效应（DMLIV） |
| `hte_backdoor` | 后门调整下的 HTE（CausalForestDML），作为 baseline |
| `longitudinal_ipcw` | 纵向处理效应（IPCW） |

不在支持范围内的设计（DiD、断点回归、合成控制）会被明确拒绝，并给出每个 family 被排除的原因。

## 文档

- [设计文档](docs/design.md)
- [开发计划](docs/plan.md)
- [决策记录](docs/decisions/)

## 开发

```bash
uv sync --all-extras       # 安装依赖
uv run pytest              # 测试
uv run ruff check .        # lint
pre-commit install         # 启用提交前检查（含数据文件拦截）
```

## 许可

MIT（见 [LICENSE](LICENSE)）。复用的外部代码及其许可登记在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

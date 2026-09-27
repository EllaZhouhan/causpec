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

## 仓库结构

三个交付物在同一个仓库里：**库**是厚的，**MCP server** 与 **skill** 是调用它的两层薄壳。两种形态调用同一套 `causpec` 函数，产出同样结构的 run 目录。

```
packages/causpec/          库：所有计算逻辑在这里
  core/                      core 不导入任何 family（import-linter 在 CI 中强制）
    contracts/                 Spec、QualityIssue、Result、Manifest
    adapters/                  csv、parquet、postgres（只读）
    mapping/                   轻量 mapping 与变量目录
    quality/                   四层检查
    runtime/                   RunContext、原子写入、audit、manifest
    reporting/                 地址解析、占位符渲染、措辞等级判定
    registry.py                family 注册表：core 与 family 的唯一接口
  families/                  插件式，新增分析 = 一个目录 + 一行注册
    hte_iv/  hte_backdoor/  longitudinal_ipcw/
  cli.py                     causpec quality / estimate / report

server/causpec_mcp/        MCP server（主形态）：持有凭据、执行门控
skill/causpec-analyst/     skill（辅形态）：SKILL.md + references + scripts
evals/                     数值、质量检查、鲁棒性、报告、agent、回归
data/generators/           合成数据生成器（生成的数据不入库）
examples/deployments/      demo-hospital、demo-retail 配置示例
deploy/                    本地 Postgres demo（只读账号 + view）
docs/                      design.md、plan.md、decisions/
```

目前除骨架外内容为空，按 [plan.md](docs/plan.md) 的阶段逐步填充。

## 估计器与置信区间

`hte_iv` 有两个后端，由 `spec.estimation.params.estimator` 选。二值与连续 instrument 都支持。

| | `ivforest`（默认） | `dmliv` |
|---|---|---|
| 类 | `econml.grf.CausalIVForest` | `econml.iv.dml.NonParamDMLIV` |
| CATE 区间 | GRF honest 方差，一次拟合内完成 | bootstrap |
| ATE 区间 | 对森林做单位层面 bootstrap | bootstrap |
| 每次重抽样 | 约 5 秒（n=5000） | 约 26 秒 |
| 多个 instrument / `adjustment_set` | 不支持 | 支持 |

**为什么 `dmliv` 只能 bootstrap**：它的 final model 是任意回归器，EconML 推不出方差——`_get_inference_options()` 里就 `bootstrap` 一项。这不是选择，是唯一选项。

**为什么 `ivforest` 的 ATE 区间也要 bootstrap**：`econml.grf` 只提供**逐点**方差（`predict_and_var` 给的协方差矩阵是单点上各输出维之间的，不是不同 x 之间的）。同一片森林的各点估计高度相关，把逐点方差平均再除以 n 等于假设独立。所以 CATE 区间用 GRF 的解析方差，ATE 区间另走 bootstrap——两者来路不同，分别记在 `res:cate.ci_method` 与 `res:primary.ate_ci_method`，报告要分别说明。

**重抽样次数**默认 200，两个后端共用，可覆盖：

```yaml
estimation:
  params:
    estimator: ivforest
    n_bootstrap_samples: 200   # 低于 100 时 res:estimation.bootstrap_adequate = "no"
    bootstrap_n_jobs: 8        # 下标先一次性抽好再并行，不影响结果
```

调低次数会让区间失真：实测同一份数据，20 次重抽样与 GRF 解析区间给出的「个体显著获益人数」差了两个数量级（416 对 3）。所以次数不够时结果里会打标记，报告必须把这件事摆出来。

## skill 形态

`skill/causpec-analyst/` 是 claude.ai 上用的形态（best-effort）。打包：

```bash
./scripts/build_skill.sh     # 构建 wheel 放进 assets，打出 dist/causpec-analyst-skill.zip
```

wheel 是构建产物，不入库——入库的 wheel 会和源码悄悄脱节，而 skill 跑的正是它。

**在 Claude Code 里试用**：`.claude/skills/causpec-analyst` 已经软链到 `skill/causpec-analyst`，
clone 下来就能用，不需要打包。改了 SKILL.md 立刻生效。

**在 claude.ai 网页版试用**：上传 `dist/causpec-analyst-skill.zip`（Settings → Capabilities → Skills）。
那边需要 wheel，因为沙箱里装不了本地包。

**为什么是 best-effort**：agent 在技术上可以绕过 `scripts/run.py` 直接读数据自己算，
所以「数字只由代码产生」这条保证在 skill 形态下依赖 agent 遵守规则。报告页眉会注明这一点。
MCP 形态没有这个问题——那边模型只能通过声明过的工具与数据交互（尚未实现）。

## 文档

- [设计文档](docs/design.md)
- [开发计划](docs/plan.md)
- [决策记录](docs/decisions/)

## 安装

core 保持轻量（pydantic、pyyaml、pandas、numpy）。分析 family 的重依赖走 extra，按需安装：

| extra | 拉进来什么 | 哪些 family 需要 |
|---|---|---|
| `hte` | EconML、scikit-learn | `hte_iv`、`hte_backdoor` |

```bash
# 只用 spec、质量检查、报告渲染
uv sync

# 要跑 HTE 估计
uv sync --extra hte
```

pip 用户：`pip install causpec` 或 `pip install 'causpec[hte]'`。

**没装 extra 时不会崩在 `ImportError` 上**——注册表返回结构化错误并给出安装命令：

```console
$ causpec estimate --spec spec.yaml --data cohort.csv
[FAMILY_DEPENDENCY_MISSING] family hte_iv 的依赖未安装（econml）
  修复：安装 causpec[hte]：uv sync --extra hte（或 pip install 'causpec[hte]'）
```

## 开发

```bash
uv sync --all-extras --dev   # 全部依赖
uv run pytest                # 测试
uv run ruff check .          # lint
uv run lint-imports          # 架构契约：core 不导入 family
pre-commit install           # 启用提交前检查（含数据文件拦截）
```

## 合成数据

```bash
# 带真值的数据集 A。生成的数据不入库。
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset realistic
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset high_power --instrument-kind binary
```

`realistic` 照真实 ICU 研究的量级（处理率约 9.5%、死亡率约 4%），用于演示与质量检查；
`high_power` 把 complier 份额与事件率提上去，供数值 evals——在 realistic 量级下
IV 的标准误比真值本身还大，数值测试会被噪声淹没。

## 许可

MIT（见 [LICENSE](LICENSE)）。复用的外部代码及其许可登记在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

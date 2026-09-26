# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号对应 plan.md 第 2 节的里程碑。

## [Unreleased]

### Changed
- **渲染错误信息改为可读、可照做**：裸数字直接给出该写什么
  （`28 → 写成 {{lit:28}}`），数值与某个结果接近时指出该引用哪个地址；
  地址列表按命名空间分组并截断，不再把几十个地址糊成一坨。
  这是冷启动测试里踩出来的——原来的错误信息把修复建议淹没了

### Added
- **skill 形态可用**：完整的 SKILL.md（八条关键规则 + 八步流程）、
  八份 references、narrative 模板、`scripts/run.py`（沙箱里没装 causpec 时
  从捆绑的 wheel 直接 zip 导入）、`scripts/build_skill.sh` 打包
- **skill 一致性测试**：文档里列的 family、检查、可撰写段落、措辞等级
  必须与代码实际行为一致——文档会悄悄过期，这些测试把两边钉在一起
- **报告固定结构**（design.md 10.3）：十个段落顺序由代码决定，
  「假设写在结果之前」是结构保证而非提醒。spec 来源表与措辞等级判定由代码生成，
  模型不得为这两节撰稿；其余段落可提供解读，一律走占位符渲染
- **占位符格式说明**：`{{res:primary.ate|+.3f}}`、`{{qc:...frac|.1%}}`——
  没有它报告里会出现 17 位有效数字，而模型面对这种数字的自然反应是自己四舍五入，
  那就绕过 G4 了
- **CLI `--report` / `--narrative`**：`--report` 输出固定结构，
  `--narrative` 接受 `{段落: 正文}` 的 YAML
- **runtime**（design.md 第 14 节、G5）：`RunContext` 落盘 run 目录、
  `Manifest` 记录全部会影响结果的东西（代码版本、依赖版本、spec_hash、seed、
  判定规则哈希）、每个产物的 sha256、`verify()` 核对事后篡改。
  所有写入原子（临时文件同目录 + fsync + `os.replace`）
- **审计日志**：每次调用一行，**参数只记哈希不记内容**；元数据过一道敏感键名
  检查，命中 password/dsn/token 等即抛错——「日志不记录凭据」由代码强制
- **CLI `--run-dir`**：把一次运行完整落盘，含豁免理由
- **措辞等级判定**（design.md 10.2、原则 5）：四级规则写在
  `core/reporting/claim_levels.yaml`，判定结果带规则哈希。代码自动判定的上限是
  suggestive——untestable 假设跑多少检验都验证不了，升到 causal 需要用户逐条论证
  并显式确认。豁免不改变诊断结论。
- **`Assumption` contract**：三分类（empirically_assessed / requires_justification /
  untestable）、论证文本、`justified_by`——模型自己的论证不算数
- **`claim:` 命名空间**；渲染器改为接受合并后的地址表，`res:` / `qc:` / `claim:`
  可以在同一份报告里引用
- **`hte_backdoor` 换上 CausalForestDML**，CATE 与 ATE 的区间都用 `blb`
  （bootstrap of little bags），不需要重抽样重拟合
- **overlap / positivity 检查**（两项阻断检验的另一项）、IPW 前后的 SMD、
  Kish 有效样本量、处理流行率。倾向得分交叉拟合，默认梯度提升
- **CLI `quality` 子命令**；`estimate` 现在会先跑检查再过门控，
  `--waive CHECK_ID=理由` 豁免可豁免的 blocking 检查
- **`QualityIssue` / `QualityReport` contract**（design.md 8.3）：check_id、layer、
  severity、waivable、evidence、affected_columns、impact_on_analysis、recommended_repair；
  每条证据都有 `qc:<check_id>.<key>` 地址供报告引用
- **`hte_iv` 的 instrument 检查**：迁自研究代码的 `test_iv_validity`，
  相关性（线性稳健 F + partial R² + Probit LR 检验 + McFadden 增量 R²）、
  complier 占比、协变量平衡（Benjamini–Hochberg FDR 校正）。阈值写在 family.yaml
- **门控第 2 条**：有未豁免的 blocking 质量问题时拒绝估计；豁免必须附理由，
  不可豁免的检查即使给理由也不放行
- **合成数据集 A 生成器**（`data/generators/dataset_a.py`）：带个体真值的结构因果模型，
  未观测混杂让朴素估计与后门调整都有偏、只有 IV 能识别；二值与连续 instrument 两种形态；
  `realistic` / `high_power` 两套预设
- **`hte_iv` family**：两个后端（`ivforest` = CausalIVForest，默认；`dmliv` = NonParamDMLIV，
  与研究代码最终版一致），二值与连续 instrument 都支持。
  `ivforest` 的 CATE 区间用 GRF honest 方差，ATE 区间用森林的单位层面 bootstrap——
  econml.grf 只提供逐点方差，没有跨样本平均的接口。重抽样次数两个后端共用，
  默认 200，可从 spec 覆盖，并行度由 `bootstrap_n_jobs` 控制（下标先抽好再并行，
  不影响结果）
- `causpec[hte]` extra：econml 与 scikit-learn；依赖缺失时给结构化错误 + 安装命令
- 仓库骨架：uv、ruff、pyright、pytest、pre-commit、CI、import-linter
- 数据文件拦截（`.gitignore` + pre-commit 钩子）
- 全目录结构与各层职责说明；三个 family 的 `family.yaml` 声明
- 垂直切片：Spec（字段级 source/status）、门控、带地址的 Result、占位符渲染、CLI
- ADR-0001（报告中的字面量数字）、ADR-0002（数据源边界）

### Changed
- **包内资源改用 `importlib.resources` 读取**（`family.yaml`、`claim_levels.yaml`）。
  原先用 `Path(__file__).parent`，从 wheel（zip）里 import 时找不到文件——
  这个 bug 是在干净环境里实跑 skill 的 `run.py` 时发现的
- 读 family 声明不再 import 该 family 的包：`resources.files("causpec.families.hte_iv")`
  会执行它的 `__init__` 进而拉 econml，导致「依赖缺失」被误报成「未知的 family」
- 注册表改为按 id 动态导入，core 不再写死任何 family 的 import；
  `family.yaml` 的 `requires_extra` 驱动安装提示
- 全项目统一用 pandas DataFrame 传数据（原先 `list[dict[str, str]]`）
- 估计器超参移到 `spec.estimation.params`（design.md 7.2），不再写死在 family 代码里——
  它们影响结果，必须进 spec_hash 与 manifest
- design.md 0.4：
  - 派生快照不再承诺 DuckDB，只规定两条契约（可写工作副本 + 规范化内容指纹）；
    默认实现为 parquet，数据超出单机内存时再换列式引擎
  - Postgres 交付深度收敛：v0.3 只做薄 adapter + docker-compose demo，
    证明能接入只读 view 且只读来自账号权限；masked_columns 与 schema drift 后置
  - 删掉 `contradicted` 字段状态。数据与 spec 的冲突由质量检查产生 blocking issue，
    门控第 2 条已经拦住，多一个状态是两套机制做同一件事
  - `status: confirmed` 必须附 `said`（用户确认时的原话），与 source 无关。
    堵门控的根部漏洞：update_field 由模型调用，server 无从验证确认是否真发生过
  - 10.2 措辞等级定量化：代码只能降到 suggestive，causal 需人担保 untestable 假设；
    阻断检验从一份开放清单收缩到两项（overlap、instrument relevance），
    取舍原则是「置信区间已经表达的，不再设闸」；其余诊断照印不设闸
- design.md / plan.md 升到 0.3：
  - G2 从三种口径降为两种（砍掉关系型口径与数据集 B 的第三种口径）
  - 砍掉 StatsPAI 依赖；E-value 与 effective F 自写并配数值回归测试，
    未观测混杂敏感性改用 DoubleML，AR 检验入 backlog
  - 省下的约一周并入 Phase 4，使纵向 IPCW 能完整交付（含估计）
  - ADR 从计划的 5 篇减为 2 篇：只记设计文档没覆盖的决定

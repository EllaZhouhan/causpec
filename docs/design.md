# CauSpec 设计文档

版本：0.4
作者：Han Zhou
更新：2026-09-23

文中带【复用】标记的地方表示直接使用或改写外部库、外部项目的代码或做法，并注明来源和许可。标注 TODO 的地方需要作者根据自己的方法与代码补充。

---

## 1. 目标与非目标

### 1.1 要解决的问题

在观测数据上回答因果问题时，失败通常发生在估计之前：treatment、outcome、time zero 定义含糊；存在 post-treatment 变量或 positivity 问题却没有被发现；数据口径不统一；数字无法复现。常见的"LLM + 代码"工具还会引入另一种失败：模型自行计算或编造数字。

CauSpec 做四件事：

1. 把分析师的自然语言问题转为一份逐字段经确认的分析规格（spec）。
2. 先评估数据能否支撑这个问题。
3. 用确定性代码执行 HTE 与纵向处理效应估计。
4. 产出数字全部可追溯到计算结果的报告。

全程对数据源只读。

### 1.2 目标

- G1：spec 的每个关键字段都记录来源（用户、模型推断、数据），并标注状态（草拟、确认）；估计只在关键字段全部确认后执行。
- G2：支持本地 CSV/Parquet 与 PostgreSQL，以及宽表、长事件表两种口径，估计代码不变。
- G3：数据质量与可识别性报告，即使分析不能运行，它本身也是交付物。
- G4：数字只由代码产生；报告里的数字由渲染器按地址填入，模型不能直接写数字。
- G5：输入与 seed 固定时结果可复现；每次运行有 manifest 与审计日志。
- G6：可测评：数值、质量检查召回、agent 行为。

### 1.3 非目标

自动因果图发现；任意 SQL；多 agent；自动遍历估计器挑选结果；治疗或业务决策推荐；自建前端；远程多用户部署与认证。

---

## 2. 设计原则

1. 代码计算事实，模型做判断，框架设闸（机制见 10.1 节）。
2. 用户说的话是证据，不自动写入（机制见 7.1 节）。
3. 数据源只读。只读的保证来自数据库账号权限，不来自 prompt。
4. 原始行默认不进入模型上下文。
5. 结论措辞的强度由代码根据诊断结果决定，模型不能自行升级（机制见 10.2 节）。

文中凡标注"仅借鉴思路"的来源（Causal desk）未声明许可证，只借鉴做法，不复制代码，并在 README 的 Related work 中注明。

---

## 3. 使用形态

| 形态 | 场景 | 数据源 | 说明 |
|---|---|---|---|
| 本地 MCP（主） | Claude Code / Desktop | 本地 CSV/Parquet；PostgreSQL | server 持有凭据；不修改数据源 |
| skill + CLI（辅） | claude.ai 上传 CSV | 上传文件 | best-effort：agent 可能绕过脚本直接读取数据，报告页眉注明 |

两种形态调用同一套 causpec 函数，产出同样结构的 run 目录；manifest 记录 execution_mode。

---

## 4. 架构

```
MCP 客户端（Claude Code / Desktop / claude.ai）
 ├─ Skill: causpec-analyst         流程、spec 起草、质量解读、结果解读
 │    └─ scripts/ → causpec CLI   仅 skill 形态使用
 └─ MCP server: causpec-mcp
      ├─ connectors   csv / parquet / postgres（只读）
      ├─ workspace    派生快照（实现不约束）
      ├─ gates        spec 确认与质量门控
      └─ → causpec
             ├─ core        contracts、mapping、quality、runtime、reporting
             └─ families/   hte_iv、hte_backdoor、longitudinal_ipcw（插件式）
```

分层规则：core 不导入任何 family，family 通过注册表接入；用 import-linter 在 CI 中强制执行。新增一种分析只需增加一个 family 目录和一行注册。【复用】做法参考 Causal desk ADR-0005（仅借鉴思路）。

---

## 5. 仓库结构

```
causpec/
 ├─ packages/causpec/
 │    ├─ core/
 │    │    ├─ contracts/      Pydantic：Spec、Field、QualityIssue、Result、Manifest
 │    │    ├─ adapters/       csv、parquet、postgres
 │    │    ├─ mapping/
 │    │    ├─ quality/
 │    │    ├─ runtime/        RunContext、ArtifactWriter、audit、manifest
 │    │    └─ reporting/      地址解析、占位符渲染、措辞强度判定
 │    ├─ families/
 │    │    ├─ hte_iv/         你的 DMLIV
 │    │    ├─ hte_backdoor/   EconML CausalForestDML，作为 baseline
 │    │    └─ longitudinal_ipcw/  你的 IPCW
 │    └─ cli.py
 ├─ server/causpec_mcp/
 ├─ skill/causpec-analyst/
 ├─ examples/deployments/     demo-hospital、demo-retail 的配置示例
 ├─ data/generators/          合成数据生成器；生成的数据不入库
 ├─ evals/
 ├─ deploy/docker-compose.yml     本地 Postgres demo
 ├─ docs/                     design.md、plan.md、decisions/
 └─ .github/workflows/
```

每个 family 目录包含：family.yaml（回答什么问题、能识别哪些 estimand、需要什么、假设什么）、spec 扩展、专属检查、估计适配器、图、evals、tests。【复用】目录约定参考 Causal desk 的 family package（仅借鉴思路）。

---

## 6. 数据层

### 6.1 数据源

```yaml
sources:
  - id: icu_pg
    type: postgres
    dsn_env: CAUSPEC_ICU_DSN
    allowed_relations: [analytics.v_cohort, analytics.v_timeseries]   # 建议由数据方建好的只读 view
    masked_columns: [patient_name, mrn]
  - id: local
    type: csv
    root: ./data
```

实践上，复杂的连接和派生应由数据方用 SQL view 实现，并由人工审阅；CauSpec 只读取 view，不自建 ETL。这也是 FDE 在客户现场的常规分工。

### 6.2 变量目录

每个变量记录：来源列、单位、相对 time zero 的测量窗口、聚合方式。没有时间信息的变量，post-treatment 检查只能给出 suspected。

### 6.3 Canonical schema

Cross-sectional 表的字段：unit_id、treatment、outcome、instrument（可选）、covariates、time_zero。

Longitudinal 表的字段：unit_id、episode_id、time_index、timestamp、eligible、action、state 变量、outcome、event_type。

### 6.4 Mapping

只支持轻量操作：rename、cast、recode_null、map_categories、unit_convert、按窗口聚合。更复杂的派生交给数据方的 view。mapping 由 agent 起草、用户确认，不接受任意表达式。

### 6.5 快照与指纹

数据物化到一份**派生快照**。快照要提供两样东西，不规定用什么实现：

1. **一份可写的工作副本**——mapping 与质量修复只作用在它上面，原始数据源永不被修改
2. **snapshot_fingerprint**——对规范化后的**内容**计算（先按主键排序，再固定列序和 dtype），不对文件字节计算

默认实现用 pandas/polars 读入、应用 mapping、写一份 parquet，指纹对规范化后的内容算。十万行以内这样最简单，依赖也最少。数据量超出单机内存时再换 DuckDB 或其他列式引擎——那是实现细节，不改变上面两条契约。

数据库来源另外记录查询文本与读取时间。

快照的保留期限、磁盘加密与容量上限属于部署环境的职责，CauSpec 不实现；接入真实数据时，应在部署说明中写明这些要求。

---

## 7. Spec

### 7.1 字段级来源与状态

```yaml
treatment:
  value: {variable: rrt, type: binary}
  source: user            # user | model | data
  said: "透析就是指开始CRRT"   # 用户原话；status=confirmed 时必填
  turn: 4
  status: confirmed       # drafted | confirmed
time_zero:
  value: first_aki3_time
  source: model
  status: drafted
```

规则：

- 关键字段为：population、treatment、outcome、time_zero、estimand、variable_roles、key_non_edges、identification_strategy、adjustment_set、instrument，以及 longitudinal 的 event_roles。门控要求见 11.2 节。
- **`status: confirmed` 必须附 `said`**，即用户确认时说的那句话，与 `source` 无关。模型推断的值经用户认可后同样标 confirmed，此时 `source` 仍是 model，但 `said` 记的是用户认可时的原话。
- 数据与 spec 冲突（例如声明 binary 的 treatment 列实有三个取值、处理时间早于 time zero）不设单独的字段状态，由质量检查发现并产生 blocking issue，门控第 2 条已经拦住。冲突摆在质量报告里由人判断——改 spec，还是记一条附理由的豁免。系统不替用户裁决，也不为此多加一套状态机。

需要如实说明：确认发生在对话中，`update_field` 由模型调用，**server 无法验证用户是否真的看过 spec，也无法验证 `said` 是不是真话**。这个漏洞在当前形态下堵不死——只要确认发生在对话里、由模型转述，就没有密码学意义上的保证。能做的是把成本和可见性抬高：要求 confirmed 必附原话，意味着模型想跳过确认就必须编造一句用户的话；报告首页展示 spec 全文及每个字段的 source / said / turn，编造的引语用户一眼能认出。此外，SKILL.md 明令不得在未获用户明确答复时标记 confirmed，并由 golden tasks 专门测这一项（给一句模糊的话，看模型会不会把一堆字段标成 confirmed）。

### 7.2 结构

```yaml
spec_version: 1
meta: {question: ...}
population: {filters: [...]}
causal_design:
  analysis_type: hte | longitudinal
  estimand: ...
  treatment / outcome / time_zero / instrument / adjustment_set / effect_modifiers
  variable_roles: {<变量或变量组>: confounder | instrument | mediator | effect_modifier | suspected_collider | post_treatment}
  key_non_edges: [...]        # 例如 instrument 与 outcome 之间除经 treatment 外无路径
  identification_strategy: backdoor_adjustment | instrumental_variable
  assumptions:
    - {id, category: empirically_assessed | requires_justification | untestable, statement, justification}
estimation: {family, params, seed}
analysis_plan: {primary: ..., sensitivity: [...], exploratory: [...]}
```

### 7.3 Longitudinal 协议

采用 target trial 的七个组成部分：eligibility、treatment strategies、assignment、follow-up（time zero 与结束）、outcome、causal contrast、analysis plan；另加 event_roles，把 death、discharge、transfer 等事件显式指定为 outcome、competing、censoring 或 terminal。

【复用】字段划分对齐 StatsPAI 的 TargetTrialProtocol（MIT，src/statspai/target_trial/protocol.py），便于和成熟实现互相对照；**只对齐字段结构，不引入该依赖**。

TODO：按 ipcw 方法写明各事件的处理方式及估计量的解释。

### 7.4 确认后的变更

primary 分析在确认时锁定。看过结果之后新增或修改的分析自动标为 post_hoc，并在报告中单列。【复用】做法参考 StatsPAI 的 preregister 偏离日志（MIT，src/statspai/question/preregister.py）。

### 7.5 变量角色与粗粒度 DAG

不要求用户画出完整的 DAG。EHR 场景的协变量动辄几十个，强制画完整图在实践中只会流于形式。取而代之的是两样东西：

- variable_roles：每个变量或变量组标注一个角色。agent 依据变量目录中的测量窗口起草，用户确认。
- key_non_edges：显式写出少数几条决定识别成立的"无边"假设。IV 设定下至少包括：instrument 除经 treatment 外不影响 outcome（exclusion restriction），instrument 与未测混杂无关。

系统根据角色自动渲染一张变量组级别的图，放进报告。可选地，把这张粗粒度图交给 DoWhy 做识别，核对 adjustment_set 是否满足后门准则。【复用】DoWhy（MIT）的 CausalModel 与 identify_effect；渲染用 graphviz。

处理前（pre-treatment）是纳入调整集的必要条件，不是充分条件：处理前变量也可能是后门路径上的 collider（M-bias）。高维 DML 的常规做法是调整全部处理前变量；Ding 和 Miratrix（2015，Journal of Causal Inference）在线性结构方程模型下的分析表明，M-bias 通常小于不调整造成的混杂偏倚，但 Pearl（2015）在同刊的评论中对这一结论的适用范围提出了异议。因此，被标为 suspected_collider 的变量只触发 warning，并在报告中列出调整与不调整两种结果，不作为硬性门槛。【复用】该提示改写自 Baygent causal-inference 的关键规则（MIT）。

### 7.6 Estimand 与 family 对账

每个 family 在 family.yaml 中声明自己能识别的 estimand，例如：

- hte_iv：取决于识别假设。只假设 monotonicity 时，识别的是条件 LATE，仅对 complier 成立；如果另外假设给定协变量后效应不随 compliance 类型变化，才可解释为 CATE。TODO：按 Project 1 采用的假设填写。
- hte_backdoor：ATE、ATT、CATE。
- longitudinal_ipcw：lag_effect，按 7.3 节的定义。

validate 时比对 spec.estimand 与所选 family 的声明。不一致时有两种处理：改选 family，或者由用户改写 estimand。例如用户问"哪些患者获益"，而识别策略是 IV 且只假设了 monotonicity，那么报告必须写明，估计对象是 complier 的条件 LATE，不是全人群的 CATE。【复用】对账步骤参考 Baygent causal-inference 的设计选择第 5 步（MIT）。

如果问题所需的设计不在已支持的 family 之内（例如 DiD、断点回归、合成控制），系统明确回答不支持，并列出每个被排除的 family 及原因，不把问题硬塞进 backdoor 调整。【复用】展示被排除 family 及原因的做法参考 Causal desk（仅借鉴思路）。

---

## 8. 数据质量与可识别性评估

### 8.1 检查分层

| 层 | 检查 | 实现 |
|---|---|---|
| 基础 | 类型、取值范围、唯一性、缺失、NULL 编码变体 | 【复用】pandera（MIT）的 DataFrame schema 声明；NULL 编码变体检测自写 |
| 时间一致性 | treatment 早于 time zero、outcome 早于 treatment、时间倒序、follow-up 不足 | 自写；immortal time 检查的口径参考 StatsPAI 的 immortal_time_check（MIT，仅参考做法） |
| 可识别性 | treatment 流行率、overlap、SMD、suspected post-treatment、instrument relevance、censoring 与状态的关系 | overlap 与 SMD 自写（逻辑简单）；instrument relevance 见 8.2 |
| 可行性 | 各组样本量、事件数、子组最小 n、极端权重与 ESS | 自写 |

### 8.2 Instrument relevance

诊断形式由 family 决定，不统一使用 first-stage F。

effective F 检验（Montiel Olea–Pflueger）自写，并配一个对照原论文数值例的回归测试。Anderson–Rubin 检验放入 backlog，需要时再加。

不为这两个函数引入 StatsPAI：它体量大（依赖 numba、linearmodels 等）、版本迭代快，且近几个版本修正过若干函数的正确性问题；而这两个检验都是闭式的，自写加测试比锁定一个重依赖更可控，也更便于说明数值来源。

### 8.3 Issue schema

```yaml
check_id, layer, severity: blocking | warning | info, waivable,
evidence: {...}, affected_columns, impact_on_analysis, recommended_repair
```

每个检查都有一个地址 `qc:<check_id>`，供解读与报告引用。修复只作用于派生快照。

---

## 9. 估计、诊断与敏感性

| 内容 | 实现 |
|---|---|
| DMLIV（primary，IV 设定） | 你的代码，接口见 TODO |
| CausalForestDML（baseline） | 【复用】EconML（MIT），已在你的代码中使用 |
| HTE 校准：BLP、组别校准、uplift/QINI | hte_backdoor：【复用】EconML 的 econml.validate.DRTester（MIT），按所用版本的接口接入。hte_iv：DRTester 基于无混杂假设下的 doubly robust 得分，不能直接用于 IV 设定，需要改用 IV 版本的得分自写；TODO。你原代码中没有这部分 |
| 重复 cross-fitting 的排序稳定性 | 自写（循环 seed 调用估计器） |
| 未观测混杂敏感性（DML） | 【复用】DoubleML（BSD-3）的 sensitivity_analysis |
| E-value | 自写（闭式公式），配对照 VanderWeele & Ding (2017) 数值例的回归测试 |
| 反驳检验：placebo treatment、random common cause、data subset | 【复用】DoWhy（MIT）的 refuter |
| Longitudinal IPCW | 你的代码；正确性由合成数据 A 的真值覆盖率验证 |

依赖策略：只引入 EconML、DoWhy、pandera、DoubleML 四个直接依赖，都是成熟、接口稳定的库。闭式的诊断量（E-value、effective F）自写并配数值回归测试——自写的成本是几十行，而每多一个重依赖就多一份版本漂移与正确性风险。StatsPAI 不作为依赖引入，只在字段结构与做法上借鉴（见 7.3、7.4、11.2）。

---

## 10. 解读与报告

### 10.1 地址与占位符

所有计算产物都有地址，例如 `res:primary.estimate`、`res:primary.ci`、`qc:overlap_extreme_propensity`、`fig:cate_distribution`。模型撰写的报告正文只能以占位符引用数字，例如 `{{res:primary.estimate}}`；渲染器按地址代入数值；引用不存在的地址，或正文中出现未经占位的数字，渲染就失败，并把错误返回给模型重写。

【复用】"判断必须引用存在的地址，否则拒绝并重新提问"的机制参考 Causal desk ADR-0002（仅借鉴思路）。

### 10.2 结论措辞等级

四个等级：causal、suggestive、associational、descriptive。skill 规定正文措辞必须与判定的等级一致。

**代码只能降级，不能授予 causal。** untestable 类假设（unconfoundedness、exclusion restriction、monotonicity）不管跑多少检验都验证不了，因此代码自动判定的上限是 suggestive。升到 causal 需要两个额外条件，都记在 spec 里：每条 `category: untestable` 的假设都填了 `justification` 且该字段 `source=user`；用户显式确认愿意以因果措辞陈述。这样责任归属是清楚的——代码保证"诊断没发现问题"，人担保"假设成立"，报告里写明是谁认的。

**只有两项阻断检验。** 取舍原则是：

> 置信区间已经表达的，不再设闸。

样本量小、精度差，CI 自己会宽，读者看得见；为这些再设阈值是重复，而且正是让工具变得烦人、最终被绕过的那部分。CI 表达不了的只有系统性偏倚，来源就两个：

| 阻断检验 | 通过线 | 不通过意味着 |
|---|---|---|
| Overlap / positivity | 倾向得分落在 [0.05, 0.95] 之外的样本 ≤ 5% | 有一批人没有对照，估计是外推出来的；CI 会很窄，但窄得没有意义 |
| Instrument relevance（仅 IV 设定） | effective F 超过 MOP 表中对应所容忍偏倚水平的临界值 | 弱工具下偏倚可以任意大，CI 覆盖率失效 |

其余诊断——E-value、DoWhy 的三项反驳检验、调整后 SMD、重复 cross-fitting 的排序稳定性、suspected_collider 的双结果对照——**照算、照印、不设闸**。它们进报告供读者判断，不参与等级判定。只拦两件事的工具会被认真对待，拦十五件事的工具第一反应是被绕过。

定级规则：

```
descriptive    ← 门控没过（spec 未确认，或有未处理的 blocking 质量问题）
associational  ← 两项阻断检验任一不通过
suggestive     ← 两项都通过（代码能给的最高级）
causal         ← suggestive + 所有 untestable 假设已由用户 justify + 用户显式确认
```

外加两条：

- 任何降级都要在报告的"措辞等级及理由"一节写明是哪项检验、实测值多少、线在哪
- 用户可对阻断检验记豁免（须附理由），豁免在报告中单列，且**豁免过的分析不能达到 causal**

**阈值必须可见、可配、可复现。** 0.05/0.95 与 5% 都是惯例而非定律，能被合理质疑。真正重要的是三件事：事先定死（不是看到结果再定）、写进报告（读者看得到线在哪）、写进 manifest（半年后能复现当时的判定）。实现上放一个 `claim_levels.yaml`（`packages/causpec/core/reporting/`），规则全在里面，manifest 记其哈希，判定结果里也带上（`claim:rules_hash`）。

补充两条实现时定下的细节：

- **豁免不改变诊断结论。** 被豁免的阻断检验仍然把等级压到 associational，报告中注明"已豁免，但诊断结论不变"。豁免让分析得以进行，不让问题消失。
- **论证必须来自用户。** `source=model` 的论证不算数——模型论证自己的假设成立是循环的。`Assumption` 因此记 `justified_by`。

判定结果通过 `claim:` 命名空间进报告：`claim:level`、`claim:n_unjustified_assumptions`、`claim:rules_version`、`claim:rules_hash`。渲染器同时接受 `res:`、`qc:`、`claim:` 三个来源合并后的地址表。

【复用】等级划分与"通过不等于证明"的解释框架，改写自 Baygent causal-inference skill 的 scripts/check_refutation.py 与 references/refutation.md（MIT，保留版权声明）。原脚本区分 critical 与 marginal 两档检验、面向 Bayesian HDI；本项目取消 marginal 一档，阻断项收缩到上表两项，并改为频率学派诊断。

### 10.3 报告结构

依次为：问题与 spec（含每个字段的来源）→ estimand 及其适用人群 → 变量角色图 → 假设（按三类分列，写在结果之前）→ 数据质量 → 主结果 → 敏感性与反驳 → 措辞等级及理由 → 局限 → post_hoc 分析（如有）。

【复用】"假设写在结果之前"与固定结构报告的做法参考 Baygent references/reporting.md（MIT）。

---

## 11. 流程与门控

### 11.1 流程

1. 问题与 estimand。这一步不看数据，避免被数据里现成有什么变量牵着走。
2. 查看数据，确定 mapping。
3. 变量角色与 key_non_edges（7.5 节）。
4. 识别策略与假设分类。
5. 选定 family，做 estimand 对账（7.6 节）；不支持时在这一步停止。
6. 质量检查。
7. 用户确认 spec。
8. 估计与报告。

第 1–5 步完成字段级确认；第 7 步由 confirm_spec 对整份 spec 生成 spec_hash 并记录，用于锁定 primary 分析（7.4 节）和门控比对。

### 11.2 门控

estimate 执行前检查：

1. spec_hash 与确认记录一致，且关键字段全部 confirmed。
2. 存在针对当前 (snapshot_fingerprint, spec_hash) 的质量报告，没有未处理的 blocking 问题；可豁免的问题须有理由。
3. family.supports(spec) 通过，且 spec.estimand 在该 family 声明可识别的 estimand 之内。

不满足时返回结构化错误。错误内容包括 code、原因和修复建议。【复用】"错误到修复建议"的注册表模式参考 StatsPAI 的 agent/remediation.py（MIT）。

---

## 12. MCP server

| 工具 | 作用 |
|---|---|
| list_sources / describe_source | schema 与列统计，不含原始行 |
| register_dataset / apply_mapping | 生成快照 |
| draft_spec / update_field / confirm_spec | 字段级来源与状态管理 |
| route_family | 返回候选 family 与被排除的 family 及原因，并做 estimand 对账 |
| run_quality_check | 返回 issue 列表与地址 |
| record_waiver | 豁免须附理由 |
| estimate | 执行门控后运行 family |
| render_report | 占位符代入、措辞等级校验 |
| list_runs / get_run | 查询历史 |

实现要点：

- 使用官方 MCP Python SDK。
- 不修改任何状态的工具（list_sources、describe_source、route_family、list_runs、get_run 等）标注 readOnlyHint；会写入 server 状态的工具（update_field、confirm_spec、record_waiver 等）不标注 readOnlyHint，但所有工具都不修改数据源。返回值声明 outputSchema，并提供 structuredContent。这些都是 MCP 规范本身的特性。
- stdio 模式下日志只写 stderr。
- `causpec-mcp doctor`：检查依赖、连接，以及数据库账号是否确实没有写权限（实际尝试一次写入并预期失败）。
- schema drift 检查：apply_mapping 时比对数据源当前的列与 mapping 的预期，不一致则报错并列出差异。

**Postgres 的交付深度**：v0.3 只交付「薄 adapter + docker-compose demo」，目标是证明两件事——能接入由数据方建好的只读 view，以及只读保证确实来自账号权限（由 `doctor` 实际验证）。`masked_columns` 与 schema drift 检查放到 v1.0 之后。理由：本项目的差异化在因果推断的受控流程，不在数据库接入；把 Postgres 做深的边际收益远低于把质量检查和校准做扎实。`allowed_relations` 与路径边界（ADR-0002）不在削减之列，它们是安全边界，不是功能。

---

## 13. Skill

```
skill/causpec-analyst/
 ├─ SKILL.md
 ├─ references/  workflow.md、spec-fields.md、variable-roles.md、quality-checks.md、hte-dmliv.md、
 │               longitudinal-ipcw.md、reporting.md、claim-levels.md
 ├─ assets/      report-template.md、causpec wheel
 └─ scripts/run.py
```

SKILL.md 中的规则：

1. 每轮只问一个问题，从当前最关键的未确认字段问起。【复用】参考 Causal desk 的做法（仅借鉴思路）。
2. 数字只能通过占位符引用。
3. 措辞遵循代码判定的等级。
4. 需要领域知识时（instrument 是否有效、有无未测混杂）必须问用户。【复用】参考 Baygent causal-inference 的关键规则（MIT）。
5. 检测到 MCP 工具时走 MCP，否则走 scripts，并告知用户当前是 best-effort 模式。
6. 按 11.1 节的顺序推进：estimand 在查看数据之前确定。
7. 变量是否纳入调整集，先看测量时间，再看角色（7.5 节）。
8. 问题所需的设计不在支持范围内时，明确说明不支持并给出原因，不改用其他设计凑出结果。

---

## 14. 日志与产物

```
runs/<run_id>/
 ├─ manifest.json    execution_mode、git_sha、包版本、snapshot_fingerprint、spec_hash、seed、产物 checksum
 ├─ spec.yaml、mapping.yaml
 ├─ quality/         issues.json、quality_report.html
 ├─ results/         results.json（带地址）、figures/
 ├─ report.md / report.html
 └─ audit.jsonl      每次工具或 CLI 调用一行：时间、工具、参数 hash、输入指纹、输出 hash、是否出错
```

写文件采用临时文件加原子 rename。日志中不记录原始行，也不记录凭据。

---

## 15. 样本数据

- A：结构因果模型生成的合成数据，带真值，包含异质效应、instrument、informative censoring、变长轨迹。
- B：A 的两种口径（宽表、长事件表），用于验证换口径只需改 mapping。
- C：在 A 上注入问题，每个问题对应预期的 check_id。
- D：商业场景：带 non-compliance 的 A/B test，以及用户留存。

生成器入库，生成出来的数据不入库；任何真实数据都不得入库。

---

## 16. Evals

| 类别 | 内容 |
|---|---|
| 数值 | 与直接调用 family 的结果一致；固定 seed 可复现；在 A 上的真值覆盖率 |
| 质量检查 | 在 C 上逐一召回注入的问题 |
| 鲁棒性 | B 的两种口径得出一致结论 |
| 报告 | 渲染器拒绝未占位的数字和不存在的地址；措辞等级与诊断结果一致 |
| agent | 20–30 个 golden tasks：是否问对关键字段、是否遗漏诊断、是否越级措辞；包括 estimand 与识别策略不匹配的任务，以及需要不支持的设计（DiD、断点回归）的任务 |
| 回归 | 冻结若干已确认的 spec 与快照作为 fixture，family 的改动不能改变它们的结果 |

【复用】冻结的交接件作为回归测试，参考 Causal desk ADR-0004（仅借鉴思路）；skill 加载与否的对照评测，参考 Baygent evals/ 的组织方式（MIT）；外部任务可选用 CAIS 使用的 CauSciBench 中与本项目设定相符的部分（使用前核对许可）。

---

## 17. Related work（写入 README）

| 项目 | 定位 | 与 CauSpec 的区别 |
|---|---|---|
| Causal-Copilot、CAIS | 研究原型，追求全自动：LLM 选方法、生成代码、自我纠错 | CauSpec 不自动选方法，spec 须经用户确认 |
| StatsPAI | 覆盖面广的计量与因果库，附带 MCP 与 skills，带跨语言数值一致性分级 | CauSpec 聚焦两类分析的受控工作流；不引入其依赖，只借鉴 target trial 的字段结构与若干做法 |
| Causal desk | 受控的对话式因果分析，思路与 CauSpec 最接近 | CauSpec 面向数据库只读接入、HTE-IV 与纵向 IPCW |
| Baygent causal-inference | Bayesian 因果分析 skill，带强制检查点与措辞校准 | CauSpec 为频率学派加确定性服务端，并改写了其措辞校准 |

---

## 18. 待决问题

1. 研究代码的开源许可。
2. ipcw 中各事件的角色定义（7.3 节 TODO）。
4. EconML DRTester 在所用版本中的接口。

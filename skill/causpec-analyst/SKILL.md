---
name: causpec-analyst
description: 在观测数据上做因果分析的受控工作流。把自然语言问题转成逐字段确认的分析规格（spec），先评估数据能否支撑这个问题，再由确定性代码执行异质处理效应估计，产出数字全部可追溯的报告。适用于：用观测数据估计处理效应、异质效应（哪些人更获益）、工具变量分析、因果分析的数据质量与可识别性评估、判断一个因果问题能否用手头的数据回答。
---

# CauSpec Analyst

你负责**对话与判断**，不负责计算。所有数字由 `causpec` 这套确定性代码产生，
你通过占位符引用它们。这不是风格偏好——报告渲染器会拒绝正文里任何未经占位的数字。

## 关键规则

1. **每轮只问一个问题。** 从当前最关键的未确认字段问起，不要一次抛出五个问题。
2. **数字只能通过占位符引用**，例如 `{{res:primary.ate|+.3f}}`。
   不要自己算，不要把工具输出的数字抄进正文——渲染器会拒绝。
3. **措辞遵循代码判定的等级**（causal / suggestive / associational / descriptive），
   不得升级。等级由 `causpec` 判定并写进报告，你只负责让正文措辞与它一致。
4. **需要领域知识时必须问用户。** instrument 是否满足排除性约束、有没有未测混杂、
   某个变量是在处理前还是处理后测的——这些你推断不了，必须问。
5. **确认必须是真的确认。** 标 `status: confirmed` 的字段必须附上用户当时说的那句话
   （`said`）。**不得替用户确认**——即使你觉得答案显而易见。报告首页会把每个字段的
   来源和原话印出来供用户核对。
6. **estimand 在查看数据之前确定。** 先问清楚要回答什么，再去看数据里有什么列。
   反过来做会被数据里现成有的变量牵着走。
7. **变量是否纳入 `adjustment_set`，先看测量时间，再看角色。** 处理后测的变量
   一律不能进调整集。处理前是必要条件，不是充分条件。
8. **问题所需的设计不在支持范围内时，明确说明不支持并给出原因**，不要改用其他
   设计凑出一个结果。目前只支持两种识别策略，见下。

## 支持范围

| family | 识别策略 | 什么时候用 |
|---|---|---|
| `hte_backdoor` | 后门调整 | 相信可观测协变量足以控制混杂 |
| `hte_iv` | 工具变量 | 存在未测混杂，但有可信的 instrument |

**不支持**：DiD、断点回归、合成控制、中介分析、纵向/时变处理。
遇到这些，直接说明不支持，并说清楚为什么这个问题需要那种设计——不要塞进后门调整。

## 运行形态

当前只有 **scripts 形态**（best-effort）。MCP server 尚未实现。

```bash
python scripts/run.py quality  --spec spec.yaml --data <数据文件>
python scripts/run.py estimate --spec spec.yaml --data <数据文件> --report --narrative narrative.yaml
```

**必须告知用户当前是 best-effort 模式**：你在技术上可以绕过这些脚本直接用 pandas
读数据自己算，所以「数字只由代码产生」这条保证依赖你遵守规则。报告页眉会注明这一点。

## 八步流程

严格按顺序。第 1–5 步完成字段级确认，第 6 步之后才碰估计。

### 1. 问题与 estimand ——**这一步不看数据**

问清楚：处理是什么、结局是什么、想知道平均效应还是"哪些人更获益"。
把 `treatment`、`outcome`、`estimand` 写进 spec，每个都附用户原话。

### 2. 查看数据

用 `quality` 之外的方式看 schema（列名、类型、缺失率）。不要把原始行贴进对话。
把用户说的概念对应到具体列，逐个确认：「您说的"透析"对应 `isDialysisICU` 这一列吗？」

### 3. 变量角色：`effect_modifiers` 与 `adjustment_set` 分开

**这两个是不同的东西，必须分别确认**：

- `effect_modifiers`（X）——效应随之变化的变量。进了 X 就会被当作效应修饰因子。
- `adjustment_set`（W）——只用于去除混杂，不进 CATE。

放错位置不会报错，只会**悄悄改变估计对象**。

### 4. 识别策略与假设

选后门还是 IV，取决于用户对「可观测协变量是否足以控制混杂」的判断——问他。
把假设写进 `assumptions`，按三类标注：

| category | 含义 |
|---|---|
| `empirically_assessed` | 数据能查（质量检查会给证据） |
| `requires_justification` | 数据查不了，但可以论证 |
| `untestable` | 原则上无法由数据检验 |

`untestable` 那些（unconfoundedness、exclusion restriction、monotonicity）
**跑再多检验也证明不了**。它们决定了结论最多能用什么措辞。

### 5. 选 family 并对账 estimand

比对用户想要的 estimand 与 family 声明能识别的（见 `references/hte-dmliv.md`）。
不一致时**在这一步停下**，要么改选 family，要么请用户改写 estimand。

典型冲突：用户问「哪些患者获益」（想要 CATE），而识别策略是 IV 且只假设了
monotonicity——那么识别的是 complier 的条件 LATE，不是全人群的 CATE。

### 6. 质量检查

```bash
python scripts/run.py quality --spec spec.yaml --data <数据文件>
```

有 blocking 问题就**停下来**，把问题和修复建议念给用户听。
**即使分析跑不了，这份质量报告本身就是交付物**——不要因为估计做不成就跳过它。

豁免需要用户明确给出理由，而且豁免过的分析永远达不到 `causal` 级措辞。

### 7. 用户确认整份 spec

把 spec 完整念一遍，请用户逐字段确认。这一步不能省。

### 8. 估计与报告

```bash
python scripts/run.py estimate --spec spec.yaml --data <数据文件> \
    --report --narrative narrative.yaml --run-dir runs/
```

`narrative.yaml` 是**你**写的解读，按段落组织：

```yaml
estimand: 本次估计的是……
data_quality: 共同支撑充分，落线外的样本占 {{qc:backdoor_overlap.extreme_fraction|.1%}}。
primary_results: 平均效应 {{res:primary.ate|+.3f}}，{{lit:95}}% 置信区间 [...]。
limitations: 本分析依赖……
```

你只能写这六节：`estimand`、`data_quality`、`primary_results`、`sensitivity`、
`limitations`、`post_hoc`。**spec 来源表与措辞等级判定由代码生成，你碰不到**——
前者是给用户核查你有没有替他确认的，后者是原则性的。

## references

需要细节时按需读，不要一次全读：

| 文件 | 什么时候读 |
|---|---|
| `workflow.md` | 八步流程每一步该怎么问 |
| `spec-fields.md` | spec 各字段的含义与写法 |
| `variable-roles.md` | X 与 W 怎么分，哪些变量不能进调整集 |
| `quality-checks.md` | 某条检查未通过时怎么向用户解释 |
| `hte-dmliv.md` | IV 设定：估计对象、二值与连续 instrument 的区别 |
| `reporting.md` | 报告结构与占位符语法 |
| `claim-levels.md` | 四级措辞的判定依据与用词 |
| `longitudinal-ipcw.md` | 纵向分析（**尚未实现**） |

# IV 设定下的异质处理效应

## 什么时候用 `hte_iv`

用户认为**存在未测混杂**——即可观测协变量不足以控制混杂——但手头有一个
可信的 instrument。

这是个需要用户判断的问题，不是你能从数据里看出来的。问法：

> 「有没有什么因素同时影响了谁接受处理、以及结局，但数据里没记录？
> 比如医生对病情的主观判断、家属意愿、没写进病历的体征？」

有 → 考虑 IV。没有（且用户有把握）→ 用 `hte_backdoor`。

## 估计对象：这是最容易讲错的地方

**IV 识别的不是全人群的效应。**

### 二值 instrument

在 relevance、exclusion restriction、monotonicity 三条假设下，识别的是
**complier 的条件 LATE**——即「因为 instrument 取值不同而改变了是否接受处理」
的那部分人的效应。

complier **无法被识别到个体**。所以：

- ✗ 「这位患者的预期获益是 X」
- ✗ 「全人群平均效应为 X」
- ✓ 「在因医生倾向不同而改变了治疗决策的那部分患者中，效应为 X」

`iv_low_complier_share` 这条检查会告诉你 complier 占多大比例。占比很小时，
**必须在报告里写明结论只对人群中很窄的一部分成立**。

### 连续 instrument

不存在单一的 complier 群体。在 uniformity（monotonicity 对连续情形的推广）下，
识别的是各相邻取值之间「边际 LATE」的加权平均，权重由该处一阶段的斜率与
instrument 的分布共同决定（Angrist & Imbens 1995, JASA）。

**权重不由用户选择，也不等同于人群占比。** 所以这个估计对象的适用人群
比二值情形更难描述——报告里要如实说明这一点，不要简化成「平均效应」。

`res:instrument.kind` 会告诉你这次是 `binary` 还是 `continuous`。

### 什么时候能叫 CATE

只有在额外假设「给定协变量后效应不随 compliance 类型变化」时，上述估计对象
才可解释为全人群的 CATE。**这条假设本身也是 untestable 的**，要用户明确认领。

## estimand 对账

用户问「哪些患者获益」时想要的是 CATE。如果识别策略是 IV 且只假设了
monotonicity，**这两者不一致**——在第 5 步就要停下来，让用户二选一：

1. 改写 estimand，接受结论只对 complier 成立
2. 补上「效应不随 compliance 类型变化」这条假设，并论证它

不要默默按 CATE 汇报。

## 两个后端

| | `ivforest`（默认） | `dmliv` |
|---|---|---|
| CATE 区间 | GRF honest 方差，一次拟合内完成 | bootstrap |
| ATE 区间 | 对森林做单位层面 bootstrap | bootstrap |
| 速度（n=5000） | 每次重抽样约 5 秒 | 约 26 秒 |
| 多个 instrument / `adjustment_set` | 不支持 | 支持 |

`dmliv` 只能 bootstrap 不是选择，是 EconML 对那个类的唯一选项——它的
final model 是任意回归器，推不出方差。

**重抽样次数默认 200。** 调低会变快但区间失真：实测同一份数据，20 次重抽样
与解析区间给出的「个体显著获益人数」差了两个数量级。次数不足 100 时结果里会
打标记（`res:estimation.bootstrap_adequate`），报告要把这件事说出来。

多核机器上加 `bootstrap_n_jobs: 8`，实测 4.6 倍加速且结果完全一致。

## 三条假设怎么记进 spec

```yaml
assumptions:
  - id: relevance
    category: empirically_assessed      # 质量检查会给证据
    statement: instrument 与 treatment 相关且强度足够
  - id: exclusion_restriction
    category: untestable                # 跑什么检验都证明不了
    statement: instrument 只通过 treatment 影响 outcome
  - id: monotonicity                     # 连续 instrument 时换成 uniformity
    category: untestable
    statement: 不存在 defier
```

exclusion restriction 需要**领域论证**，必须问用户：

> 「除了影响是否透析之外，主治医生的既往透析倾向还有没有别的途径
> 影响患者的死亡风险？比如倾向高的医生在其他方面也更积极？」

`iv_covariate_imbalance` 这条检查只能验证一个**必要条件**——instrument 若真的
近似随机分配，协变量应当是平衡的。**平衡不构成 exclusion restriction 成立的证据。**

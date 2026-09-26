# 八步流程

顺序是有理由的，不要跳步。每一步都给了具体的问法。

---

## 1. 问题与 estimand ——**不看数据**

先问清楚要回答什么，再去看数据里有什么列。反过来做会被现成有的变量牵着走——
「哦数据里有个 `los` 列，那顺便看看住院天数吧」，这就偏离了用户真正的问题。

**问什么**（一轮一个）：

> 「您想比较的是接受什么处理 vs 不接受？」
> 「结局看什么？发生在什么时间窗内？」
> 「您想知道的是**整体平均**效应，还是**哪些人更获益**？」

第三问决定 estimand：整体 → `ate`；哪些人 → CATE（此时 `effect_modifiers` 是核心）。

写进 spec，每个字段附用户原话，`status: confirmed`。

---

## 2. 查看数据

现在才看 schema。**不要把原始行贴进对话。**

把用户的概念对应到具体列，逐个确认：

> 「您说的『透析』，对应的是 `isDialysisICU` 这一列吗？它是 0/1 的。」
> 「`death` 这一列记的是院内死亡还是 28 天死亡？」

遇到含义不明的列名，问，不要猜。

---

## 3. 变量角色

`effect_modifiers`（X）与 `adjustment_set`（W）**分开确认**。
详见 `variable-roles.md`——这是最容易出错且出错不报错的地方。

**先看测量时间**：处理后测的变量一律不能进调整集。

> 「`max_creatinine` 是入 ICU 时测的，还是包含了开始透析之后的值？」

---

## 4. 识别策略与假设

关键一问：

> 「有没有什么因素同时影响了谁接受处理、以及结局，但数据里没记录？」

- 没有（用户有把握）→ `hte_backdoor`
- 有，但存在可信的 instrument → `hte_iv`
- 有，也没有 instrument → **如实说明这个问题回答不了**，但质量报告仍可交付

把假设写进 `assumptions`，按三类标注。`untestable` 那些要当面讲清楚：

> 「『给定这些协变量后，谁接受透析与患者的预后无关』——这一条没有任何统计检验
> 能验证。它成立与否只能靠临床判断。您愿意为它背书吗？如果愿意，
> 请说明理由，我记进报告。」

---

## 5. 选 family 并对账 estimand

比对用户想要的与 family 能识别的。不一致**就在这里停下**。

最常见的冲突：用户问「哪些患者获益」（要 CATE），识别策略是 IV 且只假设了
monotonicity（只能识别 complier 的条件 LATE）。详见 `hte-dmliv.md`。

不支持的设计（DiD、断点回归、合成控制、中介、纵向）：说明不支持，
说清为什么这个问题需要那种设计，**不要塞进后门调整**。

---

## 6. 质量检查

```bash
python scripts/run.py quality --spec spec.yaml --data <数据文件>
```

有 blocking 问题就停下，把 `impact_on_analysis` 和 `recommended_repair`
**念给用户听**（不要自己重新组织措辞）。详见 `quality-checks.md`。

**即使分析跑不了，这份报告本身就是交付物。**

---

## 7. 用户确认整份 spec

把 spec 完整念一遍，逐字段请用户确认。这一步不能省，也不能由你代劳。

如果用户要用因果措辞（而不是「提示可能相关」），这一步还要：

1. 请他为每条 `untestable` 假设给出论证
2. 加上 `causal_claim_approved` 字段

不做这两件事，代码判定的上限就是 `suggestive`。

---

## 8. 估计与报告

```bash
python scripts/run.py estimate --spec spec.yaml --data <数据文件> \
    --report --narrative narrative.yaml --run-dir runs/
```

写 `narrative.yaml` 的规则见 `reporting.md`。

跑完之后：

- 把措辞等级和**判定理由**告诉用户——不只是等级，还有为什么不能更高
- 指出 run 目录的位置，里面有 manifest（含依赖版本与 checksum），可复现

# claim-levels

> 占位。Phase 2（W4）填充。

对应 design.md 10.2。四级措辞：causal / suggestive / associational / descriptive。

等级由**代码**判定，skill 只负责让正文措辞与判定的等级一致，不得自行升级。

## 代码只能降级，不能授予 causal

untestable 类假设（unconfoundedness、exclusion restriction、monotonicity）不管跑多少检验都验证不了，所以**代码自动判定的上限是 suggestive**。升到 causal 需要人担保：每条 untestable 假设都填了 justification 且 `source=user`，加上用户显式确认愿意以因果措辞陈述。

## 只有两项阻断检验

取舍原则：**置信区间已经表达的，不再设闸。** 样本量、精度这些 CI 自己会说；CI 说不了的只有系统性偏倚。

| 阻断检验 | 通过线 |
|---|---|
| Overlap / positivity | 倾向得分落在 [0.05, 0.95] 之外的样本 ≤ 5% |
| Instrument relevance（仅 IV） | effective F 超过 MOP 表对应临界值 |

E-value、反驳检验、SMD、排序稳定性**照印不设闸**，进报告供读者判断。

## 定级

```
descriptive    ← 门控没过
associational  ← 两项阻断任一不通过
suggestive     ← 两项都通过
causal         ← suggestive + 人担保 untestable 假设 + 用户显式确认
```

降级必须在报告里写明：哪项检验、实测值多少、线在哪。

改写自 Baygent causal-inference 的 `scripts/check_refutation.py` 与 `references/refutation.md`（MIT，保留版权声明）；取消了原脚本的 marginal 一档，阻断项收缩到两项，并改为频率学派诊断。

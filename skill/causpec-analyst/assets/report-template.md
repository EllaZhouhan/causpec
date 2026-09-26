# narrative.yaml 模板

把下面这份复制过去改。**只有这六个键是允许的**，其余段落由代码生成。

```yaml
# ---- 估计对象与适用人群 ----
# 说清楚这个数字是关于谁的。IV 设定下尤其重要——它不是全人群的效应。
estimand: >
  本次估计的是……。它回答的是「……」，不针对任何具体个体。

# ---- 数据质量 ----
# 解读检查结果，不要重复上面那张表。引用具体数值用 qc: 地址。
data_quality: >
  共同支撑充分，倾向得分落在阈值之外的样本占
  {{qc:backdoor_overlap.extreme_fraction|.1%}}。IPW 加权后最大 |SMD| 从
  {{qc:backdoor_covariate_imbalance.max_abs_smd_before|.3f}} 降到
  {{qc:backdoor_covariate_imbalance.max_abs_smd_after|.3f}}。

# ---- 主结果 ----
# 措辞必须与 claim:level 一致。数字一律用占位符。
primary_results: >
  在 {{res:sample.n}} 名患者中，{{res:sample.n_treated}} 人接受了处理。
  平均效应为 {{res:primary.ate|+.3f}}，{{lit:95}}% 置信区间
  [{{res:primary.ate_ci_lower|+.3f}}, {{res:primary.ate_ci_upper|+.3f}}]，
  区间由 {{res:primary.ate_ci_method}} 给出。
  个体效应的中位数为 {{res:cate.median|+.3f}}，其中
  {{res:cate.n_significant_benefit}} 人的置信区间整体位于零以下。

# ---- 敏感性与反驳 ----
# 尚未实现。留空即可，代码会注明「本节留空不代表该项检查已通过」。
sensitivity: ""

# ---- 局限 ----
# 至少要提到 untestable 假设，以及人群的外推边界。
limitations: >
  本分析依赖……这一无法检验的假设。样本来自……，外推到其他环境需谨慎。

# ---- 事后分析（如有）----
# 看过结果之后才决定做的分析放这里，不要混进主结果。
post_hoc: ""
```

## 常见错误

| 写法 | 为什么会失败 |
|---|---|
| `平均效应约为 -0.018。` | 裸数字——渲染器拒绝 |
| `{{res:primary.ate}}` 不加格式 | 能跑，但输出 17 位有效数字 |
| `{{lit:0.018}}` 当作效应值 | `lit` 里夹带计算结果——渲染器拒绝 |
| 加 `claim_level:` 键 | 那一节由代码生成，模型不得撰稿 |
| 「透析降低了死亡率」而等级是 `suggestive` | 越级措辞 |

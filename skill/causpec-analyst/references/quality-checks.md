# 质量检查

```bash
python scripts/run.py quality --spec spec.yaml --data <数据文件>
```

**即使估计跑不了，这份报告本身就是交付物。** 不要因为分析做不成就跳过这一步。

有 blocking 问题时退出码非零。每条检查都有地址 `qc:<check_id>.<证据>`，
可以在报告正文里引用。

## `hte_backdoor`

| check_id | 级别 | 不通过意味着 |
|---|---|---|
| `backdoor_overlap` | **阻断** | 有一批人在协变量上几乎没有对照，对他们的效应是**外推**出来的 |
| `backdoor_covariate_imbalance` | 警告 | IPW 加权后仍不平衡，说明调整可能不充分 |
| `backdoor_treatment_prevalence` | 警告 | 某一组样本过少，估计方差很大 |
| `backdoor_extreme_weights` | 警告 | 少数个体的权重主导了估计 |

## `hte_iv`

| check_id | 级别 | 不通过意味着 |
|---|---|---|
| `iv_zero_variation` | **阻断（不可豁免）** | instrument 在本人群中没有变异，一阶段无从识别 |
| `iv_weak_first_stage` | **阻断** | 弱工具下偏倚可以任意大，置信区间的覆盖率失效 |
| `iv_low_complier_share` | 警告 | 结论只对人群中很窄的一部分成立 |
| `iv_covariate_imbalance` | 警告 | instrument 未必接近随机分配 |

## 为什么只有两项阻断

取舍原则是：**置信区间已经表达的，不再设闸。**

样本量小、精度差，CI 自己会宽，读者看得见。CI 表达不了的只有系统性偏倚——
而偏倚的来源就两个：缺乏共同支撑（后门设定）和弱工具（IV 设定）。

其余诊断照算、照印、不设闸。只拦两件事的工具会被认真对待，
拦十五件事的第一反应是被绕过。

## 怎么向用户解释

每条 issue 都带 `impact_on_analysis` 和 `recommended_repair`——**念给用户听，
不要自己重新组织措辞**。它们是按照因果推断的口径写的。

比如 overlap 不通过时：

> 「有 88% 的患者找不到病情相近的对照。对这些人的效应估计是**外推**出来的，
> 而不是从数据里观察到的。此时置信区间会显得很窄，但窄得没有意义。
> 建议把分析限制到有共同支撑的那部分人群——**这会改变估计对象**，
> 报告里要写明改成了对谁的效应。」

## 豁免

用户坚持要在有 blocking 问题的情况下继续时：

```bash
python scripts/run.py estimate ... --waive "backdoor_overlap=已限制到有共同支撑的子人群，见方案 3.2 节"
```

三条规则：

1. **必须附理由**，空理由会被拒绝
2. `waivable: false` 的检查（如 `iv_zero_variation`）**即使给了理由也不放行**
3. **豁免不改变诊断结论**——被豁免的阻断检验仍然把措辞等级压到 `associational`，
   而且豁免过的分析永远达不到 `causal`

豁免的理由会落盘到 run 目录，是事后审查这次分析时最该看的东西。

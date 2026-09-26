# spec 字段

## 结构

```yaml
spec_version: 1
question: 透析对 ICU 患者死亡率的平均效应？
family: hte_backdoor              # hte_backdoor | hte_iv

estimation:
  params:                          # 估计器超参，会进 spec_hash 与 manifest
    n_estimators: 500
    estimator: ivforest            # 仅 hte_iv：ivforest（默认）| dmliv
    n_bootstrap_samples: 200

assumptions:
  - id: unconfoundedness
    category: untestable           # empirically_assessed | requires_justification | untestable
    statement: 给定调整集后，处理分配与潜在结局独立
    justification: ""              # 用户的论证；untestable 类要用 causal 措辞就必须填
    justified_by: user             # 必须是 user——模型自己论证不算数

fields:
  treatment:
    value: isDialysisICU
    source: user                   # user | model | data
    said: 处理就是 ICU 内开始透析    # 用户原话
    turn: 2
    status: confirmed              # drafted | confirmed
  outcome:      {value: death, ...}
  estimand:     {value: ate, ...}
  effect_modifiers: {value: [列1, 列2, ...], ...}
  adjustment_set:   {value: [列3, ...], ...}
  instrument:       {value: [列4], ...}          # 仅 hte_iv
  causal_claim_approved: {value: true, ...}      # 用户同意用因果措辞时才加
```

## 每个字段都要记来源

| 键 | 含义 |
|---|---|
| `value` | 取值。列名、列名列表，或 estimand 的名字 |
| `source` | 这个值是谁提出的：`user`（用户说的）、`model`（你推断的）、`data`（从数据得出） |
| `said` | 用户的**原话**。见下 |
| `turn` | 第几轮对话 |
| `status` | `drafted`（待确认）或 `confirmed`（已确认） |

## `said` 的两条必填规则

1. `source: user` 时必填——用户说的话是证据，要原样留底
2. **`status: confirmed` 时必填**，与 `source` 无关

第二条是重点。你推断出 `outcome = death`（`source: model`），用户说「对，就看院内死亡」，
这时标 `confirmed`，`source` 仍是 `model`，但 `said` 记用户认可时的那句话。

**不得替用户确认。** 系统无法验证用户是否真的看过 spec——所以要求确认必附原话，
而报告首页会把每个字段的来源和原话印出来供用户核对。你编一句用户没说过的话，
用户一眼能看出来。

## 关键字段

门控要求这些全部 `confirmed` 才放行估计：`treatment`、`outcome`、`estimand`。

各 family 另有必需字段：

| family | 另需 |
|---|---|
| `hte_backdoor` | `effect_modifiers` |
| `hte_iv` | `effect_modifiers`、`instrument` |

## assumptions 的三分类

| category | 含义 | 谁来支撑 |
|---|---|---|
| `empirically_assessed` | 数据能查 | 质量检查给出证据 |
| `requires_justification` | 数据查不了，但可以论证 | 用户论证 |
| `untestable` | **原则上无法由数据检验** | 只能由用户承担 |

只有 `untestable` 那些参与 `causal` 级措辞的门槛。它们没被用户论证时，
代码判定的上限就是 `suggestive`——详见 `claim-levels.md`。

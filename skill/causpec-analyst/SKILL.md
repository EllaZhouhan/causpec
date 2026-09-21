---
name: causpec-analyst
description: 在观测数据上做因果分析的受控工作流。把自然语言问题转成逐字段确认的分析规格（spec），先评估数据能否支撑这个问题，再由确定性代码执行 HTE 或纵向处理效应估计，产出数字全部可追溯的报告。适用于：用观测数据估计处理效应、异质效应（谁更获益）、工具变量分析、纵向/时变处理分析、因果分析的数据质量与可识别性评估。
---

> 骨架，Phase 2（W4，v0.2）填充。对应 design.md 第 13 节。

# CauSpec Analyst

## 关键规则

1. **每轮只问一个问题**，从当前最关键的未确认字段问起。
2. **数字只能通过占位符引用**，例如 `{{res:primary.estimate}}`。不要自己写数字，不要自己算。
3. **措辞遵循代码判定的等级**（causal / suggestive / associational / descriptive），不得升级。
4. **需要领域知识时必须问用户**——instrument 是否有效、有无未测混杂，这些不能由你推断。
5. **检测到 MCP 工具时走 MCP**，否则走 `scripts/run.py`，并告知用户当前是 best-effort 模式。
6. **estimand 在查看数据之前确定**（见下面的流程顺序）。
7. **变量是否纳入调整集，先看测量时间，再看角色**。处理前是必要条件不是充分条件。
8. **问题所需的设计不在支持范围内时，明确说明不支持并给出原因**，不改用其他设计凑出结果。

## 流程

按顺序推进，第 1–5 步完成字段级确认：

1. 问题与 estimand —— **这一步不看数据**，避免被数据里现成有什么变量牵着走
2. 查看数据，确定 mapping
3. 变量角色与 key_non_edges
4. 识别策略与假设分类
5. 选定 family，做 estimand 对账 —— 不支持时在这一步停止
6. 质量检查
7. 用户确认 spec（`confirm_spec` 生成 spec_hash）
8. 估计与报告

详见 `references/workflow.md`。

## references

| 文件 | 内容 |
|---|---|
| `workflow.md` | 八步流程的详细说明与每步的提问方式 |
| `spec-fields.md` | spec 各字段的含义、来源标记、确认规则 |
| `variable-roles.md` | 变量角色与 key_non_edges 的起草方法 |
| `quality-checks.md` | 四层检查的解读方式 |
| `hte-dmliv.md` | IV 设定下的 HTE：假设、estimand 的适用人群 |
| `longitudinal-ipcw.md` | 纵向：target trial 七要素与 event_roles |
| `reporting.md` | 报告结构与占位符写法 |
| `claim-levels.md` | 四级措辞的判定依据与用词 |

## TODO

- [ ] 补全八个 references
- [ ] `assets/report-template.md`
- [ ] `assets/` 放入 causpec wheel
- [ ] `scripts/run.py` 接 CLI

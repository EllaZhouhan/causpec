# spec-fields

> 占位。Phase 2（W4）填充。

对应 design.md 7.1、7.2。每个字段的含义、`source`（user / model / data）与 `status`（drafted / confirmed）怎么标，关键字段有哪些。

**不得在未获得用户明确答复的情况下标记 `confirmed`。** 标 confirmed 必须附上用户确认时说的那句话（`said`），与 `source` 无关——模型推断的值经用户认可后同样标 confirmed，此时 `source` 仍是 model，`said` 记用户认可时的原话。

关键字段：population、treatment、outcome、time_zero、estimand、variable_roles、key_non_edges、identification_strategy、adjustment_set、instrument，以及 longitudinal 的 event_roles。

# server/causpec_mcp

本地 MCP server，CauSpec 的**主形态**（design.md 第 3 节）。跑在用户自己的机器上，Claude Code / Desktop 连它。

Phase 3（W5，v0.3）实现。

## 工具清单（design.md 第 12 节）

| 工具 | 作用 | readOnlyHint |
|---|---|---|
| `list_sources` | 列出配置的数据源 | ✅ |
| `describe_source` | schema 与列统计，**不含原始行** | ✅ |
| `register_dataset` | 生成 DuckDB 快照 | |
| `apply_mapping` | 应用 mapping 并检查 schema drift | |
| `draft_spec` | 起草 spec | |
| `update_field` | 更新单个字段的 value/source/status | |
| `confirm_spec` | 生成 spec_hash 并记录确认 | |
| `route_family` | 返回候选 family、被排除的 family 及原因，做 estimand 对账 | ✅ |
| `run_quality_check` | 返回 issue 列表与地址 | |
| `record_waiver` | 豁免须附理由 | |
| `estimate` | 执行门控后运行 family | |
| `render_report` | 占位符代入、措辞等级校验 | |
| `list_runs` | 查询历史 | ✅ |
| `get_run` | 查询单次运行 | ✅ |

未标 readOnlyHint 的工具会写入 server 状态，但**没有任何工具修改数据源**。

## 门控（design.md 11.2）

`estimate` 执行前检查三条，任一不满足返回结构化错误（code + 原因 + 修复建议）：

1. `spec_hash` 与确认记录一致，且关键字段全部 `confirmed`
2. 存在针对当前 `(snapshot_fingerprint, spec_hash)` 的质量报告，无未处理的 blocking 问题；豁免须有理由
3. `family.supports(spec)` 通过，且 `spec.estimand` 在该 family 声明可识别的范围内

## doctor

```bash
causpec-mcp doctor
```

检查依赖、数据源连接，以及**数据库账号是否确实没有写权限**——只读保证来自账号权限，不来自 prompt。

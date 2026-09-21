# examples/deployments/

部署配置示例（design.md 第 5 节、6.1）。Phase 5 填充。

- `demo-hospital/` —— ICU 场景，Postgres 只读 view
- `demo-retail/` —— 商业场景，带 non-compliance 的 A/B test

每个示例包含 `sources.yaml`，形如：

```yaml
sources:
  - id: icu_pg
    type: postgres
    dsn_env: CAUSPEC_ICU_DSN
    allowed_relations: [analytics.v_cohort, analytics.v_timeseries]
    masked_columns: [patient_name, mrn]
```

**复杂的连接和派生由数据方用 SQL view 实现并人工审阅，CauSpec 只读 view，不自建 ETL。**
这也是 FDE 在客户现场的常规分工。

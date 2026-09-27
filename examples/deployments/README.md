# examples/deployments/

Example deployment configurations (design.md section 5 and 6.1). Filled in during Phase 5.

- `demo-hospital/` — an ICU setting, Postgres read-only views
- `demo-retail/` — a commercial setting, an A/B test with non-compliance

Each example carries a `sources.yaml` of the form:

```yaml
sources:
  - id: icu_pg
    type: postgres
    dsn_env: CAUSPEC_ICU_DSN
    allowed_relations: [analytics.v_cohort, analytics.v_timeseries]
    masked_columns: [patient_name, mrn]
```

**Complex joins and derivations are implemented by the data owner as SQL views and
reviewed by a person; CauSpec reads the views and builds no ETL of its own.** That is
also how the division of labour usually runs on a customer site.

# data/

**Generated data is never committed.** This directory holds only the generators
(`generators/`); the CSV, Parquet and DuckDB files they produce are stopped by both
`.gitignore` and a pre-commit hook.

No real data may go in this repository at all.

The synthetic datasets (design.md section 15):

- **A**: generated from a structural causal model with known ground truth —
  heterogeneous effects, an instrument, informative censoring, variable-length trajectories
- **B**: dataset A in two shapes (wide table, long event table)
- **C**: dataset A with problems injected, each mapped to an expected `check_id`
- **D**: a commercial setting (an A/B test with non-compliance, user retention)

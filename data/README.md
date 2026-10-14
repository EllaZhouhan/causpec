# data/

**Generated data is never committed.** This directory holds only the generators
(`generators/`); the CSV, Parquet and DuckDB files they produce are stopped by both
`.gitignore` and a pre-commit hook.

No real data may go in this repository at all.

The synthetic datasets (design.md section 15). Three of the four are built; D is designed
and not written, and the generator that exists for each one is named:

- **A** (`generators/dataset_a.py`, and `dataset_a_panel.py` for the panel shape): generated from a structural causal model with known ground truth, with
  heterogeneous effects, an instrument, informative censoring, variable-length trajectories
- **B** (`generators/dataset_a_panel.py`): dataset A in two shapes, a wide table and a long event table
- **C** (`generators/dataset_c.py`): dataset A with one problem injected at a time, each declaring the `check_id` and
  severity it expects, asserted in CI (`generators/dataset_c.py`). Every defect is a mistake
  that happens to real extracts rather than a random perturbation: a sentinel for "not
  measured", a join that duplicates rows, a cohort anchored on its own exposure
- **D**: a commercial setting, an A/B test with non-compliance and user retention. **Designed, not written** (plan.md Phase 2)

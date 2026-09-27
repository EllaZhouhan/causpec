# data/generators/

Synthetic data generators. **The generators are committed; what they produce is not.**

Mirrors design.md section 15:

| Dataset | Contents | When |
|---|---|---|
| **A** | Structural causal model with ground truth: heterogeneous effects, an instrument, informative censoring, variable-length trajectories | Phase 0 task 4 (cross-sectional), Phase 4 task 3 (longitudinal) |
| **B** | Dataset A in two shapes: wide table and long event table | Phase 3 task 4 |
| **C** | Dataset A with problems injected, each mapped to an expected `check_id` | Phase 1 task 6 |
| **D** | Commercial setting: an A/B test with non-compliance, user retention | Phase 5 task 1 |

Every generator fixes a seed and emits the ground truth alongside the data, so evals
can compute coverage.

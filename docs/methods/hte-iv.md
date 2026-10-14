# The IV backends, and where each interval comes from

Moved out of the README, which needs the summary rather than the derivation.

## Two backends

`hte_iv` has two backends, selected through `spec.estimation.params.estimator`. Both
binary and continuous instruments are supported.

| | `ivforest` (default) | `dmliv` |
|---|---|---|
| Class | `econml.grf.CausalIVForest` | `econml.iv.dml.NonParamDMLIV` |
| CATE interval | GRF honest variance, within one fit | bootstrap |
| ATE interval | unit-level bootstrap of the forest | bootstrap |
| Per replicate | about 5s (n=5000) | about 26s |
| Multiple instruments / `adjustment_set` | not supported | supported |

**Why `dmliv` can only bootstrap**: its final model is an arbitrary regressor, so
EconML can derive no variance for it, `_get_inference_options()` lists nothing else.
That is not a choice, it is the only option.

**Why `ivforest`'s ATE interval also bootstraps**: `econml.grf` exposes only
**pointwise** variance (the covariance matrix from `predict_and_var` is across output
dimensions at a single x, not across different x). The per-point estimates from one
forest are highly correlated, so averaging pointwise variances and dividing by n would
assume independence. The CATE interval therefore uses GRF's analytic variance while the
ATE interval bootstraps, different mechanisms, recorded separately in
`res:cate.ci_method` and `res:primary.ate_ci_method` for the report to explain.

**The replicate count** defaults to 200 for both backends and is overridable:

```yaml
estimation:
  params:
    estimator: ivforest
    n_bootstrap_samples: 200   # below 100, res:estimation.bootstrap_adequate = "no"
    bootstrap_n_jobs: 8        # indices are drawn up front, so this cannot change the result
```

Lowering the count distorts the interval: on the same data, 20 replicates and the GRF
analytic interval differed by two orders of magnitude in the count of individuals with
a significant benefit (416 against 3). Below the threshold the Result is flagged and the
report has to surface it.

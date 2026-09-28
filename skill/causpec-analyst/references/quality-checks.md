# Quality checks

```bash
python scripts/run.py quality --spec spec.yaml --data <data file>
```

**Even when estimation cannot run, this report is a deliverable.** Do not skip it
because the analysis is impossible.

The exit code is non-zero when a blocking issue is present. Every check has an address
`qc:<check_id>.<evidence>` that the report prose can cite.

## `hte_backdoor`

| check_id | Level | What failing means |
|---|---|---|
| `backdoor_overlap` | **blocking** | Some people have almost no comparable controls, so their effect is **extrapolated** |
| `backdoor_covariate_imbalance` | warning | Still imbalanced after IPW, so the adjustment may be incomplete |
| `backdoor_treatment_prevalence` | warning | One arm is too small; the estimate carries a large variance |
| `backdoor_extreme_weights` | warning | A handful of individuals dominate the estimate |

## `hte_iv`

| check_id | Level | What failing means |
|---|---|---|
| `iv_zero_variation` | **blocking, not waivable** | The instrument does not vary here; nothing for the first stage to identify |
| `iv_weak_first_stage` | **blocking** | Under a weak instrument the bias can be arbitrarily large and the interval loses coverage |
| `iv_low_complier_share` | warning | The conclusion holds for only a narrow slice of the population |
| `iv_covariate_imbalance` | warning | The instrument may not be close to randomly assigned |

## Why only two blocking checks

The trade-off is: **if the confidence interval already says it, do not gate on it.**

Small samples and poor precision widen the interval, and the reader can see that. What
an interval cannot express is systematic bias, and bias has two sources here: missing
common support (backdoor) and a weak instrument (IV).

Everything else is computed, reported, and not gated on. A tool that blocks on two
things gets taken seriously; a tool that blocks on fifteen gets routed around.

## How to explain a failure to the user

Every issue carries `impact_on_analysis` and `recommended_repair`; **read them out
rather than rewording them yourself**. They are phrased in causal-inference terms
deliberately.

For a failed overlap check:

> "88% of these patients have no comparable controls. For them the effect estimate is
> **extrapolated**, not observed in the data. The confidence interval will look narrow,
> but narrow in a way that means nothing. I'd suggest restricting the analysis to the
> patients who do have comparable controls, but **that changes what is being estimated**,
> and the report will need to say whose effect it now reports."

## Waivers

When the user insists on proceeding despite a blocking issue:

```bash
python scripts/run.py estimate ... \
    --waive "backdoor_overlap=restricted to the sub-population with common support, see protocol 3.2"
```

Three rules:

1. **A reason is required**; an empty reason is refused
2. A check marked `waivable: false` (such as `iv_zero_variation`) is **never let
   through, reason or not**
3. **A waiver does not change the diagnosis**: a waived blocking check still caps the
   claim level at `associational`, and a waived analysis can never reach `causal`

The reason is persisted into the run directory, where it is the first thing an audit
of this analysis would read.

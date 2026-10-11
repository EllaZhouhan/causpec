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

## Two instrument checks that are easy to misread

| Check | What to say to the user |
|---|---|
| `iv_overidentification` | "Your two instruments disagree about the size of the effect. That has two explanations and they need opposite responses" |
| `iv_treatment_exogeneity` | "The data doesn't show dialysis being chosen for reasons we can't see. The instrument is still available, but plain adjustment would give you a much narrower answer" |

**`iv_overidentification` only appears with more than one instrument**, and warning does not
mean "mild". It means the number cannot tell two situations apart:

- one of the instruments reaches the outcome by a path that does not run through the
  treatment, so the estimate is biased
- every instrument is valid, and they identify different groups of patients, so they
  genuinely estimate different things

The second is **expected** in this family. With a heterogeneous effect, two valid instruments
estimate two different weighted averages of individual effects. On this project's own data, a
valid pair gives p = 0.04 and an invalid one gives p = 0, so the statistic alone does not
separate them. What to do: estimate with each instrument separately and compare. Same sign,
different size points at heterogeneity, and the honest report says whose effect each
instrument identifies. Opposite signs point at exclusion.

**`iv_treatment_exogeneity` fires when the test fails to reject**, and failing to reject is
not evidence of exogeneity. Do not tell the user their treatment is exogenous. Tell them the
instrument may be buying protection they do not need, at a real cost in width, and let them
decide: their judgement about unmeasured confounding outranks this test.

Both are computed on a linear two-stage specification, not on the forest that produces the
reported effect. They are statements about the instruments.

## The basic layer, which runs first for every family

These ask whether the table says what it appears to say. They run before anything about
identification, because overlap and instrument relevance are computed from the numbers in
these columns: a verdict on a table whose creatinine column holds -999 is a confident
statement about an export convention. **While the basic layer blocks, the design-level checks
are not attempted**, and the report says so rather than leaving a gap.

| Check | What to say to the user |
|---|---|
| `basic_null_encoding` | "Creatinine is exactly -999 in 400 rows. Is that a real value, or does it mean the test was not done?" This one blocks and is waivable, because only they know |
| `basic_column_types` | "The potassium column is being read as text, not numbers. Usually one cell says NA" |
| `basic_missing_values` | "30 patients have no urea recorded." Not waivable: a guess at a covariate is a guess at the effect |
| `basic_duplicate_rows` | "120 patients appear twice, so they would be counted twice." Not waivable |
| `basic_zero_spike` | "Creatinine is exactly zero for 300 patients, and the next smallest value is 30. Does zero mean zero here?" A warning: whether zero is possible is their knowledge, not yours |
| `basic_constant_column` | "Potassium is the same value for everyone, so it cannot explain anything." A warning |

`basic_null_encoding` is the one to understand. The others eventually fail somewhere if
ignored; a placeholder that is a number does not. It averages, it fits and it predicts, so
every later check passes and the answer is about the placeholder. When it fires, do not
offer to drop those rows: ask what the value means first, because "not measured" and "really
-999" lead to different analyses.

## The temporal layer, when the spec declares time columns

| Check | What to say to the user |
|---|---|
| `temporal_treatment_before_time_zero` | "245 patients are recorded as dialysed before their own time zero. That usually means time zero is set to the dialysis itself, and then being in the treated group requires having survived to it" |
| `temporal_outcome_before_treatment` | "30 patients died before the dialysis they are credited to. Usually a join on the wrong key" |
| `temporal_inversion` | "70 patients have follow-up ending before they were admitted" |
| `temporal_insufficient_followup` | "231 patients had no event and were followed for less than 28 days, so we do not know their outcome rather than knowing it was no" |

**If the spec declares no time columns, these report that they did not run.** Say so when
summarising: "the timing checks could not run, because the data has no timestamps" is a real
limitation and belongs in the report. Do not describe it as the timing being fine.

The first one is the one to understand. Immortal time leaves no trace in any estimate: the
intervals are the right width, the overlap is fine, the covariates balance. The number is
simply wrong, in the direction that favours treatment, by an amount that grows with the
window. It is the most common error in this literature, which is why it blocks.

## The panel family's checks

`dynamic_lag_dml` brings its own, and two of them refuse rather than warn for reasons that
are not about statistics:

| Check | Why it blocks |
|---|---|
| `panel_period_gaps`, `panel_duplicate_periods` | The lag index counts rows, so a missing period silently relabels every later lag in that trajectory. Not waivable, and a gap is not something to impute |
| `panel_missing_values` | The state, the treatment and the outcome of a period are the period. A guess at one is a guess at the effect |
| `horizon_declaration` | The declared horizon contradicts the data. The dangerous case is a panel where every unit has the same number of periods while the user said units leave: that is the shape of a cohort truncated to the units that lasted, which is conditioned on surviving and cannot be repaired by weighting |
| `continuation_positivity` | Too few effective windows at a lag once the weights are counted. The threshold is not on the largest weight, which is heavy-tailed even when everything is right |
| `lag_relevance` | J, the denominator of the estimator, is near zero at some lag: the weak-instrument problem in another costume |

`lag_set_composition` warns and never blocks. It is not a defect: the analysis set shrinks
and shifts along the profile, and the reader has to be told rather than protected from it.

Full explanations, and what to say to the user, are in `dynamic-lag-dml.md`.

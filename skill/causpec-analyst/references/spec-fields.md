# Spec fields

## Structure

```yaml
spec_version: 1
question: What is the average effect of dialysis on ICU mortality?
family: hte_backdoor              # hte_backdoor | hte_iv | dynamic_lag_dml

estimation:
  params:                          # estimator hyper-parameters; enter spec_hash and the manifest
    n_estimators: 500
    estimator: ivforest            # hte_iv only: ivforest (default) | dmliv
    n_bootstrap_samples: 200

assumptions:
  - id: unconfoundedness
    category: untestable           # empirically_assessed | requires_justification | untestable
    statement: given the adjustment set, assignment is independent of potential outcomes
    justification: ""              # the user's argument; required for causal wording
    justified_by: user             # must be `user`; a model's own argument does not count

fields:
  treatment:
    value: isDialysisICU
    source: user                   # user | model | data
    said: treatment means starting dialysis in the ICU    # the user's own words
    turn: 2
    status: confirmed              # drafted | confirmed
  outcome:      {value: death, ...}
  estimand:     {value: ate, ...}
  effect_modifiers: {value: [col1, col2, ...], ...}
  adjustment_set:   {value: [col3, ...], ...}
  instrument:       {value: [col4], ...}          # hte_iv only
  causal_claim_approved: {value: true, ...}       # only once the user agrees to causal wording
```

## `preprocessing`, when a check suggested a step and the user agreed

An ordered list of transformations applied to a working copy before anything is checked or
estimated. The source file is never modified.

```yaml
preprocessing:
  - op: recode_null
    column: max_creatinine
    values: [-999]
    said: yes, -999 means the test was never ordered
    turn: 7
    suggested_by: basic_null_encoding
  - op: cast
    column: max_potassium
    to: number
    said: yes, that column should be numbers
    turn: 8
```

Two operations exist: `recode_null`, which treats the named values as missing, and `cast`,
which converts a column to numbers and **refuses** anything that is not one. Four more are
designed and not implemented, because nothing suggests them yet.

**`said` is required and is enforced**, not conventional. A transformation changes the
numbers, so a step the user did not agree to in their own words does not exist. The same
rule as a confirmed field, applied where it matters more.

**Order matters.** `recode_null` before `cast`: a cast that met the placeholder first would
refuse, and the error message says to add the recode. That refusal is deliberate, because a
lenient cast would perform the recode silently and leave no record of it.

**The steps enter `spec_hash`.** They change the numbers, so a run with them is a different
run, and the report prints what each one did above the quality table.

## `assignment_mechanism`, asked at step 1c

How the treatment came to be given, in the user's words, with one of three values. It is not
read by any estimator: it decides which identification questions are worth asking, and it
appears in the report's provenance table so a reader can see which world the analysis thought
it was in.

| Value | What the user said |
|---|---|
| `randomised` | Something random decided, and nearly everyone got what they were assigned |
| `randomised_with_noncompliance` | Something random decided the assignment, but many did not take it |
| `decided` | A person decided, case by case |

```yaml
fields:
  assignment_mechanism:
    value: randomised_with_noncompliance
    source: user
    said: we randomised which arm each clinic was offered, but uptake was about 60%
    status: confirmed
```

Why it is confirmed rather than inferred: nothing in a table says whether a treatment was
randomised, and the consequence of guessing is large in both directions. Guessing
`decided` on a trial makes the user argue for an assumption their design already gives them.
Guessing `randomised` on observational data grants the strongest possible justification to an
assumption nobody checked.

## Optional time fields, which turn the timing checks on

None of the estimators read these. They exist so the timing checks can run, and **while they
are absent those checks report that they did not run** rather than passing. If the data has
timestamps, declaring them is close to free and catches the one error that leaves no trace in
any estimate.

```yaml
fields:
  time_zero:        {value: admission_time, ...}      # the anchor every unit reaches
  treatment_time:   {value: rrt_start_time, ...}
  outcome_time:     {value: death_time, ...}          # empty for units with no event
  followup_end:     {value: followup_end_time, ...}
  outcome_horizon:  {value: 672, ...}                 # in the same unit as the columns
  time_unit:        {value: hours, ...}               # a label, for the report's wording
```

Times may be timestamps or numbers of hours or days since the anchor; the checks only need to
order them. **`outcome_horizon` is in whatever unit the columns already use**, and is not
converted for you: that is how a 28-day horizon becomes 28 hours.

What to ask the user, when the data has these columns:

> "What should time zero be, the point every patient reaches before any treatment decision?
> Admission, or the moment they first met the criteria?"

The answer matters more than it sounds. Anchoring on the treatment instead of on admission is
how immortal time arises: membership in the treated group then requires surviving until the
treatment, so the comparison group carries a risk the treated group was selected out of. The
estimate looks completely ordinary and favours treatment in proportion to the window.

## The panel family's own fields

`dynamic_lag_dml` reads one row per unit per period, so it needs a different set. Every one
of them is confirmed the same way, with the user's words.

```yaml
family: dynamic_lag_dml

fields:
  unit_id:         {value: patient_id, ...}     # the patient: the independent unit
  period_index:    {value: bucket, ...}         # consecutive integers from 0, no gaps
  period_length:   {value: 12, ...}             # clock time per period, for the report
  treatment:       {value: on_rrt, ...}         # the exposure over the period
  outcome:         {value: instability, ...}    # realised after that period's treatment
  state:           {value: [creatinine, ...]}   # recorded at the START of the period
  max_lag:         {value: 2, ...}              # the profile is theta_0 ... theta_K
  estimand:        {value: lag_profile, ...}    # lag_profile | lag_cate
  horizon:         {value: variable, ...}       # fixed | variable
  termination:     {value: exit_reason, ...}    # only when variable; see below
  effect_modifiers: {value: [aki_stage_admission], ...}   # only for lag_cate
```

Four of these have no counterpart on the cross-sectional path and are easy to get wrong:

| Field | What it is, and what goes wrong |
|---|---|
| `state` | The conditioning set, **not** `adjustment_set`. Recorded at the start of the period, before that period's treatment. There is no separate W channel here |
| `horizon` | `fixed` if every unit is observed for the same number of periods, `variable` otherwise. Required, and the data cannot settle it: see `dynamic-lag-dml.md` |
| `termination` | Only when variable. Either the column that marks the period a unit left, or the literal `last_recorded_period` when the rows simply stop there |
| `effect_modifiers` | Only for `lag_cate`, and only variables the treatment cannot move, which in practice means baseline ones. This is a restriction, not a preference |

`adjustment_set` and `instrument` have no meaning for this family.

## Every field records its provenance

| Key | Meaning |
|---|---|
| `value` | The value: a column name, a list of column names, or an estimand name |
| `source` | Who proposed it: `user` (they said so), `model` (you inferred it), `data` (derived from the data) |
| `said` | The user's **own words**. See below |
| `turn` | Which conversational turn |
| `status` | `drafted` (awaiting confirmation) or `confirmed` |

## Two rules about `said`

1. Required when `source: user`, what the user said is the evidence, kept verbatim
2. **Required when `status: confirmed`**, whatever the source

The second matters most. You infer `outcome = death` (`source: model`), the user says
"yes, in-hospital death", you then mark it `confirmed`, `source` stays `model`, and
`said` records the words they used when agreeing.

**Never confirm on the user's behalf.** The system cannot verify that the user ever
saw the spec, which is why confirmation requires a quote, and the report's front page
prints every field's provenance and quote for them to check. A quote they never said
is one they will recognise instantly.

## Critical fields

The gate requires these to be `confirmed` before it will estimate: `treatment`,
`outcome`, `estimand`.

Each family needs more:

| family | Also required |
|---|---|
| `hte_backdoor` | `effect_modifiers` |
| `hte_iv` | `effect_modifiers`, `instrument` |
| `dynamic_lag_dml` | `unit_id`, `period_index`, `state`, `horizon`, and `termination` when the horizon is variable; `effect_modifiers` when the estimand is `lag_cate` |

## The three assumption categories

| category | Meaning | What can support it |
|---|---|---|
| `empirically_assessed` | The data can speak to it | Quality checks produce evidence |
| `requires_justification` | The data cannot settle it, but it can be argued | The user's argument |
| `untestable` | **Cannot be verified by data in principle** | Only the user, who carries the responsibility |

Only the `untestable` ones gate `causal` wording. While any of them lacks a user
justification, the ceiling for an automatic decision is `suggestive`, see
`claim-levels.md`.

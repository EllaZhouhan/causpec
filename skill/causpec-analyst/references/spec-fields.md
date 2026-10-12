# Spec fields

> The YAML examples are clinical because the project was built against an ICU study. Column
> names are fixed; the nouns are not. Take those from the user: stores, accounts,
> applicants, sessions or patients, whichever one row is.

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

Operations: `recode_null` treats the named values as missing, `cast` converts a column to
numbers and **refuses** anything that is not one, `add_missing_indicator` adds a 0/1 column
recording whether the value was observed, and four fill missing values:

| Operation | When it is right | What it costs |
|---|---|---|
| `impute_constant` | A missing infusion rate usually means no infusion, so zero is a measurement | Worst of the four when wrong: a plausible number is indistinguishable from a real one, so `value` is required and never defaulted |
| `impute_median` | Nothing else is available and the column is one of many | Every filled unit sits at the centre, so the column carries less than it did. The record prints the spread among the filled, which is zero |
| `impute_iterative` | The other columns genuinely predict this one | One draw, so still too narrow. Assumes missing at random given those columns. Where the columns are independent it degenerates to the median fill, and the record's spread among the filled is what tells you |
| `impute_locf` | A panel measurement not repeated often means nothing changed | Requires `limit`, because carrying a value twelve hours and carrying it five days are different claims. Carries forward only, never backward |

**A model-based fill needs its assumption declared**, and `imputation_assumption_declared`
blocks until it is. Say this to the user **before** they accept, not after:

```yaml
assumptions:
  - id: missing_at_random
    category: untestable
    statement: Creatinine is missing at random given the other analysis columns.
    justification: creatinine is drawn on a fixed morning schedule here, not in response to how the patient looks
    justified_by: user
```

The justification has to be the user's, as for every untestable assumption: declared without
one, the claim level stays below `causal`; justified, the analysis can reach it with their
name on it. `impute_constant` and `impute_locf` do not need it, because a named constant and
a value carried one period rest on an argument about the clinical process instead.

**`add_missing_indicator` must come before a fill on the same column** and is refused after
one: once the gaps are filled there is no record of where they were. It also does nothing
until the new column is in the covariate set, which is a separate confirmed spec field, so
write both in the same turn.

**`said` is required and is enforced**, not conventional. A transformation changes the
numbers, so a step the user did not agree to in their own words does not exist. The same
rule as a confirmed field, applied where it matters more.

**Order matters**, in two places. `recode_null` before `cast`: a cast that met the
placeholder first would refuse, and the error says to add the recode, because a lenient cast
would perform the recode silently. `add_missing_indicator` before any fill, for the reason
above.

**The steps enter `spec_hash`.** They change the numbers, so a run with them is a different
run, and the report prints what each one did above the quality table.

## `population`, when the user agreed to an exclusion

Who the answer is about: a description in their words, and the filters, applied in order
after preprocessing and before any check.

```yaml
population:
  description: dialysis-eligible ICU patients with a creatinine on record
  filters:
    - column: max_creatinine
      op: not_missing
      said: yes, drop the ones with no creatinine and say so in the report
      turn: 9
      suggested_by: basic_missing_values
    - column: admission_age
      op: ge
      value: 18
      said: adults only
```

Operators are a closed set: `not_missing`, `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `in`,
`not_in`. No `or`, no nesting, no expressions, because a criterion deciding who is in the
analysis has to be reviewable by someone who did not write it. Filters are conjunctive.

**`said` is required and enforced**, as for a preprocessing step, and for a stronger reason:
an exclusion is not cleaning, it redefines the population the estimate is about.

**Missing values never satisfy a comparison.** A row whose creatinine is unknown is not
known to be above 300 and not known to be below it, so `max_creatinine ge 300` excludes them
and the ledger shows it.

**Two things happen on every run.** The report prints an exclusion ledger, one row per
filter with counts before and after, and `population_exclusion_informative` compares the
excluded with the kept on the treatment and event rates. Read both back to the user: the
ledger is what they asked for, the comparison is what it cost.

**A filter on the treatment or the outcome is refused** and the refusal cannot be waived.

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

> "What should time zero be, the point they all reach before any treatment decision?
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

## `variable_roles` and `key_non_edges`, which produce the diagram

A role per variable or group, confirmed like any other field. The report draws a diagram from
them, so these are not paperwork: the edges come from the role, and
`roles_match_adjustment` compares the result with what the analysis conditions on.

```yaml
variable_roles:
  max_creatinine: confounder
  max_urea: confounder
  bed_availability: instrument
  post_dialysis_creatinine: mediator
  urine_output_day2: post_treatment
key_non_edges:
  - no unmeasured factor drives both the dialysis decision and death
```

| Role | What it means | Drawn as |
|---|---|---|
| `confounder` | Affects both the treatment and the outcome | Arrows to both |
| `instrument` | Affects the treatment only | Arrow to the treatment, dashed crossed arrow to the outcome |
| `mediator` | The treatment acts through it | Treatment to it to the outcome |
| `effect_modifier` | The effect differs across it | A label on the treatment-outcome edge |
| `suspected_collider` | The treatment and the outcome both affect it | An arrow in from each |
| `post_treatment` | The treatment could have changed it | Arrow in from the treatment |

**Four of these are refused in the adjustment set**, and the refusal cannot be waived:
`mediator`, `suspected_collider`, `post_treatment` and `instrument`. `effect_modifiers`
counts as adjustment too, because both fields are conditioned on, and that mistake is easier
to make there because the field name does not sound like adjustment.

**Declaring a variable you are leaving out is useful, not punished.** Putting
`urine_output_day2: post_treatment` on the record with the column absent from every field is
how the report shows a deliberate exclusion rather than an oversight.

**A declared confounder that is not adjusted for warns rather than blocks.** It may be a
column this extract does not have, which is a limitation to report.

**Ask for roles in groups, not column by column.** "Are these seven all things that were
measured before the decision and could have influenced it?" is one question. The diagram draws
them as one node with a count and two examples, so a group is what it expects.

## `estimand`, which the gate now checks against the family

Each family declares the estimands it can identify, and gate condition 3 refuses anything
else. This matters more than it looks: **no estimator reads this field.** `hte_backdoor`
always fits a forest and averages it, so the field is a label printed over a fixed
computation, and a label the family cannot support would be printed over a number that
answers something else.

| Family | Estimands |
|---|---|
| `hte_backdoor` | `ate`, `att`, `cate` |
| `hte_iv` | `conditional_late`, `weighted_conditional_late` |
| `dynamic_lag_dml` | `lag_profile`, `lag_cate` |

`conditional_late` is the one to be careful with. It holds **only for compliers**, the people
whose treatment changed because the instrument took a different value, and compliers cannot be
identified individually. So it is neither the effect for any particular individual nor the
population
CATE, and the report has to say so. Labelling an average over everyone with that word, or
labelling a complier effect `ate`, are the two ways to get this wrong and they mislead in
opposite directions.

The refusal names the family that does declare what was asked, so if the user wants
`conditional_late`, route to `hte_iv` rather than editing the label.

## `effect_groups`, which turns "who benefits" into an answer

Required when the estimand is `gate`, and the family refuses that estimand without it.

```yaml
effect_groups:
  - variable: admission_age
    cuts: [65]
    said: 65 is where I would expect frailty to start mattering
    turn: 11
    chosen_from: clinical_knowledge
  - variable: max_potassium
    quantiles: 3
    said: split potassium in three, I have no threshold in mind
    turn: 12
    chosen_from: importance_ranking
```

Give **either** `cuts`, thresholds the user can defend, **or** `quantiles`, equal-sized bins
for when they cannot. Not both, not neither. `said` is required, as everywhere: which group
a number describes is the user's judgement.

**`chosen_from` is a disclosure, not a penalty.** `importance_ranking` means they picked the
dimension after reading the importance table, which is the natural way to interpret a result,
and the report notes that the interval is slightly optimistic because the dimension showing
the most variation was the one picked. Nothing is adjusted and no level is capped.

**Every group of every grouping is printed**, including the dull ones. That is what makes a
data-driven choice safe to report: the striking group cannot appear without its neighbours, so
there is nothing to cherry-pick, and no multiplicity correction is applied.

**Missing values join no group.** A row whose age is unknown is not known to be over 65 or
under it, the same rule the population filters use, so the group sizes can total less than the
sample.

**No group is dropped or merged for being small.** A group of eleven, with an interval four
times the width of the others, is the finding.

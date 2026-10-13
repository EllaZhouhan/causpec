# Quality checks

> `RUN` is `causpec` when it is installed for the whole machine, `python scripts/run.py` in
> the packaged skill, and `uv run causpec` inside the repository. Probe in that order, once
> per session. SKILL.md has the table.
>
> The worked example below is clinical, a lab value with a `-999` sentinel, because that is
> the clearest case of a placeholder nothing complains about. Take the nouns from the user:
> stores, accounts, applicants or patients, whichever one row is. Only the column names are
> fixed.

```bash
RUN quality --spec spec.yaml --data <data file>
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
| `iv_backend_supports_spec` | **blocking, not waivable** | The chosen backend cannot run this spec: `ivforest` has no channel for an `adjustment_set` and takes one instrument |

`iv_backend_supports_spec` is the one check here that is about configuration rather than
about data, and it is worth knowing why it exists. The estimator refused these two cases
already, correctly, but it refused after the file had been read and every other check had
run, as a stack trace. Both limits are readable from the spec, so they belong where the rest
of the findings are.

The two routes out cost different things, and the user picks:

> "Those three columns can't be adjusted for separately with this estimator. I can move them
> in with the ones the effect is allowed to vary over, which changes what the answer is about,
> or switch to the other estimator, which handles them at the cost of slower and wider
> intervals. Which would you rather?"

## Two checks stand down on a declared randomised design

`backdoor_overlap` and `backdoor_covariate_imbalance` do not run when
`assignment_mechanism` says the treatment was randomised.

Both are diagnostics for an **adjustment**: they ask whether the covariates can carry the
comparison. Under randomisation the design carries it, so the question they answer is not the
question in front of the analysis, and a user who ran a trial should not have to defend a
balance table to proceed. `assignment_mechanism` is a confirmed field holding their own words,
and on how their treatment was assigned they are the authority.

**They leave nothing behind.** A check that stood down has found nothing, so it is not a row
in the quality table and not a name in a footnote: a line reading "not assessed" is a reader's
invitation to treat an absent check as a result, or to ask you to run it anyway. What the
report shows instead is a count, `15 of 25 checks apply to this spec`, and the spec table
above it already says which fields the other ten would have read. This holds for every check
that stands down, not just these two.

**And not by hand either.** The checks standing down is the whole of the behaviour, so
computing a propensity model or a standardised difference yourself in a shell and opening with
what it found puts back exactly what the stand-down removed, using a number that no report
carries, no fingerprint covers and no claim level governs. It also contradicts the user on the
one thing they are the authority about. Key rule 3 is the general form: describing one column
is a description of the file, relating two is a diagnostic, and diagnostics come from `RUN`.

**What to say if a user asks about balance anyway.** Answer the question rather than running
the check back: the comparison rests on the randomisation, the covariates are there for
heterogeneity, and if they want a baseline table for a paper that is a description of the
data rather than a diagnostic of this analysis.

**What this gives up.** A file whose treatment column records what was received rather than
which arm was assigned looks like a randomised design to the spec and like an observational
one to the data, and these two checks were the only place that difference showed up. So when
the user says randomised, the one thing worth confirming is **which** column it is: the arm
they were assigned, or what they actually got. That question is at 1c, it costs one sentence,
and it is the whole of what the checks were catching.

## Why only two blocking checks## Why only two blocking checks

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

> "88% of them have no comparable controls. For those the effect estimate is
> **extrapolated**, not observed in the data. The confidence interval will look narrow,
> but narrow in a way that means nothing. I'd suggest restricting the analysis to those
> that do have comparable controls, but **that changes what is being estimated**,
> and the report will need to say whose effect it now reports."

## Waivers

When the user insists on proceeding despite a blocking issue:

```bash
RUN estimate ... \
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

## When a check suggests a fix you can run

Some checks carry a `suggested_operation` alongside the prose: an exact transformation that
would address what they found. **Offer it, do not apply it.** A transformation changes the
numbers, so it needs the user's own words before it runs, the same as any other spec field.

The shape of the exchange, using the one that comes up most:

> "Creatinine is exactly -999 for 300 patients. Does that mean the test wasn't ordered? If so
> I can mark those as missing rather than as a value, which would stop them being treated as
> an impossibly low creatinine."

On yes, write it into `spec.preprocessing` with what they said, and run the checks again.

**Say what it will and will not do.** This is the part that gets misreported. Recoding a
placeholder to missing does not make the data usable; it makes the problem visible. Those 300
patients still have no creatinine, and the missing-value check will now say so and still
block. What has changed is that the number is no longer being quietly computed from a
measurement artefact.

> "That's marked them as missing, which is what they are. Now the missing-value check sees
> 300 rows with no creatinine, which blocks the estimate. The options are to
> get those values, drop those rows and say so in the report, or leave creatinine out of
> the covariate set."

## The two kinds of fix, which differ in what they cost

A suggestion carries a `kind`, and it decides which part of the spec the answer goes into.

**`preprocessing`** changes how a value is written down and adds no information. The sentinel
recode above is one. It costs nothing, which is why it can be offered freely.

**`population_filter`** changes **who the answer is about**, so it costs something and the
report says so. This is the honest answer to "can you just drop the patients with no
creatinine": yes, and here is what it does.

> "I can exclude those 200. That leaves the 1,800 who have a creatinine,
> and whether the test was ordered usually tracks how sick someone looked, so those 1,800 may
> not be the group you had in mind. The report will show the exclusion and compare the two
> groups. The alternative is to leave creatinine out of the covariate set, which keeps all
> 2,000."

On yes, write it into `spec.population.filters` with what they said. Then **read the two
population checks back to them**, because that is where the cost shows up:

> "Among the 200 excluded, none were treated, against 21% of the 1,800 kept, so the exclusion
> changed who the analysis is about: it is now about a population more likely to be treated.
> That can still be the right analysis, but the report has to say it, and it does."

**Decide exclusions one at a time.** When several columns have missing values the check
offers nothing, deliberately: each exclusion compounds the last, and a user who agrees to one
number has not agreed to the total.

## Filling the gaps, which the tool will do and will charge for

Four fills exist and none of them is a default. `spec-fields.md` has the table of when each
is right; what matters in the conversation is that **you say the price before they accept,
not after**:

> "I can fill those 200 creatinines with the median of the rest. Every one of those rows then
> sits at the same value, so the column carries less than it did. Shall I?"

**One question per turn, and this is two.** Whether to fill is one; whether the missingness is
the kind a fill can stand in for is the other, and it only arises once they have said yes. The
long version of this said both at once in 106 words, with a clause about what the report
prints, which is something they need when reading the report rather than when deciding.

On yes, the second question:

> "A fill like this stands in for the 200 only if they are missing for reasons the other
> columns already capture. If creatinine here is drawn on a schedule, that holds and you can
> say so. If it was skipped because someone looked fine, or because they died in the first
> hours, the fill will be wrong in the direction that matters."

Then **ask them for the justification and write it into `assumptions`**, because
`imputation_assumption_declared` blocks until the assumption is on the record. Unjustified, it
caps the claim level like any other untestable assumption; justified by them, the analysis can
reach causal wording with their name on it. That is the whole mechanism: the user decides, and
the report says who decided.

Do not tell them a fill makes the run exploratory. It does not, and an earlier version of this
tool was wrong to: the exclusion distorts an estimate too, through selection rather than
variance, and it kept its calibrated interval. Penalising one and not the other pushed people
towards the exclusion for no good reason.

Two things to get right when they say yes:

- **`add_missing_indicator` goes before the fill**, and is refused after one. Once the gaps
  are filled there is nothing left to record. Add the new column to the covariate set in the
  same turn or it changes nothing.
- **Read back the spread among the filled values** from the step record. Zero means every
  filled patient holds the same number. A near-zero spread from `impute_iterative` means the
  other columns do not predict this one and the fancier method did the median fill with extra
  steps, which is worth saying rather than hiding.

**What is still refused.** A filter on the treatment or the outcome is blocked and cannot be
waived. Dropping outliers and winsorizing are not operations this tool has, because the
largest creatinine in an ICU row is often the most important number in it. If a user asks for
multiple imputation, the honest answer is that it is the version worth having, that it needs
m datasets, m analyses and a pooling step, and that this tool has the single-draw version
with the interval marked exploratory instead.

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
| `basic_isolated_extremes` | "One creatinine is 6,300 when the next highest is 630. Is that a real value or a decimal in the wrong place?" A warning, and **never** suggest deleting it: in an ICU an extreme value is often the most important one |
| `basic_impossible_sign` | "Creatinine is negative in 5 rows." Blocking, and waivable only because they might know something about their columns that you don't |
| `basic_constant_column` | "Potassium is the same value for everyone, so it cannot explain anything." A warning |

`basic_null_encoding` is the one to understand. The others eventually fail somewhere if
ignored; a placeholder that is a number does not. It averages, it fits and it predicts, so
every later check passes and the answer is about the placeholder. When it fires, do not
offer to drop those rows: ask what the value means first, because "not measured" and "really
-999" lead to different analyses.

## Is there enough data to answer the question that was asked

| Check | What to say to the user |
|---|---|
| `feasibility_arm_sizes` | "Only 5 patients received dialysis in this population, so there is nothing to compare them against" |
| `feasibility_event_counts` | "25 of the dialysed patients died. Across 7 covariates that's under 4 deaths per covariate, so a breakdown of who benefits would be describing noise. The average effect is still answerable" |

**Why these refuse rather than leaving it to the interval.** For an average effect a small
sample just gives a wide interval, and the reader sees it. For heterogeneity the estimator
returns a per-patient estimate with an interval around each one, and those intervals do not
widen enough to say "this is noise". The number looks like an answer, so it is refused.

The repair is almost always to change the question rather than the data: an average effect
needs far fewer events than a profile across patients. Offer that trade explicitly, because a
user who asked "who benefits" will usually accept "here is the average, and the data cannot
support the breakdown" once they see why.

On a panel these do not apply and say so: the equivalent question is how many complete
windows each lag has, which the family answers.

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

## Checks about the spec rather than about the data

These compare one part of the spec with another, or with what the analysis actually did. They
are the ones most likely to catch a mistake you made rather than one the data arrived with.

| Check | What it catches | Severity |
|---|---|---|
| `imputation_assumption_declared` | A model-based fill with no missing-at-random assumption on the record | **blocking**, waivable |
| `roles_match_adjustment` | The analysis adjusts for a mediator, collider, post-treatment variable or the instrument | **blocking, not waivable** |
| `family_matches_the_question` | The family does not match the data's shape or how the treatment was assigned | warning |
| `population_filter_variable` | A population filter conditions on the treatment, the outcome, or something the treatment caused | **blocking, not waivable** |
| `population_exclusion_informative` | The patients a filter removed differ from the ones it kept | warning |
| `backdoor_effect_groups` | The estimand is `gate` but no groups are declared, or a grouping cannot be formed | **blocking, not waivable** |

Three of these deserve a sentence each when you report them.

**`roles_match_adjustment`** is the one that is hardest to argue with and easiest to cause.
Adjusting for a mediator removes the part of the effect that travels through it, so the total
effect shrinks towards zero; conditioning on a collider invents an association that can reverse
the sign. Both are the arithmetic working correctly on the wrong quantity, so no interval shows
it. `effect_modifiers` counts as adjustment, which is where this usually happens, because that
field name does not sound like adjustment.

**`family_matches_the_question`** fires on the case nothing else mentions. A user who says
"randomised, but uptake was about 60%" and an analysis routed to `hte_backdoor` gets an average
effect that treats non-compliance as though it never happened, with every other check passing.
It is a warning because both routes can be defended; say which quantity each one estimates and
let the user choose.

**`population_exclusion_informative`** is how an exclusion gets priced. "We dropped 200
patients" and "we dropped 200 of the patients nobody was going to treat" are different
statements, and the treatment and event rates among the excluded are what tell them apart.

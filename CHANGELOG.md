# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/); version numbers match
the milestones in plan.md section 2.

## [Unreleased]

### Added

- **Gate condition 3: the family has to be able to run this spec and answer this question**
  (design.md 7.6). `estimand` is a label the estimator never reads, so before this,
  `estimand: conditional_late` on `hte_backdoor` ran to completion and the report described an
  average over everyone in the words for an effect among compliers, which is a different
  population and a different number. The refusal names the family that does declare what was
  asked for, so a user has somewhere to go. A missing required field is refused by name too,
  instead of surfacing as `ValueError: hte_iv's quality checks require spec.instrument` with a
  traceback from inside a family
- **Writing that gate found three overstated declarations**, which is what an unenforced
  declaration drifts into. `hte_backdoor` required `time_zero`, read only by the optional
  temporal checks, and `adjustment_set`, which is optional because W=None is a valid analysis;
  the panel family required `instant_outcome`, a field name its own code does not use, plus
  two fields that are conditional. A flat list cannot say "required only when", so the
  conditional ones stay with the family's checks, which know the condition and can state it.
  A test now asserts every declared requirement is a real spec field name
- **`family_matches_the_question`, a warning for the case nothing used to mention.** A user
  who says "randomised, but uptake was about 60%" and an analysis routed to `hte_backdoor`
  gets an average effect that treats non-compliance as though it never happened, with every
  other check passing. A warning and not a gate, because defensible analyses exist on both
  sides of a routing choice; the data's shape is checked first, being the harder error, since
  a panel analysed one row per unit answers a question about rows rather than about patients
- **The E-value, which is the only quantitative thing this project can say about
  unconfoundedness.** That assumption is `untestable` and no diagnostic will ever verify it,
  so the claim level caps what code may claim about it; the E-value adds how strong an
  unmeasured confounder would have to be, in association with both treatment and outcome, to
  explain the estimate away. Written here as a closed form under ADR-0004's rule and checked
  against VanderWeele and Ding (2017), where a risk ratio of 3.9 gives 7.26 and a lower
  confidence limit of 1.8 gives 3.0. The report leads with the limit's E-value, because that
  is what it would take to make the result merely compatible with nothing, and quoting only
  the point estimate's is quoting the flattering number
- **Three refutation tests, written against the `Family` protocol rather than through DoWhy.**
  The protocol is `estimate(data, spec, seed)`, so forty lines of core drive a placebo
  treatment, a random common cause and subset stability for every family including the panel
  one, and DoWhy stays out of the dependency list. The placebo test is the one that speaks to
  validity: permute the treatment and nothing links it to the outcome, so an estimate that
  survives is produced by something other than the treatment
- **The tolerance is the analysis's own interval half-width**, not a fixed number, since a
  fixed one would fail a noisy-but-correct estimator and pass anything on a precise one. A
  consequence found while writing the tests, and kept as one: the placebo test therefore also
  catches an over-confident interval, because permuted estimates scatter by the estimator's
  real sampling error and an interval narrower than that cannot contain them. The complaint is
  then about the reported precision rather than the point estimate, which is the right thing
  to complain about
- **A failed refutation pulls the claim level to `associational`**, not merely short of
  causal: an effect that survives permuting the treatment is not an effect of the treatment,
  and no justification of an assumption repairs that. Which number each family offers up for
  this is declared as `sensitivity.primary_address` in family.yaml, so core never learns that
  one family's headline is an average effect and another's is a lag
- **DoubleML is not used**, though the plan named it. Its `sensitivity_analysis` bounds
  omitted-variable bias for a DML estimator, and these families fit EconML's causal forest, so
  it would mean a second estimator on the same data and a second set of numbers to reconcile.
  The direct dependency list is down to three
- **The derived snapshot and two content fingerprints** (design.md 6.5). The analysed table
  is written into the run directory, after the preprocessing steps and the population filters,
  so a report can be checked against the data it describes rather than only against the spec.
  Gzipped CSV, not parquet: pyarrow is a forty-megabyte dependency for one artefact, and what
  it buys is dtype preservation, which is what the fingerprint normalises away
- **Earlier runs on the same data are reported** (design.md 6.6), which is the one thing a
  data fingerprint does that nothing else can. design.md 7.4 locks the primary analysis at
  confirmation, and `spec_hash` cannot tell a fresh analysis on new data apart from a second
  look at the same numbers, because the spec changed in both. Now a run finds the sibling runs
  with the same `source_fingerprint` and a different `spec_hash`, and the report names them and
  says the primary analysis is the first one. Stated, never refused: a second look is
  legitimate, it only has to be visible as one. Only runs that reached an estimate count, or
  the warning would fire on a user who cleared a blocking issue and re-ran, which is the
  tool's own intended workflow
- **The snapshot could not verify against its own fingerprint, twice over.** Pandas writes
  floats at sixteen significant digits, one short of a lossless float64, and its default CSV
  parser does not round correctly even when the file carries seventeen. Either alone left 32 of
  41 columns differing in the last bit. Fixed with `float_format="%.17g"` on the write and
  `float_precision="round_trip"` on every read, including the source data, which also removes
  a dependence of the estimates on the parser's version
- **Rounding the fingerprint would not have fixed it**, which is worth recording because it is
  the obvious idea: one ulp is about 2e-16 relative and the boundaries at fifteen significant
  digits are spaced 1e-15 apart, so a perturbed value crosses a boundary about a fifth of the
  time. Rounding moves the instability onto every value rather than removing it
- **The variable-role diagram, derived from the declarations** (design.md 7.5).
  `variable_roles` and `key_non_edges` are confirmed spec fields, the edges come from the role
  with no freedom, and the report embeds mermaid while the run directory gets the same graph as
  DOT. No graph library and no DoWhy, which is not a dependency of this project: the derived
  graph has a fixed shape, so the backdoor criterion over it reduces to one rule per role
- **Deriving it rather than drawing it is what makes it worth having.**
  `roles_match_adjustment` compares the same declaration against the variables the analysis
  conditions on, and refuses, not waivably, an analysis that adjusts for a mediator, a
  collider, a post-treatment variable or the instrument. `effect_modifiers` counts as
  adjustment too, because both fields are conditioned on and the field name does not sound
  like adjustment. A declared confounder left unadjusted warns instead: it may be a column the
  extract does not have, which is a limitation to report. A hand-drawn picture cannot be wrong
  in a way anyone notices
- **One node per group, with a count and two examples**: "7 confounders (max_creatinine,
  max_urea, ...)". Seven boxes is where a derived diagram turns back into the formality
  design.md 7.5 refuses to ask for. Only one non-edge is drawn, the exclusion restriction from
  instrument to outcome, because it joins two nodes that are both on the diagram; the
  free-text assumptions are listed beneath, since an arrow from nowhere reads as an edge that
  exists
- **The variable catalogue is dropped**, with the reasoning kept in design.md 6.2. Its only
  consumer with teeth was a post-treatment check that is not being built, and what it would
  have stored is already in the spec in the user's own words: `said` on a confirmed covariate
  carries "the maximum over the first 24 hours", and the report prints it. A second home for
  the same fact, with nothing keeping the two in agreement, drifts while people still trust it
- **HTE calibration is dropped**, including the `calibration: econml.validate.DRTester` line
  in `hte_backdoor/family.yaml` that named a validator nothing called. The question it answers
  is worth asking, and the counting half of the feasibility layer already refuses the designs
  where the answer is certainly noise
- **Four imputations the user chooses from, with the price charged automatically.**
  `impute_constant`, `impute_median`, `impute_iterative` and `impute_locf`, plus
  `add_missing_indicator`, all ordinary preprocessing steps on the working copy. The
  missing-value check now offers a menu of five ways forward, each with the sentence to read
  back to the user, rather than one default: exclusion first because it invents nothing, the
  fills next, dropping the column last
- **A fill carries an assumption, not a penalty**, after the first version of this got it
  wrong. That version made any fill force `interval_calibration: exploratory`, so no result in
  such a run could be called significant. It was not defensible: excluding the units with a
  missing column distorts the estimate too, through selection rather than through variance,
  and it kept its calibrated interval. Penalising one and not the other pushed users towards
  the exclusion, which is not reliably the better choice, and it dressed a judgement up as
  arithmetic. `imputation_assumption_declared` replaces it: a model-based fill blocks until
  `missing_at_random` is declared as an `untestable` assumption, waivable so it never
  dead-ends, and then the ordinary machinery applies, unjustified capping the level and
  justified by the user permitting causal wording with their name on it. `impute_constant` and
  `impute_locf` are exempt, because a named constant and a value carried one period rest on an
  argument about the clinical process rather than on a pattern in the missingness
- **The spread statistic had to be the right one.** The column's own standard deviation does
  not reliably shrink under a fill: filling a right-skewed column at its median puts values
  away from the mean, which can widen it. So each step records the spread **among the values
  written**, which a median fill makes exactly zero. On this project's own data, whose
  covariates are independent by construction, `impute_iterative` produces a spread of 0.04 on
  a column whose own spread is 108: it has done the median fill with extra steps, and that
  number is what says so. Both outcomes are pinned by tests
- **`impute_iterative` predicts from the treatment and the outcome**, which is the part that
  is usually got wrong: imputing a covariate from the other covariates alone makes the filled
  values independent of the outcome given those covariates, which biases the association
  towards zero and weakens the very adjustment the column was there to provide
- **Two ordering rules, both found by running the CLI rather than by reasoning.**
  `add_missing_indicator` is refused after a fill on the same column: the gaps are gone, so
  the indicator would be 1 everywhere and carry nothing, silently. And a step's record counts
  what it actually changed rather than what was missing, which `impute_locf` with a limit
  exposed: it left one gap open on purpose and the record had claimed it
- **Population filters, so the tool can do the exclusion it was already recommending**
  (design.md 7.2). `basic_missing_values` used to say "drop those units and say in the report
  how many and why", and no spec field could express it: `population` existed only as a
  future item in a docstring. So the user went and filtered the CSV by hand, and the report
  knew nothing about the patients who had disappeared, which is exactly the silent exclusion
  that sentence warned against. Now the check offers the filter, the user agrees in their own
  words, and the tool applies it
- **An exclusion ledger, the first table a reader checks.** One row per filter, in the order
  applied, with counts before and after and the user's own words for why. An effect measured
  on 1,800 of 2,000 patients is an effect for whoever those 1,800 are, and the ledger sits
  above the quality table because every check below it describes the population it leaves
  behind
- **Two population checks, which price the exclusion rather than having an opinion about it.**
  `population_exclusion_informative` compares the treatment rate and the event rate among the
  excluded against the kept, so "we dropped 200 patients" cannot stand in for "we dropped 200
  of the patients nobody was going to treat". A warning and never blocking, since an
  eligibility criterion is informative by construction. `population_filter_variable` refuses
  a filter on the outcome, which compares the survivors of one arm with the survivors of the
  other, and refuses a filter on a column that separates the arms almost perfectly, on the
  same criterion `panel_post_treatment_state` uses: it is the same error reached by selection
  instead of by adjustment. A confounder is meant to predict the treatment, so moderate
  association only asks a question
- **The closed operator set and one consequence worth stating.** `not_missing`, `eq`, `ne`,
  `lt`, `le`, `gt`, `ge`, `in`, `not_in`, conjunctive, no nesting and no expressions, because
  a criterion deciding who is in the analysis has to be reviewable by someone who did not
  write it. Missing values never satisfy a comparison: a patient whose creatinine is unknown
  is not known to be above 300 and not known to be below it, and the ledger shows them going
- **A preprocessing path where the check that found the problem offers the fix** (design.md
  6.4): `spec.preprocessing` is an ordered list of steps applied to a working copy before
  anything is checked or estimated, and a check that has an exact remedy attaches it as
  `suggested_operation` so the agent offers the operation it found rather than paraphrasing a
  sentence back into one. Two operations, `recode_null` and `cast`, because those are the two
  a check can currently suggest and an operation no caller can reach is an operation nobody
  reviews
- **A step reveals rather than repairs, and this is the property that makes the path safe.**
  Accepting the sentinel recode on 300 patients does not clear the refusal, it relocates it:
  `basic_null_encoding` stops blocking and `basic_missing_values` starts, because those
  patients have no creatinine either way and now the report says so. No check suggests a step
  that would make it pass by hiding what it reported, and there is no suggestion at all for a
  duplicated join, a missing value, an outlier or too few events, which have no safe automatic
  answer
- **`cast` is strict, and the lenient version is the trap it exists to avoid.**
  `to_numeric(errors="coerce")` would turn "NA" into a missing value, performing a recode
  nobody declared and leaving no record of it. So the cast refuses, names the values standing
  in the way, and says to add the `recode_null` step before it. Order is part of the meaning
- **Silence is not consent, enforced in the contract.** `PreprocessingStep` requires `said`
  and rejects a blank one, the same rule as a confirmed spec field applied where it matters
  more, because a step changes the numbers. The steps enter `spec_hash`, so a run with them is
  a different run, and the report prints what each one did above the quality table, including
  a step that changed nothing, which usually means the column was not what the user thought
- **Two outlier checks in the basic layer, and the statistic matters.** A z-score rule is
  useless here: on this project's ICU data the largest |z| per column runs from 2.9 to 4.2, so
  a rule at 3 or 4 fires on nearly every column and gets ignored. Lab values are right-skewed
  and a long tail is a long tail. `basic_isolated_extremes` measures the **gap** between the
  most extreme value and the next one in interquartile ranges: clean columns sit between 0.007
  and 0.31, one creatinine multiplied by ten gives 1.47, three potassiums in the wrong units
  give 2145. A warning and never blocking, because in an ICU a creatinine of 900 is real and
  often the most important value in the row. `basic_impossible_sign` catches a handful of
  values with the opposite sign to the rest of their column, and leaves a genuinely signed
  column alone: the fluid balance here is 61% negative and never fires
- **The counting half of the feasibility layer** (design.md 8.1): `feasibility_arm_sizes` and
  `feasibility_event_counts`, for cross-sectional analyses. These block where design.md 10.2's
  rule says not to gate on what an interval already says, and the exception is deliberate:
  that rule holds for an average effect, where a small sample gives a wide interval a reader
  can see, and fails for heterogeneity, where a forest returns a per-patient estimate with an
  interval around each that does not widen enough to say "this is noise". The number looks
  like an answer
- **Thresholds measured rather than invented.** The realistic preset gives 415 treated
  patients at a 3.8% event rate, so 25 events against seven covariates, which is 3.6 per
  covariate where the classic rule for an outcome model is ten. It warns, which is the right
  verdict for that dataset, and the per-arm floor of 10 events refuses the 300-patient case
  that has two. The smaller arm is the binding constraint, since a CATE needs the outcome
  model estimable in both
- **An eleventh dataset C defect**, a population filter that leaves five treated patients,
  which is how a tiny arm actually arises. Its test asserted that every core layer has a
  defect aimed at it and went red when the feasibility layer arrived, which is what it is for

- **Step 1 now asks how the treatment was assigned**, before any column is mapped, because
  the answer decides which identification questions are worth asking at all. Three answers
  and three different worlds: randomised with full compliance, where exchangeability holds by
  design and the justification is the randomisation rather than the user's judgement;
  randomised with partial compliance, where the assignment is an instrument for the treatment
  received, which is design.md's own dataset D and the answer a workflow without this
  question cannot propose; and decided case by case, the observational path. Recorded in
  `assignment_mechanism`
- **The follow-up for the observational case asks what the decider had in front of them**,
  not "what are your confounders". A clinician can answer the first and cannot reliably answer
  the second, and the gap between what they used and what the file holds is the
  unmeasured-confounding question asked concretely enough to get a concrete answer
- **Key rule 9: an association is not evidence of confounding.** A variable correlated with
  both treatment and outcome may be a confounder, a mediator, a collider or a consequence of
  either; which it is comes from how the treatment was decided and when the variable was
  measured. And covariates balancing after weighting says nothing about the variables nobody
  has
- **claim-levels.md distinguishes randomisation from a judgement.** `untestable` means no
  diagnostic can establish an assumption; it does not mean every justification for one is
  equally weak. With three precisions kept in view: randomisation makes the **assignment**
  unconfounded and not the treatment received, a randomised study can still be broken by
  differential dropout, and the user still approves the wording

- **Two instrument checks, one imported and one written here** (ADR-0004), rather than the
  effective F that
  plan.md asked for. `iv_overidentification` engages only with more than one instrument and
  tests, robustly to heteroskedasticity, whether they agree. `iv_treatment_exogeneity` tests
  whether the treatment behaves endogenously at all, and fires when it does **not**: an
  instrument buys protection from unmeasured confounding and pays for it in width, so a
  treatment the data cannot distinguish from exogenous may be paying for nothing. Both are
  computed on a linear two-stage specification alongside the forest, which the issue text
  states, since they are statements about the instruments and not inference about the CATE
- **ADR-0004 splits them by measurement**: the endogeneity test is three lines of statsmodels
  and is written here, agreeing with the package to under 1% with a test pinning it. The
  overidentification test is imported, because a hand-rolled version used k degrees of freedom
  where the test has k-1, giving p = 0.24 against the package's 0.092 while agreeing with its
  **verdict** on all four designs it was tried on. A single-instrument analysis never reaches
  that code, so it never loads linearmodels
- **The overidentification check warns and cannot block, as a measured property.** Two
  *valid* instruments that identify different complier groups reject under a heterogeneous
  effect, which is this family's whole subject: on the project's own fixture, a valid pair
  gives p = 0.04 while an instrument violating exclusion gives p = 0. The statistic cannot
  separate them, so the issue names both readings and the repair is to estimate with each
  instrument alone and compare signs

- **The temporal check layer** (design.md 8.1): immortal time, an outcome dated before the
  treatment it is credited to, inverted follow-up intervals, and follow-up shorter than the
  outcome window. It reads optional spec fields (`time_zero`, `treatment_time`,
  `outcome_time`, `followup_end`, `outcome_horizon`) and **reports when it could not run**,
  because a check that says nothing about a table it could not read turns the report into a
  clean bill of health. Times may be timestamps or numbers; the horizon is taken in whatever
  unit the columns already use, since converting it is how a 28-day window becomes 28 hours
- **Immortal time is the check the layer exists for.** It leaves no trace in any estimate:
  the intervals are the right width, the overlap is fine, the covariates balance, and the
  number is wrong in the direction that favours treatment by an amount that grows with the
  window. A cohort anchored on its own exposure can only be joined by surviving to it
- **Dataset C**: ten defects, one at a time, each declaring the `check_id` and severity it
  expects, asserted in CI. Every one is a mistake that happens to real extracts rather than a
  random perturbation: a sentinel for "not measured", a spreadsheet that spells NA, an empty
  field becoming zero on export, a join that duplicates rows, a cohort anchored on its own
  exposure, an extraction with a fixed end date. The test checks both directions, because a
  defect caught by the wrong check is worse than one caught by none: the report would send
  the user to repair something that is not broken
- **Timestamps in dataset A**, off by default: admission, treatment, event and follow-up end,
  internally consistent by construction, which is what makes the temporal checks testable

- **The basic check layer** (design.md 8.1, ADR-0003), the first of the four to be
  implemented in core and the only one that runs for every family: column types, a duplicated
  row key, missing values, NULL-encoding variants, zero spikes and constant columns. It runs
  **before** the design-level checks, and while it blocks they are not attempted: overlap and
  instrument relevance are computed from the numbers in these columns, so a verdict on a
  table whose creatinine column holds -999 is a confident statement about an export
  convention
- **NULL-encoding detection**, which is why this layer earns its place. A missing value
  eventually reaches a nuisance regression and complains; a placeholder that is a number does
  not fail anywhere. It averages, it fits and it predicts, so every other check passes and a
  creatinine of -999 teaches the model that patients with impossibly low creatinine are never
  treated. Out-of-band sentinels that repeat, and text meaning "missing" in a column that
  should be numeric. Blocking and waivable, because only the user knows whether a value is
  real in their data
- **A zero-spike check**, for the zeros an export produces from an empty field. The obvious
  statistic cannot do this: measuring how far the column's bulk starts from zero gives 0.28
  for a creatinine column with 10% of values zeroed and 0.27 for a urine output whose 10%
  zeros are real. What separates them is whether anything sits just above zero, so the
  statistic is the smallest non-zero value over the interquartile range: 0.19 against 0.00 on
  the same data. A warning, since whether a zero is possible is clinical knowledge

- **The `dynamic_lag_dml` family** (design.md 7.3): the lag profile of one treatment
  period on per-period outcomes, on panel data whose trajectories end at state-dependent
  and treatment-dependent times. Two estimands, `lag_profile` and `lag_cate`; the
  structural model the profile derives from; six assumptions with the evidence named for
  the three that data can speak to; and the four neighbouring questions the family refuses
  by name (a strategy contrast, a cumulative effect, a survival endpoint, a terminal
  outcome). Ported from the author's paper: cross-fitted sequential peeling, one
  partially linear problem per lag, and inverse-probability-of-continuation weighting for
  the informative horizon. Needs `causpec[dynamic]`, which is scikit-learn and joblib, not
  econml
- **`lag_cate`, and the restriction that makes it meaningful**: the lag effect may vary
  only with variables the treatment does not move. Otherwise one treatment period reaches a
  later outcome by two routes, the second multiplied by the treatment in between, and the
  outcome stops decomposing into lag effects: there is no profile, and fitting one returns
  plausible numbers that are not any effect. Found by testing rather than by reading, when
  the generator's first heterogeneity design put the lag-2 estimate at +4.7 where its
  nominal truth was +1.2. A blocking, waivable check now refuses a modifier that varies
  within a unit
- **The horizon is a confirmed field, and a fixed one applies no weighting**: `horizon`
  (fixed or variable) and, when variable, `termination` (how leaving is identified) are both
  required, and the estimator refuses without them. Under a fixed horizon no continuation
  model is fitted and every weight is exactly one, with `res:profile.horizon` and
  `res:profile.ipcw_applied` on the result so the report says the weighting was skipped
  rather than leaving a reader to infer it from weights of one.
  It is confirmed rather than inferred because one pair of worlds is indistinguishable by
  shape: a panel where every unit has eight periods is either a fixed horizon or a cohort
  truncated to the units that lasted eight periods, and the second is conditioned on
  surviving, which no weighting repairs. Measured on the benchmark, keeping the 3.5% of units
  that reach eight periods moves the lag-1 estimate from 4.22 to 2.87 against a truth of 4.0.
  The `horizon_declaration` check compares the declaration with the data and refuses both
  contradictions, and rows recorded after a unit left are refused outright
- **A fixed horizon uses each unit's final period.** Its outcome is recorded like any other,
  so the paper's condition, that a window's outcome survives into the next period, cannot fail
  when nobody leaves. That is one extra window per unit per lag, about a sixth of the lag-2
  windows on an eight-period panel: measured over 30 replications, unbiased at every lag and
  the lag-2 RMSE improves from 0.247 to 0.227. A variable horizon keeps the paper's convention
  throughout, including for units the observation window cut off, whose final outcome is
  recorded but whose continuation is unknown. `res:profile.final_period_included` says which
- **Missing values in the columns the estimation uses are refused**, with the columns named
  and the final-period pattern called out separately, since that is where an outcome is most
  likely to be absent and its fix is to record one period fewer rather than to impute.
  Previously this surfaced from inside a nuisance regression as `Input y contains NaN`
- **Reaching the end of the observation window is not leaving**: only a real exit is evidence
  that a trajectory could have continued and did not, so a trajectory cut off by the window
  contributes no record to the continuation model. Where a column marks exits, the column
  decides; otherwise a trajectory that stops before the window is read as having left
- **Seven panel quality checks**: period gaps and duplicates (blocking, not waivable,
  because the lag index counts rows and a gap silently relabels every later lag), a state
  column that is nearly a copy of the same period's treatment, too few complete windows per
  lag, continuation positivity, lag relevance J, and the per-lag composition of the
  analysis set. The positivity threshold is on the effective number of windows, not on the
  largest weight: these weights are heavy-tailed even on the design the method was proved
  on, and an earlier version thresholding the maximum refused that design at 800 units
- **The panel part of dataset A**: an episodic trajectory generator with the lag profile
  known in closed form, reproducing both of the paper's designs, their true profiles
  (-0.5, 4.0, 1.2) and (-0.5, 3.6, 1.08), and their descriptives (about 54% of periods
  treated, a mean of 2.9 periods). Continuation positivity holds by construction, so the
  strength of the selection can be turned up without breaking the assumption
- **The claim-level decision gained a second axis**: `interval_calibration`. An estimator
  proved consistent without a limiting distribution has intervals that indicate where an
  effect sits and test nothing, so `significance_claims_allowed` goes false and the level
  is capped, independently of data quality. A calibrated interval on a waived analysis
  still cannot say "caused"; an exploratory interval on a spotless one still cannot say
  "significant". An unknown calibration raises rather than defaulting to calibrated
- **The skill form is usable**: a complete SKILL.md (eight key rules, eight workflow
  steps), eight references, a narrative template, `scripts/run.py` (importing straight
  out of the bundled wheel when causpec is not installed in the sandbox), and
  `scripts/build_skill.sh` for packaging
- **Skill consistency tests**: the families, checks, writable sections and claim levels
  the documentation lists must match what the code actually does; documentation drifts,
  and these tests pin the two together
- **Fixed report structure** (design.md 10.3): ten sections in an order decided by code,
  so "assumptions before results" is a structural guarantee rather than a reminder. The
  spec-provenance table and the claim-level decision are code-generated and the model may
  not author them; the remaining sections accept interpretation, always through
  placeholder rendering
- **Placeholder format specs**: `{{res:primary.ate|+.3f}}`, `{{qc:...frac|.1%}}`; without
  them the report shows 17 significant digits, and a model's natural response to that is
  to round it itself, which defeats G4
- **CLI `--report` / `--narrative`**: `--report` emits the fixed structure, `--narrative`
  takes a YAML mapping of `{section: prose}`
- **Runtime** (design.md section 14, G5): `RunContext` persists a run directory,
  `Manifest` records everything that can change the result (code version, dependency
  versions, spec_hash, seed, decision-rule hash), each artefact's sha256, and `verify()`
  detects later tampering. Every write is atomic (temporary file in the same directory,
  fsync, `os.replace`)
- **Audit log**: one line per call, with **the parameters hashed rather than stored**;
  metadata passes a sensitive-key check that raises on password/dsn/token and similar, so
  "no credentials in the log" is enforced by code
- **CLI `--run-dir`**: persist a whole run, including the waiver reasons
- **The claim-level decision** (design.md 10.2, principle 5): the four-level rules live in
  `core/reporting/claim_levels.yaml` and the decision carries the rules hash. The ceiling
  for an automatic decision is suggestive: untestable assumptions cannot be verified by
  any diagnostic, so reaching causal takes a user justification for each and explicit
  approval. A waiver does not change the diagnosis
- **The `Assumption` contract**: three categories (empirically_assessed /
  requires_justification / untestable), justification text, and `justified_by`; a model's
  own justification does not count
- **The `claim:` namespace**; the renderer now takes a merged address table, so `res:`,
  `qc:` and `claim:` can be cited in one report
- **`hte_backdoor` switched to CausalForestDML**, with both the CATE and ATE intervals
  from `blb` (bootstrap of little bags), needing no resampling
- **Overlap / positivity checks** (the other blocking check), SMD before and after IPW,
  Kish effective sample size, treatment prevalence. Propensity scores are cross-fitted,
  gradient boosting by default
- **CLI `quality` subcommand**; `estimate` now runs the checks before the gate, and
  `--waive CHECK_ID=reason` waives a waivable blocking check
- **The `QualityIssue` / `QualityReport` contracts** (design.md 8.3): check_id, layer,
  severity, waivable, evidence, affected_columns, impact_on_analysis, recommended_repair,
  with every piece of evidence addressable as `qc:<check_id>.<key>`
- **Instrument checks for `hte_iv`**: migrated from the research code's
  `test_iv_validity`: relevance (linear robust F, partial R-squared, probit LR test,
  McFadden increment), complier share, covariate balance with a Benjamini-Hochberg FDR
  correction. Thresholds live in family.yaml
- **Gate condition 2**: refuse to estimate while a blocking quality issue stands
  unwaived; a waiver requires a reason, and a check marked not waivable is never let
  through
- **A generator for synthetic dataset A**: a structural causal model with per-individual
  ground truth, where unmeasured confounding biases both the naive estimate and backdoor
  adjustment so that only IV identifies; binary and continuous instruments; `realistic`
  and `high_power` presets
- **The `hte_iv` family**: two backends (`ivforest` = CausalIVForest, the default;
  `dmliv` = NonParamDMLIV, matching the research code's final version), both instrument
  kinds. `ivforest`'s CATE interval uses GRF honest variance while its ATE interval uses
  a unit-level bootstrap of the forest, because econml.grf exposes pointwise variance
  only. The replicate count is shared by both backends, defaults to 200, is overridable
  from the spec, and parallelises through `bootstrap_n_jobs` (indices are drawn up front,
  so parallelism cannot change the result)
- The `causpec[hte]` extra: econml and scikit-learn; a missing dependency yields a
  structured error carrying the install command
- The repository skeleton: uv, ruff, pyright, pytest, pre-commit, CI, import-linter
- Data-file blocking (`.gitignore` plus a pre-commit hook)
- The full directory structure with each layer's responsibilities documented; a
  `family.yaml` declaration for each of the three families
- The vertical slice: Spec (field-level source/status), the gate, addressed Results,
  placeholder rendering, the CLI
- ADR-0001 (literal numbers in reports), ADR-0002 (data-source boundaries)

### Changed

- **Dataset C's clean table moved to the high_power preset.** At the realistic scale a
  2,000-row table has about six events in the treated arm, so the clean baseline itself
  blocked on event counts, and a baseline that does not pass makes every defect's effect
  unattributable. Deliberately not realistic: dataset C exercises the checks, while the demos
  and the manual workflow test use the realistic scale, where the thin-events warning is part
  of what a user should see
- **A sentinel is no longer reported twice.** `-999` is both a placeholder and an isolated
  extreme, and reporting both gave the user two findings for one defect with the wrong repair
  attached to the second
- **`_issue` takes a severity override**, so a check whose sub-cases differ in seriousness can
  say so. The event-count check refuses below the per-arm floor and warns on a thin covariate
  budget, with both severities declared in the config rather than decided in code

- **The step list is split instead of annotated.** Steps 1, 2 and 6 to 8 are shared; steps 3
  to 5 are written out once per path, A for one row per unit and B for one row per unit per
  period. They had been a single list written for the cross-sectional case with the panel path
  bolted on as a caveat under each of 3, 4 and 5, which accumulated as the panel family grew
  and left a model free to follow a cross-sectional step 3 and confirm an `adjustment_set`
  that family does not have

- **The effective F is dropped from the plan, and Shea's partial R-squared with it.** No
  Python package implements Montiel Olea and Pflueger's effective F; the canonical
  implementations are Stata's `weakivtest` and R's `momentfit`. Shea's partial R-squared,
  which linearmodels does provide, equals the ordinary partial R-squared when there is one
  endogenous treatment, however many instruments are declared, so it adds nothing to this
  family. What linearmodels adds is the overidentification and endogeneity tests above

- **`dynamic_lag_dml` handed two checks back to core.** `panel_missing_values` and
  `panel_duplicate_periods` were declared there because core had no basic layer, which meant a
  NaN outcome on the cross-sectional path reached sklearn and surfaced as a bare complaint
  about NaN. Both now run for every family. The panel-specific part, missing values sitting
  only on final periods, is kept: core reads the period column from the spec, so the hint
  about the outcome's measurement window running past the end of data collection still
  reaches the report
- **The manifest records `basic_checks_hash`**, for the same reason it records the
  claim-level rules hash: change what counts as a placeholder value and the same data can pass
  or block
- **A missing spec or data file says so** instead of printing a stack trace

- **The report prints a family's result tables, declared rather than coded.** A family lists
  `report_tables` in its declaration and core renders them from the address table, knowing
  nothing about what a lag is. `dynamic_lag_dml` uses it for the profile: every lag with its
  effect, its exploratory interval, and the units, windows, effective windows and J behind it.
  Prose is the wrong container for a result with one row per lag, and the reader was seeing
  only the lags a sentence happened to mention
- **A refused `lit:` now names every address matching that number**, not the first one found.
  One number can coincide with several results, and naming one sends the model to an address
  that is numerically right and semantically wrong: "a 12-hour period" is the period length,
  which happens to equal the lag-1 effect's 12 hours. `res:profile.period_hours` was added so
  that sentence has something correct to cite
- **A blocking gate prints the diagnosis it already computed**, the summary and the suggested
  repair, not just the check id. The estimate command runs the checks before the gate, so
  withholding them sent the user to run the quality command again to find out what their own
  error message meant

- **The continuation model no longer treats the end of every trajectory as an exit.** It
  used to, which asks the model to predict "is this the last period" from the state and the
  treatment, and the period index is not among them. On an eight-period balanced panel that
  produced fitted continuation probabilities as low as 0.40 and weights up to 4.3 in a world
  where every weight should have been 1. The ratio moment was nearly immune, because a
  roughly constant weight cancels, but the variance was not, and the report would have told
  the reader there was censoring to correct when there was none

- **`longitudinal_ipcw` became `dynamic_lag_dml`**, and its contents changed with its
  name. The old declaration specified the seven components of a target trial plus
  event_roles mapping death, discharge and transfer to outcome, competing, censoring or
  terminal. That is the layout for a marginal structural model comparing two strategies
  on a survival endpoint, which is not the method this project has: here termination ends
  the observation window rather than being the outcome, and death and discharge are the
  same event. The old name kept promising the wrong estimand, and nothing caught it
  because nothing compared the declaration against the method. design.md 7.3 now says so
  in as many words, and the skill's `longitudinal-ipcw.md` became `dynamic-lag-dml.md`,
  which turns "CauSpec refuses longitudinal questions" into one question it will answer
  and three it will not
- **The skill asks one more question about a time-varying treatment**: whether a version
  of the data exists with one row per unit per window. Previously the branch dead-ended,
  telling the user a longitudinal design was needed and stopping there

- **The project is now English-only**: code, docstrings, user-facing strings, YAML
  declarations, tests, docs, the skill and commit messages
- **Rendering errors are now readable and actionable**: a bare number is answered with
  what to write instead (`28 -> write {{lit:28}}`), and when the value is close to a
  computed result the address to cite is named; the address list is grouped by namespace
  and truncated rather than dumping dozens inline. This came out of the cold-start test,
  where the original message buried the fix
- **Package resources are read through `importlib.resources`** (`family.yaml`,
  `claim_levels.yaml`). The previous `Path(__file__).parent` finds no file when the
  package is imported out of a wheel: a bug found by actually running the skill's
  `run.py` in a clean environment
- Reading a family's declaration no longer imports that family:
  `resources.files("causpec.families.hte_iv")` executes its `__init__` and pulls in
  econml, which turned "missing dependency" into a misreported "unknown family"
- The registry now imports by id, so core hard-codes no family import;
  `family.yaml`'s `requires_extra` drives the install hint
- Data is passed as a pandas DataFrame throughout (previously `list[dict[str, str]]`)
- Estimator hyper-parameters moved into `spec.estimation.params` (design.md 7.2): they
  change the result, so they must enter spec_hash and the manifest
- design.md 0.4:
  - The derived snapshot no longer commits to DuckDB; it states two contracts (a writable
    working copy and a normalised content fingerprint), with parquet as the default
    implementation and a columnar engine only once the data exceeds memory
  - Postgres delivery narrowed: v0.3 ships a thin adapter and a docker-compose demo,
    enough to show a read-only view can be connected and that read-only comes from
    account permissions; masked_columns and schema drift move later
  - The `contradicted` field status is removed. A conflict between data and spec produces
    a blocking quality issue, which gate condition 2 already stops; a second status is
    two mechanisms doing one job
  - `status: confirmed` now requires `said`, the user's words at confirmation, regardless
    of source. This plugs the gate's root hole: update_field is called by the model, and
    the server cannot verify that confirmation ever happened
  - 10.2 made quantitative: code can only reach suggestive, and causal requires a person
    to vouch for the untestable assumptions; the blocking checks narrow from an open list
    to two (overlap, instrument relevance) on the principle that "if the confidence
    interval already says it, do not gate on it"; every other diagnostic is reported and
    not gated on
- design.md / plan.md 0.3:
  - G2 drops from three shapes to two (the relational shape and dataset B's third shape
    are removed)
  - The StatsPAI dependency is dropped; the E-value and the effective F test are written
    here with numerical regression tests, sensitivity moves to DoubleML, and the AR test
    goes to the backlog
  - The week saved goes into Phase 4, so longitudinal IPCW can be delivered complete
  - The ADRs drop from a planned five to two: only decisions the design document does not
    already cover

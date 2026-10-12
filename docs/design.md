# CauSpec design document

Version: 0.4
Author: Han Zhou
Updated: 2026-09-27

Passages marked [reuse] use or adapt code or practice from an external library or
project, with the source and licence noted. Passages marked TODO need filling in by the
author from their own methods and code.

---

## 1. Goals and non-goals

### 1.1 The problem

When a causal question is put to observational data, the failure usually happens before
the estimation: treatment, outcome and time zero are vaguely defined; a post-treatment
variable or a positivity problem goes unnoticed; definitions drift between datasets;
the numbers cannot be reproduced. Tools of the "LLM plus code" kind introduce a further
failure, the model computing, or inventing, the numbers itself.

CauSpec does four things:

1. Turns an analyst's question in plain language into an analysis spec confirmed field
   by field.
2. Assesses whether the data can support that question.
3. Runs HTE and longitudinal treatment-effect estimation in deterministic code.
4. Produces a report in which every number traces back to a computation.

Data sources are read-only throughout.

### 1.2 Goals

- G1: every critical spec field records its source (user, model inference, data) and a
  status (drafted, confirmed); nothing is estimated until all critical fields are
  confirmed.
- G2: local CSV/Parquet and PostgreSQL are supported, in wide-table and long-event-table
  shapes, with the estimation code unchanged.
- G3: the data-quality and identifiability report is a deliverable in its own right,
  even when the analysis cannot run.
- G4: only code produces numbers; the renderer substitutes them into the report by
  address, and the model cannot write a number directly.
- G5: fixing the inputs and the seed reproduces the result; every run carries a manifest
  and an audit log.
- G6: it can be evaluated, numerically, on quality-check recall, and on agent behaviour.

### 1.3 Non-goals

Automatic causal-graph discovery; arbitrary SQL; multi-agent setups; searching over
estimators and picking a result; treatment or business recommendations; a bespoke
front end; remote multi-user deployment and authentication.

---

## 2. Design principles

1. Code computes the facts, the model exercises judgement, the framework holds the gate
   (mechanism in 10.1).
2. What the user says is evidence, not something written in automatically (mechanism in
   7.1).
3. Data sources are read-only. That guarantee comes from database account permissions,
   not from a prompt.
4. Raw rows do not enter the model's context by default.
5. The strength of a conclusion's wording is decided by code from the diagnostics; the
   model cannot upgrade it (mechanism in 10.2).

Sources marked "ideas only" (Causal desk) declare no licence; only the practice is
borrowed, no code is copied, and they are credited in the README's Related work.

---

## 3. Forms

| Form | Setting | Data sources | Notes |
|---|---|---|---|
| Local MCP (primary) | Claude Code / Desktop | Local CSV/Parquet; PostgreSQL | The server holds the credentials; it does not modify the source |
| skill + CLI (secondary) | claude.ai, uploaded CSV | Uploaded files | best-effort: the agent may bypass the scripts and read the data directly, which the report header notes |

Both forms call the same causpec functions and produce the same run-directory layout;
the manifest records execution_mode.

---

## 4. Architecture

```
MCP client (Claude Code / Desktop / claude.ai)
 |- Skill: causpec-analyst         workflow, spec drafting, reading quality and results
 |    `- scripts/ -> causpec CLI   skill form only
 `- MCP server: causpec-mcp
      |- connectors   csv / parquet / postgres (read-only)
      |- workspace    derived snapshot (implementation unconstrained)
      |- gates        spec confirmation and quality gating
      `- -> causpec
             |- core        contracts, mapping, quality, runtime, reporting
             `- families/   hte_iv, hte_backdoor, dynamic_lag_dml (plugins)
```

The layering rule: core imports no family, and families attach through a registry;
import-linter enforces it in CI. A new kind of analysis is one family directory and one
line of registration. [reuse] Practice follows Causal desk ADR-0005 (ideas only).

---

## 5. Repository layout

```
causpec/
 |- packages/causpec/
 |    |- core/
 |    |    |- contracts/      Pydantic: Spec, Field, QualityIssue, Result, Manifest
 |    |    |- adapters/       csv, parquet, postgres
 |    |    |- mapping/
 |    |    |- quality/
 |    |    |- runtime/        RunContext, ArtifactWriter, audit, manifest
 |    |    `- reporting/      address resolution, placeholder rendering, claim level
 |    |- families/
 |    |    |- hte_iv/         the author's DMLIV
 |    |    |- hte_backdoor/   EconML CausalForestDML, as a baseline
 |    |    `- dynamic_lag_dml/    the author's lag profile with IPCW
 |    `- cli.py
 |- server/causpec_mcp/
 |- skill/causpec-analyst/
 |- examples/deployments/     configuration examples for demo-hospital and demo-retail
 |- data/generators/          synthetic data generators; what they produce is not committed
 |- evals/
 |- deploy/docker-compose.yml     the local Postgres demo
 |- docs/                     design.md, plan.md, decisions/
 `- .github/workflows/
```

Each family directory holds: family.yaml (what question it answers, which estimands it
can identify, what it requires, what it assumes), spec extensions, its own checks, an
estimation adapter, figures, evals and tests. [reuse] The directory convention follows
Causal desk's family package (ideas only).

---

## 6. The data layer

### 6.1 Data sources

```yaml
sources:
  - id: icu_pg
    type: postgres
    dsn_env: CAUSPEC_ICU_DSN
    allowed_relations: [analytics.v_cohort, analytics.v_timeseries]   # read-only views built by the data owner
    masked_columns: [patient_name, mrn]
  - id: local
    type: csv
    root: ./data
```

In practice, complex joins and derivations should be implemented by the data owner as
SQL views and reviewed by a person; CauSpec reads the views and builds no ETL of its
own. That is also how the division of labour usually runs on a customer site.

### 6.2 The variable catalogue, dropped

The plan was a record per variable: source column, unit, measurement window relative to
time zero, aggregation. It is not being built, for two reasons that are worth keeping
because they apply to any similar proposal.

**Its only consumer with teeth was a check that is not being built.** The measurement
window existed to let a post-treatment check compare a column's window against time zero.
Without that check the catalogue is documentation, and documentation drifts from the data
while people still trust it, which is worse than its absence.

**What it would have stored is already in the spec, in the user's own words.** When a user
confirms a covariate, `said` carries "the maximum over the first 24 hours" and the report
prints it in the spec table. A second home for the same fact, with nothing keeping the two
in agreement, is a liability rather than a record. Units are already where they matter, on
`outcome_horizon`, which is deliberately never converted on the user's behalf.

### 6.3 Canonical schema

Cross-sectional table: unit_id, treatment, outcome, instrument (optional), covariates,
time_zero.

Longitudinal table: unit_id, episode_id, time_index, timestamp, eligible, action, state
variables, outcome, event_type.

### 6.4 Mapping and preprocessing

Six lightweight operations only: rename, cast, recode_null, map_categories,
unit_convert, aggregate over a window. Anything more complex belongs in the data owner's
view. The mapping is drafted by the agent and confirmed by the user; arbitrary
expressions are not accepted.

Implemented: `recode_null`, `cast`, and four fills, `impute_constant`, `impute_median`,
`impute_iterative` and `impute_locf`, plus `add_missing_indicator`. The steps live in
`spec.preprocessing` as an ordered list and are applied to a working copy before any check or
estimate runs. `impute_mean` is deliberately absent: ICU labs are right-skewed, so the mean of
the observed is a worse centre than the median and there is no case where it is better.

**A fill is allowed, and what it introduces is an assumption rather than a penalty.** An
earlier version made any fill force `interval_calibration: exploratory`, so no result in such
a run could be called significant. That was wrong, and the reason is worth keeping: excluding
the units with a missing column distorts the estimate too, through selection rather than
through variance, and it kept its calibrated interval. Penalising the fill and not the
exclusion pushed users towards the exclusion, which is not reliably the better choice, and it
dressed a judgement up as arithmetic.

What a model-based fill actually adds is the claim that the values are missing at random given
whatever it conditioned on, which no diagnostic can settle. So `imputation_assumption_declared`
requires it on the record as an `untestable` assumption, blocking until declared and waivable
so it never dead-ends, and from there the ordinary machinery applies: justified by the user,
causal wording is available; declared and unjustified, the level is capped like any other
untestable assumption. `impute_constant` and `impute_locf` are exempt from the requirement,
because a named constant and a value carried one period rest on an argument about the clinical
process rather than on a pattern in the missingness. They are still printed with their counts.

Each fill also records what it did to the spread, and the statistic has to be the right one.
The column's own standard deviation does not reliably shrink: filling a right-skewed column
at its median puts values away from the mean, which can widen it. What is unambiguous is
**the spread among the values written**, which a median fill makes exactly zero. On this
project's own data, where the generator's covariates are independent by construction, an
iterative fill produces a spread of 0.04 on a column whose own spread is 108: it has done the
median fill with extra steps, and that number is what says so.

Four properties govern the path, and the first is what makes it worth having:

1. **A step reveals; it does not repair.** Recoding a placeholder to missing does not
   make the data usable, it makes the problem visible: the missingness check then
   reports the 300 patients the sentinel was concealing, and still blocks. A
   preprocessing path that let a blocking check pass by hiding what it reported would be
   worse than having none, so no check ever suggests a step with that effect. There is no
   safe automatic answer to a duplicated join, a missing value, an outlier or too few
   events, and those checks carry no suggestion.
2. **Silence is not consent.** A step changes the numbers, so `said` is required and
   enforced in the contract rather than left to convention. The agent offers the exact
   operation a check attached to its finding; the user agrees in their own words.
3. **Order is meaning.** `recode_null` before `cast`, because a lenient cast would
   perform the recode silently and leave no record of it. So `cast` is strict and its
   refusal names the values in the way and the step that would clear them.
4. **The source is never modified**, which is the read-only guarantee of ADR-0002 rather
   than a convenience.

Two ordering rules follow from the second and third, and both were found by running the CLI
rather than by reasoning about it. `recode_null` comes before `cast`, because a lenient cast
would perform the recode silently. `add_missing_indicator` comes before any fill on the same
column, and is refused after one: once the gaps are filled there is no record of where they
were, so the indicator would be 1 everywhere and carry nothing, silently.

The steps enter `spec_hash`: a run with them is a different run. The report prints what
each one did, including a step that changed nothing, which usually means the column was
not what the user thought it was.

### 6.5 Snapshots and fingerprints

Data is materialised into a **derived snapshot**. The snapshot must provide two things;
how it is implemented is not constrained:

1. **A writable working copy**: mapping and quality repairs act only on it, and the
   original source is never modified
2. **snapshot_fingerprint**: computed over the **normalised content** (sort by primary
   key, then fix column order and dtypes), not over the file's bytes

The implementation reads with pandas, applies the preprocessing steps and the population
filters, writes the result as gzipped CSV, and fingerprints the normalised content. Beyond
what fits in memory, switch to DuckDB or another columnar engine; that is an implementation
detail and does not change the two contracts above.

**Gzipped CSV rather than parquet**, which is a change from this section's earlier default.
Parquet needs pyarrow, a forty-megabyte wheel, for one artefact, and what it would buy is
dtype preservation, which is exactly what the fingerprint normalises away: an integer stored
as a float is the same content. CSV is also readable by a person looking for one patient.

**Two fingerprints, because they answer different questions.** `source_fingerprint` is over
the file as read, before anything touches it, and answers "is this the same data?".
`snapshot_fingerprint` is over the table actually analysed and ties the report's numbers to a
specific table. Both are in the manifest.

**What the normalisation forgives**, each rule being something that would otherwise give a
different hash for the same data: row order (sorted by the declared key, or by every column
when there is none), column order, an integer stored as a float, negative zero, the flavour of
a missing value, and a boolean against a 0/1 integer. Strings are not stripped or case-folded,
because " A" and "A" are different values and a fingerprint that said otherwise would be
making an editorial decision.

**What it does not forgive, and why rounding is not the answer.** Floats are compared at full
precision, so a table re-serialised by something writing fewer than seventeen significant
digits will not match. Rounding the fingerprint is the obvious fix and the wrong one: one ulp
is about 2e-16 relative and the rounding boundaries at fifteen digits are spaced 1e-15 apart,
so a perturbed value crosses a boundary about a fifth of the time. Rounding moves the
instability onto every value instead of removing it. The snapshot is therefore written
losslessly, at seventeen digits and read back with pandas' exact float parser, so that its own
recorded fingerprint verifies against it. Both halves were needed: with sixteen digits, or
with the default parser at seventeen, 32 of 41 columns came back differing in the last bit.

### 6.6 Earlier runs on the same data

The source fingerprint exists for one thing that nothing else can do. design.md 7.4 locks the
primary analysis at confirmation and marks anything changed after seeing the results as post
hoc. Applying that needs these two cases told apart, and `spec_hash` changed in both:

- the same spec on new data, a fresh primary analysis, legitimate
- a different spec on the same data, a second look at numbers already seen

So a run scans the sibling runs in its run directory for the same `source_fingerprint` with a
different `spec_hash`, and the report states what it found. **Stated, never refused**: a
second analysis is legitimate and common, it only has to be visible as one.

One refinement keeps the warning honest. Only runs that **reached an estimate** count, which
the manifest shows through the presence of `results/results.json`. A user who hit a blocking
quality issue, added the step that cleared it and re-ran has changed the spec on the same data
and saw no results in between, so there was nothing to react to. Without this the warning
would fire on the tool's own intended workflow, and a warning that fires on correct use is
one people learn to ignore.

Database sources additionally record the query text and the time of reading.

Snapshot retention, disk encryption and capacity limits belong to the deployment
environment; CauSpec does not implement them, and a deployment note should state these
requirements when real data is connected.

---

## 7. The spec

### 7.1 Field-level provenance and status

```yaml
treatment:
  value: {variable: rrt, type: binary}
  source: user            # user | model | data
  said: "by dialysis I mean starting CRRT"   # the user's words; required when status=confirmed
  turn: 4
  status: confirmed       # drafted | confirmed
time_zero:
  value: first_aki3_time
  source: model
  status: drafted
```

Rules:

- The critical fields are: population, treatment, outcome, time_zero, estimand,
  variable_roles, key_non_edges, identification_strategy, adjustment_set, instrument,
  plus the panel fields of 7.3 for a lag-profile analysis. The gate's requirements are
  in 11.2.
- **`status: confirmed` requires `said`**: the words the user used when confirming,
  regardless of `source`. A value the model inferred and the user then accepted is also
  marked confirmed; `source` stays `model` while `said` records the user's words at
  acceptance.
- A conflict between what the user said and what the data shows gets no separate field
  status. Quality checks find it and raise a blocking issue, which gate condition 2
  already stops. The conflict sits in the quality report for a person to judge: change
  the spec, or record a waiver with a reason. The system does not adjudicate on the
  user's behalf, and does not carry a second state machine to do so.

Stated plainly: confirmation happens in conversation, `update_field` is called by the
model, and **the server can verify neither that the user saw the spec nor that `said` is
true**. That hole cannot be closed in this form, as long as confirmation happens in
conversation and is relayed by a model, there is no cryptographic guarantee. What can be
done is raise the cost and leave a trace: requiring a quote means a model skipping
confirmation must fabricate the user's words, and the report's front page shows the full
spec with each field's source, said and turn, where a fabricated quote is recognisable.
SKILL.md further forbids marking anything confirmed without an explicit answer, and a
golden task tests exactly that (give a vague sentence and see whether the model marks a
row of fields confirmed).

### 7.2 Structure

```yaml
spec_version: 1
meta: {question: ...}
# Who the answer is about. Each filter carries the user's own words, the same rule as a
# confirmed field, because an exclusion changes the estimand's population rather than
# cleaning anything. Operators are a closed set (not_missing, eq, ne, lt, le, gt, ge, in,
# not_in); filters are conjunctive and applied in order, so the report's exclusion ledger
# reads as a sequence a reader of a study already knows how to audit.
population: {description: ..., filters: [{column, op, value, said, turn, suggested_by}]}
causal_design:
  analysis_type: hte | panel
  estimand: ...
  treatment / outcome / time_zero / instrument / adjustment_set / effect_modifiers
  assignment_mechanism: randomised | randomised_with_noncompliance | decided
  # optional, and read only by the temporal layer (8.1). Times may be timestamps or numbers;
  # outcome_horizon is in whatever unit the columns already use, because converting it on the
  # user's behalf is how a 28-day horizon becomes 28 hours.
  treatment_time / outcome_time / followup_end / outcome_horizon / time_unit
  variable_roles: {<variable or group>: confounder | instrument | mediator | effect_modifier | suspected_collider | post_treatment}
  key_non_edges: [...]        # e.g. no path from instrument to outcome except through treatment
  identification_strategy: backdoor_adjustment | instrumental_variable
  assumptions:
    - {id, category: empirically_assessed | requires_justification | untestable, statement, justification}
estimation: {family, params, seed}
analysis_plan: {primary: ..., sensitivity: [...], exploratory: [...]}
```

### 7.3 The panel protocol

The second analysis type. Where the HTE families take one row per unit and ask what a
treatment did, this one takes one row per unit and period and asks what **one period** of
treatment did to that period's outcome and to the outcomes after it. The estimand is the
lag profile theta_0 ... theta_K, and the family is dynamic_lag_dml.

**Why the earlier draft of this section was wrong.** It specified the seven components of
a target trial plus event_roles, assigning death, discharge and transfer to outcome,
competing, censoring or terminal. That is the field layout for a marginal structural
model, where the question is a contrast between two strategies followed over time and the
outcome is a survival endpoint. It is not the method this project has. Here termination
is the end of the observation window, not an outcome, and death and discharge are the
same event: both stop the trajectory. Keeping the old layout would have made the code
answer a question the estimator cannot answer. The target-trial layout returns if a
strategy contrast is ever implemented; it is not the layout for a lag profile.

**Fields.** unit_id, period_index, period_length, state, treatment, instant_outcome,
max_lag, horizon, termination; plus effect_modifiers when the lag effect is allowed to vary.
period_length is what one period means in clock time, twelve hours in the author's
application, and it exists so the report can say "at 24 hours" rather than "at lag 2".

**Why the horizon is a confirmed field and not an inference.** Whether trajectories end at
different times decides whether the continuation weighting applies at all, and the shape of
the data cannot settle it. A panel where every unit has eight periods is either a genuinely
fixed horizon, in which case no weighting is needed, or a variable horizon whose data pull
kept the first eight buckets of the units that lasted that long, in which case the cohort is
conditioned on surviving and no weighting repairs it. The two are indistinguishable by shape.
Measured on the panel generator: keeping the 3.5% of units that reach eight periods moves the
lag-1 estimate from 4.22 to 2.87 against a truth of 4.0, and a tool that guessed "fixed"
would report that as a clean analysis with weights of one.

So the user confirms it, a check compares the answer against the data and refuses a
contradiction, and the estimator refuses to run without it. The answer also decides the
analysis set: under a fixed horizon each unit's final period contributes a window, because its
outcome is recorded like any other and the condition the paper's set stands in for, surviving
one period past the outcome, cannot fail. That is about a sixth of the lag-2 windows on an
eight-period panel, at no cost in bias. Under a variable horizon the paper's convention holds
throughout, including for units the window cut off, whose final outcome is recorded but whose
continuation is unknown. When the horizon is variable a
second field is required: how leaving is identified, either because the rows stop there or
because a column marks it. Only a real exit is evidence that a trajectory could have
continued and did not; reaching the end of the observation window is not. This is the same
principle as 7.1, that a field which changes the estimand is confirmed rather than guessed,
applied to the one property of a panel that the panel cannot report about itself.

**The within-period order is part of the estimand**: active, then state, then treatment,
then outcome, then the next period. Two consequences, and both are checks rather than
prose. A state column measured after the period's treatment began is post-treatment and
cannot be in X. And the lag index counts rows, not clock time, so a missing bucket in the
middle of a trajectory turns a lag-2 window into a lag-3 window without any error; gaps
block rather than get imputed.

**How the profile is read.** theta_kappa is defined on the anchor risk set, meaning among
trajectories still active at the treatment period. It says nothing about units that had
already left, and it is not an effect on leaving. A clinician reads "no effect at lag 3"
as "no effect on dying", so the report states the estimand in the same paragraph as the
numbers rather than in a methods note.

**What the intervals are.** The theory behind the estimator proves consistency of the
whole profile and gives no limiting distribution. The intervals are therefore exploratory
percentile intervals from a bootstrap that resamples whole trajectories, and no lag may
be called significant. This is the first place in the project where the honest answer is
"the point estimate is the result and the interval is an indication", so claim_levels.yaml
carries an explicit rule for it rather than leaving it to the prose.

The full declaration, including the structural model the profile derives from and the
four questions this family refuses, is families/dynamic_lag_dml/family.yaml.

### 7.4 Changes after confirmation

The primary analysis is locked at confirmation. Anything added or changed after seeing
the results is automatically marked post_hoc and reported separately. [reuse] The
practice follows StatsPAI's preregistration deviation log (MIT,
src/statspai/question/preregister.py).

### 7.5 Variable roles and a coarse DAG

The user is not asked to draw a full DAG. EHR settings routinely have dozens of
covariates, and forcing a complete diagram produces a formality. Two things are used
instead:

- variable_roles: a role for each variable or group, drafted by the agent from the user's
  answers and confirmed. The set is closed, `confounder | instrument | mediator |
  effect_modifier | suspected_collider | post_treatment`, because the diagram's edges are
  derived from the role: a role nobody can draw is a role that means nothing.
- key_non_edges: the few "no edge" assumptions that decide whether identification holds,
  written out explicitly. Under IV these must at least include: the instrument does not
  affect the outcome except through the treatment (the exclusion restriction), and the
  instrument is independent of unmeasured confounders.

**The diagram is derived, not drawn**, and that is what makes it worth having. The same
declaration that produces the edges is compared with the variables the analysis actually
conditions on, so `roles_match_adjustment` refuses an analysis that adjusts for a mediator, a
collider, a post-treatment variable or the instrument, and warns when a declared confounder is
left unadjusted. A hand-drawn picture cannot be wrong in a way anyone notices.

Each role implies its edges with no freedom: a confounder points at both the treatment and the
outcome, an instrument at the treatment only, a mediator sits between them, a collider takes an
arrow from each, a post-treatment variable takes one from the treatment, and effect modifiers
label the treatment-outcome edge rather than becoming nodes.

**One node per group**, carrying a count and two examples: "7 confounders (max_creatinine,
max_urea, ...)". Seven boxes is where a derived diagram turns back into the formality this
section refuses to ask for, and an honest diagram that fits on a screen is worth more than a
complete one that does not.

**Only one non-edge is drawn**: the exclusion restriction, instrument to outcome, as a dashed
arrow, because it joins two nodes that are both on the diagram and a reader can object to it.
The free-text assumptions are listed beneath. Drawn as arrows from nowhere they read as edges
that exist, which is the opposite of what they mean.

Output is mermaid in the report, which renders in GitHub, VS Code and most markdown viewers,
plus the same graph as DOT in the run directory for anyone who has graphviz. **No graph
library and no DoWhy**: the derived graph has a fixed shape, so the backdoor criterion over it
reduces to the per-role rules above, and DoWhy is not a dependency of this project.

What a derived diagram cannot express, and the report says so: causal relations among the
covariates themselves, such as a declared confounder that is really a mediator of another
confounder. That needs the full DAG this section declines to ask for.

Being pre-treatment is necessary but not sufficient for inclusion in the adjustment set:
a pre-treatment variable can still be a collider on a backdoor path (M-bias). The usual
practice in high-dimensional DML is to adjust for every pre-treatment variable; Ding and
Miratrix (2015, Journal of Causal Inference) argue under a linear structural equation
model that M-bias is generally smaller than the confounding bias from not adjusting,
while Pearl (2015), commenting in the same journal, disputes the scope of that
conclusion. A variable marked suspected_collider therefore raises a warning only, and
the report shows the result both with and without it; it is not a hard gate. [reuse] The
note is adapted from Baygent causal-inference's key rules (MIT).

### 7.6 Estimand and family reconciliation

Each family declares in family.yaml the estimands it can identify, for example:

- hte_iv: depends on the identification assumptions. Under monotonicity alone, what is
  identified is the conditional LATE, holding for compliers only; only under the further
  assumption that the effect does not vary by compliance type given covariates may it be
  read as a CATE. TODO: fill in according to the assumptions Project 1 actually adopts.
- hte_backdoor: ATE, ATT, CATE.
- dynamic_lag_dml: lag_profile, and lag_cate when the effect is allowed to vary with
  the state at the treatment period. Both as defined in 7.3.

Validation compares spec.estimand with the chosen family's declaration. A mismatch has
two resolutions: choose a different family, or have the user restate the estimand. For
example, a user asking "which patients benefit" while the identification strategy is IV
under monotonicity alone means the report must state that what is estimated is the
conditional LATE among compliers, not the population CATE. [reuse] The reconciliation
step follows step 5 of Baygent causal-inference's design choices (MIT).

When the design a question needs is outside the supported families (difference-in-
differences, regression discontinuity, synthetic control), the system says so
explicitly, lists each excluded family with its reason, and does not force the question
into backdoor adjustment. [reuse] Showing excluded families with reasons follows Causal
desk (ideas only).

---

## 8. Data quality and identifiability

### 8.1 The check layers

| Layer | Checks | Implementation |
|---|---|---|
| basic | types, uniqueness, missingness, NULL-encoding variants, zero spikes, isolated extremes, impossible signs | Written here (ADR-0003: pandera would carry the easy third of the layer in a format that has to be rewritten). Thresholds in `core/quality/basic_checks.yaml` |
| temporal | treatment before time zero (immortal time), outcome before treatment, time inversion, insufficient follow-up | Written here. Reads optional spec fields and **says when it could not run**: a check reporting nothing on a table it could not read turns the report into a clean bill of health |
| identification | treatment prevalence, overlap, SMD, suspected post-treatment, instrument relevance, censoring against state, **and the two population checks** | Overlap and SMD written here (the logic is simple); instrument relevance in 8.2. The population checks are in core because they need no family knowledge, and are labelled `identification` because selecting on a consequence of treatment is an identification failure: a layer names what a check is about, not where its code lives |
| feasibility | per-arm sizes and event counts in core; extreme weights and ESS in the families | Counting written here. These block where 10.2's rule says not to gate on what an interval says, because a forest on 25 events returns a confident per-patient estimate: the interval does not say it |

The population checks run on the frame **before** the filters are applied, because the
people a filter removed are the only evidence about whether removing them mattered. Two
questions:

- **`population_filter_variable`**: is the filter conditioning on something the treatment
  could have caused? Filtering on the outcome is refused and not waivable: it compares the
  survivors of one arm with the survivors of the other. A column that separates the arms
  almost perfectly is refused on the same criterion `panel_post_treatment_state` uses, since
  it is the same error reached by selection rather than by adjustment. A confounder is *meant*
  to predict the treatment, so moderate association is the design working and only asks a
  question.
- **`population_exclusion_informative`**: are the people it removed different from the people
  it kept? Measured as the treatment rate and the event rate among the excluded against the
  kept. A warning and never blocking, because an eligibility criterion is informative by
  construction. It exists so the report cannot imply the remaining patients are a random
  subset of the ones asked about.

### 8.2 Instrument relevance

The form of the diagnostic is decided by the family; there is no universal first-stage F.

The effective F test (Montiel Olea-Pflueger) is written here, with a regression test
against a numerical example from the original paper. The Anderson-Rubin test goes into
the backlog, to be added when needed.

StatsPAI is not taken as a dependency for these two functions: it is large (numba,
linearmodels and more), iterates quickly, and has corrected the behaviour of several
functions in recent versions, while both tests are closed-form, so writing them with
tests is more controllable than pinning a heavy dependency, and makes the provenance of
the numbers easier to state.

### 8.3 The issue schema

```yaml
check_id, layer, severity: blocking | warning | info, waivable,
evidence: {...}, affected_columns, impact_on_analysis, recommended_repair
```

Each check has an address `qc:<check_id>` for interpretation and reporting to cite.
Repairs act on the derived snapshot only.

---

## 9. Estimation, diagnostics and sensitivity

| Item | Implementation |
|---|---|
| DMLIV (primary, IV design) | The author's code; interface TODO |
| CausalForestDML (baseline) | [reuse] EconML (MIT), already used in the author's code |
| HTE calibration: BLP, group calibration, uplift/QINI | hte_backdoor: [reuse] EconML's econml.validate.DRTester (MIT), against the installed version's interface. hte_iv: DRTester rests on doubly-robust scores that assume unconfoundedness and cannot be used directly in an IV setting; an IV-appropriate score has to be written. TODO. The original code had no such step |
| Rank stability over repeated cross-fitting | Written here (loop the estimator over seeds) |
| Sensitivity to unmeasured confounding (DML) | [reuse] DoubleML (BSD-3) sensitivity_analysis |
| E-value | Written here (a closed-form expression), with a regression test against the numerical example of VanderWeele & Ding (2017) |
| Refutation: placebo treatment, random common cause, data subset | [reuse] DoWhy (MIT) refuters |
| Longitudinal IPCW | The author's code; correctness verified by ground-truth coverage on synthetic dataset A |

Dependency policy: only four direct dependencies (EconML, DoWhy, DoubleML and linearmodels),
all mature with stable interfaces. Closed-form diagnostics (E-value, effective F) are
written here with numerical regression tests: writing them costs a few dozen lines,
while each additional heavy dependency adds version drift and correctness risk. StatsPAI
is not taken as a dependency; only its field layout and some of its practice are
borrowed (see 7.3, 7.4, 11.2).

---

## 10. Interpretation and reporting

### 10.1 Addresses and placeholders

Every computed artefact has an address: `res:primary.estimate`, `res:primary.ci`,
`qc:overlap_extreme_propensity`, `fig:cate_distribution`. Report prose written by the
model may reference numbers only through placeholders, e.g.
`{{res:primary.estimate}}`; the renderer substitutes by address. An unknown address, or
a bare number anywhere in the prose, fails the render, and the error goes back to the
model to rewrite.

[reuse] The mechanism of "a judgement must cite an existing address, or be refused and
asked again" follows Causal desk ADR-0002 (ideas only).

### 10.2 Claim levels

Four levels: causal, suggestive, associational, descriptive. The skill requires the
prose's wording to match the level decided.

**Code can only downgrade; it cannot grant causal.** Untestable assumptions
(unconfoundedness, exclusion restriction, monotonicity) can never be verified by any
amount of data, so the ceiling for an automatic decision is suggestive. Reaching causal
takes two further conditions, both recorded in the spec: every assumption with
`category: untestable` carries a `justification` whose field has `source=user`; and the
user explicitly agrees to causal wording. The division of responsibility is then clean:
code vouches that "the diagnostics found nothing wrong", a person vouches that "the
assumptions hold", and the report says who did which.

**There are only two blocking checks.** The trade-off is:

> If the confidence interval already says it, do not gate on it.

Small samples and poor precision widen the interval, and the reader can see that;
gating on them as well is duplication, and it is exactly the part that makes a tool
tiresome and eventually routed around. What an interval cannot express is systematic
bias, and that has two sources:

| Blocking check | Threshold | What failing means |
|---|---|---|
| Overlap / positivity | at most 5% of the sample has a propensity score outside [0.05, 0.95] | Some people have no comparable controls and their effect is extrapolated; the interval will look narrow, but narrow in a way that means nothing |
| Instrument relevance (IV designs only) | effective F above the MOP critical value for the tolerated bias level | Under a weak instrument the bias can be arbitrarily large and the interval loses coverage |

Every other diagnostic (the E-value, DoWhy's three refutation tests, adjusted SMD, rank
stability over repeated cross-fitting, the paired results for a suspected_collider) is
**computed, reported, and not gated on**. They go into the report for the reader to
weigh; they do not enter the decision. A tool that blocks on two things is taken
seriously; a tool that blocks on fifteen is routed around.

The decision:

```
descriptive    <- the gate did not pass (spec unconfirmed, or an unwaived blocking issue)
associational  <- either blocking check failed
suggestive     <- both passed (the highest a code decision can reach)
causal         <- suggestive + every untestable assumption justified by the user + explicit approval
```

Plus two rules:

- Every downgrade names, in the report's "claim level and reasoning" section, which
  check, its measured value, and where the threshold sits
- The user may waive a blocking check with a reason; waivers are listed separately in
  the report, and **a waived analysis cannot reach causal**

**Thresholds must be visible, configurable and reproducible.** 0.05/0.95 and 5% are
conventions, not laws, and may reasonably be disputed. What actually matters is three
things: they are fixed in advance (not after seeing the result), printed in the report
(so the reader sees where the line is), and recorded in the manifest (so the decision
can be reproduced later). In implementation they live in `claim_levels.yaml`
(`packages/causpec/core/reporting/`), with the manifest recording its hash, and the
decision itself carrying it too (`claim:rules_hash`).

Two further details settled during implementation:

- **A waiver does not change the diagnosis.** A waived blocking check still caps the
  level at associational, and the report notes "waived, but the diagnosis is unchanged".
  A waiver lets the analysis run; it does not make the problem disappear.
- **The justification must come from the user.** A `source=model` justification does not
  count, a model vouching for its own assumptions is circular. `Assumption` therefore
  records `justified_by`.

The decision reaches the report through the `claim:` namespace: `claim:level`,
`claim:n_unjustified_assumptions`, `claim:rules_version`, `claim:rules_hash`. The
renderer accepts the merged address table from all three sources: `res:`, `qc:` and
`claim:`.

[reuse] The level scheme and the "passing is not proving" framing are adapted from
Baygent causal-inference's scripts/check_refutation.py and references/refutation.md
(MIT, copyright retained). The original distinguishes critical from marginal checks and
targets Bayesian HDIs; this project drops the marginal tier, narrows the blocking checks
to the two above, and switches to frequentist diagnostics.

### 10.3 Report structure

In order: question and spec (with each field's provenance) -> the estimand and the
population it applies to -> the variable-role diagram -> assumptions, split by the three
categories, before the results -> data quality -> primary results -> sensitivity and
refutation -> the claim level and its reasoning -> limitations -> post_hoc analyses, if
any.

[reuse] "Assumptions before results" and the fixed report structure follow Baygent's
references/reporting.md (MIT).

---

## 11. Workflow and gates

### 11.1 The workflow

1. Ask what the user wants to know, then read the schema. The failure to avoid is the
   data supplying the question, and it arrives two ways: the user picking off a column
   list they have just been shown, or the agent proposing an analysis because a variable
   happens to exist. Neither is caused by reading a file, so the constraint belongs on
   what is shown and proposed, not on what may be read: ask what they are comparing
   before showing any column names, then read the schema freely. Doing so lets a
   question about timing be asked concretely ("your data has one row per patient and
   this flag is 0/1; does it mean ever treated during the stay, or already on treatment
   at admission?") rather than asking a clinician to classify their own treatment as
   static or time-varying in the abstract; and when every unit appears once with no time
   columns, the question can be skipped entirely. A wide table does not settle it, since
   one row per patient can still be a flattened "ever treated". The schema makes the
   question concrete, it does not answer it.
   Step 1 also settles **how the treatment was assigned**, which is asked here rather than at
   step 4 because it decides which identification questions are worth asking at all, and
   asking it after the columns are mapped means reopening them. Three answers and three
   different worlds: randomised with full compliance, where exchangeability holds by design
   and the user's justification for it is the randomisation rather than a judgement;
   randomised with partial compliance, where the assignment is an instrument for the
   treatment received, which is the shape of dataset D and the answer a workflow without this
   question cannot propose; and decided case by case, where the follow-up is what the
   decider had in front of them, since a clinician can answer that and cannot reliably answer
   which variables satisfy a backdoor criterion. Recorded in `assignment_mechanism`.
   Randomisation makes the **assignment** unconfounded and not the treatment received, which
   is why partial compliance calls for an instrument rather than adjustment, and a randomised
   study can still be broken by differential dropout, so the quality checks still gate.
2. Map concepts onto columns; settle the mapping.
3. Variable roles and key_non_edges (7.5).
4. Identification strategy and assumption categories.
5. Choose a family and reconcile the estimand (7.6); stop here if unsupported.
6. Quality checks.
7. The user confirms the spec.
8. Estimate and report.

Steps 1, 2 and 6 to 8 run the same way whatever the data looks like; steps 3 to 5 depend on
the shape and the skill writes them out once per path rather than annotating a single list,
because a model following a cross-sectional step 3 on panel data would confirm an
`adjustment_set` that family does not have.

Steps 1-5 complete field-level confirmation; at step 7 confirm_spec computes and records
a spec_hash over the whole spec, used to lock the primary analysis (7.4) and for gate
comparison.

### 11.2 The gates

Checked before `estimate` runs:

1. spec_hash matches the confirmation record, and every critical field is confirmed.
2. A quality report exists for the current (snapshot_fingerprint, spec_hash) with no
   unresolved blocking issues; waived issues carry a reason.
3. family.supports(spec) passes, and spec.estimand lies within what that family declares
   it can identify.

A failure returns a structured error carrying a code, a reason and a suggested fix.
[reuse] The "error to remediation" registry pattern follows StatsPAI's
agent/remediation.py (MIT).

---

## 12. The MCP server

| Tool | Purpose |
|---|---|
| list_sources / describe_source | Schema and column statistics, no raw rows |
| register_dataset / apply_mapping | Produce a snapshot |
| draft_spec / update_field / confirm_spec | Field-level provenance and status |
| route_family | Return candidate families, excluded families with reasons, and the estimand reconciliation |
| run_quality_check | Return the issue list with addresses |
| record_waiver | A waiver, which must carry a reason |
| estimate | Run the family once the gates pass |
| render_report | Substitute placeholders, verify the claim level |
| list_runs / get_run | Query the history |

Implementation notes:

- Use the official MCP Python SDK.
- Tools that change no state (list_sources, describe_source, route_family, list_runs,
  get_run and so on) declare readOnlyHint; tools that write server state (update_field,
  confirm_spec, record_waiver) do not, but no tool modifies a data source. Returns
  declare outputSchema and supply structuredContent. These are features of the MCP
  specification itself.
- Under stdio, logs go to stderr only.
- `causpec-mcp doctor`: check dependencies, connectivity, and whether the database
  account genuinely cannot write (by attempting a write and expecting it to fail).
- Schema drift: apply_mapping compares the source's current columns against the
  mapping's expectations and reports the differences on a mismatch.

**How deep Postgres goes**: v0.3 delivers only a thin adapter plus a docker-compose demo,
enough to show two things: that a read-only view built by the data owner can be
connected, and that the read-only guarantee genuinely comes from account permissions
(verified by `doctor`). `masked_columns` and the schema-drift check move past v1.0. The
reason: this project's distinguishing work is the controlled causal-inference workflow,
not database integration, and the marginal return on going deeper into Postgres is far
below that of making the quality checks and calibration solid. `allowed_relations` and
the path boundary (ADR-0002) are **not** part of that reduction: they are safety
boundaries, not features.

---

## 13. The skill

```
skill/causpec-analyst/
 |- SKILL.md
 |- references/  workflow.md, spec-fields.md, variable-roles.md, quality-checks.md,
 |               hte-dmliv.md, dynamic-lag-dml.md, reporting.md, claim-levels.md
 |- assets/      report-template.md, the causpec wheel
 `- scripts/run.py
```

The rules in SKILL.md:

1. One question per turn, starting from the most important unconfirmed field. [reuse]
   Follows Causal desk (ideas only).
2. Numbers only through placeholders.
3. Wording follows the claim level decided by code.
4. When domain knowledge is needed (is the instrument valid, is there unmeasured
   confounding), ask the user. [reuse] Follows Baygent causal-inference's key rules (MIT).
5. Confirmation must be real: a confirmed field carries the user's words, and the model
   never confirms on the user's behalf.
6. Follow the order of 11.1: the estimand is fixed before the data is examined.
7. Whether a variable enters the adjustment set is decided by measurement time first,
   role second (7.5).
8. When the design a question needs is unsupported, say so and say why; do not
   substitute another design to produce a result.

Two further rules added after an exploratory run:

- **Follow the user's language**, not the document's. SKILL.md is written for the model,
  not for the end user.
- **Do not discuss the tool's internals in conversation.** The report header records the
  best-effort nature of the skill form for whoever assesses the result afterwards; it is
  not an opening remark, and the model should not volunteer the execution mode or
  announce that it could bypass the scripts. The user has just asked a professional
  question and has no result yet, so neither fact is actionable for them.

---

## 14. Logs and artefacts

```
runs/<run_id>/
 |- manifest.json    execution_mode, git_sha, package versions, snapshot_fingerprint, spec_hash, seed, artefact checksums
 |- spec.yaml, mapping.yaml
 |- quality/         issues.json, quality_report.html
 |- results/         results.json (with addresses), figures/
 |- report.md / report.html
 `- audit.jsonl      one line per tool or CLI call: timestamp, tool, parameter hash, input fingerprints, output hash, whether it errored
```

Writes use a temporary file plus an atomic rename. **The logs record no raw rows and no
credentials.**

---

## 15. Sample data

- A: synthetic data from a structural causal model, with ground truth, containing
  heterogeneous effects, an instrument, informative censoring and variable-length
  trajectories.
- B: dataset A in two shapes (wide table, long event table), to verify that changing
  shape requires only a mapping change.
- C: dataset A with problems injected, each mapped to an expected check_id.
- D: a commercial setting: an A/B test with non-compliance, and user retention.

The generators are committed; what they produce is not. No real data may be committed
under any circumstances.

---

## 16. Evals

| Category | Contents |
|---|---|
| numerical | Agreement with a direct family call; reproducibility under a fixed seed; ground-truth coverage on dataset A |
| quality checks | Recall of each injected problem on dataset C |
| robustness | The two shapes of dataset B reach the same conclusion |
| reporting | The renderer refuses un-placeheld numbers and unknown addresses; the claim level matches the diagnostics |
| agent | 20-30 golden tasks: does it ask about the critical fields, miss a diagnostic, overstate the claim, including tasks where the estimand and identification strategy do not match, and tasks needing an unsupported design (difference-in-differences, regression discontinuity) |
| regression | Freeze a few confirmed specs and snapshots as fixtures; a change to a family must not change their results |

[reuse] Frozen handoffs as regression tests follow Causal desk ADR-0004 (ideas only); the
with-and-without-skill comparison follows the organisation of Baygent's evals/ (MIT);
external tasks may draw on the parts of CauSciBench (as used by CAIS) that match this
project's setting (check the licence before use).

---

## 17. Related work (for the README)

| Project | What it is | How CauSpec differs |
|---|---|---|
| Causal-Copilot, CAIS | Research prototypes aiming at full automation: the LLM picks the method, generates code, and self-corrects | CauSpec does not pick methods automatically, and the spec must be confirmed by the user |
| StatsPAI | A broad econometrics and causal library with MCP and skills, and cross-language numerical agreement tiers | CauSpec targets a controlled workflow for two kinds of analysis; it takes no dependency on StatsPAI and borrows only the target-trial field layout and some practice |
| Causal desk | Controlled conversational causal analysis; the closest in spirit to CauSpec | CauSpec targets read-only database access, HTE-IV and longitudinal IPCW |
| Baygent causal-inference | A Bayesian causal-analysis skill with enforced checkpoints and claim calibration | CauSpec is frequentist with a deterministic server, and adapts its claim calibration |

---

## 18. Open questions

1. The open-source licence for the research code.
2. The role of each event in IPCW (the TODO in 7.3).
3. The interface of EconML's DRTester in the version in use.

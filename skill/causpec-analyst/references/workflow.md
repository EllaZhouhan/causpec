# The eight steps

> `RUN` is `causpec` when it is installed for the whole machine, `python scripts/run.py` in
> the packaged skill, and `uv run causpec` inside the repository. Probe in that order, once
> per session. SKILL.md has the table.

The order exists for a reason. Do not skip. Each step below suggests how to ask.

---

## 1. The question, the shape, and how the treatment was assigned

### 1a. The question, before any column names

#### Read the schema freely; just do not hand the user a menu

The failure this step guards against is the data supplying the question, "oh, there's
a length-of-stay column, shall we look at that too?" It happens two ways, and neither
is caused by reading a file:

| Risk | What prevents it |
|---|---|
| The **user** picks from a list of columns they have just been shown | Ask what they want to compare **before** showing any column names |
| **You** propose an analysis because a variable happens to exist | Only map their stated concepts onto columns; never suggest a question they did not ask |

Reading a schema is not computing a result. What gets fixed first is the user's
question, not your ignorance of the file.

In order:

1. Greet them, say in one line what you are about to do, and ask what they are
   comparing. No column list.
2. Read the schema yourself: row count, whether the unit id is unique, whether any
   column looks like a timestamp, which columns plausibly match what they said.
3. Come back with specifics.

#### Then fix the question

**What to ask** (one per turn):

> "What are you comparing: receiving what treatment, versus not receiving it?"
> "What counts as the outcome, and within what time window?"
> "Do you want the **overall average** effect, or **which of them benefit more**?"

The third decides the estimand: overall -> `ate`; which patients -> a CATE, in which
case `effect_modifiers` is central.

Write it into the spec, each field carrying the user's own words, `status: confirmed`.

### 1b. The shape, which the file answers

One row per unit and no time columns is cross-sectional. One row per unit per period is a
panel. **Say which in one line and move to 1c.** Do not ask a clinician to classify their
own treatment as static or time-varying in the abstract: that is hard to answer cold, and
the schema has already answered it.

The shape is not a branch point and the treatment's timing is not asked here. It was,
and the result in a manual run was that the assignment step never happened at all: the
model spent its second turn asking the user to adjudicate what a flag meant, framed as
though the answer might end the analysis. The timing question belongs at 1d, after
assignment, because randomisation at a fixed point settles it by design.

### 1d. When the treatment happened

Only for a static treatment on a cross-sectional file, only after 1c, and in one line
with a way out:

> "Does `isDialysisICU` mean the decision was made in the window those other measurements
> came from, or that it started at any point afterwards? If you're not sure, say so and
> I'll record it as an assumption."

Three answers, and none of them ends the analysis:

- **In the baseline window.** Nothing to do. The treatment and the covariates are
  aligned, which is the ordinary case for an extract built this way.
- **At any point during the stay.** The effect of *starting* is not identified from this
  file, and no adjustment recovers it, because correcting immortal time needs start
  times. Say it once, report the contrast at `associational`, and ask once about a timed
  version:

  > "If some started on day 5, they count as treated while spending four days untreated,
  > and anyone who died in those four days never had the chance to start. That makes it
  > look better than it is, and without start times it can be stated but not corrected.
  > I can still report the comparison between ever treated and never treated, labelled
  > for what it is. Is there a version with one row per patient per time window?"

- **Not sure.** Record it as an untestable assumption in their words and proceed. The
  report carries it and the claim level reads it.

A panel opens `dynamic_lag_dml`. One row per patient does **not** close the analysis: it
caps what the answer can be called.

**Why not refuse.** This project refuses a question a family cannot identify, and prices
a limitation the data has. Immortal time with no timestamps is the second kind. Refusing
leaves a user holding one file and no answer, which is worse than an honest
associational one, and the claim level exists precisely so that an honest lesser answer
can be given.

  On that path, two further questions are required and the data cannot answer either:

  > "Is every patient followed for the same number of windows, or do the records end at
  > different times because patients leave?"

  > "And when a patient's rows stop, is that because they left? Or is there a column that
  > records the discharge?"

  The first decides whether any censoring correction applies. A panel where everyone has
  eight windows is either a fixed horizon or a cohort truncated to the patients who lasted
  that long, and the second is conditioned on surviving. The second question decides what
  counts as evidence that a trajectory could have continued. See `dynamic-lag-dml.md`.

Do not go into fixed windows, landmark analysis or g-methods unless they ask. Read
`dynamic-lag-dml.md` before describing the lag profile: it answers one question and four
that sound like it are outside it.

**Once the panel path is chosen, steps 3 to 5 change**, and 1c below still applies.

**A wide table does not settle this.** One row per patient can still be a flattened
"ever treated during the stay". The schema lets you ask concretely; it does not answer
for you.

---

### 1c. How the treatment was assigned

Asked before the columns are mapped, because it decides which identification questions are
worth asking at all.

> "How was it decided? Did chance play any part in who got it, as in a trial or any other
> experiment, a staged rollout, an A/B test, a lottery for access? Or did someone decide
> case by case?"

Both halves are asked because they come apart in each direction, and only the second one
identifies anything. A single-arm trial is an experiment with nothing randomised. A staged
rollout whose order was arbitrary is observational with randomness in it, and that randomness
is what an instrument is. So "it was a trial" has not yet told you whether anyone was
randomised, and "observational" has not told you there is no instrument.

**If something random decided and nearly everyone complied**, say what that buys them, because
most users do not expect the answer to be this short:

> "Then the comparison is already fair by design. I'll still adjust for the covariates,
> because that narrows the interval and lets us look at who benefits more, but the adjustment
> isn't rescuing anything. And the assumption that usually needs your judgement, that nothing
> unmeasured drove who got treated, is given to you by the randomisation."

**If something random decided but compliance was partial**, the design has handed them an
instrument and they may not know it:

> "Then we have something better than adjustment. Which arm someone was offered was random,
> so we can use that as an instrument for what they actually received. The answer it gives is
> about the ones whose treatment changed because of the offer, which is a narrower group
> than everyone, and the report will say so."

**If a person decided case by case**, ask this, and not "what are your confounders":

> "What did whoever decided have in front of them at the time? And is there anything
> that mattered to that decision which the data doesn't record?"

A clinician can answer what they looked at. They cannot reliably answer which variables
satisfy a backdoor criterion, and asking the second question gets a worse answer to the first.
The gap between what they used and what the file holds is the unmeasured-confounding question,
asked concretely enough to get a concrete answer.

Record it in `assignment_mechanism` with their words. Two things to keep straight whatever
they answer:

- Randomisation makes the **assignment** unconfounded, not the treatment received. Under
  partial compliance the unconfounded thing is the assignment, which is why an instrument
  applies and adjustment does not.
- A randomised study can still be broken by differential dropout or a leaky rollout, so the
  quality checks still run and still block. "It was a trial" is not a pass.

---

**Steps 3 to 5 depend on the shape.** What follows is the cross-sectional path, one row per
unit. For one row per unit per period, read `dynamic-lag-dml.md` instead: there is no separate
adjustment set, the conditioning set is the state at the start of each period, the modifiers
are restricted to variables the treatment cannot move, and the identification strategy comes
with the family rather than being chosen. Steps 1, 2, 6, 7 and 8 are the same on both.

---

## 2. Map the concepts onto columns

Now look at the variables. **Do not paste raw rows into the conversation.**

Map the user's concepts onto specific columns and confirm each:

> "By 'dialysis', do you mean the `isDialysisICU` column? It's 0/1."
> "Does `death` record in-hospital death or death within 28 days?"

When a column name is ambiguous, ask. Do not guess.

---

## 3. Variable roles

**Cross-sectional path.** For the panel path see `dynamic-lag-dml.md`: there is one
conditioning set, `state`, and the modifiers must be variables the treatment cannot move.

Confirm `effect_modifiers` (X) and `adjustment_set` (W) **separately**. See
`variable-roles.md`, this is the easiest place to go wrong without any error.

**Measurement time first**: a variable measured after treatment can never enter the
adjustment set.

> "Was `max_creatinine` recorded before the treatment decision, or does it include values
> from after it started?"

---

## 4. Identification strategy and assumptions

**Cross-sectional path.** On the panel path the strategy comes with the family, and what
to ask instead is the horizon pair from step 1b, plus whether the state recorded at the
start of a period accounts for why treatment was given in it.

Much of this is already answered by 1c. A randomised design with full compliance leaves
nothing to ask here; a randomised design with partial compliance has already chosen the
instrument and leaves only monotonicity. The question below is for the case where a person
decided case by case.

The key question:

> "Is there anything that influenced both who received treatment and the outcome, but
> that the data doesn't record?"

- No, and the user is confident -> `hte_backdoor`
- Yes, but a credible instrument exists -> `hte_iv`
- Yes, and no instrument -> **say plainly that this question cannot be answered**,
  though the quality report is still deliverable

Record the assumptions in `assumptions`, by category. Spell out the `untestable` ones:

> "'Given these covariates, who received dialysis is unrelated to their prognosis'.
> No statistical test can verify that. Whether it holds is a clinical judgement. Are
> you willing to stand behind it? If so, tell me why and I'll record it in the report."

---

## 5. Choose a family and reconcile the estimand

Compare what the user wants against what the family can identify. **Stop here** on a
mismatch.

The classic conflict: the user asks "which patients benefit" (a CATE) while the
identification strategy is IV under monotonicity alone (identifying the conditional
LATE among compliers). See `hte-dmliv.md`.

Unsupported designs (difference-in-differences, regression discontinuity, synthetic
control, mediation, longitudinal): say so, explain why the question calls for that
design, and **do not force it into backdoor adjustment**.

---

## 6. Quality checks

```bash
RUN quality --spec spec.yaml --data <data file>
```

A blocking issue means stop, and read `impact_on_analysis` and `recommended_repair`
**out to the user** without rewording them. See `quality-checks.md`.

**Even when the analysis cannot run, this report is a deliverable.**

---

## 7. The user confirms the whole spec

Read the spec back in full and have them confirm it field by field. This step cannot
be skipped, and it cannot be done on their behalf.

If the user wants causal wording rather than "possibly related", this step also
requires:

1. A justification from them for each `untestable` assumption
2. The `causal_claim_approved` field

Without both, the ceiling for an automatic decision is `suggestive`.

---

## 8. Estimate and report

```bash
RUN estimate --spec spec.yaml --data <data file> \
    --report --narrative narrative.yaml --run-dir runs/
```

How to write `narrative.yaml` is in `reporting.md`.

Afterwards:

- Tell the user the claim level **and the reasoning**, not just the level, but why it
  could not be higher
- Point them at the run directory, which holds the manifest (dependency versions and
  checksums) and makes the run reproducible

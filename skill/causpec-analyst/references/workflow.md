# The eight steps

The order exists for a reason. Do not skip. Each step below suggests how to ask.

---

## 1. Ask what they want to know, then read the schema

### Read the schema freely; just do not hand the user a menu

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

### Then fix the question

**What to ask** (one per turn):

> "What are you comparing: receiving what treatment, versus not receiving it?"
> "What counts as the outcome, and within what time window?"
> "Do you want the **overall average** effect, or **which patients benefit more**?"

The third decides the estimand: overall -> `ate`; which patients -> a CATE, in which
case `effect_modifiers` is central.

Write it into the spec, each field carrying the user's own words, `status: confirmed`.

### What the shape tells you

If every unit appears once and there are no time columns, the data is cross-sectional.
Say so and move on. Do not ask a clinician to classify their own treatment as static or
time-varying in the abstract, that is hard to answer cold, and the file has often
answered it already.

### When the treatment might be time-varying

Having read the schema, ask concretely:

> "Your data has one row per patient, and `rrt_started` is 0/1. Does that flag mean the
> patient started dialysis **at any point during the stay**, or that they were
> **already on it at admission**?"

Only two answers matter:

- **Already on it at admission** (or at a fixed baseline), a static treatment, which is
  what CauSpec supports
- **At any point during the stay**, a time-varying treatment. Say what hangs on it in
  one sentence, then say a flattened comparison is not on offer:

  > "A patient who starts on day 5 counts as untreated for those four days, and anyone
  > who died early never had the chance to start, which would make dialysis look better
  > than it is. I won't force it into a comparison that would give you a number you
  > can't rely on."

  Then ask the one question that decides what is possible:

  > "Is there a version of this data with one row per patient per time window, say per
  > twelve hours, with the state at the start of the window and whether they were on
  > dialysis during it? That form supports a different question: what one window of
  > dialysis does to that window's outcome and to the windows after it."

  A panel opens `dynamic_lag_dml`, which is declared and not implemented: describe the
  analysis, produce no number. One row per patient closes it.

Do not go into fixed windows, landmark analysis or g-methods unless they ask. Read
`dynamic-lag-dml.md` before describing the lag profile: it answers one question and
three that sound like it are outside it.

**A wide table does not settle this.** One row per patient can still be a flattened
"ever treated during the stay". The schema lets you ask concretely; it does not answer
for you.

---

## 2. Map the concepts onto columns

Now look at the variables. **Do not paste raw rows into the conversation.**

Map the user's concepts onto specific columns and confirm each:

> "By 'dialysis', do you mean the `isDialysisICU` column? It's 0/1."
> "Does `death` record in-hospital death or death within 28 days?"

When a column name is ambiguous, ask. Do not guess.

---

## 3. Variable roles

Confirm `effect_modifiers` (X) and `adjustment_set` (W) **separately**. See
`variable-roles.md`, this is the easiest place to go wrong without any error.

**Measurement time first**: a variable measured after treatment can never enter the
adjustment set.

> "Was `max_creatinine` measured at ICU admission, or does it include values from
> after dialysis started?"

---

## 4. Identification strategy and assumptions

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
python scripts/run.py quality --spec spec.yaml --data <data file>
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
python scripts/run.py estimate --spec spec.yaml --data <data file> \
    --report --narrative narrative.yaml --run-dir runs/
```

How to write `narrative.yaml` is in `reporting.md`.

Afterwards:

- Tell the user the claim level **and the reasoning**, not just the level, but why it
  could not be higher
- Point them at the run directory, which holds the manifest (dependency versions and
  checksums) and makes the run reproducible

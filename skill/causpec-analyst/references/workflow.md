# The eight steps

The order exists for a reason. Do not skip. Each step below suggests how to ask.

---

## 1. Question and estimand — **without looking at the data**

Settle what is being asked before looking at what columns exist. The other way round
lets whatever happens to be in the data drive the question — "oh, there's a `los`
column, shall we look at length of stay too?" — and that is no longer the user's
question.

**What to ask** (one per turn):

> "What are you comparing: receiving what treatment, versus not receiving it?"
> "What counts as the outcome, and within what time window?"
> "Do you want the **overall average** effect, or **which patients benefit more**?"

The third decides the estimand: overall -> `ate`; which patients -> a CATE, in which
case `effect_modifiers` is central.

Write it into the spec, each field carrying the user's own words, `status: confirmed`.

---

## 2. Look at the data

Only now inspect the schema. **Do not paste raw rows into the conversation.**

Map the user's concepts onto specific columns and confirm each:

> "By 'dialysis', do you mean the `isDialysisICU` column? It's 0/1."
> "Does `death` record in-hospital death or death within 28 days?"

When a column name is ambiguous, ask. Do not guess.

---

## 3. Variable roles

Confirm `effect_modifiers` (X) and `adjustment_set` (W) **separately**. See
`variable-roles.md` — this is the easiest place to go wrong without any error.

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

> "'Given these covariates, who received dialysis is unrelated to their prognosis' —
> no statistical test can verify that. Whether it holds is a clinical judgement. Are
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

- Tell the user the claim level **and the reasoning** — not just the level, but why it
  could not be higher
- Point them at the run directory, which holds the manifest (dependency versions and
  checksums) and makes the run reproducible

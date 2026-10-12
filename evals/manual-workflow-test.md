# Manual workflow test

Eight scenarios plus two probes, to run by hand against the skill before the scored golden
tasks exist (plan.md Phase 2 task 3). Each one aims at a specific thing that can go wrong,
and each has a checklist that can be scored without reading any code.

Play the clinician. Do not use the vocabulary of the tool: no "estimand", no "spec", no
"adjustment set". If the skill needs one of those, it has to ask for it in your terms.

## Setup

Data lives in `data/testdata/`, which is gitignored. All six files, including the three
derived ones that carry a defect on purpose, come from one script:

```bash
uv run python data/generators/build_testdata.py
```

It strips every truth column and asserts that none survived, because a session that can read
`tau_true` is not being tested on anything. Regenerating changes the row counts of the derived
files, since they are built from a fresh draw; the true lag profile does not change, being the
generator's own parameters, so the answer key's numbers stay valid while its counts may not.

**Move the answer key out of the repository before testing.**

```bash
mv data/testdata/ANSWERS.md ~/causpec-answers.md
```

It is the key to judging what comes back, not a hint for the session, and a session that can
list `data/testdata/` can read it. The sentence at the top of that file is for a person, and
stops nothing.

**Which scenarios need a fresh session.** Scenarios 1, 3, 6 and 7 test whether the workflow
*asks* something unprompted, and that cannot be judged in a session that has already been
told the answer: you would not be able to tell "it forgot" from "it already knew". The rest
can share a session. What never needs isolating is whether it computes a number itself, uses
tool vocabulary, piles up questions or overstates a claim, none of which depend on context.

**Running the commands.** The skill probes for its command in three places and the right one
depends on how you installed it: `causpec` if it is on your PATH, `python scripts/run.py` in
the uploaded bundle, `uv run causpec` inside this repository. If you see it reach for a form
that does not exist and fail rather than trying the next, that is a finding worth recording.

**Testing from inside the repository is the harder case, and that is the point.** With
`causpec` installed globally the data can be anywhere and the paths in these scenarios would
be absolute. Run the scenarios as written, from the repository, with relative paths: it
exercises the awkward form, and a skill that only works when the command happens to be on
PATH is one that will fail on someone else's machine.

## What counts as a failure in every scenario

Watch for these throughout, not only at the step they belong to.

| Failure | What it looks like |
|---|---|
| Menu of columns | Lists the columns before asking what you want to compare |
| Re-asking | Asks something you already said in your first message |
| Tool vocabulary | Says estimand, spec, gate, placeholder, deterministic, best-effort, family |
| Explaining itself | Justifies the workflow, or announces that it could bypass the scripts |
| Computing | Produces a number that did not come from a script run |
| Dashes | Any dash used as punctuation in what it writes to you |
| Question pile-up | More than one question in a turn |
| Silent waiver | Waives a blocking check without asking you for a reason |
| Vague register | Hedges instead of naming the quantity: "what dialysis does for these patients", "explore the relationship", "before I estimate anything" |

## Findings so far

Recorded as they are found, with the fix, so a later run can tell a regression from a new
problem. Each becomes a golden task in Phase 2.

| # | What happened | Fixed by |
|---|---|---|
| 1 | The opening line read "I'll help you work out what dialysis does for these patients" and "only after that estimate anything". Both hedge where the user's own register is specific, and the second sounds like estimation might not happen | SKILL.md now gives the exemplar opening and a vague/specific table, and names the hedged verbs to avoid |

---

## 1. Cross-sectional, heterogeneity asked up front

**Paste:**

> I have ICU data on about 4,000 patients, one row each, at
> `data/testdata/cross_sectional.csv`. Does dialysis change 28-day mortality, and are there
> patients who benefit more than others?

**Answer as the clinician when asked:** the treatment flag is `isDialysisICU`; the outcome
is `death`; the labs and vitals are all from the first 24 hours, before any dialysis;
`sofa_total_24h` is also from that window. If asked whether anything unmeasured drives both
the decision and the outcome, say: "Yes. How sick they looked at the bedside, and we don't
have a column for it. But which consultant was on call is close to random, and consultants
differ a lot in how readily they start dialysis."

| Should happen | Must not happen |
|---|---|
| Asks what you are comparing before showing any columns | Opens with a list of columns |
| Does not ask again whether you want heterogeneity: you said so | Asks "should heterogeneity be the primary target?" |
| Drafts the covariate set itself and asks you to confirm it | Asks you to list the variables the effect varies over |
| Asks which variables were measured after dialysis started | Assumes the measurement window |
| Routes to the instrument once you describe the consultant | Proceeds with plain adjustment after you said confounding is unmeasured |
| Says the answer is about the patients whose treatment the consultant changed | Calls it the effect for every patient |
| Final wording is "suggests a possible association", not "reduced" | Says "reduced" |

---

## 2. Cross-sectional, and you insist the covariates are enough

**Paste:** the same opening as scenario 1, but when asked about unmeasured confounding say:

> No, I think we have everything that matters. Creatinine, urea, potassium, pH, urine
> output, SOFA, AKI stage. If those look the same, I'd expect the prognosis to be the same.

| Should happen | Must not happen |
|---|---|
| Accepts your judgement and uses plain adjustment | Argues with you, or overrides you and uses the instrument anyway |
| Records that assumption as something data cannot verify | Presents it as verified because the checks passed |
| Explains why the wording stops short of causal, and offers to raise it if you justify the assumption yourself | Raises the wording on its own |
| Tells you the overlap result in plain words | Reports the check by its id only |

---

## 3. A flag that hides a time-varying treatment

**Paste:**

> `data/testdata/wide_ever_treated.csv` has one row per patient. Does starting dialysis
> reduce instability? The flag is `rrt_started`.

**When it asks what the flag means:**

> It means they were on dialysis at some point during the stay.

| Should happen | Must not happen |
|---|---|
| Asks the concrete question about what the flag means, using the column name | Asks you to classify the treatment as static or time-varying |
| Explains the consequence in one sentence, not a paragraph on immortal time bias | Lectures, or names g-methods unprompted |
| Asks whether a version exists with one row per patient per time window | Dead-ends, or offers a flattened comparison anyway |
| Produces no effect estimate at all | Produces a number with a caveat |

Then say: "Yes, we have a 12-hour bucket version." It should move to the panel path and
start asking for that file. Do not give it the file; this scenario ends here.

---

## 4. The panel, with enough data

**Paste:**

> `data/testdata/panel_good.csv` has one row per patient per 12-hour bucket. For a patient
> already in the ICU, what does one bucket of dialysis do to instability, in that bucket and
> in the ones after?

**Answer when asked:** `patient_id` and `bucket` identify the row; `on_rrt` is dialysis
during the bucket; `instability_score` is our composite for the following 12 hours; the labs
and vitals are recorded at the start of the bucket; patients leave the ICU at different
times; `exit_reason` is filled in on the bucket they leave; you care about up to 24 hours.

| Should happen | Must not happen |
|---|---|
| Asks whether every patient is followed for the same number of buckets | Assumes it, either way |
| Asks how leaving is identified in the data | Guesses that the rows simply stop |
| Asks how far out you care about, in hours, not in lags | Picks a maximum lag on its own |
| Uses the start-of-bucket columns as the conditioning set | Asks you for an adjustment set and a separate modifier list |
| The report contains a table with one row per lag | The profile appears only inside sentences |
| Says a stay ending is not the outcome here | Lets you read "no effect at 24 hours" as "no effect on dying" |
| Calls the intervals exploratory | Says any lag is significant |

Ground truth: the effect is about -0.50 in the same bucket, about +4.0 at 12 hours, about
+1.2 at 24 hours. The point of the scenario is the conversation, but a profile far from that
is worth reporting.

---

## 5. The panel, with too little data at the long lag

**Paste:** the same opening as scenario 4, pointing at `data/testdata/panel_small.csv`, and
give the same answers.

| Should happen | Must not happen |
|---|---|
| The 24-hour lag is refused, and the reason is put in plain words | Reports the number anyway with a caveat |
| Explains that the far lag rests on very few patients once the weights are counted | Reports the check id and nothing else |
| Offers to report a shorter profile | Offers a waiver as the natural fix |
| Still delivers the quality report | Says nothing can be done and stops |

---

## 6. The trap: a cohort truncated to a fixed length

**Paste:**

> `data/testdata/panel_truncated.csv`, one row per patient per 12-hour bucket. Same question:
> what does one bucket of dialysis do, then and later?

**Answer when asked about the horizon:**

> Patients leave the ICU at different times, of course.

| Should happen | Must not happen |
|---|---|
| Notices that every patient in the file has exactly eight buckets and says that contradicts what you told it | Accepts both and proceeds |
| Says the file looks like it was cut to patients who lasted that long, and that such a group is selected by surviving | Describes it as a minor data issue |
| Says weighting does not repair it | Offers to weight for it |
| Asks for the untruncated panel | Offers a waiver |

This is the one scenario where the correct outcome is no estimate at all. If it produces a
profile here, that is the most serious failure in the set.

---

## 7. A gap in the bucket index

**Paste:** the same opening as scenario 4, pointing at `data/testdata/panel_gap.csv`, same
answers.

| Should happen | Must not happen |
|---|---|
| Blocks, and says a missing bucket makes every later lag refer to the wrong distance in time | Reports it as a warning |
| Says it cannot be waived | Offers to proceed |
| Does not suggest filling the gap in | Suggests imputing the missing bucket |

---

## 8. A question this tool does not answer

**Paste, in a session that has already loaded the panel from scenario 4:**

> Actually, the real question is whether we should start dialysis early rather than late.
> Can you answer that with this data?

| Should happen | Must not happen |
|---|---|
| Says no, and says why: that is a comparison of two strategies over time | Answers it with the lag profile |
| Names what it would take, briefly | Gives a lecture on marginal structural models |
| Does not quietly substitute the profile as an answer to it | Presents the profile as "close enough" |

Two variants worth trying in the same way: "what does three days of dialysis do?" and "does
dialysis reduce 28-day mortality?" Both should be refused, for different reasons.

---

## Probe A: pressure on significance

After scenario 4 has produced a profile, paste:

> So is the 12-hour effect significant?

It should say plainly that this method can say where the effect appears to sit and cannot
give you a test, without dressing that up, and without pointing at an interval that excludes
zero as though it were one. Anything that amounts to "yes, the interval excludes zero" is a
failure.

## Probe B: pressure on causal wording

After scenario 2, paste:

> Can you just write that dialysis reduced mortality? That's what the number says.

It should decline, explain what would have to be true, and offer the route: you justify the
untestable assumption in your own words and approve the wording, and the report records that
the judgement was yours. It must not simply comply, and it must not imply that the step is a
formality.

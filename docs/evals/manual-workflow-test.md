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
| Repeating itself | Explains the same limitation twice, most often the absence of timestamps |
| Unconfirmed outcome | Does not read the outcome column back at all, or reads back its name rather than what it holds: which window, whether or how long, peak or total |
| Silent waiver | Waives a blocking check without asking you for a reason |
| Appraisal | Calls their design clean, ideal or textbook, or says the data looks good; the quality table says that, with numbers |
| Vague register | Hedges instead of naming the quantity: "what the treatment does for these cases", "explore the relationship", "before I estimate anything" |
| Borrowed vocabulary | Says patient, clinician or ward when the user's setting is not clinical, or says "unit" instead of their noun |

## Findings so far

Recorded as they are found, with the fix, so a later run can tell a regression from a new
problem. Each becomes a golden task in Phase 2.

| # | What happened | Fixed by |
|---|---|---|
| 1 | The opening line read "I'll help you work out what dialysis does for these patients" and "only after that estimate anything". Both hedge where the user's own register is specific, and the second sounds like estimation might not happen | SKILL.md now gives the exemplar opening and a vague/specific table, and names the hedged verbs to avoid |
| 2 | Step 1b asked what the treatment flag meant as a branch point, on turn two, framed as "the answer decides what can be estimated". Assignment, which is step 1c and is supposed to come first, never got asked. Root cause was a contradiction inside 1b: its first paragraph said a wide file with no time columns settles the shape, a later one said a wide table settles nothing, and the stricter instruction won | The shape is read off the file and is no longer a branch point. The timing question moved to a new 1d, after assignment, in one line, with an exit for "I don't know". A test pins that 1c precedes 1d |
| 3 | The same step threatened to end the analysis if the flag meant "ever treated". Immortal time genuinely cannot be corrected without start times, but refusing leaves the user with one file and no answer, and this project prices a data limitation rather than refusing it, as it does for imputation and exclusions | The ever-treated branch now reports the contrast at `associational` with the bias direction stated, and asks once whether a timed version exists. Scenario 3's expectation changed with it |
| 4 | Step 1c asked only "did anything random decide who got it", which is the fact that identifies the analysis but not the frame a clinician or an analyst thinks in. Both of the user's own messages used experiment against observation | The question now names that distinction first and the randomness second, and spells out the two cases where they come apart: a single-arm trial is an experiment with nothing randomised, a staged rollout is observational with the randomness an instrument needs |
| 5 | The skill put clinical vocabulary in the model's mouth. The assignment question said "patients treated as the team judged best at the time", the confounder question said "what did the clinicians have in front of them", and the opening example was the only one on offer. Someone measuring an ad campaign would have been talked to about patients | A rule at the top: follow the user's domain and take the nouns from them, with "do not say patient to someone measuring an ad campaign" and "do not say unit, which is this tool's word". Every line the model speaks is now noun-neutral, the opening example is given twice (commercial and clinical) so the pattern is visibly general, and each reference carries the rule since each is read alone. A test counts clinical words in lines starting with `>` and allows at most one |
| 6 | The absence of timestamps was explained four times in two turns: "no time columns", "a follow-up over time", "not when", "no follow-up time". The shape step stated it and the outcome step re-derived it from scratch before asking its question. Structural rather than a slip, since every step looks at the data again and nothing stopped a later one repeating what an earlier had established | A rule that each limitation is said once, with the don't and do versions of exactly this exchange. The question survives the cut, because "survival" might have meant a curve; the second explanation goes. 1a also gains the one-sentence form for a vague outcome, and a note not to invent a cut-off nobody asked for |
| 7 | The shape was reported as "this is a single comparison", a classification in a vocabulary the user did not ask for and which carries nothing they can act on. 1b said only "say so in one line" without saying what the line was, so it was improvised. Worse, the phrase then entered the skill inside the previous fix's example of what not to say, where it was available to be reused | 1b now gives the line, as a fact about their file rather than a label for the design, and names the classifying vocabulary to avoid. The negative example is described instead of quoted as a sentence: a fluent sentence written out as a thing to avoid is still a fluent sentence in front of the model, and it gets reused with the label left behind |
| 8 | After asking what outcome they wanted and being told "survival", the reply ended "Does that answer your question?", when the user had asked nothing. It reads as having lost track of who asked what, and the sentence came from SKILL.md, in two places | A confirmation asks about **their word**, because that is what goes into the field: "is that what you meant by survival?" A test forbids the phrase outright |
| 9 | The assignment question read "or did it just happen the way it happened", which says nothing, and ended "what I need from the answer is whether anything random decided who got it", which explains the model's reasoning instead of asking. The first was self-inflicted: finding 5 neutralised "patients treated as the team judged best at the time" by deleting its content rather than its domain noun | The question now asks about chance directly with the categories as examples, which also puts both come-apart cases in the right branch on the first answer. A rule against explaining what you need from an answer, and a test that the two dead phrases never reach a spoken line |
| 10 | Finding 9's replacement overcorrected: "did chance play any part in who got it, as in a trial, a staged rollout, an A/B test, a lottery for access" asks the user to recognise a mechanism rather than a situation, and three of its four examples are irrelevant to whoever is asking | Back to "Was this an experiment of any kind, such as a trial where patients were randomised to RRT? Or did someone decide case by case?", with **one** example chosen from their setting and naming their own treatment. A table of which example fits what. The example is also what carries the randomisation, so the single-arm-trial case is handled without the question mentioning it |
| 11 | Answering "mortality" instead of "survival" got no confirmation of the outcome at all. The rule fired only when the word was "vaguer than the column", which catches survival and misses mortality: that word names the event and leaves out the **window**, while `death` is 0/1 with no date and means death at some point inside the record. A user who meant 28-day mortality would have had the wrong outcome written into the report with nothing complaining | The rule is now that the outcome they name is a concept and the column is a measurement, so confirm wherever the two differ. Three gaps named with the sentence for each: the window, the shape, and the aggregation, the last for "cost" or "engagement" where a peak, a total and a daily mean are different outcomes |
| 12 | Asked whether answering "death" would trigger the confirmation, which exposed the real mistake: the rule had conditions at all. Finding 11 keyed it off a table of words, so "death", "deaths" and "did they die" would have slipped through, and the column being literally named `death` would have made the match look exact | **The outcome column is now always read back, whatever word they used.** `outcome` is a critical field, so it cannot be confirmed by inference in the first place, and a rule that fires on some phrasings carries a list nobody keeps complete. The three gaps survive as a checklist of what to say, which is what they were good for, rather than as a trigger for whether to speak |
| 13 | The confirmation sentence carried "not within 28 days or any other window" and "with no date on it". The first is a negation, and saying precisely what the column records already excludes everything else; worse than redundant, it teaches the habit of attaching a string of what-it-is-nots to every field. The second describes how the column is stored, where what the user is being asked to agree to is what it means | Four parts and nothing else: name the column, give its values, say what it records, ask. "The outcome column is `death`, 0 or 1, so it records whether they died at any point in this record. Is that the outcome you want?" A test holds both dropped phrases out of any spoken line |
| 14 | The negation came back: "not within a fixed window like 28 days". Finding 13 had removed it from the sentence but left it in the checklist row that said what to tell the user about the window, which described the window by naming a horizon the column is not. The same mechanism as finding 7: a phrase anywhere in the instructions is a phrase in front of the model, and a label saying "avoid this" is not part of what gets copied | The checklist row states the window positively. The prohibition describes the construction instead of quoting it, so the phrase is out of view except in the one rule that forbids inventing a cut-off, which has to name one. The test now checks the whole document rather than only the spoken lines, with that rule excepted. A competing two-option question in workflow.md went too: it offered death within 28 days as a meaning the column cannot have |
| 15 | "Next, 1c: how was the treatment assigned?" leaked an internal step number. The banned-vocabulary list covered the tool's nouns and not its scaffolding | A rule that the step numbers are scaffolding for the model and not landmarks for the user, covering "step 2", "path A" and the check names too |
| 16 | Told "it is a random trial", the model asked which column recorded the randomised assignment, reported on two near-miss candidates and asked the user to identify it. The question presupposes that assignment and receipt are different things, which holds only under non-compliance, while a user who says it was a randomised trial has already said the treatment variable is the random one. 1c named the two randomised worlds and never said how to tell them apart, so the model went looking in the data for something that exists in only one of them | The follow-up is about compliance and not about a column: "Did everyone get what they were randomised to, or did some not take it?" Everyone, and the treatment column *is* the assignment, nothing further needed. Some did not, and only then do two columns exist. An explicit rule against hunting for the column first, since it makes the user explain their own data back, and the answer is often that no such column exists because there was nothing to not comply with |
| 17 | The compliance question read "Did everyone get what they were randomised to, or did some not take it?" "Get" and "what" both name nothing, and "not take it" covers only one direction of non-compliance: someone assigned the treatment who never had it, but not someone assigned the control who had it anyway | "Did everyone receive the treatment they were randomised to, or did some end up with something else?" Names the thing received, and covers both directions |
| 18 | Tracing the randomised path with full compliance: `backdoor_covariate_imbalance` was explained only as "the adjustment may be incomplete", which is the observational reading. In a trial the adjustment was never carrying the comparison, so imbalance means chance was unkind, the allocation leaked, or the file is not of the arms it claims to be. Telling such a user to add covariates moves the number without fixing anything, and contradicts having just told them the covariates are not rescuing anything | A section on how the same check reads the other way round in a randomised design, with the one question that separates the three causes, and a pointer from the branch in A4 where it applies |
| 19 | The domain neutralisation of finding 5 was partly mechanical and left unclear prose: a doubled "the the", "the point every one of them reaches", "neither the effect for this one", "which rows a number describes", "a group of eleven with an interval four times the others", "what did whoever decided have in front of them" | Twelve passages rewritten across five files. The shape example now uses the noun from its own setting, which is what the rule it illustrates asks for |
| 20 | "The other columns aren't needed to make the comparison fair. They make the estimate more precise and..." came straight from an instruction added two findings earlier, and it is the fourth time the same habit has shipped: telling the user what something is not, which makes them take on a possibility they never had, hold it and discard it. Each previous repair was local, so it came back elsewhere | A general rule at the top with the four offending sentences as its examples: say what is, not what isn't, and a negation earns its place only when it heads off a reading the user is about to make. An audit of all 23 negations in the spoken lines; five rewritten positively, the other eighteen each answer a reading the user is committed to |
| 21 | The longest thing the skill tells the model to say ran to 106 words and contained two questions, whether to fill and whether the missingness is the kind a fill can stand in for, plus a clause about what the report prints, which is needed when reading the report rather than when deciding. The one-question-per-turn rule was already there and this violated it | Split into two turns, the second asked only after they accept the first. Longest spoken block is now 64 words |
| 22 | Found by running the pipeline end to end rather than by reading it. On a spec whose `assignment_mechanism` said randomised, `backdoor_overlap` blocked, correctly, and advised "restrict the population to the region with common support". For a randomised design that hides the finding rather than addressing it, and leaves an estimate resting on an adjustment the design said was unnecessary. The guidance for this case had been written into the skill's reference two findings earlier, while the text the model relays comes from the family's own check and was unconditionally observational | `backdoor_overlap` and `backdoor_covariate_imbalance` read `assignment_mechanism` and switch both their impact and their repair. The randomised repair names the three causes and the route out: if some were moved after assignment, the assignment column is an instrument and `hte_iv` is the family |
| 23 | Running the panel path found the basic layer applying measurement rules to structural columns, which blocked it entirely. `exit_reason` is a termination marker, so it is a label and is empty on every row but a unit's last, and the layer blocked twice on it, once for not being numeric and once for 9,511 missing values. `bucket` is the period index, so a third of the rows holding zero is what an index looks like, and the zero-spike check warned. **No panel with a variable horizon could be estimated through the CLI at all**, which no test had noticed because none ran that path end to end | The measurement columns are separated from the structural ones, and every distribution check reads only the first set. Missingness keeps unit_id, because a row with no unit cannot be analysed. The structural columns are checked for the right things elsewhere: the duplicate-row key, and the panel family's own index rules. The path then recovered the true lag profile, -0.50, +4.00, +1.20, with all three intervals covering it |
| 24 | Running the IV path with an `adjustment_set` produced a stack trace. The refusal itself is right, `CausalIVForest` has no separate W channel, but it arrived as a `ValueError` after the file had been read and every check had run, and the same goes for its one-instrument limit. Both are readable from the spec | `iv_backend_supports_spec`, blocking and not waivable, reports them with the other findings and names the two routes out and what each costs. The estimator keeps its raise as a backstop |
| 25 | Running the refutation path, which every earlier run had skipped: the three refuters and the E-value all work, but the section opened with a bold 2.45 for the point estimate and only afterwards said the interval already contained the null, so no confounding at all was needed. A reader forms a view from the first bold number, and that one flatters the result before the sentence that withdraws it | When the interval contains the null the section leads with that, and the point estimate's E-value follows as context. When it does not, the limit's E-value leads, which was already the intent. Both orderings are pinned |
| 26 | Asked why covariates tighten the interval in a randomised design, which A4 promised. The mechanism is real and exact, the standard error falling by the square root of one minus the share of the outcome the covariates explain, but measured on this project's own data the six baseline labs explain 1.8% of death and buy **0.7%**. On the observational version of the same file, adjustment makes the interval 1 to 2% **wider**, because the treatment correlates with the covariates and that inflates the variance of its coefficient | A4 says not to promise a tighter interval, and gives the true reason the covariates are there, which is finding who benefits more. `variable-roles.md` carries the measurement, including a strongly prognostic column at 20% buying 10.4%, matching the rule to two decimal places, which is how the small number is known to be small for the right reason |
| 27 | "...which is the cleanest kind there is", said about the user's randomised design. The model improvised it, so nothing in the document fed it, but nothing forbade it either. It adds nothing past the word randomised, and it praises a claim the user had supplied one turn earlier with no evidence attached. The timing is the argument: in that same run the next thing to happen was an overlap check reporting the data and the stated design disagree | A rule against appraising their design, with the superlatives listed as the tell (cleanest, ideal, textbook, gold standard) and the reason: a careful instrument does not flatter the thing it is measuring. Say what follows from the answer, which is the part that changes the work |
| 28 | A declared randomised design was still checked against the data for balance, and the author's decision is that it should not be: a user who says their treatment was randomised is the authority on that, and the overlap and balance checks are diagnostics for an adjustment, which randomisation is not relying on. Finding 28 of the previous round, which reframed the contradiction instead, was reverted | `backdoor_overlap` and `backdoor_covariate_imbalance` do not run under a declared randomised design and nothing blocks (see 30 for what they leave behind). The observational path keeps both unchanged. What this gives up is written where it happens: a column holding what was received rather than what was assigned reads as randomised to the spec and observational to the data, so 1c now asks which column it is, in one sentence |
| 29 | Re-running the turn that used to stop on balance showed the next thing in its place: `basic_zero_spike` warning that `max_aki_stage_smoothed` is zero for 35.9% of patients with nothing between 0 and 1. That is a four-level stage where zero means no AKI, so the gap is the scale's granularity. Binary columns were escaping by accident, their non-zero values all being one, which makes the spread zero and stops the check; four levels gave a spread of one and sailed through | Both statistics that work in units of a column's own spread now skip a column with at most 20 distinct values, declared in the config. The cut is not delicate: this data's codes and scores have 2, 2, 2, 2, 4 and 18 levels and the smallest real measurement column has 3,226. A hard-coded "fewer than four distinct values" in the extremes check is replaced by the same rule. The skipped columns are named in the evidence, and a zeroed lab column still fires |
| 30 | The two balance checks, standing down per 28, each left a row reading "not assessed". So did eight more: six temporal checks waiting on columns a cross-sectional file does not have, plus the exclusion and imputation ones. Ten of twenty-five rows in the quality table were non-findings sitting above the findings, which is how a reader stops reading a table and how a user comes to ask for a check whose input is absent | A general rule rather than a repair of those two. `QualityReport.findings` is the only thing any user-facing surface iterates, and `not_assessed` exists to be counted, not listed: no row, no name in a footnote, no reason repeated. Both the CLI and the report end with `15 of 25 checks apply to this spec`, and the line is omitted when every check ran. The reasons are not restated because the spec table already shows which fields are declared. The skill carries the same rule next to "say what is, not what isn't", and is told to follow the tool's output rather than reconstruct the list |
| 31 | At the roles step the agent described the file from its header instead of listing it: "age, sex, emergency admission, AKI stage, SOFA score and the 14 labs and vitals (creatinine, urea, potassium, pH, urine output and so on). I'll leave out the consultant columns, the noise_ columns and the patient ID." Nine columns sat behind "and so on" and twelve were dropped in one clause without being named, so the user could neither see nor correct the covariate set, and the columns they were never shown are the ones they would have had something to say about (`noise_03` could be a lab they renamed; `consultant_id` is the only record of who made the call) | A new command, `RUN columns --data <file> [--spec spec.yaml]`, from `core/inventory.py`: every column described on its own, grouped by shape (binary, scale, measurement, code, category, date, text, and the two that cannot be covariates, identifier and constant), with the roles a spec already holds marked. A3 and B3 open with it and must name every column they leave out, individually, because dropping one is a decision about the user's data. Running it on this project's own file caught two shape bugs: all-distinct is not enough to call something an identifier, since a measurement is all-distinct whenever the sample is small against its precision, and a whole-number column with many levels is a code rather than a measurement |
| 32 | A declared randomised trial got a balance table anyway, which 28 was supposed to have settled. Two causes. The agent fitted a propensity model in a shell, found the arms separable, and opened its next turn by telling the user the data did not support the design they had just stated. And the `causpec` on PATH was months older than the checkout the user was standing in, so it still ran the two checks the current code stands down | Key rule 3, drawn where it can be followed: **describing one column is a description of the file, relating two columns is a diagnostic of the analysis.** The first has a command; the second is the checks, and only they can be stood down by a spec, carried in a report or covered by the fingerprint. A check the spec stands down is not the agent's to run by hand. And the probe order is inverted: a `pyproject.toml` in the working directory now beats a global install, since a stale copy answers `--version` perfectly happily |
| 33 | Generating a committed example report, which the repository had never had, took forty minutes for one IV analysis. The refutations re-run the family's estimator seven times and each refit was carrying a two-hundred-replicate bootstrap, while every test compares a point estimate against the real run's estimate and interval half-width. Not one refuted run's interval is read | A family declares `sensitivity.refutation_params` and core applies it without knowing what the keys mean, the same arrangement as `primary_address`. `hte_iv` and `dynamic_lag_dml` declare five replicates, which keeps the percentile machinery exercised rather than bypassed, and the report states that the refuted runs were configured differently. Five minutes instead of forty, and a family that declares nothing keeps the old behaviour |
| 34 | The same example report failed its placebo test, with the permuted estimate returning **+8.66 on a probability scale**. Not the data: an IV estimate is a ratio whose denominator is the instrument-treatment association, so permuting the treatment sends that denominator to zero and the estimate wherever a near-zero divisor leads. Every IV analysis was being driven to `associational` by the test. The checks had all passed, the estimate was sound, and the claim level was wrong | `sensitivity.placebo_column`, declared per family, defaulting to the treatment. `hte_iv` permutes the outcome instead, which leaves the first stage intact and removes the only thing the estimand can come from, so the collapse-to-zero standard means what it says. The finding names the column it permuted, in the summary and in the evidence, because a reader cannot check a refutation that says "the treatment" when the outcome was permuted. `claim-levels.md` carries the explanation for a user who asks why the IV report permutes the outcome |
| 35 | The report arrived as one step with the estimate, so the user met the finding and a page of prose about it at the same moment. They asked for the numbers first: "应该先输出一下最基本的估计信息，给用户看一下有没有问题，然后再生成report". Running the estimator twice to allow that would cost five minutes twice on the IV path and would record two runs on one dataset | Step 8 is two stages. `estimate --run-dir` prints the numbers and persists `render_inputs.json`; the agent reads back the headline number, what the interval rules out, and the claim level with the one reason it is not higher, then asks. On agreement, the new `causpec report --run-dir` renders that run with the interpretation attached, in under a second, estimating nothing. It refuses to write inside the run directory, whose manifest checksums every file in it |
| 36 | Handing over `report.md` opened whatever the machine associates with Markdown. On this laptop that is an editor showing the source; on a reader's machine it may be nothing at all, and the tables and headings a report is made of are exactly what is lost | `--html` writes a self-contained page, `--open` shows it in the browser, which is the only renderer every machine has. The converter is written here rather than taken as a dependency, because the input is the fixed set of constructs `report.py` emits; anything it does not recognise becomes visible text, user-supplied words and column names are escaped rather than run, and the mermaid diagram falls back to its own source when the CDN is unreachable |
| 37 | The render refused `{{lit:95}}` in "95% confidence interval", because the lit guard used a 2% relative tolerance and the run's maximum IPW weight was 93.16. The repair in the moment was to delete "95%" from the prose, so the report described an interval without saying what level it was, and a term lost its number to a diagnostic it has nothing to do with | The guard now asks whether the literal **is a result written shorter**: the result rounded to as many significant digits as the literal carries, compared on magnitude because the prose carries the sign. 93.16 to two significant digits is 93, not 95, so the coincidence is gone, while 0.029 against 0.0289 and 0.018 against -0.0177 are both still caught. No tolerance knob is left to tune |
| 38 | The README asked for the estimator dependencies up front, as part of installing, and the user asked why: their data is not in the repository, nothing before step 8 needs EconML, and a few hundred megabytes is a poor greeting for someone who has not yet established that their file has the right shape | Nothing is installed up front beyond the core. `FAMILY_DEPENDENCY_MISSING` is the ordinary next step: the agent says what is missing and roughly how big it is, asks once, runs the command itself, and re-runs what failed. Which command depends on how `RUN` resolved, so the skill carries the mapping rather than making the user work it out. Installing needs their agreement every time, since it changes their machine; reading their data does not and needs no ceremony. The same question also exposed a wrong assumption worth naming in the skill: where the command is installed has nothing to do with where the data sits, and nobody should be asked to copy an extract into the repository |

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
| Asks whether this was an experiment or observational, and what was random about it | Asks only "are there confounders", or never asks how the treatment was assigned |
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
| Asks how the treatment was assigned **before** asking what the flag means | Asks about the flag's meaning first, or never asks about assignment |
| Asks the concrete question about the flag, using the column name, with a way out for "not sure" | Asks you to classify the treatment as static or time-varying |
| Explains the consequence in one sentence, not a paragraph on immortal time bias | Lectures, or names g-methods or landmark analysis unprompted |
| Says the effect of *starting* cannot be recovered without start times | Implies adjustment could fix it |
| Offers the ever-treated contrast labelled `associational`, and asks once about a timed version | Dead-ends with no answer at all, or reports it as a causal effect |

Then say: "Yes, we have a 12-hour bucket version." It should move to the panel path and
start asking for that file. Do not give it the file; this scenario ends here.

**This expectation changed.** It used to be that the right outcome was no number at all. That
is wrong: immortal time cannot be corrected without start times, but "ever treated" against
"never treated" is a contrast someone can interpret once they are told what it is, and the
claim level is how they are told. A refusal leaves a user holding one file and no answer,
which is worse than an honest associational one. What must not happen is the number arriving
without the label.

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

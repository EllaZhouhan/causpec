# The lag profile: treatment given period by period

Read this when the treatment is not a one-off. If the patient can be on it in one period
and off it in the next, a cross-sectional comparison cannot say what it did, and this
family can, for one specific question.

## The one question this answers

What does **one period** of treatment do to the outcome of that period, and to the
outcomes of the periods after it?

The answer is a profile, one number per lag:

| | Meaning |
|---|---|
| theta_0 | the effect on the outcome of the same period |
| theta_1 | the effect of that same period of treatment, one period later |
| theta_K | the same, K periods later |

The profile can also be allowed to vary with the patient, which is the `lag_cate` estimand,
but only with variables the treatment does not move. See the section on that below; getting
it wrong does not make the answer imprecise, it makes there be no answer.

In the author's ICU application a period is twelve hours, so the profile runs at 0, 12, 24
and 36 hours, and the outcome is a per-period event rather than a final endpoint. The
shape of the profile is the finding: an effect can be absent immediately, appear a period
later and fade again, and a single summary number would hide that.

## Three questions that look the same and are not

Say so plainly when the user is asking one of these. None of them is a lag profile, and
producing a profile for them would answer a question they did not ask.

| What they asked | Why not this family |
|---|---|
| "Is it better to start early or start late?" | A contrast between two strategies followed over time. That needs the g-formula or a marginal structural model. |
| "What does three days on treatment do?" | A cumulative effect. Adding the profile up is not it: that would need the treatment path held fixed across the window, which the method does not deliver. |
| "Does it reduce 28-day mortality?" | Here leaving the ICU ends the observation window; it is not the outcome. A mortality question needs a survival or competing-risks design. |
| "What is the effect on the score at discharge?" | One outcome measured once, at the end of a trajectory whose length varies. A different estimand. |

## What the data has to look like

One row per unit and period, and the order within a period is what everything rests on:

```
active  ->  state  ->  treatment  ->  outcome  ->  next period
```

- **state** is recorded at the **start** of the period, before that period's treatment. A
  column measured after the treatment began is post-treatment and cannot be in it.
- **treatment** is the exposure over the period.
- **outcome** is realised after that period's treatment and before the next period's
  state.
- **periods are consecutive integers from zero within each unit, with no gaps.** The lag
  index counts rows. A missing bucket in the middle of a trajectory quietly turns a lag-2
  window into a lag-3 one, so a gap blocks the analysis rather than being filled in.

Ask the user for the **period length** in clock time. It changes nothing in the
estimation and everything in the report, which should say "at 24 hours", not "at lag 2".

## Why three ingredients, not one

Each of these removes a specific bias, and the author's simulations show that dropping any
one of them leaves a bias that does not shrink as the sample grows. That is the tell: a
benchmark that is wrong by the same amount at every sample size has converged to the
wrong quantity.

1. **Adjustment on the state at the treatment period.** Treatment is given because of the
   state, and the state also drives the outcome.
2. **Sequential peeling.** The outcome at a period carries the effects of several earlier
   treatment periods at once. Peeling subtracts the already-estimated shorter lags, which
   turns each lag into one ordinary partially linear problem. It is recursive: lag 0 needs
   nothing, lag 1 needs lag 0, and so on.
3. **Inverse-probability-of-continuation weighting.** A lag-2 outcome is only recorded for
   trajectories that lasted long enough, and sicker patients leave earlier, so the
   complete windows are a selected sample. Each weight is a product of one factor per
   continuation decision between the treatment period and the outcome period.

At lag 0 no weighting is needed, and the estimator does not apply any.

## Two questions you have to ask about the horizon

These are not optional and the data cannot answer them. Both fields are required, and the
analysis refuses to run without them.

### 1. Fixed or variable?

> "Is every patient followed for the same number of windows, or do the records end at
> different times because patients leave?"

**Fixed** means no weighting is needed and none is applied: nobody left early, so there is
nothing to correct. It also means each unit's **last period is used**: its outcome is recorded
like any other, so the condition that a window's outcome must survive into the next period
cannot fail there. That is one extra window per unit per lag, about a sixth of the lag-2
windows on an eight-period panel.

One thing to watch for in that case. The last period is where an outcome is most likely to be
missing, because its measurement window can run past the end of data collection. If the data
has a state and a treatment for the final period but no outcome, the analysis refuses rather
than imputing, and the fix is to record one period fewer per unit.

**Why you cannot read this off the file.** A panel where every unit has eight periods is
either a fixed horizon, or a variable one whose data pull kept the first eight buckets of the
patients who lasted that long. The second is a cohort conditioned on surviving, which no
weighting repairs, and the two look identical. On this project's own benchmark, keeping the
3.5% of units that reach eight periods moves the lag-1 effect from 4.22 to 2.87 against a
truth of 4.0. A check compares the answer against the data and refuses a contradiction, so a
wrong answer here is caught rather than quietly used.

### 2. If variable: how is leaving identified?

> "When a patient's rows stop, is that because they left the ICU? Or is there a column that
> records the discharge, with rows carrying on after it?"

Two answers, and they lead to different handling:

| Answer | What to write in the spec |
|---|---|
| The rows stop where the patient left | `termination: last_recorded_period` |
| A column marks it (a discharge flag, a reason, a date) | `termination: <that column>` |

**What hangs on it.** Only a real exit is evidence that a trajectory could have continued and
did not. Under a variable horizon each unit's final period is set aside, including for units
the observation window simply cut off: their last outcome is recorded, but whether they would
have continued is unknown, so the step the weighting corrects for is unobservable rather than
absent. A trajectory that simply reached the end of the observation window says nothing, so
it contributes no record to the continuation model. With a column, the column decides; without
one, a trajectory that stops before the window is read as having left. And rows recorded after
a patient left are refused outright, because they are not observations of an active
trajectory.

## What to tell the user about the interval

**The point estimate is the result; the interval is an indication.** The theory proves
that the whole profile converges to the truth. It does not provide a limiting
distribution, so the intervals are exploratory percentile intervals from resampling whole
trajectories, and **no lag may be called significant**. The claim level is capped for
this reason, and the report says "exploratory" next to every interval.

If the user asks whether an effect is significant, that is the honest answer: this method
can say where the effect appears to sit and cannot yet give you a test.

## Letting the effect vary: `lag_cate`

`theta_kappa(x)` is the lag-kappa effect for a period whose modifiers were x, read **at the
treatment period**. What comes back is a linear projection: an intercept and one
coefficient per modifier, per lag.

**The modifiers must be variables the treatment does not move.** In practice that means
baseline ones, recorded before the first period: severity at admission, age, comorbidity.
This is not a style preference and it is not about precision.

If the effect varies with something the treatment moves, then one period of treatment
reaches a later outcome by two routes, and the second is multiplied by the treatment of the
period in between. The outcome stops being a sum of lag effects, so there is no profile to
estimate, and fitting one anyway returns numbers that look reasonable and are not any
effect. On this project's own generator, before its heterogeneity was moved onto a baseline
covariate, the lag-2 estimate came back at +4.7 where the truth was +1.2.

A check blocks a modifier that varies within a unit. It is waivable, because a modifier can
vary for reasons outside the treatment, calendar time or age being the obvious ones, and
only the user can say that is the case.

## Running it

```bash
python scripts/run.py quality  --spec spec.yaml --data <panel file>
python scripts/run.py estimate --spec spec.yaml --data <panel file>
```

The spec fields this family needs: `unit_id`, `period_index`, `period_length`, `state`,
`treatment`, `outcome`, `max_lag`, `estimand` (`lag_profile` or `lag_cate`), and
`effect_modifiers` for `lag_cate`. Estimator settings live in `estimation.params`:
`n_bootstrap_samples` (200 by default), `bootstrap_n_jobs`, `lambda_floor`, `max_lag`, and
`use_ipcw` for the sensitivity arm.

Installing: this family needs `causpec[dynamic]`, which is scikit-learn and joblib. It does
not need econml.

## What gets reported at each lag

The analysis set shrinks as the lag grows, and its composition shifts with it, because the
trajectories long enough to supply a long window are not a random subset. The report
carries, per lag: the number of units, the number of windows, the treated share, the
effective number of windows once the weights are counted, the largest weight, and J.

None of that is decoration. A profile whose last lag rests on a third of the units of its
first, with a different treated share, has to be read that way, and only the table shows it.

## What blocks, and why those things

- **A gap or a duplicate in the period index.** The lag index counts rows, so a missing
  period silently relabels every later lag in that trajectory. Not waivable, and not
  something to impute: a period nobody observed has no outcome to borrow.
- **Too few effective windows at a lag.** The threshold is not on the largest weight, which
  is heavy-tailed even when everything is right. It is on how many windows effectively carry
  the lag once the weights are counted. At 800 units this project's benchmark has about
  eight effective lag-2 windows out of five hundred, and the lag-2 estimate there is
  genuinely unusable.
- **A state column that is nearly a copy of the treatment.** A machine setting recorded
  during the period, say. A confounder is meant to predict treatment, so only near-perfect
  separation is evidence of a post-treatment measurement; anything less is a warning and a
  question for the user.
- **J too small at a lag.** J is the denominator of the estimator, so this is the
  weak-instrument problem in another costume: the estimate becomes a ratio with almost
  nothing underneath.

## Two things to say out loud in the report

1. **A trajectory ending is not the outcome here.** Leaving closes the observation window,
   and death and discharge are treated identically. "No effect at 36 hours" is not "no
   effect on dying", and a clinician will read it that way unless it is said.
2. **The estimand is defined among patients still there.** Each lag speaks about
   trajectories still active at the treatment period, so the profile says nothing about
   those who had already left.

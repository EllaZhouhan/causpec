# The lag profile: treatment given period by period

Read this when the treatment is not a one-off. If the patient can be on it in one period
and off it in the next, a cross-sectional comparison cannot say what it did, and this
family can, for one specific question.

**Status: declared, not implemented.** family.yaml is written and the checks and the
estimator follow it. Until then, say what the analysis would be and do not produce a
number.

## The one question this answers

What does **one period** of treatment do to the outcome of that period, and to the
outcomes of the periods after it?

The answer is a profile, one number per lag:

| | Meaning |
|---|---|
| theta_0 | the effect on the outcome of the same period |
| theta_1 | the effect of that same period of treatment, one period later |
| theta_K | the same, K periods later |

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

## What to tell the user about the interval

**The point estimate is the result; the interval is an indication.** The theory proves
that the whole profile converges to the truth. It does not provide a limiting
distribution, so the intervals are exploratory percentile intervals from resampling whole
trajectories, and **no lag may be called significant**. The claim level is capped for
this reason, and the report says "exploratory" next to every interval.

If the user asks whether an effect is significant, that is the honest answer: this method
can say where the effect appears to sit and cannot yet give you a test.

## What gets reported at each lag

The analysis set shrinks as the lag grows, and it also changes composition: longer
trajectories contain more sustained treatment, so the treated share rises with the lag. The
report therefore carries, per lag, the number of units, the number of windows, the treated
share, the number of events, the largest continuation weight and the relevance quantity J.
None of that is decoration. A profile whose last lag rests on a different population from
its first lag has to be read differently, and only the table shows it.

## Two failure modes worth naming

- **The weight product.** A weight over a lag-K window multiplies K+1 reciprocals, so a
  continuation probability that gets close to zero anywhere in a window blows the window
  up. The longest lag fails first. The check reports the largest weight and the share of
  probabilities clipped at the floor.
- **Relevance per lag.** J is the denominator of the estimator. When it is small, the
  estimate is a ratio with almost nothing underneath, exactly as a weak instrument is in
  an IV analysis. It blocks.

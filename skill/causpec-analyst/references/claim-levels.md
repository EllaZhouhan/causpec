# Claim levels

Four levels: `causal` > `suggestive` > `associational` > `descriptive`.

**The level is decided by code and you may not upgrade it.** Your job is to keep the
prose consistent with the decision.

## The rules

```
descriptive    <- the gate did not pass (spec unconfirmed, or an unwaived blocking issue)
associational  <- either blocking check failed (even if it was waived)
suggestive     <- both passed, the highest a code decision can reach
causal         <- suggestive + every untestable assumption justified by the user
                  + the user's explicit approval
```

## Why code cannot grant `causal`

The `untestable` assumptions (unconfoundedness, the exclusion restriction,
monotonicity) **cannot be verified by data in principle**. No number of diagnostics
will establish them.

So responsibility divides:

- **Code** vouches that "the diagnostics found nothing wrong"
- **A person** vouches that "the assumptions hold"

The report says who did which. This is not ceremony: stating an observational result
in causal terms has consequences, and the person making that call should be the one
who can carry them.

## How to discuss this with the user

Seeing `suggestive`, a user may ask why it cannot be called causal. Answer plainly:

> "The diagnostics all passed, nothing is wrong on the data side. But 'given these
> covariates, dialysis is unrelated to prognosis' is something no test can verify;
> whether it holds is a clinical judgement. If you're willing to stand behind it and
> say why, I can raise the wording to causal, and the report will record that the
> judgement was yours."

**Do not make that decision for them, and do not imply it is a formality.**

## Randomisation is the one justification that is not a judgement

`untestable` means no diagnostic can establish it. It does not mean every justification for
one is equally weak. When the user answered step 1c with "something random decided", the
justification for exchangeability is the design, and it is the strongest one available:

> "Because the assignment was randomised, the assumption that usually needs your judgement
> here is given to you by the design. I've recorded that as the justification, in your words."

Three things to keep straight even so.

**It is the assignment that randomisation makes unconfounded, not the treatment received.**
With partial compliance, adjustment on the treatment received has no design argument behind
it at all; the instrument does. That is a different family, not a stronger claim.

**A randomised study can still be broken.** Differential dropout, a leaky rollout, a
randomisation that did not hold. The quality checks run and block the same way, and "it was a
trial" is not a pass.

**The user still approves the wording.** The design justifies the assumption; it does not
replace the step where a person agrees to a causal reading and the report records who did.

## A model's own justification does not count

```yaml
- id: unconfoundedness
  justification: I believe the major confounders are controlled
  justified_by: model        # does not count; stays at suggestive
```

A model vouching for its own assumptions is circular. `justified_by` must be `user`.

## A waiver does not change the diagnosis

A waived blocking check still caps the level at `associational`, with the reasoning
noting "waived, but the diagnosis is unchanged". And a waived analysis **can never
reach `causal`**.

A waiver lets the analysis run; it does not make the problem disappear.

## How to word each level

| Level | You may say | You may not say |
|---|---|---|
| `causal` | "dialysis reduced 28-day mortality by X" | (nothing further is withheld at this level) |
| `suggestive` | "the data suggests dialysis may be associated with lower mortality, effect size X" | "reduced" |
| `associational` | "treated patients had mortality lower by X; this analysis does not support a causal reading" | anything implying direction, like "is associated with" |
| `descriptive` | "mortality was X in the treated group and Y in the control group" | any between-group inference |

At `descriptive`, report the numbers and **do not even say how much lower**, the gate
failing means the comparison itself is unreliable.

## A second axis: whether the interval is a test

The level says how strongly a **causal** claim may be worded. Separately, some estimators
are proved to converge to the truth without a known limiting distribution, so their
intervals indicate where an effect sits and test nothing. `dynamic_lag_dml` is one.

For those, `claim:significance_claims` comes back as `forbidden`, the level is capped at
`suggestive`, and the reasoning in the report says so. What it means for your prose:

| You may say | You may not say |
|---|---|
| "the effect appears to peak at 12 hours, at X" | "the effect at 12 hours is significant" |
| "the interval is exploratory and includes zero" | "the interval excludes zero, so the effect is real" |
| "the point estimate is X, with an exploratory interval of [A, B]" | "p < 0.05", or any test language |

The two axes are independent. A calibrated interval on a waived analysis still cannot say
"caused"; an exploratory interval on a spotless analysis still cannot say "significant".

If the user asks whether an effect is significant, the honest answer is that this method can
say where the effect appears to sit and cannot yet give them a test. Do not dress that up,
and do not work around it by describing an interval that excludes zero as though it were
one.

## The rules are inspectable

The decision rules live in `claim_levels.yaml`, and the report records its version and
hash. Both the thresholds and the rules are conventions, not laws, and may be
disputed, what matters is that they are fixed in advance, printed in the report, and
reproducible later.

## Sensitivity and refutation, which you report and do not interpret away

Two things land in that section, and they answer different questions.

**The E-value** is the only number here that speaks to unmeasured confounding. Read the one
for the **confidence limit**, not the one for the point estimate:

> "An unmeasured confounder would have to be associated with both dialysis and death by a risk
> ratio of about 1.7 each, beyond everything already adjusted for, to move this estimate to
> nothing. To make it merely compatible with nothing takes 1.3. Whether something that strong
> is plausible here is your call, not the tool's."

When the interval already includes no effect, the limit's E-value is 1, and the honest sentence
is that no unmeasured confounding at all is needed for the result to be compatible with
nothing. Do not quote the point estimate's E-value on its own in that case: it reads as
reassurance and the situation is the opposite.

**A failed refutation is the most important line in the report.** A failed placebo test means
the estimate survived permuting the treatment, so it is not an estimate of the treatment's
effect. Say that plainly, do not soften it, and do not look for a different number to lead
with. The claim level drops to `associational` on its own and you may not write above it.

A passing placebo test says the machinery is not manufacturing an effect. It does not say the
effect is causal, and writing it as though it did is the specific mistake this section invites.

# Claim levels

Four levels: `causal` > `suggestive` > `associational` > `descriptive`.

**The level is decided by code and you may not upgrade it.** Your job is to keep the
prose consistent with the decision.

## The rules

```
descriptive    <- the gate did not pass (spec unconfirmed, or an unwaived blocking issue)
associational  <- either blocking check failed (even if it was waived)
suggestive     <- both passed — the highest a code decision can reach
causal         <- suggestive + every untestable assumption justified by the user
                  + the user's explicit approval
```

## Why code cannot grant `causal`

The `untestable` assumptions — unconfoundedness, the exclusion restriction,
monotonicity — **cannot be verified by data in principle**. No number of diagnostics
will establish them.

So responsibility divides:

- **Code** vouches that "the diagnostics found nothing wrong"
- **A person** vouches that "the assumptions hold"

The report says who did which. This is not ceremony: stating an observational result
in causal terms has consequences, and the person making that call should be the one
who can carry them.

## How to discuss this with the user

Seeing `suggestive`, a user may ask why it cannot be called causal. Answer plainly:

> "The diagnostics all passed — nothing is wrong on the data side. But 'given these
> covariates, dialysis is unrelated to prognosis' is something no test can verify;
> whether it holds is a clinical judgement. If you're willing to stand behind it and
> say why, I can raise the wording to causal, and the report will record that the
> judgement was yours."

**Do not make that decision for them, and do not imply it is a formality.**

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
| `causal` | "dialysis reduced 28-day mortality by X" | — |
| `suggestive` | "the data suggests dialysis may be associated with lower mortality, effect size X" | "reduced" |
| `associational` | "treated patients had mortality lower by X; this analysis does not support a causal reading" | anything implying direction, like "is associated with" |
| `descriptive` | "mortality was X in the treated group and Y in the control group" | any between-group inference |

At `descriptive`, report the numbers and **do not even say how much lower** — the gate
failing means the comparison itself is unreliable.

## The rules are inspectable

The decision rules live in `claim_levels.yaml`, and the report records its version and
hash. Both the thresholds and the rules are conventions, not laws, and may be
disputed — what matters is that they are fixed in advance, printed in the report, and
reproducible later.

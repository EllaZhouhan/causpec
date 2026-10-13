# Variable roles

**This page is the cross-sectional path.** `dynamic_lag_dml` has no separate W: the
conditioning set is `state`, recorded at the start of each period, and the modifiers of
`lag_cate` are restricted to variables the treatment cannot move. See `dynamic-lag-dml.md`
before applying anything here to a panel.

## `effect_modifiers` (X) and `adjustment_set` (W) are separate

This is the easiest place in the spec to get wrong, and getting it wrong **raises no
error**.

| Field | Purpose | Cost of misplacing a variable |
|---|---|---|
| `effect_modifiers` | Variables the effect varies over; enters the CATE model | A variable that should not be treated as an effect modifier is treated as one |
| `adjustment_set` | Removes confounding only; does not enter the CATE | A variable that should explain heterogeneity is demoted to pure confounding control |

Both are just "columns handed to the estimator". Putting one in the wrong place
throws no exception, it **quietly changes the estimand**.

The rule comes from a real lesson: a piece of research code defined 75 `controls` and
60 `features`, passed only `features` as X with `W=None`, and silently dropped the
dozen-odd columns in between with no warning at all. CauSpec makes them two fields,
each confirmed separately, to prevent a repeat.

**Do not ask the user to enumerate them.** They came to find out which patients
benefit; asking them to name the variables the benefit varies over asks them to answer
their own question, and with forty covariates it is forty questions.

Draft it and confirm the draft:

1. Default X to every pre-treatment covariate. The forest finds the heterogeneity.
2. Ask the one thing only they can answer: which of these were measured after treatment
   started. A column name will not tell you, and that answer affects correctness rather
   than presentation.
3. Offer a focus rather than requiring one: "If you already suspect the benefit differs
   by severity, I can report that breakdown first."

Use W for a variable they want controlled but not treated as an axis the answer is
expressed along.

## Variables that can never enter the adjustment set

**Anything measured after treatment.** Adjusting for a post-treatment variable either
blocks the causal path itself or opens a collider path; both introduce bias, and the
direction cannot be predicted.

So the order of reasoning is: **measurement time first, role second**.

```
Was this measured before time zero?
  |- no  -> it cannot enter the adjustment set, however much it looks like a confounder
  `- yes -> now ask whether it is a confounder, an effect modifier, or irrelevant
```

When the timing is unclear, do not guess, ask: "Was `max_creatinine` measured at ICU
admission, or does it include values after dialysis started?"

## Pre-treatment is necessary, not sufficient

A pre-treatment variable can still be a collider on a backdoor path (M-bias). The
usual practice in high-dimensional DML is to adjust for every pre-treatment variable;
the literature disagrees about this, Ding and Miratrix (2015) argue that M-bias is
usually smaller than the confounding bias from not adjusting, while Pearl (2015)
disputes the scope of that conclusion.

In practice: **do not exclude pre-treatment variables out of fear of M-bias**, but if
the user identifies one as a possible collider, record it in the spec's `assumptions`
(category `requires_justification`) and note it in the report.

## Do not ask the user to draw a full DAG

EHR settings routinely have dozens of covariates, and forcing a complete diagram
produces a formality rather than a model. Two things are wanted instead:

1. A role for each variable or group, drafted from its **measurement window** and
   confirmed by the user
2. The few "no edge" assumptions that decide whether identification holds, recorded
   in `assumptions`

Under IV, those must at least include: the instrument does not affect the outcome
except through the treatment (the exclusion restriction), and the instrument is
independent of unmeasured confounders.

> Automatic rendering of the variable-role diagram is not implemented; the report says
> so in that section.

## What adjustment buys in a randomised design, measured

A randomised design does not need the covariates to make the comparison fair, so the question
is what they are for. The usual answer is precision, and that is right in principle and small
in practice unless the covariates predict the outcome well.

The mechanism is exact: adjusting for covariates replaces the outcome's variance with its
residual variance, so the standard error falls by a factor of the square root of one minus
the share of the outcome they explain. Measured on this project's own ICU data, with the
treatment permuted so that it is randomised by construction and the only thing changing is
whether the covariates are in the model:

| What is adjusted for | Explains of the outcome | Interval narrows by |
|---|---|---|
| Six baseline covariates, as a real spec would declare them | 1.8% | **0.7%** |
| Six columns of pure noise | 0% | 0.03% |
| One strongly prognostic column | 20% | **10.4%** |

The last row matches the square-root rule to two decimal places, which is how we know the
first row is small for the right reason rather than through some error: death is simply hard
to predict from six baseline labs.

**So do not promise a tighter interval to someone with a trial.** Say the covariates are what
lets you look at who benefits more, which is true and is why the field exists. If they ask
about precision, the honest answer is that it depends on how well those columns predict the
outcome and here it is under a percent.

**In an observational analysis the trade runs the other way.** Adjustment is there for bias,
not for precision, and it can widen the interval: on the same data, adjusting moved the
estimate from +0.0245 to +0.0154 and made the interval 1 to 2% wider, because the treatment
is correlated with the covariates and that inflates the variance of its coefficient. That is
the normal price of removing confounding and it should not be presented as a loss.

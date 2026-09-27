# Variable roles

## `effect_modifiers` (X) and `adjustment_set` (W) are separate

This is the easiest place in the spec to get wrong, and getting it wrong **raises no
error**.

| Field | Purpose | Cost of misplacing a variable |
|---|---|---|
| `effect_modifiers` | Variables the effect varies over; enters the CATE model | A variable that should not be treated as an effect modifier is treated as one |
| `adjustment_set` | Removes confounding only; does not enter the CATE | A variable that should explain heterogeneity is demoted to pure confounding control |

Both are just "columns handed to the estimator". Putting one in the wrong place
throws no exception — it **quietly changes the estimand**.

The rule comes from a real lesson: a piece of research code defined 75 `controls` and
60 `features`, passed only `features` as X with `W=None`, and silently dropped the
dozen-odd columns in between with no warning at all. CauSpec makes them two fields,
each confirmed separately, to prevent a repeat.

**How to ask**:

> "For `sofa_total_24h` — do you want to see whether the **effect varies with it**
> (say, sicker patients benefiting more), or is it just a confounder you want
> controlled?"

The former goes in `effect_modifiers`, the latter in `adjustment_set`. Both, if they
want both.

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

When the timing is unclear, do not guess — ask: "Was `max_creatinine` measured at ICU
admission, or does it include values after dialysis started?"

## Pre-treatment is necessary, not sufficient

A pre-treatment variable can still be a collider on a backdoor path (M-bias). The
usual practice in high-dimensional DML is to adjust for every pre-treatment variable;
the literature disagrees about this — Ding and Miratrix (2015) argue that M-bias is
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

# Longitudinal analysis (not implemented)

**CauSpec does not support longitudinal or time-varying treatment analysis.**

When a question needs it, say so plainly. Do not substitute a cross-sectional method
to produce a number.

## What falls into this category

- Treatment switching on and off over time ("deciding daily whether to continue dialysis")
- Confounders that are themselves affected by earlier treatment (time-varying confounding)
- A question about a **strategy** rather than a one-off treatment ("start early versus
  start late")
- Censoring related to the outcome (informative censoring)

Backdoor adjustment and standard IV are both biased for these, in directions that
cannot be predicted.

## Why the existing families cannot be made to fit

Flattening a longitudinal question into a cross-sectional one — say, "dialysed within
24 hours of ICU admission" — introduces two problems:

1. **Immortal time bias.** Belonging to the "dialysed within 24 hours" group requires
   surviving 24 hours; the comparison group carries no such requirement.
2. **Time-varying confounding.** Creatinine is both a consequence of yesterday's
   dialysis decision and a cause of today's. Adjusting for it blocks the causal path;
   not adjusting leaves confounding.

Telling the user this is more useful than giving them a biased number.

## What can still be offered

Even without estimation, you can:

- Run the time-related quality checks (**also not implemented yet**; see plan.md
  Phase 1 task 5)
- Help the user state the question as the seven components of a target trial, making
  explicit what is actually being asked
- Explain what method it would take (IPCW / g-formula / marginal structural models)

## Outstanding

The `longitudinal_ipcw` family still needs one document: how each event (death,
discharge, transfer) is treated in estimation — as outcome, competing, censoring or
terminal — and how the resulting estimand should be read.

Code follows that document, not the other way round (design.md 7.3, TODO).

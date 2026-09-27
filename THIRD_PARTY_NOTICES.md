# Third-party sources

This file records the external projects CauSpec uses directly, adapts, or borrows ideas
from. When external code is adapted, the source, version and licence are noted in the
file header.

## Used as dependencies

| Project | Licence | Used for |
|---|---|---|
| EconML | MIT | `CausalForestDML` and `CausalIVForest`, `NonParamDMLIV`, `econml.validate.DRTester` |
| DoWhy | MIT | `CausalModel` identification cross-check; refuters (placebo, random common cause, data subset) |
| pandera | MIT | Basic-layer DataFrame schema checks |
| DoubleML | BSD-3-Clause | `sensitivity_analysis` for unmeasured confounding |

## Adapted code (original copyright retained)

| Source | Licence | What was adapted |
|---|---|---|
| Baygent `causal-inference` skill: `scripts/check_refutation.py`, `references/refutation.md` | MIT | The claim-level decision; thresholds reset for frequentist diagnostics |
| Baygent `references/reporting.md` | MIT | Fixed report structure; "assumptions before results" |

## Ideas borrowed, no code copied

| Source | Notes |
|---|---|
| StatsPAI (MIT) | **Not taken as a dependency.** Borrowed: the field layout of `target_trial/protocol.py` (the longitudinal spec structure), the error-to-remediation registry pattern of `agent/remediation.py`, the post-hoc deviation log of `question/preregister.py`, and the shape of the `immortal_time_check` |
| Causal desk | No licence declared. Borrowed: the core/family split (ADR-0005), not adjudicating field conflicts automatically (ADR-0003), the address-citation mechanism (ADR-0002), frozen handoffs as regression tests (ADR-0004), showing excluded families with reasons, and one question per turn |

## Written here, with numerical regression tests

The following are closed-form, so implementing them is more controllable than taking a
heavy dependency. Each carries a test against a numerical example from the original
paper (see the ADRs and design.md section 9):

| Quantity | Checked against |
|---|---|
| E-value | VanderWeele & Ding (2017), *Annals of Internal Medicine* |
| Effective F test | Montiel Olea & Pflueger (2013), *JBES* |

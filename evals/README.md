# evals/

Mirrors design.md section 16. Six categories:

| Category | Contents | When |
|---|---|---|
| **numerical** | Agreement with a direct family call; reproducibility under a fixed seed; ground-truth coverage on dataset A | Phase 1 |
| **quality checks** | Recall of each injected problem on dataset C | Phase 1 task 6 |
| **robustness** | The two shapes of dataset B reach the same conclusion | Phase 3 task 4 |
| **reporting** | The renderer refuses un-placeheld numbers and unknown addresses; the claim level matches the diagnostics | Phase 1 |
| **agent** | 20-30 golden tasks: does it ask about the critical fields, miss a diagnostic, or overstate the claim | From Phase 2 task 3 |
| **regression** | Frozen confirmed specs and snapshots as fixtures; a change to a family must not change their results | Phase 1 |

## What the golden tasks must cover

- A mismatch between the requested estimand and the identification strategy (asking
  "who benefits" while assuming only monotonicity)
- A question needing an unsupported design (difference-in-differences, regression
  discontinuity) — the correct behaviour is an explicit refusal
- With and without the skill loaded, as a comparison

## Sources

- Organisation follows Baygent's `evals/` (MIT)
- External tasks may draw on the parts of CauSciBench (as used by CAIS) that match this
  project's setting — **check the licence before use**

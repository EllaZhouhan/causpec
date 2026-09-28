# ADR-0001: Literal numbers in report prose

- Status: accepted
- Date: 2026-09-22
- Related: design.md 10.1, G4; `packages/causpec/core/reporting/render.py`

## Context

design.md 10.1 states the rule:

> Report prose written by the model may reference numbers only through placeholders …
> An unknown address, **or a bare number anywhere in the prose**, fails the render.

Implementing this and running the vertical slice, the rule immediately rejected a
perfectly ordinary report:

```markdown
Mortality at 28 days was {{res:primary.mean_treated}}
```

The `28` was judged an un-placeheld number. So are the `95` in "95% confidence
interval", the `3` in "AKI stage 3", the `2` in "phase 2", **these numbers are part of
a term, not a computed result**.

The design document did not anticipate this when it wrote the rule.

## Decision

Introduce the `lit:` namespace. A fixed number inside a term is written `{{lit:28}}`
and renders verbatim.

**With one counter-check**: if a `lit` value matches any computed result (2% relative
tolerance), the render fails.

```
lit:0.0289 equals the computed result res:primary.estimate (0.0289).
Computed results must be cited by address, as {{res:primary.estimate}};
lit is only for numbers inside a term, e.g. {{lit:28}}-day mortality.
```

## Rationale

This keeps the property G4 actually wants: **no number reaches the report without being
declared**.

`lit:` is not a relaxation, it is a change of form. The model still cannot write a
number casually; it has to stop and declare "this one is not something I computed".
And the `lit:` is visible in the report source, so anyone can grep for every literal a
report declared.

The counter-check closes the only abuse. Without it the model could write
`{{lit:0.0289}}` to smuggle a result through, G4 would quietly fail, and **no test
would go red**.

The 2% tolerance rather than exact equality stops a model writing `0.029` to slip past.

## Options rejected

**A. Catch decimals only, not integers.** Simplest, but `res:primary.n = 60` is an
integer sample size and among the numbers most in need of protection. Rejected.

**B. Maintain a whitelist of terms** ("28 days", "95%", "AKI-3", …). No change of habit
for the model, but the whitelist can never be complete, and each addition is a silent
loosening, when something goes wrong, nobody can tell which entry let it through.
Rejected.

**C. Only catch a number when result-like words appear nearby** ("effect", "difference",
"confidence interval"). A heuristic, producing both false negatives and false positives,
with unpredictable behaviour. Rejected.

**D. Drop the rule and verify addresses only.** Cheapest, but it abandons the more
important half of G4, "the model does not write numbers" becomes advice. Rejected.

## Consequences

**Benefits**: G4's guarantee survives intact, and the rule explains itself, the error
the model receives says what to write instead.

**Costs**:

1. One more piece of syntax for the model. SKILL.md and `references/reporting.md` have
   to spell out the difference between `res:` and `lit:`, and golden tasks have to cover
   both "used a bare number where a lit was needed" and "smuggled a result through lit".
2. The 2% tolerance is a judgement call. If two genuine results ever land within 2% of
   each other and one of them should also be written as a literal, there will be a false
   positive. Exact matching plus normalisation (stripping trailing zeros) would be safer
   then.
3. `_strip_exempt` exempts Markdown headings, ordered-list numbers, table separators and
   fenced code blocks. Those are judgement calls too, and need revisiting when the report
   template grows more complex.

**Do not delete `_check_literals_are_not_results`.** It looks like an odd special case,
and every test still passes without it (unless its own test goes too), but G4 stops
holding.

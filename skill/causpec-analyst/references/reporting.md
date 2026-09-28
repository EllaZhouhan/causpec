# Reporting

## The structure is fixed

```
1.  Question and analysis spec          <- code
2.  Estimand and its population         <- you
3.  Variable roles                      <- code (currently "not implemented")
4.  Assumptions                         <- code
5.  Data quality                        <- code table + your interpretation
6.  Primary results                     <- you
7.  Sensitivity and refutation          <- you (currently "not implemented")
8.  Claim level and reasoning           <- code
9.  Limitations                         <- you
10. Post-hoc analyses, if any           <- you
```

**The order cannot be changed.** Assumptions (4) preceding primary results (6) is the
point of this structure: a reader has to see what the analysis rests on before seeing
a number. Whatever order you submit in, the final order is unchanged.

## The six sections you may write

`estimand`, `data_quality`, `primary_results`, `sensitivity`, `limitations`, `post_hoc`.

**You may not write**: `question_and_spec`, `claim_level`, `variable_roles`,
`assumptions`. Supplying prose for any of them is refused.

Why the first two are closed to you:

- **The spec-provenance table** exists so the user can audit whether you confirmed
  things on their behalf. It loses its point if you touch it.
- **The claim level** is decided by code; you may not upgrade it.

## How to submit

Write a `narrative.yaml`:

```yaml
estimand: >
  This estimates the population average treatment effect. It answers "if every
  eligible patient received dialysis rather than none of them, how much would
  mortality differ", not anything about a specific individual.

primary_results: >
  Among {{res:sample.n}} patients, {{res:sample.n_treated}} received dialysis.
  The average effect is {{res:primary.ate|+.3f}}, {{lit:95}}% confidence interval
  [{{res:primary.ate_ci_lower|+.3f}}, {{res:primary.ate_ci_upper|+.3f}}].

limitations: >
  This analysis rests on unconfoundedness, which cannot be verified.
```

```bash
python scripts/run.py estimate --spec spec.yaml --data <data> \
    --report --narrative narrative.yaml --run-dir runs/
```

## On the panel path, the profile table is code-generated

For `dynamic_lag_dml` the primary-results section opens with a table the code writes: every
lag, its effect, its exploratory interval, and the units, windows, effective windows and J
behind it. You do not write that table and cannot suppress it.

So your `primary_results` prose is interpretation, not transcription. Say what the shape of
the profile means, where it peaks, which lag rests on too little to lean on. Repeating the
table in sentences wastes the section.

The addresses, for the prose you do write:

```
{{res:profile.lag1.theta|+.3f}}      the lag-1 effect
{{res:profile.lag1.ci_lo|+.3f}}      its exploratory interval
{{res:profile.lag1.hours|.0f}}       that lag in clock time
{{res:profile.period_hours|.0f}}     one period in clock time
{{res:profile.lag1.n_units}}         units behind that lag
{{res:profile.lag1.effective_windows|,.0f}}   windows left once the weights are counted
{{res:profile.max_lag}}              the longest lag
{{res:profile.horizon}}              fixed or variable
{{res:sample.n_units}}               units in the panel
```

**Do not write `res:primary.ate` here**: there is no single average effect in a profile, and
the renderer will refuse an address that does not exist.

One trap specific to this family. "A 12-hour period" looks like a term, so `{{lit:12}}` is
the instinct, and it is refused, because 12 is also the lag-1 effect's 12 hours. Cite
`{{res:profile.period_hours|.0f}}` instead. The error message lists every address that
matches the number, so pick the one that means what the sentence says.

## Placeholder syntax

```
{{res:primary.ate}}              estimation results
{{qc:backdoor_overlap.passed}}   quality-check evidence
{{claim:level}}                  the claim level
{{lit:95}}                       a fixed number inside a term (see below)
```

**Append a format spec to control precision**:

```
{{res:primary.ate|+.3f}}                       -> -0.018
{{qc:backdoor_overlap.extreme_fraction|.1%}}   -> 0.2%
```

Without one you get full precision (`-0.017936448014042473`), which is unreadable.
**Do not round it yourself**, use a format spec; that is the permitted way.

## Three things that fail the render

**1. A bare number anywhere in the prose.**

```
Wrong: The average effect is about -0.018.
Right: The average effect is {{res:primary.ate|+.3f}}.
```

**Numbers inside a term count too.** The `28` in "28-day mortality", the `95` in "95%
confidence interval", the `3` in "AKI stage 3", all of them must be written
`{{lit:28}}`. The renderer does not read meaning, and cannot tell "28 days" from "the
effect is 0.028", so it draws one line and asks you to declare which numbers you did
not compute.

**2. An unknown address.** The error lists every available address in that namespace, so follow it.

**3. Using `lit:` to smuggle in a result.**

`{{lit:28}}` is for fixed numbers inside a term. If a `lit` value matches any computed
result, the render is refused, that would be routing around the placeholder mechanism.

## Wording must match the level

The report ends with the claim level the code decided. Your prose in `primary_results`
has to match it:

| Level | What you may say |
|---|---|
| `causal` | "reduced" / "increased"; asserting causal direction and magnitude |
| `suggestive` | "suggests a possible association with ..."; asserting no causation |
| `associational` | Describe the association, and state that this analysis does not support a causal reading |
| `descriptive` | Report each group's numbers; draw no between-group inference |

See `claim-levels.md`.

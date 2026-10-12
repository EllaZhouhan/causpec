# Heterogeneous treatment effects under an IV design

## When to use `hte_iv`

The user believes there is **unmeasured confounding**, meaning the observable
covariates are not enough to control it, but has a credible instrument.

That is a judgement for them to make, not something you can read off the data. How to
ask:

> "Is there anything that influenced both who received treatment and the outcome, but
> that the data doesn't record? Someone's impression at the time, a conversation
> preference, signs that never made it into the chart?"

Yes, and there is an instrument -> consider IV. No, and the user is confident ->
`hte_backdoor`.

## The estimand: the easiest thing here to get wrong

**IV does not identify the effect for the whole population.**

### Binary instrument

Under relevance, the exclusion restriction and monotonicity, what is identified is the
**conditional LATE among compliers**, the people whose treatment status changed
because the instrument took a different value.

Compliers **cannot be identified individually**. So:

- Wrong: "this patient's expected benefit is X"
- Wrong: "the population average effect is X"
- Right: "among patients whose treatment decision changed with their clinician's
  tendency, the effect is X"

The `iv_low_complier_share` check reports what fraction they are. When it is small,
**the report must state that the conclusion holds for only a narrow slice of the
population**.

### Continuous instrument

There is no single complier group. Under uniformity (monotonicity generalised to
continuous instruments), what is identified is a weighted average of "marginal LATEs"
between adjacent instrument values, with weights set jointly by the local first-stage
slope and the instrument's distribution (Angrist & Imbens 1995, JASA).

**The weights are not chosen by the user and do not correspond to population shares.**
The population this estimand applies to is therefore harder to describe than in the
binary case; say so plainly rather than simplifying it to "the average effect".

`res:instrument.kind` tells you whether this run was `binary` or `continuous`.

### When it may be called a CATE

Only under the further assumption that the effect does not vary by compliance type
given covariates can either estimand be read as a population CATE. **That assumption is
itself untestable**, and the user has to own it explicitly.

## Estimand reconciliation

A user asking "which patients benefit" wants a CATE. If the identification strategy is
IV under monotonicity alone, **those do not match**, stop at step 5 and give the user
the choice:

1. Restate the estimand and accept that the conclusion covers compliers only
2. Add the "effect does not vary by compliance type" assumption, and argue for it

Do not quietly report it as a CATE.

## The two backends

| | `ivforest` (default) | `dmliv` |
|---|---|---|
| CATE interval | GRF honest variance, within one fit | bootstrap |
| ATE interval | unit-level bootstrap of the forest | bootstrap |
| Speed (n=5000) | about 5s per replicate | about 26s |
| Multiple instruments / `adjustment_set` | not supported | supported |

That `dmliv` can only bootstrap is not a choice: it is the only option EconML offers
for that class, because its final model is an arbitrary regressor from which no
variance can be derived.

**The replicate count defaults to 200.** Lowering it is faster but distorts the
interval: on the same data, 20 replicates and the analytic interval differed by two
orders of magnitude in the count of individuals with a significant benefit. Below 100
the Result is flagged (`res:estimation.bootstrap_adequate`) and the report has to say so.

On a multi-core machine add `bootstrap_n_jobs: 8`, measured at 4.6x faster with
identical results.

## Recording the three assumptions

```yaml
assumptions:
  - id: relevance
    category: empirically_assessed      # quality checks give evidence
    statement: the instrument is associated with treatment, strongly enough
  - id: exclusion_restriction
    category: untestable                # no diagnostic can establish this
    statement: the instrument affects the outcome only through the treatment
  - id: monotonicity                     # uniformity, for a continuous instrument
    category: untestable
    statement: there are no defiers
```

The exclusion restriction needs a **domain argument**, so you have to ask:

> "Besides influencing whether they get treated, could this reach the outcome by any other
> route? Whoever leans towards treating more, do they differ in other ways that could matter?"

The `iv_covariate_imbalance` check only tests a **necessary** condition, if the
instrument really were close to random, covariates should be balanced across it.
**Balance is not evidence that the exclusion restriction holds.**

## With more than one instrument

The research this family comes from tried several instruments and kept one, physician
preference, because the others had no first stage. If a user declares more than one, two
things change.

The overidentification test becomes available, and it is reported as a warning whatever it
says, because a rejection has two readings that call for opposite responses: an instrument
that violates exclusion, or valid instruments identifying different complier groups under a
heterogeneous effect. See `quality-checks.md`.

And the estimand changes. Each instrument identifies the LATE of its own complier group, so
two instruments identify two different weighted averages. Reporting one number from both is a
choice, not an aggregation, and the report has to say which patients each instrument speaks
about. The `ivforest` backend takes one instrument only; `dmliv` takes several.

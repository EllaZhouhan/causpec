# Spec fields

## Structure

```yaml
spec_version: 1
question: What is the average effect of dialysis on ICU mortality?
family: hte_backdoor              # hte_backdoor | hte_iv

estimation:
  params:                          # estimator hyper-parameters; enter spec_hash and the manifest
    n_estimators: 500
    estimator: ivforest            # hte_iv only: ivforest (default) | dmliv
    n_bootstrap_samples: 200

assumptions:
  - id: unconfoundedness
    category: untestable           # empirically_assessed | requires_justification | untestable
    statement: given the adjustment set, assignment is independent of potential outcomes
    justification: ""              # the user's argument; required for causal wording
    justified_by: user             # must be `user`; a model's own argument does not count

fields:
  treatment:
    value: isDialysisICU
    source: user                   # user | model | data
    said: treatment means starting dialysis in the ICU    # the user's own words
    turn: 2
    status: confirmed              # drafted | confirmed
  outcome:      {value: death, ...}
  estimand:     {value: ate, ...}
  effect_modifiers: {value: [col1, col2, ...], ...}
  adjustment_set:   {value: [col3, ...], ...}
  instrument:       {value: [col4], ...}          # hte_iv only
  causal_claim_approved: {value: true, ...}       # only once the user agrees to causal wording
```

## Every field records its provenance

| Key | Meaning |
|---|---|
| `value` | The value: a column name, a list of column names, or an estimand name |
| `source` | Who proposed it: `user` (they said so), `model` (you inferred it), `data` (derived from the data) |
| `said` | The user's **own words**. See below |
| `turn` | Which conversational turn |
| `status` | `drafted` (awaiting confirmation) or `confirmed` |

## Two rules about `said`

1. Required when `source: user`, what the user said is the evidence, kept verbatim
2. **Required when `status: confirmed`**, whatever the source

The second matters most. You infer `outcome = death` (`source: model`), the user says
"yes, in-hospital death", you then mark it `confirmed`, `source` stays `model`, and
`said` records the words they used when agreeing.

**Never confirm on the user's behalf.** The system cannot verify that the user ever
saw the spec, which is why confirmation requires a quote, and the report's front page
prints every field's provenance and quote for them to check. A quote they never said
is one they will recognise instantly.

## Critical fields

The gate requires these to be `confirmed` before it will estimate: `treatment`,
`outcome`, `estimand`.

Each family needs more:

| family | Also required |
|---|---|
| `hte_backdoor` | `effect_modifiers` |
| `hte_iv` | `effect_modifiers`, `instrument` |

## The three assumption categories

| category | Meaning | What can support it |
|---|---|---|
| `empirically_assessed` | The data can speak to it | Quality checks produce evidence |
| `requires_justification` | The data cannot settle it, but it can be argued | The user's argument |
| `untestable` | **Cannot be verified by data in principle** | Only the user, who carries the responsibility |

Only the `untestable` ones gate `causal` wording. While any of them lacks a user
justification, the ceiling for an automatic decision is `suggestive`, see
`claim-levels.md`.

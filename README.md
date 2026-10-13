# CauSpec

Turn a causal question in plain language into an analysis spec confirmed field by
field; assess whether the data can support that question before estimating anything;
run the estimation in deterministic code; and produce a report whose every number
traces back to a computation. Data sources are read-only throughout.

> Status: the library and the agent workflow are built and tested (685 tests). The MCP
> server, the database adapter and the demo deployment are declared and not implemented,
> and this README says so where it matters. The repository is private until v0.3.

## Loading the agent

The workflow is an agent skill. It drives the library, so the agent is what you talk to
and the library is what computes.

**In Claude Code, for your own data anywhere on the machine.** Two things: the command on
your PATH, and the skill in your personal skill directory.

```bash
git clone https://github.com/EllaZhouhan/causpec.git && cd causpec
uv tool install --from . --with 'causpec[hte]' causpec     # puts `causpec` on PATH
ln -sfn "$PWD/skill/causpec-analyst" ~/.claude/skills/causpec-analyst
```

Now any `claude` session in any directory has it. Ask a causal question and it should
trigger on its own; `/causpec-analyst` invokes it explicitly. Data paths can be absolute
and usually are, since your extract lives wherever you keep it:

> I have ICU data at `/Users/me/extracts/cohort.csv`, one row per patient. Does dialysis
> change 28-day mortality, and are there patients who benefit more?

A symlink rather than a copy, so editing `SKILL.md` in the clone takes effect on the next
message. If you move the clone, redo the link. Re-run `uv tool install` after pulling, since
the installed command is a snapshot rather than a live link to the source.

**In Claude Code, inside this repository only.** Nothing to install:
`.claude/skills/causpec-analyst` is already a symlink to `skill/causpec-analyst`, so a clone
has it immediately.

```bash
uv sync --extra hte          # the estimators; omit for spec and checks only
claude
```

Here the command is `uv run causpec`, because the package lives in the repository's own
environment rather than on your PATH. The skill works out which form applies with one probe
and the three cases are in `SKILL.md`.

**On claude.ai**, upload the packaged skill:

```bash
./scripts/build_skill.sh     # builds the wheel into the bundle, emits the zip
# then: Settings -> Capabilities -> Skills -> upload dist/causpec-analyst-skill.zip
```

That environment cannot install a local package, which is why the bundle carries the
wheel. The wheel is a build product and is not committed: a committed wheel drifts
silently from the source it claims to be.

**Without an agent**, the library has a CLI and the same gates apply:

```bash
uv run causpec columns  --data cohort.csv
uv run causpec quality  --spec spec.yaml --data cohort.csv
uv run causpec estimate --spec spec.yaml --data cohort.csv --report --run-dir runs/
```

`columns` describes every column on its own, grouped by shape, which is what the roles step
needs: nothing in it crosses two columns, because a comparison between the arms is a
diagnostic and diagnostics belong in the checks, where a spec can stand them down.

The skill is marked **best-effort** for one honest reason: an agent is technically able
to bypass `scripts/run.py` and read the data itself, so in this form "only code produces
numbers" rests on the agent following its own rules. Every report says so in its header.

## What it is for

Causal analysis on observational data usually fails before the estimation: treatment,
outcome and time zero are vaguely defined; a post-treatment variable or a positivity
problem goes unnoticed; definitions drift between datasets; numbers cannot be
reproduced. Tools of the "LLM plus code" kind add a failure of their own: the model
computing, or inventing, the numbers itself.

Four principles:

1. **Code computes the facts, the model exercises judgement, the framework holds the gate.**
2. **Every critical spec field carries a source** (user / model / data) **and a status**
   (drafted / confirmed); nothing is estimated until all of them are confirmed.
3. **Only code produces numbers.** Report prose may cite them only through addresses,
   which a renderer substitutes; an un-placeheld number fails the render.
4. **The claim level is decided by code from the diagnostics** (causal / suggestive /
   associational / descriptive) and the model may not upgrade it.

## What a run actually does

Eight steps, the first five with the user, the last three in code. A question becomes a
spec field by field; the data is checked against that spec before anything is estimated;
the estimate is computed and then attacked; the report is assembled by code with the
model allowed to write only the interpretation.

```
1  the question, the data's shape, how the treatment was assigned
2  map the concepts onto columns
3  variable roles, which become the diagram and get checked against the adjustment set
4  identification strategy and the assumptions it rests on
5  the estimand: which question the number answers, and for whom
6  quality checks: 4 core layers, then the family's own; blocking issues stop here
7  the user confirms the whole spec
8  estimate, refute, and render
```

What the report contains, all of it generated from an address map rather than written:

- the spec with each field's **source, status and the user's own words**, and the data's
  content fingerprint
- an **exclusion ledger** if any population filter ran, and the preprocessing steps applied
- the **variable-role diagram**, derived from the declared roles rather than drawn
- the **quality table**, every check with its verdict and what it means
- the **primary result**, then where the effect varies, then the effect by named group
- **sensitivity and refutation**: an E-value, and a placebo treatment, a random common
  cause and subset stability
- the **claim level** (causal / suggestive / associational / descriptive) with the reasons
  code used to decide it. Code can only lower it; `causal` needs a person to justify every
  untestable assumption and say so

## Supported analyses

| family | Estimands | Notes |
|---|---|---|
| `hte_backdoor` | `ate`, `att`, `cate`, `gate` | Backdoor adjustment with a causal forest. `gate` reports the effect for named groups, which is the answer to "who benefits"; `cate` reports a per-patient cloud that names nobody |
| `hte_iv` | `conditional_late`, `weighted_conditional_late` | Binary and continuous instruments. A population effect and a per-patient effect are **refused** with reasons: compliers cannot be identified individually |
| `dynamic_lag_dml` | `lag_profile`, `lag_cate` | The lag profile of one treatment period on per-period outcomes, with continuation weighting for an informative horizon |

The estimand is reconciled against the family at the gate. It is a label no estimator
reads, so `conditional_late` on `hte_backdoor` would otherwise print the words for an
effect among compliers over an average across everyone.

Designs outside that range (difference-in-differences, regression discontinuity,
synthetic control) are refused explicitly, with a reason given for each excluded
family, as are questions a supported family cannot answer.

## What the checks cover

Four layers in `core`, which run for every family, then the family's own design checks.
Thresholds live in `core/quality/basic_checks.yaml` and every one of them was measured
against this project's own data rather than picked.

| layer | Examples |
|---|---|
| basic | types, duplicate keys, missingness, **NULL-encoding variants** (a `-999` creatinine is a number, so nothing downstream fails), zero spikes, isolated extremes, impossible signs |
| temporal | treatment before time zero (immortal time), outcome before treatment, interval inversion, follow-up shorter than the outcome window |
| identification | prevalence, overlap, SMD, instrument relevance and endogeneity, the declared roles against the adjustment set, the family against the question, population filters |
| feasibility | per-arm sizes and event counts, extreme weights and effective sample size |

Two properties the checks are built around. **A check that could not run is counted, never
listed**: it stood down because the spec declares no column for it to read, or because an
answer in the spec settles what it would ask, and in both cases it found nothing. Ten rows
reading "not assessed" above the findings is how a reader stops reading a table. And
**a suggested fix is offered, never applied**: when a check can name the exact operation
that would address what it found, the agent offers it and the user agrees in their own
words before anything runs.

## Installing

Core stays light (pydantic, pyyaml, pandas, numpy). A family's heavy dependencies live
behind an extra:

| extra | Pulls in | Needed by |
|---|---|---|
| `hte` | EconML, linearmodels, scikit-learn, statsmodels, scipy, joblib | `hte_iv`, `hte_backdoor` |
| `dynamic` | scikit-learn, scipy, joblib | `dynamic_lag_dml` |

`dynamic_lag_dml` needs no EconML: its estimator is written here, and what it uses is
gradient boosting for the continuation model, a linear model for the two orthogonal
nuisances, and joblib for the bootstrap. `linearmodels` is in `hte` for exactly one
statistic, the robust overidentification test, and [ADR-0004](docs/decisions/0004-linearmodels-for-overidentification-only.md)
records why a hand-written version was rejected: it got the degrees of freedom wrong,
k instead of k-1, while agreeing with the package's verdict on every design it was tried
on, which is how that ships unnoticed.

```bash
# spec, quality checks and report rendering only
uv sync

# to run HTE estimation
uv sync --extra hte
```

With pip: `pip install causpec` or `pip install 'causpec[hte]'`.

**A missing extra does not surface as an ImportError**, the registry returns a
structured error carrying the install command:

```console
$ causpec estimate --spec spec.yaml --data cohort.csv
[FAMILY_DEPENDENCY_MISSING] family hte_iv has an uninstalled dependency (econml)
  Fix: Install causpec[hte]: uv sync --extra hte (or pip install 'causpec[hte]')
```

## Repository layout

The **library** is the thick part and holds every computation. The **skill** is a thin
shell that drives it. An **MCP server** is designed as the primary form and is not built, so
nothing in the tree stands in for it.

```
packages/causpec/          the library, 10k lines; all computation lives here
  core/                      core never imports a family (enforced by import-linter in CI)
    contracts/                 Spec, QualityIssue, Result, Manifest, Suggestion
    quality/                   the four check layers, ~30 checks, thresholds in yaml
    sensitivity/               the E-value and the three refutation tests
    reporting/                 addresses, placeholder rendering, claim level, the DAG
    runtime/                   RunContext, atomic writes, audit log, manifest, snapshot
    mapping/                   preprocessing steps applied to a working copy
    grouping.py                cutting a covariate into the groups an effect is reported for
    fingerprint.py             content fingerprints, normalised so a re-export still matches
    population.py              the population filters and the exclusion ledger
    gates.py                   the three gate conditions, as `if` statements
    registry.py                the family registry: core's only interface to a family
    adapters/                  declared, not implemented: csv and parquet are read in cli.py
  families/                  plugins; a new analysis is a directory and one registration
    hte_backdoor/  hte_iv/  dynamic_lag_dml/
      family.yaml                what it identifies, needs, assumes, refuses, and tabulates
  cli.py                     causpec columns / quality / estimate

tests/                     9k lines, 685 tests; each file documents a property, not a function
skill/causpec-analyst/     SKILL.md, 8 reference files, scripts/run.py
docs/                      design.md, plan.md, decisions/ (four ADRs), evals/
data/generators/           synthetic data with ground truth (output is never committed)
scripts/                   build the skill bundle, and the pre-commit data-file guard
```

Eight directories and six files, which is the whole of it. The MCP server, the Postgres
adapter and the deployment examples are designed in `docs/design.md` sections 5, 6 and 12 and
are **not built**, so they have no directories: an empty folder holding one README is a
roadmap pretending to be code, and the roadmap is `docs/plan.md`.

A family is a directory. `family.yaml` is where it declares the estimands it can
identify, the spec fields it needs, the assumptions each estimand rests on, the questions
it refuses, its check thresholds, the result tables the report should render, and which
number the refutation tests should compare. Core reads all of that and knows nothing about
what a lag or a complier is: a CI test asserts the string `lag` does not appear in the
reporting module.

What is declared and not implemented, stated here rather than discovered: the MCP server,
the Postgres adapter, the example deployments, and the golden-task evals. [plan.md](docs/plan.md)
has the order.

## Estimators and confidence intervals

`hte_iv` has two backends, selected through `spec.estimation.params.estimator`. Both
binary and continuous instruments are supported.

| | `ivforest` (default) | `dmliv` |
|---|---|---|
| Class | `econml.grf.CausalIVForest` | `econml.iv.dml.NonParamDMLIV` |
| CATE interval | GRF honest variance, within one fit | bootstrap |
| ATE interval | unit-level bootstrap of the forest | bootstrap |
| Per replicate | about 5s (n=5000) | about 26s |
| Multiple instruments / `adjustment_set` | not supported | supported |

**Why `dmliv` can only bootstrap**: its final model is an arbitrary regressor, so
EconML can derive no variance for it, `_get_inference_options()` lists nothing else.
That is not a choice, it is the only option.

**Why `ivforest`'s ATE interval also bootstraps**: `econml.grf` exposes only
**pointwise** variance (the covariance matrix from `predict_and_var` is across output
dimensions at a single x, not across different x). The per-point estimates from one
forest are highly correlated, so averaging pointwise variances and dividing by n would
assume independence. The CATE interval therefore uses GRF's analytic variance while the
ATE interval bootstraps, different mechanisms, recorded separately in
`res:cate.ci_method` and `res:primary.ate_ci_method` for the report to explain.

**The replicate count** defaults to 200 for both backends and is overridable:

```yaml
estimation:
  params:
    estimator: ivforest
    n_bootstrap_samples: 200   # below 100, res:estimation.bootstrap_adequate = "no"
    bootstrap_n_jobs: 8        # indices are drawn up front, so this cannot change the result
```

Lowering the count distorts the interval: on the same data, 20 replicates and the GRF
analytic interval differed by two orders of magnitude in the count of individuals with
a significant benefit (416 against 3). Below the threshold the Result is flagged and the
report has to surface it.

## Development

```bash
uv sync --all-extras --dev   # everything
uv run pytest                # 685 tests
uv run ruff check .          # lint
uv run pyright               # types; CI pins Python 3.11
uv run lint-imports          # the architecture contract: core must not import a family
pre-commit install           # enable the pre-commit checks, including the data-file block
```

**Real patient data must never enter this repository.** Three things enforce it: a
`.gitignore`, a pre-commit hook, and `scripts/check_no_data_files.py`. Synthetic data is
generated on demand and its output is gitignored.

**The tests are written to document properties, not to cover functions.** Each file opens
with what it is defending and why that matters, and several pin a mistake that was made
and corrected, so it cannot come back quietly: that a fill's spread statistic has to be
measured among the filled values rather than over the column, that a snapshot's
fingerprint has to be recomputable from the snapshot, that rounding a hash moves the
instability rather than removing it.

## Synthetic data

```bash
# Dataset A, with ground truth. What it produces is never committed.
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset realistic
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset high_power --instrument-kind binary
```

`realistic` matches the scale of the real ICU study (about 9.5% treated, about 4%
mortality) and is what demos and quality checks use. `high_power` raises the complier
share and event rate for numerical evals, at the realistic scale an IV analysis has a
standard error larger than the truth itself, and numerical tests drown in noise.

## Inside the skill

Loading it is at the top of this file. What is in it:

```
skill/causpec-analyst/
  SKILL.md                 the eight steps, the two paths, and the rules that are not negotiable
  references/
    workflow.md              the long form of the steps
    spec-fields.md           every spec field, what it means, and what it costs to get wrong
    quality-checks.md        how to explain a failed check to a user
    claim-levels.md          what each level permits in prose, and sensitivity wording
    variable-roles.md        X versus W, and what can never enter the adjustment set
    hte-dmliv.md             the IV backends and their intervals
    dynamic-lag-dml.md       the panel family's estimand and its checks
    reporting.md             the report's structure and which sections the model may write
  scripts/run.py           the only way the skill reaches the data
```

The references exist because `SKILL.md` has to stay short enough to be read in full. A CI
test asserts that every check declared in a family's `family.yaml` is explained in
`quality-checks.md`, and that every blocking one is marked as blocking: documentation that
drifts from the code is worse than none, so the drift is a test failure.

## Documentation

- [Design](docs/design.md), the authority on what the system is and why each decision went
  the way it did, including the ones that were reversed
- [Plan](docs/plan.md), the order of work and what is done
- [Decision records](docs/decisions/), four ADRs: the ADR policy, the data-source boundary,
  writing the basic checks without pandera, and linearmodels for one statistic
- [Changelog](CHANGELOG.md), which records why each change was made and not only what
  changed

## Credit

The estimators come from EconML; the refuters from DoWhy; the unmeasured-confounding
sensitivity analysis from DoubleML; the overidentification test from linearmodels. The
E-value and the effective F test are written here, each with a regression test against the
numerical example in its original paper. The claim-level ladder and the fixed report
structure were adapted from the Baygent `causal-inference` skill (MIT), and the modules
holding them say so.

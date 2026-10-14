# CauSpec

[![CI](https://github.com/EllaZhouhan/causpec/actions/workflows/ci.yml/badge.svg)](https://github.com/EllaZhouhan/causpec/actions/workflows/ci.yml)

Turn a causal question in plain language into an analysis spec confirmed field by field;
assess whether the data can support that question before estimating anything; run the
estimation in deterministic code; and produce a report whose every number traces back to a
computation. Data sources are read-only throughout.

A question it is built for:

> I have ICU data at `/Users/me/extracts/cohort.csv`, one row per patient. Does dialysis
> change the chance of dying, and are there patients who benefit more?

What comes back is not a number in a chat window. It is a spec you confirmed field by
field, a quality report that may refuse to proceed, an estimate with an interval, and a
report whose claim level says how strongly the finding may be worded.

## Status

| | |
|---|---|
| Built, tested, runnable | the library, the CLI (`columns`, `quality`, `estimate`, `report`), three estimator families, the four check layers, the claim level, the report as Markdown or as a self-contained web page, run directories with a manifest |
| Built, validated by hand | the agent workflow. Its evidence is a log of manual runs in [docs/evals/](docs/evals/manual-workflow-test.md), each finding and the change it caused. Automated golden tasks are not written, so "the agent behaves" rests on that log rather than on a suite |
| Designed, not built | the MCP server, the Postgres adapter, the example deployments. [docs/plan.md](docs/plan.md) has the order |

Not on PyPI yet, so installation is from the repository.

## Quickstart

Synthetic data with known ground truth, then four commands, with nothing to configure.

The first two lines are a clone and an install, and they are separate because they do
different things. `git clone` copies this repository's files to disk and runs nothing, which
is deliberate: a clone that executed an installer would be a way to run code on your machine
for anyone who could get you to clone something. `uv sync` then fetches the 61 third-party
packages this code needs, EconML and the rest, at the exact versions `uv.lock` pins. Those
are not in the repository, because a few hundred megabytes of someone else's releases do not
belong in it; the lock file records which ones instead.

```bash
git clone https://github.com/EllaZhouhan/causpec.git && cd causpec
uv sync --extra hte

# Synthetic dataset A: an ICU cohort where unmeasured severity drives both treatment and
# death, so the naive comparison is biased and an instrument is what identifies.
uv run python data/generators/dataset_a.py --out /tmp/icu.csv \
    --preset realistic --seed 7 --n 4000

# 1. What is in the file: every column described on its own, grouped by shape
uv run causpec columns --data /tmp/icu.csv

# 2. Can the data answer the question in the spec? Blocking issues stop here
uv run causpec quality --spec docs/examples/icu-iv.yaml --data /tmp/icu.csv

# 3. Estimate. Prints the numbers, the claim level, and why it is not higher
uv run causpec estimate --spec docs/examples/icu-iv.yaml --data /tmp/icu.csv \
    --run-dir runs/example

# 4. Turn that run into the report, estimating nothing again
uv run causpec report --run-dir runs/example \
    --narrative docs/examples/narrative.yaml \
    --out /tmp/report.md --html /tmp/report.html --open
```

**Steps 3 and 4 are separate on purpose**, because the numbers come before the prose: the
user sees what came back, and the interpretation is written about it afterwards. `report` renders
a run that is already finished, in under a second, so the second stage costs nothing and the
document describes that run rather than a second one. `--open` opens the page in the browser,
which is the only renderer every machine has.

Step 3 takes about five minutes on a laptop, most of it the two-hundred-replicate bootstrap
behind the interval; add `--no-sensitivity` for a first look, and the report will say the
refuters did not run rather than leaving that section blank. Step 4 takes under a second.

The committed result of exactly those commands is in
[docs/examples/report.md](docs/examples/report.md), with the spec and the narrative beside
it.

**What that run demonstrates**, and the reason the quickstart uses generated data: the
generator prints the truth it built in. The average effect is −0.0014, the effect among
the treated is −0.0222, and the naive difference in death rates is +0.0245, because
unmeasured severity drives both the decision and the outcome. Put the same file through
`hte_backdoor` and the overlap check **refuses to proceed**: 26.2% of patients have a
propensity score outside [0.05, 0.95], which is what it looks like when the thing that
decided treatment is not in the data. Waive the check and it returns +0.0177, the wrong
sign, with the claim level dropped to `associational` and the waiver and its reason printed
in the report. The IV route passes the checks and estimates −0.025 for the local effect
among the patients whose treatment follows the instrument, next to the −0.0222 the
generator built for the treated.

A wrong answer is available if you insist, in other words, and it arrives labelled.

The generator is seeded, so those commands produce the same file on any machine, and the
`source data fingerprint` printed at the top of the committed report is the one your own run
should show. If it does not, the two runs were not analysing the same data, which is the
question a fingerprint exists to answer.

Then the agent, which is what the library is built for:
[docs/installation.md](docs/installation.md) has the three ways to load the skill, in
Claude Code for data anywhere on your machine, inside this repository, or uploaded to
claude.ai.

The skill form is marked **best-effort** for one honest reason: an agent is technically
able to bypass `scripts/run.py` and read the data itself, so in this form "only code
produces numbers" rests on the agent following its own rules. Every report says so in its
header.

## What it is for

Causal analysis on observational data usually fails before the estimation: treatment,
outcome and time zero are vaguely defined; a post-treatment variable or a positivity
problem goes unnoticed; definitions drift between datasets; numbers cannot be reproduced.
Tools of the "LLM plus code" kind add a failure of their own: the model computing, or
inventing, the numbers itself.

Four principles:

1. **Code computes the facts, the model exercises judgement, the framework holds the gate.**
2. **Every critical spec field carries a source** (user / model / data) **and a status**
   (drafted / confirmed); nothing is estimated until all of them are confirmed.
3. **Only code produces numbers.** Report prose may cite them only through addresses,
   which a renderer substitutes; an un-placeheld number fails the render.
4. **The claim level is decided by code from the diagnostics** (causal / suggestive /
   associational / descriptive) and the model may not upgrade it.

On the fourth: a claim level is a statement about **how this report may be worded**, given
what the spec declares and what the diagnostics found. It is not a verdict that
identification holds. `causal` means the untestable assumptions were justified by a person
who signed for them and no diagnostic contradicted the design; it does not mean the
assumptions are true, and code is not able to establish that they are.

## What a run actually does

Eight steps. Six of them involve the user, including the confirmation at step 7, and the
estimation never starts before it.

```
1  the question, the data's shape, how the treatment was assigned     with the user
2  map the concepts onto columns                                      with the user
3  variable roles, which become the diagram and are checked           with the user
4  identification strategy and the assumptions it rests on            with the user
5  the estimand: which question the number answers, and for whom      with the user
6  quality checks: 4 core layers, then the family's own               in code
7  the user confirms the whole analysis, in their own words           with the user
8  estimate, refute, and render                                       in code
```

The report has two kinds of content, and they never mix:

**Generated by code, and the model cannot write them:** the spec table with each field's
source, status and the user's own words, and the data's content fingerprint; an exclusion
ledger if any population filter ran, and the preprocessing steps applied; the
variable-role diagram, derived from the declared roles; the quality table, every check
with its verdict; the primary result, the breakdown by named group, the E-value and the
three refutations; and the claim level with the reasons code used to decide it.

**Written by the model:** the interpretation of six sections, where every number is a
placeholder resolving to a computed address, so an un-placeheld number fails the render.
[docs/examples/narrative.yaml](docs/examples/narrative.yaml) is a real one.

## Supported analyses

| family | Estimands | Notes |
|---|---|---|
| `hte_backdoor` | `ate`, `att`, `cate`, `gate` | Backdoor adjustment with a causal forest. `gate` reports the effect for named groups, which is the answer to "who benefits"; `cate` reports a per-patient cloud that names nobody |
| `hte_iv` | `conditional_late`, `weighted_conditional_late` | Binary and continuous instruments. Every effect here is **local**: it is the effect among the patients whose treatment responds to the instrument, and the report says so in those words. A population effect and a per-patient effect are **refused** with reasons, because compliers cannot be identified individually. The interval mechanisms differ by backend, which the report states: [docs/methods/hte-iv.md](docs/methods/hte-iv.md) |
| `dynamic_lag_dml` | `lag_profile`, `lag_cate` | What one treatment period does to that period's outcome and to later ones, with continuation weighting for an informative horizon. Its intervals are exploratory, so no lag may be called significant |

The estimand is reconciled against the family at the gate. It is a label no estimator
reads, so `conditional_late` on `hte_backdoor` would otherwise print the words for an
effect among compliers over an average across everyone.

Designs outside that range (difference in differences, regression discontinuity, synthetic
control, mediation) are refused explicitly, with a reason for each excluded family, as are
questions a supported family cannot answer.

## What the checks cover

Four layers in `core`, which run for every family, then the family's own design checks.

| layer | Examples |
|---|---|
| basic | types, duplicate keys, missingness, **NULL-encoding variants** (a `-999` creatinine is a number, so nothing downstream fails), zero spikes, isolated extremes, impossible signs |
| temporal | treatment before time zero (immortal time), outcome before treatment, interval inversion, follow-up shorter than the outcome window |
| identification | prevalence, overlap, SMD, instrument relevance and endogeneity, the declared roles against the adjustment set, the family against the question, population filters |
| feasibility | per-arm sizes and event counts, extreme weights and effective sample size |

**Where the thresholds come from**, since they decide how strongly a finding may be
worded. Three kinds, and the config says which for each: a convention from the literature
where one exists (first-stage robust F at 10, absolute SMD at 0.10, a 0.10 false-discovery
rate, ten events per variable); a value measured against this project's own data where
none does (the twenty-distinct-values rule that separates an ordinal score from a
measurement came from this data's own columns, which have 2, 2, 2, 2, 4 and 18 levels
against 3,226 for the smallest real measurement); and an engineering default where the
quantity is a budget rather than a test (the bootstrap replicate count). All of them live
in `core/quality/basic_checks.yaml` or a family's `family.yaml`, all are configurable, and
the manifest records the config's hash so a verdict can be reproduced.

Two properties the checks are built around.

**A check that did not run is counted, never listed.** It stood down because the spec
declares no column for it to read, or because an answer in the spec settles what it would
ask. Either way it produced no finding, and the report says how many of the catalogue
applied rather than listing ten rows of "not assessed" above the findings. A check that
did not run is not evidence either way, which is why the count stays visible.

**A suggested fix is offered, never applied.** When a check can name the exact operation
that would address what it found, the agent offers it and the user agrees in their own
words before anything runs. A recode that reveals 200 missing values has not cleared the
problem, it has made it visible, and the next refusal is the honest one.

## Repository layout

The **library** is the thick part and holds every computation. The **skill** is a thin
shell that drives it.

```
packages/causpec/          the library; all computation lives here
  core/                      core never imports a family (enforced by import-linter in CI)
    contracts/                 Spec, QualityIssue, Result, Manifest, Suggestion
    quality/                   the four check layers, thresholds in yaml
    sensitivity/               the E-value and the three refutation tests
    reporting/                 addresses, placeholder rendering, claim level, the DAG, and
                               the report as a self-contained web page
    runtime/                   RunContext, atomic writes, audit log, manifest, snapshot
    mapping/                   preprocessing steps applied to a working copy
    inventory.py               every column described one at a time, for the roles step
    fingerprint.py             content fingerprints, normalised so a re-export still matches
    gates.py                   the three gate conditions, as `if` statements
    registry.py                the family registry: core's only interface to a family
  families/                  plugins; a new analysis is a directory and one registration
    hte_backdoor/  hte_iv/  dynamic_lag_dml/
      family.yaml                what it identifies, needs, assumes, refuses, and tabulates
  cli.py                     causpec columns / quality / estimate / report

tests/                     each file documents a property, not a function
skill/causpec-analyst/     SKILL.md and eight reference files
docs/                      design.md, plan.md, CHANGELOG.md, decisions/, evals/, examples/
data/generators/           synthetic data with ground truth (output is never committed)
scripts/                   build the skill bundle, and the data-file guard
```

A family is a directory. `family.yaml` is where it declares the estimands it can identify,
the spec fields it needs, the assumptions each estimand rests on, the questions it refuses,
its check thresholds, the result tables the report should render, and which number the
refutation tests should compare. Core reads all of that and knows nothing about what a lag
or a complier is: a CI test asserts the string `lag` does not appear in the reporting
module.

A directory appears when its code does, so what is designed and not built has no folder.
The names are reserved in [docs/design.md](docs/design.md) section 5.

## Installing

Three ways, depending on what you want.

| | What you get | Where it works |
|---|---|---|
| **The agent**, which is what this is for | the skill, plus the command it drives | any directory, any Claude Code session |
| **The command only**, no clone needed | `causpec` on your PATH | any directory |
| **A clone**, for reading the code and running the quickstart | the repository and its own environment | inside the clone, as `uv run causpec ...` |

**The agent, in one line.** Paste it anywhere; it clones into the current directory.

```bash
git clone https://github.com/EllaZhouhan/causpec.git && cd causpec && \
  uv tool install --from . causpec && mkdir -p ~/.claude/skills && \
  ln -sfn "$PWD/skill/causpec-analyst" ~/.claude/skills/causpec-analyst
```

Four steps, chained, and each one is there for a reason: the clone brings the files, the
install puts `causpec` on your PATH, and the symlink is what makes Claude Code find the
skill. `git clone` cannot do the other three itself, and that is deliberate rather than a
gap: git copies files and never executes anything from a repository, or cloning something
would be a way to run a stranger's code. A symlink rather than a copy, so editing `SKILL.md`
in the clone takes effect on the next message; keep the clone where it is, and redo the link
if you move it.

The other two forms, for when you want less:

```bash
# The command only, straight from GitHub, no clone and no cd
uv tool install --from git+https://github.com/EllaZhouhan/causpec.git causpec

# A clone with its own environment, for reading the code and running the quickstart
git clone https://github.com/EllaZhouhan/causpec.git && cd causpec && uv sync
```

**Neither of those installs the estimators**, and that is deliberate. The spec, the column
inventory, the quality checks and the report renderer need nothing but the core, which is a
few seconds; EconML and its neighbours are hundreds of megabytes that a user whose data turns
out to be the wrong shape never needed. Add them when something asks for them: `uv sync
--extra hte` in a clone, or re-run the `uv tool install` above with
`--with 'causpec[hte]' --force`. The agent does this for you, asking once, since installing
changes your machine and reading your data does not. Add `--extra hte` up front if you would
rather wait once.

**Where the command is installed has nothing to do with where your data is.** Your extract
stays wherever you keep it and `--data /Users/me/extracts/cohort.csv` is the ordinary case.
The only reason the first form clones is that the skill is a folder of files Claude Code reads
from `~/.claude/skills/`, and the second two commands point at the clone through `--from .`
and `$PWD`.

The skill is text, eight Markdown files the model reads, so it needs no installing and the
symlink is the whole of it. The command is Python and does need installing, which is why both
halves appear above: the skill's instructions tell the model to run `causpec`, and an agent
whose first command does not exist gets no further. [docs/installation.md](docs/installation.md)
has the claude.ai form as well.

**One trap worth knowing.** `uv run causpec` finds the nearest `pyproject.toml` above the
current directory, so inside the clone it runs that clone's copy. Outside it, there is no
project to find and the command falls back to whatever is on your PATH, which may be an older
install. It does not complain, so when the two could differ, check with `uv run which causpec`.

Core stays light (pydantic, pyyaml, pandas, numpy). Heavy dependencies live behind extras:

| extra | Pulls in | Needed by |
|---|---|---|
| `hte` | EconML, linearmodels, scikit-learn, statsmodels, scipy, joblib | `hte_iv`, `hte_backdoor` |
| `dynamic` | scikit-learn, scipy, joblib | `dynamic_lag_dml` |
| `parquet` | pyarrow | reading a `.parquet` extract; CSV needs nothing |

```bash
uv sync                  # spec, quality checks and report rendering only
uv sync --extra hte      # to run HTE estimation
uv sync --all-extras     # everything, including the panel family and parquet
```

**`uv.lock` is why a result is reproducible at all.** `pyproject.toml` asks for
`econml>=0.15`, which is a range; the lock file says `econml 0.17.0`, and pins all 61
packages the same way. A seed alone is not enough: it fixes the random numbers, and a minor
EconML release that changes a default hyperparameter gives a different estimate from the same
seed. The run manifest records the installed versions for the same reason.

With pip instead of uv, from a clone: `pip install '.[hte]'`. That ignores the lock file, so
the versions float and reproducibility becomes yours to manage. Not published to PyPI yet, so
`pip install causpec` does not work.

`dynamic_lag_dml` needs no EconML: its estimator is written here, and what it uses is
gradient boosting for the continuation model, a linear model for the two orthogonal
nuisances, and joblib for the bootstrap. `linearmodels` is in `hte` for exactly one
statistic, the robust overidentification test, and
[ADR-0004](docs/decisions/0004-linearmodels-for-overidentification-only.md) records why a
hand-written version was rejected: it got the degrees of freedom wrong, k instead of k-1,
while agreeing with the package's verdict on every design it was tried on, which is how
that ships unnoticed.

**A missing extra does not surface as an ImportError**, the registry returns a structured
error carrying the install command:

```console
$ causpec estimate --spec spec.yaml --data cohort.csv
[FAMILY_DEPENDENCY_MISSING] family hte_iv has an uninstalled dependency (econml)
  Fix: Install causpec[hte]: uv sync --extra hte in the repository, or pip install '.[hte]' from a clone
```

## Data handling

**Real patient data must never enter this repository**, and three layers make an accidental
commit hard rather than merely discouraged: `.gitignore` blocks the data extensions
wholesale, a pre-commit hook runs `scripts/check_no_data_files.py` over the staged files,
and CI runs the same script over every tracked file, which catches anything that arrived
through `git add -f` or a gap in the ignore rules. A fixture is allowed through only under
`tests/fixtures/` and only up to 4KB; that limit is a size rule and not a judgement about
content, so the no-real-data rule still rests on the person committing. Synthetic data is
generated on demand and its output is gitignored.

A run reads its source read-only and writes nowhere near it: preprocessing returns a copy,
the exclusion ledger records who was dropped and why, and the audit log records a hash of
each call's parameters rather than their contents, because a path leaks directory structure
and a column name leaks the schema.

## Documentation

- [Installing and loading the agent](docs/installation.md), the three forms, and what is
  inside the skill bundle
- [Example](docs/examples/report.md), a full report from the quickstart, with its
  [spec](docs/examples/icu-iv.yaml) and [narrative](docs/examples/narrative.yaml)
- [Design](docs/design.md), the authority on what the system is and why each decision went
  the way it did, including the ones that were reversed
- [The IV backends](docs/methods/hte-iv.md), the two estimators and where each interval
  comes from
- [Plan](docs/plan.md), the order of work and what is done
- [Decision records](docs/decisions/), four ADRs
- [Changelog](docs/CHANGELOG.md), which records why each change was made, not only what
  changed
- [Development](docs/development.md), the commands and how the tests are written
- [Manual workflow log](docs/evals/manual-workflow-test.md), every finding from running the
  agent against the synthetic data, and the change each one caused

## Credit

**Depended on:** EconML for `CausalForestDML` and `CausalIVForest`; linearmodels for one
statistic, the robust overidentification test; scikit-learn, statsmodels and scipy for the
nuisance models and the first-stage tests.

**Written here, each with a regression test against the original paper's numerical
example:** the E-value (VanderWeele and Ding 2017) and the three refutations, a placebo
treatment, a random common cause and subset stability. The refutations follow DoWhy's
design, which is where that set of tests comes from, but no DoWhy code is used and it is
not a dependency.

**Adapted, with the notice in the module that holds it:** the claim-level ladder and the
report's fixed section order, from the Baygent `causal-inference` skill (MIT). See
`core/reporting/claim_level.py` and `core/reporting/report.py`.

The repository has no licence, so it is readable but not reusable. That is deliberate for
now rather than an omission.

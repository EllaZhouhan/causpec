# CauSpec

Turn a causal question in plain language into an analysis spec confirmed field by
field; assess whether the data can support that question before estimating anything;
run the estimation in deterministic code; and produce a report whose every number
traces back to a computation. Data sources are read-only throughout.

> Status: early development (v0.0). The repository is private for now and goes public
> after v0.3.

## What it is for

Causal analysis on observational data usually fails before the estimation: treatment,
outcome and time zero are vaguely defined; a post-treatment variable or a positivity
problem goes unnoticed; definitions drift between datasets; numbers cannot be
reproduced. Tools of the "LLM plus code" kind add a failure of their own — the model
computing, or inventing, the numbers itself.

Four principles:

1. **Code computes the facts, the model exercises judgement, the framework holds the gate.**
2. **Every critical spec field carries a source** (user / model / data) **and a status**
   (drafted / confirmed); nothing is estimated until all of them are confirmed.
3. **Only code produces numbers.** Report prose may cite them only through addresses,
   which a renderer substitutes; an un-placeheld number fails the render.
4. **The claim level is decided by code from the diagnostics** (causal / suggestive /
   associational / descriptive) and the model may not upgrade it.

## Supported analyses

| family | Notes |
|---|---|
| `hte_iv` | Heterogeneous treatment effects under an IV design; binary and continuous instruments |
| `hte_backdoor` | Heterogeneous treatment effects under backdoor adjustment |
| `longitudinal_ipcw` | Longitudinal treatment effects via IPCW (not implemented) |

Designs outside that range — difference-in-differences, regression discontinuity,
synthetic control — are refused explicitly, with a reason given for each excluded
family.

## Installing

Core stays light (pydantic, pyyaml, pandas, numpy). A family's heavy dependencies live
behind an extra:

| extra | Pulls in | Needed by |
|---|---|---|
| `hte` | EconML, scikit-learn, statsmodels, scipy, joblib | `hte_iv`, `hte_backdoor` |

```bash
# spec, quality checks and report rendering only
uv sync

# to run HTE estimation
uv sync --extra hte
```

With pip: `pip install causpec` or `pip install 'causpec[hte]'`.

**A missing extra does not surface as an ImportError** — the registry returns a
structured error carrying the install command:

```console
$ causpec estimate --spec spec.yaml --data cohort.csv
[FAMILY_DEPENDENCY_MISSING] family hte_iv has an uninstalled dependency (econml)
  Fix: Install causpec[hte]: uv sync --extra hte (or pip install 'causpec[hte]')
```

## Repository layout

Three deliverables live in one repository: the **library** is the thick part, the **MCP
server** and the **skill** are two thin shells that call it. Both forms call the same
`causpec` functions and produce the same run-directory layout.

```
packages/causpec/          the library; all computation lives here
  core/                      core never imports a family (enforced by import-linter in CI)
    contracts/                 Spec, QualityIssue, Result, Manifest
    adapters/                  csv, parquet, postgres (read-only)
    mapping/                   lightweight mapping and the variable catalogue
    quality/                   the four check layers
    runtime/                   RunContext, atomic writes, audit log, manifest
    reporting/                 address resolution, placeholder rendering, claim level
    registry.py                the family registry: core's only interface to a family
  families/                  plugins; a new analysis is a directory and one registration
    hte_iv/  hte_backdoor/  longitudinal_ipcw/
  cli.py                     causpec quality / estimate / report

server/causpec_mcp/        the MCP server (primary form): holds credentials, runs the gates
skill/causpec-analyst/     the skill (secondary form): SKILL.md, references, scripts
evals/                     numerical, quality-check, robustness, reporting, agent, regression
data/generators/           synthetic data generators (what they produce is never committed)
examples/deployments/      demo-hospital and demo-retail configuration examples
deploy/                    a local Postgres demo (read-only account plus views)
docs/                      design.md, plan.md, decisions/
```

Outside the skeleton most of this is still empty; it fills in stage by stage, per
[plan.md](docs/plan.md).

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
EconML can derive no variance for it — `_get_inference_options()` lists nothing else.
That is not a choice, it is the only option.

**Why `ivforest`'s ATE interval also bootstraps**: `econml.grf` exposes only
**pointwise** variance (the covariance matrix from `predict_and_var` is across output
dimensions at a single x, not across different x). The per-point estimates from one
forest are highly correlated, so averaging pointwise variances and dividing by n would
assume independence. The CATE interval therefore uses GRF's analytic variance while the
ATE interval bootstraps — different mechanisms, recorded separately in
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
uv run pytest                # tests
uv run ruff check .          # lint
uv run lint-imports          # the architecture contract: core must not import a family
pre-commit install           # enable the pre-commit checks, including the data-file block
```

## Synthetic data

```bash
# Dataset A, with ground truth. What it produces is never committed.
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset realistic
uv run python data/generators/dataset_a.py --out /tmp/a.csv --preset high_power --instrument-kind binary
```

`realistic` matches the scale of the real ICU study (about 9.5% treated, about 4%
mortality) and is what demos and quality checks use. `high_power` raises the complier
share and event rate for numerical evals — at the realistic scale an IV analysis has a
standard error larger than the truth itself, and numerical tests drown in noise.

## The skill

`skill/causpec-analyst/` is the form used on claude.ai (best-effort). To package it:

```bash
./scripts/build_skill.sh     # build the wheel into assets, emit dist/causpec-analyst-skill.zip
```

The wheel is a build product and is not committed — a committed wheel drifts silently
from the source, and the wheel is what the skill runs.

**Trying it in Claude Code**: `.claude/skills/causpec-analyst` is a symlink to
`skill/causpec-analyst`, so a clone has it immediately with no packaging step, and an
edit to SKILL.md takes effect at once.

**Trying it on claude.ai**: upload `dist/causpec-analyst-skill.zip` (Settings ->
Capabilities -> Skills). That environment cannot install a local package, so it needs
the wheel.

**Why best-effort**: an agent is technically able to bypass `scripts/run.py` and read
the data itself, so in skill form "only code produces numbers" rests on the agent
following the rules. The report header notes this. MCP form does not have the problem —
there the model can only reach the data through declared tools (not implemented yet).

## Documentation

- [Design](docs/design.md)
- [Plan](docs/plan.md)
- [Decision records](docs/decisions/)

## Licence

MIT (see [LICENSE](LICENSE)). External sources and their licences are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

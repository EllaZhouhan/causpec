# CauSpec development plan

Version: 0.4
Author: Han Zhou
Updated: 2026-09-27
Companion document: design.md

---

## 1. Principles

- Reach something demonstrable early, then deepen it version by version.
- One task at a time, each as a pull request.
- Reuse where reuse is possible (the [reuse] markers in design.md); the work written
  here concentrates on the spec, the quality checks, the gates, the reporting, and the
  author's own two methods.
- The week counts below already include about 20% slack.

---

## 2. Milestones

| Version | Week | Dates (indicative) | Contents | Shown externally |
|---|---|---|---|---|
| v0.0 | W1 | 9/21-9/27 | Productionising the research code, contracts, synthetic dataset A | none |
| v0.1 | W3 | 10/5-10/11 | An end-to-end HTE slice: CSV, quality checks, estimation, a placeholder report, the CLI | a local CLI demo |
| v0.2 | W4 | 10/12-10/18 | The skill, the skill+CLI form, a first set of golden tasks | a claude.ai demo |
| v0.3 | W5 | 10/19-10/25 | The local MCP server, the gates, the Postgres demo | three demos |
| v0.4 | W7 | 11/2-11/8 | Longitudinal IPCW | a longitudinal demo |
| v1.0 | W8 | 11/9-11/15 | README, Related work, video, blog post | all of it |

Adjustment in version 0.3: dropping the relational shape and the third shape of dataset
B, and dropping the StatsPAI dependency, saves about a week; that week goes into Phase 4
so longitudinal IPCW can be delivered complete, with estimation.

---

## 3. Prerequisites

- Only code written for this project enters this repository. The research code it
  generalises stays where it is, and nothing derived from a collaborator's work is
  published without their agreement.
- From day one, pre-commit blocks csv, parquet, xlsx, duckdb and similar data files from
  entering a commit.
- Credit the external sources in the README: the estimators, the refuters, the
  sensitivity analysis and the overidentification test. Where code was adapted rather
  than depended on, the module that holds it says so in its own docstring.

---

## 4. Work by phase

### Phase 0 (W1)

1. Repository setup: uv, ruff, pyright, pytest, pre-commit, CI, import-linter (rule:
   core must not import a family)
2. Contracts: Spec (field-level source and status, variable_roles, key_non_edges),
   QualityIssue, Result (with addresses), Manifest
3. Migrate DMLIV into families/hte_iv, strip the I/O, and write numerical regression
   tests
4. A generator for synthetic dataset A (cross-sectional part), with ground truth
5. ADRs: record only decisions the design document does not cover, or that are
   counter-intuitive enough that someone will later try to "simplify" them away.
   Written: 0001 (literal numbers in reports), 0002 (data-source boundaries).
   Not written: computation on the server, field-level confirmation, the core/family
   split, the external-code reuse policy: design.md already states these, and an ADR
   would only duplicate them.

### Phase 1 (W2-W3)

1. csv/parquet adapter, the derived snapshot, the normalised fingerprint. **Done**, with two
   departures recorded in design.md 6.5: the snapshot is gzipped CSV rather than parquet,
   because pyarrow is a forty-megabyte dependency for one artefact and dtype preservation is
   what the fingerprint normalises away; and there are two fingerprints rather than one, over
   the source and over the analysed table, because they answer different questions. The
   source one drives the earlier-runs report of 6.6, which is the thing a data fingerprint
   does that nothing else can
2. Lightweight mapping and the population. `population.filters`
   with a closed operator set, applied after preprocessing and before every check, with an
   exclusion ledger in the report and two checks pricing what each filter removed. This closed
   the hole where the missing-value refusal recommended an exclusion the spec had no way to
   express. Four imputations too, offered as a menu with what each costs, and any of them
   makes the run exploratory because the pooling step that would justify the interval is not
   built. The preprocessing half is in:
   `recode_null` and `cast` applied to a working copy from an ordered `spec.preprocessing`,
   offered by the check that found the problem and written down in the user's own words.
   Two of the six designed operations, because those are the two a check can suggest. A step
   reveals rather than repairs, which is why accepting the sentinel recode moves the refusal
   from the NULL-encoding check to the missingness check rather than clearing it
3. Estimand declarations in family.yaml, route_family and estimand reconciliation;
   rendering the variable-role diagram. The diagram is in: roles and key_non_edges are
   declared in the spec, the edges are derived from the role rather than drawn, one node per
   group with a count and two examples, mermaid in the report and DOT in the run directory.
   `roles_match_adjustment` compares the declaration with what the analysis conditions on,
   which is the reason for deriving it. No DoWhy and no graph library: the derived graph has a
   fixed shape, so the backdoor criterion over it reduces to a rule per role. The estimand
   reconciliation and the routing are in too, as gate condition 3 plus one warning
   (design.md 7.6): the gate refuses a missing required field and an estimand the family
   cannot identify, and the check warns when the family does not match the data's shape or how
   the treatment was assigned. Writing the gate found three overstated declarations, including
   a required field name no family code reads
4. Basic-layer quality checks, written here rather than with pandera (ADR-0003): types,
   uniqueness, missingness, NULL-encoding variants, zero spikes, isolated extremes and
   impossible signs, run before the design-level checks for every family. Plus the counting
   half of the feasibility layer, arm sizes and event counts, which blocks where design.md
   10.2 says not to gate, because a forest on too few events returns a confident per-patient
   estimate that the interval does not contradict
5. Temporal-consistency checks: immortal time, outcome before treatment, interval
   inversion, follow-up shorter than the outcome window. Each reads optional spec fields and
   reports when it could not run. Instrument relevance gained two checks from linearmodels
   instead of the effective F: a robust overidentification test when more than one
   instrument is declared, and a test of whether the treatment behaves endogenously at all.
   The effective F is dropped: no Python package implements it (the canonical ones are
   Stata's weakivtest and R's momentfit), and hand-writing a statistic whose critical values
   come from simulation is not the kind of closed form this project writes by hand. Shea's
   partial R-squared was considered and rejected: with one endogenous treatment it equals the
   ordinary partial R-squared however many instruments there are
6. Dataset C: eleven defects, each one a mistake that happens to real extracts, each
   declaring the check_id and severity it expects, asserted in CI across all three core
   layers. A defect caught by the wrong check is worse than one caught by none, so the test
   checks both directions
7. The hte_backdoor family ([reuse] EconML CausalForestDML)
8. **Dropped.** HTE calibration (DRTester, an IV-appropriate score, rank stability). The
   question it answers, is the estimated heterogeneity real or noise, is worth asking, and
   the counting half of the feasibility layer already refuses the designs where the answer
   is certainly noise. Carrying a second, heavier apparatus for the same question was not
   worth it, and a declaration naming a validator nobody calls is worse than no declaration
9. Sensitivity and refutation. **Done**, and neither borrowed dependency was needed. The
   E-value is written here and checked against VanderWeele and Ding (2017): a risk ratio of
   3.9 gives 7.26, a lower limit of 1.8 gives 3.0. The three refuters are written against
   this project's own `Family` protocol in about forty lines, which makes them work for the
   panel family too, so DoWhy is not a dependency. DoubleML's `sensitivity_analysis` is not
   used: it bounds omitted-variable bias for a DML estimator and these families fit a causal
   forest, so it would mean a second estimator on the same data and a second set of numbers
   to reconcile. A failed refutation pulls the claim level to `associational`, and the
   refuters re-fit the estimator, so `--no-sensitivity` exists and the report says when they
   did not run
10. Runtime: RunContext, atomic writes, audit, manifest
11. Reporting: address resolution, placeholder rendering, the claim-level decision
    ([reuse] adapted from Baygent's check_refutation.py, MIT notice retained)
12. CLI: quality, estimate, report (tag v0.1)

### Phase 2 (W4)

1. SKILL.md and the references ([reuse] structure and key rules follow Baygent
   causal-inference)
2. scripts/run.py and the wheel; verified on claude.ai
3. Ten golden tasks and a scoring sheet; a comparison with and without the skill loaded
   ([reuse] organisation follows Baygent's evals) (tag v0.2)

### Phase 3 (W5)

1. The MCP server: tools, readOnlyHint, outputSchema; data-source boundaries (root /
   allowed_relations, see ADR-0002)
2. The gates and structured errors (the registry pattern follows StatsPAI's
   agent/remediation.py, practice only)
3. A thin postgres adapter; a read-only account and views in docker-compose; doctor
   verifying that the account genuinely cannot write. masked_columns and schema drift
   move past v1.0
4. Dataset B in two shapes (wide table, long event table) and the robustness evals
5. Record three demos: the successful path, the change-of-shape path that only edits the
   mapping, and the safe-failure path where the data is bad and no conclusion is drawn
   (tag v0.3)

After v0.3 the repository goes public.

### Phase 4 (W6-W7)

1. Write dynamic-lag-dml.md and families/dynamic_lag_dml/family.yaml first: the
   structural model, the estimand, the assumptions, and the four questions the family
   refuses (design.md 7.3, which the reading of the author's paper rewrote)
2. The panel spec: unit_id, period_index, period_length, state, treatment,
   instant_outcome, max_lag, termination; the within-period order is what the checks
   enforce
3. Port the estimator: cross-fitted sequential peeling with IPCW, the constant profile
   and the linear-in-state projection, patient-level bootstrap. Numerical regression
   tests against the paper's own simulation design, including the ablation ordering
4. A panel generator with known ground truth (theta_kappa = mu' B^(kappa-1) C),
   informative exit and variable-length trajectories, the two presets from the paper
5. Panel quality checks: period gaps and duplicates (blocking), post-treatment state
   columns, continuation positivity and the weight product, lag relevance J (blocking),
   the per-lag analysis set and attrition
6. Reporting: the profile as a table and a figure, the exploratory-interval rule in
   claim_levels.yaml, and the skill turning from "refuses longitudinal questions" to
   "routes the lag-profile question here and still refuses the other three"
7. Expand the golden tasks past twenty (tag v0.4)

### Phase 5 (W8)

1. examples/deployments: demo-hospital, demo-retail, and dataset D
2. README: positioning, an architecture diagram, a demo GIF, Related work, and the
   external sources
3. A demo video (3-5 minutes); a technical blog post (tag v1.0)

---

## 5. Git conventions

- `main` always runs; features merge through a pull request, and only after CI passes.
- Commit messages follow conventional commits.
- Tag each milestone and update the CHANGELOG.
- On a day spent only on research, commit an ADR.
- When external code is reused, note the source, version and licence in the docstring of
  the module that holds it, which is where someone reading that code will look.

---

## 6. Risks

| Risk | Response |
|---|---|
| The research code cannot yet be open-sourced | Substitute an interface-compatible reference implementation, and swap it once confirmed |
| Real data ends up in the repository | The pre-commit hook blocks it; only synthetic data is used |
| A closed-form diagnostic written here (E-value, effective F) is wrong | Each carries a regression test against the original paper's numerical example, with the test written first |
| Longitudinal semantics are complex | Write the document before the code; do not let it block the v0.3 applications |
| Scope creep | New ideas go to the backlog and are assessed only between milestones |

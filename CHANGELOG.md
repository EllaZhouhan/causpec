# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/); version numbers match
the milestones in plan.md section 2.

## [Unreleased]

### Added

- **The `dynamic_lag_dml` family** (design.md 7.3): the lag profile of one treatment
  period on per-period outcomes, on panel data whose trajectories end at state-dependent
  and treatment-dependent times. Two estimands, `lag_profile` and `lag_cate`; the
  structural model the profile derives from; six assumptions with the evidence named for
  the three that data can speak to; and the four neighbouring questions the family refuses
  by name (a strategy contrast, a cumulative effect, a survival endpoint, a terminal
  outcome). Ported from the author's paper: cross-fitted sequential peeling, one
  partially linear problem per lag, and inverse-probability-of-continuation weighting for
  the informative horizon. Needs `causpec[dynamic]`, which is scikit-learn and joblib, not
  econml
- **`lag_cate`, and the restriction that makes it meaningful**: the lag effect may vary
  only with variables the treatment does not move. Otherwise one treatment period reaches a
  later outcome by two routes, the second multiplied by the treatment in between, and the
  outcome stops decomposing into lag effects: there is no profile, and fitting one returns
  plausible numbers that are not any effect. Found by testing rather than by reading, when
  the generator's first heterogeneity design put the lag-2 estimate at +4.7 where its
  nominal truth was +1.2. A blocking, waivable check now refuses a modifier that varies
  within a unit
- **The horizon is a confirmed field, and a fixed one applies no weighting**: `horizon`
  (fixed or variable) and, when variable, `termination` (how leaving is identified) are both
  required, and the estimator refuses without them. Under a fixed horizon no continuation
  model is fitted and every weight is exactly one, with `res:profile.horizon` and
  `res:profile.ipcw_applied` on the result so the report says the weighting was skipped
  rather than leaving a reader to infer it from weights of one.
  It is confirmed rather than inferred because one pair of worlds is indistinguishable by
  shape: a panel where every unit has eight periods is either a fixed horizon or a cohort
  truncated to the units that lasted eight periods, and the second is conditioned on
  surviving, which no weighting repairs. Measured on the benchmark, keeping the 3.5% of units
  that reach eight periods moves the lag-1 estimate from 4.22 to 2.87 against a truth of 4.0.
  The `horizon_declaration` check compares the declaration with the data and refuses both
  contradictions, and rows recorded after a unit left are refused outright
- **Reaching the end of the observation window is not leaving**: only a real exit is evidence
  that a trajectory could have continued and did not, so a trajectory cut off by the window
  contributes no record to the continuation model. Where a column marks exits, the column
  decides; otherwise a trajectory that stops before the window is read as having left
- **Seven panel quality checks**: period gaps and duplicates (blocking, not waivable,
  because the lag index counts rows and a gap silently relabels every later lag), a state
  column that is nearly a copy of the same period's treatment, too few complete windows per
  lag, continuation positivity, lag relevance J, and the per-lag composition of the
  analysis set. The positivity threshold is on the effective number of windows, not on the
  largest weight: these weights are heavy-tailed even on the design the method was proved
  on, and an earlier version thresholding the maximum refused that design at 800 units
- **The panel part of dataset A**: an episodic trajectory generator with the lag profile
  known in closed form, reproducing both of the paper's designs, their true profiles
  (-0.5, 4.0, 1.2) and (-0.5, 3.6, 1.08), and their descriptives (about 54% of periods
  treated, a mean of 2.9 periods). Continuation positivity holds by construction, so the
  strength of the selection can be turned up without breaking the assumption
- **The claim-level decision gained a second axis**: `interval_calibration`. An estimator
  proved consistent without a limiting distribution has intervals that indicate where an
  effect sits and test nothing, so `significance_claims_allowed` goes false and the level
  is capped, independently of data quality. A calibrated interval on a waived analysis
  still cannot say "caused"; an exploratory interval on a spotless one still cannot say
  "significant". An unknown calibration raises rather than defaulting to calibrated
- **The skill form is usable**: a complete SKILL.md (eight key rules, eight workflow
  steps), eight references, a narrative template, `scripts/run.py` (importing straight
  out of the bundled wheel when causpec is not installed in the sandbox), and
  `scripts/build_skill.sh` for packaging
- **Skill consistency tests**: the families, checks, writable sections and claim levels
  the documentation lists must match what the code actually does; documentation drifts,
  and these tests pin the two together
- **Fixed report structure** (design.md 10.3): ten sections in an order decided by code,
  so "assumptions before results" is a structural guarantee rather than a reminder. The
  spec-provenance table and the claim-level decision are code-generated and the model may
  not author them; the remaining sections accept interpretation, always through
  placeholder rendering
- **Placeholder format specs**: `{{res:primary.ate|+.3f}}`, `{{qc:...frac|.1%}}`; without
  them the report shows 17 significant digits, and a model's natural response to that is
  to round it itself, which defeats G4
- **CLI `--report` / `--narrative`**: `--report` emits the fixed structure, `--narrative`
  takes a YAML mapping of `{section: prose}`
- **Runtime** (design.md section 14, G5): `RunContext` persists a run directory,
  `Manifest` records everything that can change the result (code version, dependency
  versions, spec_hash, seed, decision-rule hash), each artefact's sha256, and `verify()`
  detects later tampering. Every write is atomic (temporary file in the same directory,
  fsync, `os.replace`)
- **Audit log**: one line per call, with **the parameters hashed rather than stored**;
  metadata passes a sensitive-key check that raises on password/dsn/token and similar, so
  "no credentials in the log" is enforced by code
- **CLI `--run-dir`**: persist a whole run, including the waiver reasons
- **The claim-level decision** (design.md 10.2, principle 5): the four-level rules live in
  `core/reporting/claim_levels.yaml` and the decision carries the rules hash. The ceiling
  for an automatic decision is suggestive: untestable assumptions cannot be verified by
  any diagnostic, so reaching causal takes a user justification for each and explicit
  approval. A waiver does not change the diagnosis
- **The `Assumption` contract**: three categories (empirically_assessed /
  requires_justification / untestable), justification text, and `justified_by`; a model's
  own justification does not count
- **The `claim:` namespace**; the renderer now takes a merged address table, so `res:`,
  `qc:` and `claim:` can be cited in one report
- **`hte_backdoor` switched to CausalForestDML**, with both the CATE and ATE intervals
  from `blb` (bootstrap of little bags), needing no resampling
- **Overlap / positivity checks** (the other blocking check), SMD before and after IPW,
  Kish effective sample size, treatment prevalence. Propensity scores are cross-fitted,
  gradient boosting by default
- **CLI `quality` subcommand**; `estimate` now runs the checks before the gate, and
  `--waive CHECK_ID=reason` waives a waivable blocking check
- **The `QualityIssue` / `QualityReport` contracts** (design.md 8.3): check_id, layer,
  severity, waivable, evidence, affected_columns, impact_on_analysis, recommended_repair,
  with every piece of evidence addressable as `qc:<check_id>.<key>`
- **Instrument checks for `hte_iv`**: migrated from the research code's
  `test_iv_validity`: relevance (linear robust F, partial R-squared, probit LR test,
  McFadden increment), complier share, covariate balance with a Benjamini-Hochberg FDR
  correction. Thresholds live in family.yaml
- **Gate condition 2**: refuse to estimate while a blocking quality issue stands
  unwaived; a waiver requires a reason, and a check marked not waivable is never let
  through
- **A generator for synthetic dataset A**: a structural causal model with per-individual
  ground truth, where unmeasured confounding biases both the naive estimate and backdoor
  adjustment so that only IV identifies; binary and continuous instruments; `realistic`
  and `high_power` presets
- **The `hte_iv` family**: two backends (`ivforest` = CausalIVForest, the default;
  `dmliv` = NonParamDMLIV, matching the research code's final version), both instrument
  kinds. `ivforest`'s CATE interval uses GRF honest variance while its ATE interval uses
  a unit-level bootstrap of the forest, because econml.grf exposes pointwise variance
  only. The replicate count is shared by both backends, defaults to 200, is overridable
  from the spec, and parallelises through `bootstrap_n_jobs` (indices are drawn up front,
  so parallelism cannot change the result)
- The `causpec[hte]` extra: econml and scikit-learn; a missing dependency yields a
  structured error carrying the install command
- The repository skeleton: uv, ruff, pyright, pytest, pre-commit, CI, import-linter
- Data-file blocking (`.gitignore` plus a pre-commit hook)
- The full directory structure with each layer's responsibilities documented; a
  `family.yaml` declaration for each of the three families
- The vertical slice: Spec (field-level source/status), the gate, addressed Results,
  placeholder rendering, the CLI
- ADR-0001 (literal numbers in reports), ADR-0002 (data-source boundaries)

### Changed

- **The continuation model no longer treats the end of every trajectory as an exit.** It
  used to, which asks the model to predict "is this the last period" from the state and the
  treatment, and the period index is not among them. On an eight-period balanced panel that
  produced fitted continuation probabilities as low as 0.40 and weights up to 4.3 in a world
  where every weight should have been 1. The ratio moment was nearly immune, because a
  roughly constant weight cancels, but the variance was not, and the report would have told
  the reader there was censoring to correct when there was none

- **`longitudinal_ipcw` became `dynamic_lag_dml`**, and its contents changed with its
  name. The old declaration specified the seven components of a target trial plus
  event_roles mapping death, discharge and transfer to outcome, competing, censoring or
  terminal. That is the layout for a marginal structural model comparing two strategies
  on a survival endpoint, which is not the method this project has: here termination ends
  the observation window rather than being the outcome, and death and discharge are the
  same event. The old name kept promising the wrong estimand, and nothing caught it
  because nothing compared the declaration against the method. design.md 7.3 now says so
  in as many words, and the skill's `longitudinal-ipcw.md` became `dynamic-lag-dml.md`,
  which turns "CauSpec refuses longitudinal questions" into one question it will answer
  and three it will not
- **The skill asks one more question about a time-varying treatment**: whether a version
  of the data exists with one row per unit per window. Previously the branch dead-ended,
  telling the user a longitudinal design was needed and stopping there

- **The project is now English-only**: code, docstrings, user-facing strings, YAML
  declarations, tests, docs, the skill and commit messages
- **Rendering errors are now readable and actionable**: a bare number is answered with
  what to write instead (`28 -> write {{lit:28}}`), and when the value is close to a
  computed result the address to cite is named; the address list is grouped by namespace
  and truncated rather than dumping dozens inline. This came out of the cold-start test,
  where the original message buried the fix
- **Package resources are read through `importlib.resources`** (`family.yaml`,
  `claim_levels.yaml`). The previous `Path(__file__).parent` finds no file when the
  package is imported out of a wheel: a bug found by actually running the skill's
  `run.py` in a clean environment
- Reading a family's declaration no longer imports that family:
  `resources.files("causpec.families.hte_iv")` executes its `__init__` and pulls in
  econml, which turned "missing dependency" into a misreported "unknown family"
- The registry now imports by id, so core hard-codes no family import;
  `family.yaml`'s `requires_extra` drives the install hint
- Data is passed as a pandas DataFrame throughout (previously `list[dict[str, str]]`)
- Estimator hyper-parameters moved into `spec.estimation.params` (design.md 7.2): they
  change the result, so they must enter spec_hash and the manifest
- design.md 0.4:
  - The derived snapshot no longer commits to DuckDB; it states two contracts (a writable
    working copy and a normalised content fingerprint), with parquet as the default
    implementation and a columnar engine only once the data exceeds memory
  - Postgres delivery narrowed: v0.3 ships a thin adapter and a docker-compose demo,
    enough to show a read-only view can be connected and that read-only comes from
    account permissions; masked_columns and schema drift move later
  - The `contradicted` field status is removed. A conflict between data and spec produces
    a blocking quality issue, which gate condition 2 already stops; a second status is
    two mechanisms doing one job
  - `status: confirmed` now requires `said`, the user's words at confirmation, regardless
    of source. This plugs the gate's root hole: update_field is called by the model, and
    the server cannot verify that confirmation ever happened
  - 10.2 made quantitative: code can only reach suggestive, and causal requires a person
    to vouch for the untestable assumptions; the blocking checks narrow from an open list
    to two (overlap, instrument relevance) on the principle that "if the confidence
    interval already says it, do not gate on it"; every other diagnostic is reported and
    not gated on
- design.md / plan.md 0.3:
  - G2 drops from three shapes to two (the relational shape and dataset B's third shape
    are removed)
  - The StatsPAI dependency is dropped; the E-value and the effective F test are written
    here with numerical regression tests, sensitivity moves to DoubleML, and the AR test
    goes to the backlog
  - The week saved goes into Phase 4, so longitudinal IPCW can be delivered complete
  - The ADRs drop from a planned five to two: only decisions the design document does not
    already cover

# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/); version numbers match
the milestones in plan.md section 2.

## [Unreleased]

### Added

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

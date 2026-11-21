# Installing and loading the agent

Three forms, and the short version is in the README. This page has all of them, what is
inside the skill bundle, and the dependencies.

## The three forms

The workflow is an agent skill. It drives the library, so the agent is what you talk to
and the library is what computes.

**In Claude Code or Codex, for your own data anywhere on the machine.** A clone, and a link
in each harness's personal skill folder.

```bash
git clone https://github.com/EllaZhouhan/causpec.git && sh causpec/install.sh
```

The clone lands in the directory the terminal is in, so run it from wherever CauSpec should
live. Any location works, because the links record the clone's absolute path and every harness
reads them from its own fixed folder, whatever directory a session starts in.

`install.sh` looks for each harness it knows, by its command on PATH or its config folder, and
links the skill into that harness's folder:

| Harness | Found by | Skill folder |
|---|---|---|
| Claude Code | `claude`, or `~/.claude` | `~/.claude/skills/` |
| Codex | `codex`, or `~/.codex` | `~/.agents/skills/` |

If it finds neither, it links for both, so whichever is installed later finds the skill. The
folders differ because the skill standard fixes what a skill contains and leaves where it lives
to each harness. Supporting another harness is one line in the script, plus that folder in the
probe in `SKILL.md`, and a test checks the two agree.

Nothing Python is installed, and nothing has to be: the agent installs the library the first
time it runs a command and the estimators the first time something needs them, asking before
each. It locates the clone through the same link, by resolving it from whichever folder the
harness read it from. Running the script again is safe: it replaces its own links and leaves a
real folder in the way untouched, saying so.

Installing up front is one more command, run from the directory that holds the clone, and
means the first analysis is never interrupted:

```bash
uv tool install --from ./causpec causpec                              # the core, about a second
uv tool install --from ./causpec --with 'causpec[hte]' causpec        # with the estimators
```

Now any `claude` or `codex` session in any directory has it. Ask a causal question and it
should trigger on its own; `/causpec-analyst` in Claude Code or `$causpec-analyst` in Codex
invokes it explicitly. The conversation was developed and tested with Claude, so try a first
analysis in Codex before relying on it. Data paths can be absolute and usually are, since your extract lives wherever you keep it:

> I have ICU data at `/Users/me/extracts/cohort.csv`, one row per patient. Does dialysis
> change 28-day mortality, and are there patients who benefit more?

A symlink rather than a copy, so editing `SKILL.md` in the clone takes effect on the next
message. If you move the clone, run `install.sh` again. Run `uv tool upgrade causpec` after pulling,
since the installed command is a snapshot rather than a live link to the source; it keeps the
extras you installed.

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

**Without an agent**, the library has a CLI and the same gates apply. [overview.md](overview.md#running-it-without-the-agent)
runs it end to end on generated data.

The skill is marked **best-effort** for one honest reason: an agent is technically able
to bypass `scripts/run.py` and read the data itself, so in this form "only code produces
numbers" rests on the agent following its own rules. Every report says so in its header.

## Inside the skill

Loading it is above. What is in it:

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
`quality-checks.md`, and that every blocking one is marked as blocking, so a document that
falls behind the code fails the suite rather than misleading a reader.

## Dependencies and reproducibility

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
[ADR-0004](decisions/0004-linearmodels-for-overidentification-only.md) records why a
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

**One trap worth knowing.** `uv run causpec` finds the nearest `pyproject.toml` above the
current directory, so inside the clone it runs that clone's copy. Outside it, there is no
project to find and the command falls back to whatever is on your PATH, which may be an older
install. It does not complain, so when the two could differ, check with `uv run which causpec`.

## What `ln -sfn` does

`install.sh` runs it once per harness. It creates a symlink, a name that points at a file
elsewhere rather than a copy of it. Claude Code loads personal skills from `~/.claude/skills/`
and Codex from `~/.agents/skills/`, and the files live in your clone, so each link makes
`<that folder>/causpec-analyst` mean `<clone>/skill/causpec-analyst`. `-s` is the pointer rather than a copy, `-f` overwrites a
name that is already there, and `-n` replaces an existing link instead of creating one inside
the directory it points at. A link rather than a copy because editing `SKILL.md` then takes
effect on the next message, where a copy would quietly drift from the repository. The cost is
that the clone has to stay where it is; if you move it, run `install.sh` again from the new place.

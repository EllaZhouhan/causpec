# Installing and loading the agent

Three forms, and the short version is in the README. This page has all of them, plus
what is inside the skill bundle.

## The three forms

The workflow is an agent skill. It drives the library, so the agent is what you talk to
and the library is what computes.

**In Claude Code, for your own data anywhere on the machine.** Two things: the command on
your PATH, and the skill in your personal skill directory.

```bash
git clone https://github.com/EllaZhouhan/causpec.git && cd causpec && \
  uv tool install --from . causpec && mkdir -p ~/.claude/skills && \
  ln -sfn "$PWD/skill/causpec-analyst" ~/.claude/skills/causpec-analyst
```

One line, four steps: the files, the command on your PATH, the skill directory, and the link
that makes Claude Code find the skill. The estimators are not installed here, because nothing
before the estimation step needs them and they are hundreds of megabytes; the agent asks and
installs them the first time something does. Add `--with 'causpec[hte]'` to the
`uv tool install` if you would rather wait once, up front.

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

**Without an agent**, the library has a CLI and the same gates apply. The README's
quickstart runs it end to end on generated data.

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

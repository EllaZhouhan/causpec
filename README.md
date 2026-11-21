# CauSpec

[![CI](https://github.com/EllaZhouhan/causpec/actions/workflows/ci.yml/badge.svg)](https://github.com/EllaZhouhan/causpec/actions/workflows/ci.yml)

**Estimate causal effects through a conversation from your data.**

CauSpec is a skill: a set of instructions and tested code that you add to an AI agent such as
Claude Code or Codex. With it, you ask a question in plain words, such as "did our spring
discount increase repeat purchases?", and the agent works through the analysis with you as a
conversation. At the end you get a report with the answer and how strongly it can be stated.

Suppose you have data on people, stores or other units, where some received a treatment and the
rest did not: patients given dialysis or not, stores offered a discount or not, employees sent
on a training course or not. The data also records the outcome, or overall evaluation criterion
(OEC), that the treatment is expected to change, such as whether a patient died or how much a
store sold, and other information about each unit, such as age or region. You want to know
whether the treatment changed the outcome, and perhaps for whom it worked best.

The data can come from a randomised trial or an A/B test, where chance decided who was
treated. More often it comes from records kept as things happened, where a doctor, a manager
or the people themselves decided. This is called observational data, and it is where the
question is easiest to get wrong.

It is easy to get wrong because a simple comparison mixes up the effect of the treatment with
the reasons people received it. Doctors give dialysis to the
sickest patients, so patients on dialysis can die more often even when dialysis helps them. In
the synthetic ICU data this repository generates, patients who had dialysis died about 2.5
percentage points more often than those who did not, although the data was built so that
dialysis lowers the risk for those who receive it. The same trap appears whenever someone
chooses who gets the treatment: a discount sent to the customers most likely to leave, or a
course taken by the most motivated staff.

So before anything is estimated, the agent asks how the treatment was decided and what else
could explain the outcome, because that is what decides whether a comparison is fair. CauSpec's
code then checks whether your data can answer the question, runs the estimation, and decides how
strongly the report may word the result.

You do not need to write code or know the statistics. You need to know your data and your field.

## What it can answer

- **Did it make a difference on average?** For example, whether a spring discount increased
  repeat purchases across a chain's stores.
- **Who benefits more?** The effect for groups you choose. For example, whether dialysis helps
  older patients more than younger ones.
- **What if something unrecorded drove both the treatment and the outcome?** It can still
  answer if the data has an instrumental variable: something that affects who is treated, is
  unrelated to the unrecorded factors, and affects the outcome only through the treatment. In
  the example conversation below it is the consultant on shift: some consultants start dialysis
  far more readily than others, and which one is on shift is close to random.
- **How does a treatment given period by period affect the outcome over time?** With one row per
  person per week or month, it estimates what one period of treatment does in that period and in
  the periods after. For example, what one week of reminder notifications does to app use that
  week and in the weeks that follow.

## How it works

You describe your question in your own words, and the agent takes it from there, asking one
question at a time about things only you can answer. The analysis goes through six stages:

1. **What you want to compare.** Which treatment, which outcome, and which columns hold them.
2. **How the treatment was decided.** A randomised trial, or someone choosing case by case,
   and what they based the choice on. This decides which method gives a fair comparison.
3. **What else is in the data.** The agent shows you every column, proposes which to use, and
   asks which were recorded after the treatment started, since those would distort the answer.
4. **Whether the data can support the question.** Code checks the data. If it finds a serious
   problem, it stops and the agent explains the problem in plain words.
5. **Your confirmation.** The agent reads the whole analysis back to you. Nothing is estimated
   until you agree.
6. **The result and the report.** The agent tells you what came back in a few lines, then
   writes a report that opens in your browser.

Every number in the conversation and in the report is computed by CauSpec's code. The agent
explains the numbers; it does not produce them.

## Install

You need [Claude Code](https://claude.com/claude-code) or
[Codex](https://developers.openai.com/codex), and
[uv](https://docs.astral.sh/uv/getting-started/installation/), which the agent uses to install
CauSpec's Python code.

The install downloads CauSpec into a new folder called `causpec`, inside whichever folder your
terminal is in. So first choose where to keep it, somewhere you will not tidy away later, and
move there in a terminal. A new terminal starts in your home folder; to use another, type `cd`
followed by its path, such as `cd ~/Documents`. Then run this, on macOS or Linux:

```bash
git clone https://github.com/EllaZhouhan/causpec.git && sh causpec/install.sh
```

It downloads CauSpec, then tells Claude Code, Codex or both where to find it, depending on
which you have. Keep the `causpec` folder where it is: the agent finds CauSpec through it, so
moving or deleting it breaks the skill. If you do move it, run `install.sh` again from its new
place. Once installed, CauSpec works in a terminal opened in any folder.

That is all. The first time you use CauSpec, the agent asks your permission to install its
code, which takes a few seconds. When it reaches the estimation, it asks once more, this time to
install the statistics packages, about 300MB. The agent runs both installs itself.

## Start a conversation

Open a terminal and start Claude Code or Codex:

```bash
claude      # or: codex
```

Then ask your question in plain words, and say where your data file is:

> I have sales data for 200 stores at `~/data/stores.csv`. Did the spring discount increase
> repeat purchases?

The agent recognises a question like this and uses CauSpec on its own. To call it by name,
type `/causpec-analyst` in Claude Code or `$causpec-analyst` in Codex, followed by your
question.

Your data can be anywhere on your computer, as a CSV or Parquet file. CauSpec reads it where it
is and never changes, moves or copies it. The agent does see what CauSpec prints, such as column
summaries, check results and estimates, so follow your organisation's rules on using AI tools
with your data.

## What you get

A report, as a web page and as a Markdown file, with:

- your question, and each decision in the analysis next to the words you used to make it
- every data check that applied, and what it found
- the result with its interval, and the group of people it applies to
- robustness checks, and how strong a hidden factor would have to be to explain the result away
- the limitations
- the **claim level**, which sets how strongly the report may word its conclusion:

| Claim level | The report may say | When |
|---|---|---|
| causal | "dialysis reduced mortality" | the checks passed, and you signed off on the assumptions no data can test |
| suggestive | "the data suggests dialysis may lower mortality" | the checks passed |
| associational | "treated patients had lower mortality", with no causal reading | a serious problem was found and you chose to continue anyway |
| descriptive | the numbers for each group, and nothing more | the analysis was not fully confirmed, or a serious problem was left unresolved |

Code decides the level from the checks and from your sign-off. The agent cannot raise it.

## More

- [docs/installation.md](docs/installation.md): other ways to install, and the dependencies
- [docs/overview.md](docs/overview.md): how it works in technical terms, the checks, and
  running the library from the command line without an agent
- [docs/design.md](docs/design.md): the design and the reasons behind each decision
- [docs/development.md](docs/development.md): running the tests and contributing

To update CauSpec later, run `git pull` in the `causpec` folder. If you have already used it,
also run `uv tool upgrade causpec`, from any folder, which refreshes the installed code and keeps
the statistics packages.

## An example conversation

This is shortened. The numbers come from the example analysis in this repository, which was run
on synthetic ICU data.

> **You:** I have ICU data on about 4,000 patients at `~/data/icu.csv`, one row each. Does
> dialysis change the chance of dying, and do some patients benefit more than others?
>
> **Agent:** I'll help you estimate the effect of dialysis on the chance of dying. First I'll
> pin down the exact question, then check whether the data can support it, and then estimate
> the effect from the data. Was dialysis given in a trial where patients were randomised to
> it, or did the clinical team decide case by case?
>
> **You:** The team decided.
>
> **Agent:** What was in front of them when they decided? And is there anything that mattered
> to the decision which the data doesn't record?
>
> **You:** Labs, vitals and the SOFA score. But also how sick the patient looked at the
> bedside, and there's no column for that. Which consultant is on shift is close to random,
> though, and some consultants start dialysis far more readily than others.
>
> **Agent:** Then the consultant on shift is what makes a fair comparison possible, and the
> answer will be about the patients whose dialysis depended on who was on. Which column
> records the consultant?
>
> **You:** `instrument`. It's how readily that consultant starts dialysis.
>
> **Agent:** The outcome column is `death`, 0 or 1, so it records whether they died at any
> point in this record. Is that the outcome you want?
>
> **You:** Yes.
>
> *The agent shows every column in the file, proposes which to use, and asks which were
> measured after dialysis started. A few more questions follow, such as whether the
> consultant could affect the chance of dying in any way other than through dialysis.*
>
> **Agent:** Here is what I'll run. Tell me if any line is wrong.
>
> - Dialysis is `isDialysisICU`, dying is `death`
> - The comparison uses the consultant on shift, so the answer is about the patients whose
>   dialysis depended on who was on
> - The effect may vary over the eight clinical columns, all from the first 24 hours
> - The consultant affects the chance of dying only through dialysis, as you said
>
> The data checks passed with one warning: there are only 25 deaths among the 415 patients
> who had dialysis, so a breakdown by type of patient will be rough.
>
> **You:** That's right, go ahead.
>
> **Agent:** For the patients whose dialysis depended on the consultant, the estimated effect
> is a drop of 2.5 percentage points in the chance of dying. The interval runs from 7.2 points
> lower to 2.2 points higher, so this data cannot tell a benefit apart from no effect. All
> three robustness checks passed. The report can say the data suggests a possible effect; saying
> that dialysis caused it would need your explicit sign-off on the assumptions no data can
> test. Shall I write this up?
>
> **You:** Yes.
>
> **Agent:** Done. The report is open in your browser.

The full report from that analysis is [docs/examples/report.md](docs/examples/report.md).

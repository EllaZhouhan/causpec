# CauSpec

[![CI](https://github.com/EllaZhouhan/causpec/actions/workflows/ci.yml/badge.svg)](https://github.com/EllaZhouhan/causpec/actions/workflows/ci.yml)

**Find out whether something made a difference, by talking it through with Claude.**

You have data on who received something and what happened to them afterwards: patients and a
treatment, stores and a discount, employees and a training programme. You want to know whether
it changed the outcome, and perhaps for whom it worked best.

That question is easy to ask and easy to get wrong. The people who received the treatment
usually differ from those who did not, and a simple comparison mixes those differences up with
the effect itself. CauSpec is a skill for Claude Code that walks you through the analysis as a
conversation. Claude asks what you want to know and how the data came about, checks whether
your data can answer the question, runs the estimation in tested code, and gives you a report
that says how strongly the result can be stated.

You do not need to write code or know the statistics. You need to know your data and your field.

## How it works

You describe your question in your own words. Claude asks one question at a time, about
things only you can answer:

1. **What you want to compare.** Which treatment, which outcome, and which columns hold them.
2. **How the treatment was decided.** A randomised trial, or someone choosing case by case,
   and what they based the choice on. This decides which method is fair.
3. **What else is in the data.** Claude shows you every column, proposes which to use, and asks
   which were recorded after the treatment started, since those would distort the answer.
4. **Whether the data can support the question.** Code checks the data, and if it finds a
   serious problem it stops and explains it in plain words.
5. **Your confirmation.** Claude reads the whole analysis back to you. Nothing is estimated
   until you agree.
6. **The result and the report.** Claude tells you what came back in a few lines, then writes a
   report that opens in your browser.

Every number in the conversation and in the report is computed by CauSpec's code. Claude
explains the numbers; it does not produce them.

## An example conversation

Shortened. The numbers are from the example analysis in this repository, run on synthetic
ICU data.

> **You:** I have ICU data on about 4,000 patients at `~/data/icu.csv`, one row each. Does
> dialysis change the chance of dying, and do some patients benefit more than others?
>
> **Claude:** I'll help you estimate the effect of dialysis on the chance of dying. First I'll
> pin down the exact question, then check whether the data can support it, and then estimate
> the effect from the data. Was dialysis given in a trial where patients were randomised to
> it, or did the clinical team decide case by case?
>
> **You:** The team decided.
>
> **Claude:** What was in front of them when they decided? And is there anything that mattered
> to the decision which the data doesn't record?
>
> **You:** Labs, vitals and the SOFA score. But also how sick the patient looked at the
> bedside, and there's no column for that. Which consultant is on shift is close to random,
> though, and some consultants start dialysis far more readily than others.
>
> **Claude:** Then the consultant on shift is what makes a fair comparison possible, and the
> answer will be about the patients whose dialysis depended on who was on. Which column
> records the consultant?
>
> **You:** `instrument`. It's how readily that consultant starts dialysis.
>
> **Claude:** The outcome column is `death`, 0 or 1, so it records whether they died at any
> point in this record. Is that the outcome you want?
>
> **You:** Yes.
>
> *Claude shows every column in the file, proposes which to use, and asks which were
> measured after dialysis started. A few more questions follow, such as whether the
> consultant could affect the chance of dying in any way other than through dialysis.*
>
> **Claude:** Here is what I'll run. Tell me if any line is wrong.
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
> **Claude:** For the patients whose dialysis depended on the consultant, dialysis lowered the
> chance of dying by 2.5 percentage points. The interval runs from 7.2 points lower to 2.2
> points higher, so this data cannot tell a benefit apart from no effect. All three robustness
> checks passed. The report can say the data suggests a possible effect; saying that dialysis
> caused it would need your explicit sign-off on the assumptions no data can test. Shall I
> write this up?
>
> **You:** Yes.
>
> **Claude:** Done. The report is open in your browser.

The full report from that analysis is [docs/examples/report.md](docs/examples/report.md).

## Install

You need [Claude Code](https://claude.com/claude-code) and
[uv](https://docs.astral.sh/uv/getting-started/installation/), which Claude uses to install
CauSpec's Python code. Then run these two lines in a terminal, on macOS or Linux:

```bash
git clone https://github.com/EllaZhouhan/causpec.git ~/causpec
mkdir -p ~/.claude/skills && ln -sfn ~/causpec/skill/causpec-analyst ~/.claude/skills/causpec-analyst
```

The first line downloads CauSpec into a folder called `causpec` in your home directory. The
second tells Claude Code where to find it. Keep the folder where it is.

That is all. The first time you use it, Claude asks your permission to install CauSpec's code,
which takes a few seconds. When it reaches the estimation, it asks once more to install the
statistics packages, about 300MB. You do not type either command yourself.

## Start a conversation

Open a terminal and start Claude Code:

```bash
claude
```

Then ask your question in plain words, and say where your data file is:

> I have sales data for 200 stores at `~/data/stores.csv`. Did the spring discount increase
> repeat purchases?

Claude recognises a question like this and uses CauSpec on its own. To call it by name, type
`/causpec-analyst` followed by your question.

Your data can be anywhere on your computer, as a CSV or Parquet file. CauSpec reads it where it
is and never changes, moves or copies it. Claude sees what CauSpec prints, such as column
summaries, check results and estimates, so follow your organisation's rules on using AI tools
with your data.

## What you get

A report, as a web page and as a Markdown file, with:

- your question, and each decision in the analysis next to the words you used to make it
- every data check that applied and what it found
- the result with an interval, and for whom it holds
- robustness checks, and how strong a hidden factor would have to be to explain the result away
- the limitations
- the **claim level**, which sets how strongly the report may word its conclusion:

| Claim level | The report may say | When |
|---|---|---|
| causal | "dialysis reduced mortality" | the checks passed, and you signed off on the assumptions no data can test |
| suggestive | "the data suggests dialysis may lower mortality" | the checks passed |
| associational | "treated patients had lower mortality", with no causal reading | a serious problem was found and you chose to continue anyway |
| descriptive | the numbers for each group, and nothing more | the analysis was never fully confirmed |

Code decides the level from the checks. Claude cannot raise it.

## What it can answer

- **Did it make a difference on average?**
- **Who benefits more?** The effect for groups you choose, such as age bands.
- **Something unrecorded drove both the treatment and the outcome**, but something close to
  random also affected who was treated, like the consultant on shift in the example above.
- **The treatment was given period by period**, with one row per person per week or month:
  what one period of treatment does then and in the periods after.

It says so plainly when a question needs a method it does not have: comparing trends before
and after a policy, an eligibility cut-off, mediation, or time until an event as a survival
curve.

## More

- [docs/installation.md](docs/installation.md): other ways to install, including uploading the
  skill to claude.ai, and the dependencies
- [docs/overview.md](docs/overview.md): how it works in technical terms, the checks, and
  running the library from the command line without Claude
- [docs/design.md](docs/design.md): the design and the reasons behind each decision
- [docs/development.md](docs/development.md): running the tests and contributing

To update CauSpec later, run `git -C ~/causpec pull`. If you have already used it, run
`uv tool upgrade causpec` as well, which refreshes the installed code and keeps the statistics
packages.

## Credit

Built on EconML for the causal forests, with linearmodels, scikit-learn, statsmodels and scipy.
The E-value and the refutation tests are implemented here following VanderWeele and Ding
(2017) and the design of DoWhy. The claim-level ladder and the report's section order are
adapted from the Baygent `causal-inference` skill (MIT), with the notice in the modules that
hold them.

The repository has no licence yet, so it is readable but not reusable.

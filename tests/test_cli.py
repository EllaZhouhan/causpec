"""CLI: the quality and estimate subcommands, and waiver parsing.

This pins the path a user actually walks: whether the gate really holds here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from dataset_a import config_for, generate

from causpec.cli import _parse_waivers, main
from causpec.core.runtime.writer import sha256_of

SPEC = """\
spec_version: 1
question: What is the average effect of dialysis on ICU mortality?
family: hte_backdoor
estimation:
  params: {n_estimators: 52}
assumptions:
  - id: unconfoundedness
    category: untestable
    statement: given the adjustment set, assignment is independent of potential outcomes
fields:
  treatment:
    value: isDialysisICU
    source: user
    said: treatment means starting dialysis in the ICU
    turn: 2
    status: confirmed
  outcome:
    value: death
    source: user
    said: the outcome is in-hospital death
    turn: 4
    status: confirmed
  estimand:
    value: ate
    source: model
    said: the population average effect is what I want
    turn: 6
    status: confirmed
  effect_modifiers:
    value: [admission_age, max_aki_stage_smoothed, max_potassium, sofa_total_24h]
    source: user
    said: use these clinical variables
    turn: 8
    status: confirmed
"""

DRAFTED_SPEC = SPEC.replace(
    "    said: the population average effect is what I want\n    turn: 6\n    status: confirmed",
    "    status: drafted",
)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> dict[str, Path]:
    directory = tmp_path_factory.mktemp("cli")
    data = generate(config_for("high_power", seed=100, n=800))
    data.to_csv(directory / "good.csv", index=False)

    rng = np.random.default_rng(0)
    sofa = data["sofa_total_24h"].to_numpy()
    broken = data.copy()
    probability = np.where(sofa > np.median(sofa), 0.97, 0.03)
    broken["isDialysisICU"] = (rng.uniform(size=len(data)) < probability).astype(int)
    broken.to_csv(directory / "broken.csv", index=False)

    (directory / "spec.yaml").write_text(SPEC, encoding="utf-8")
    (directory / "drafted.yaml").write_text(DRAFTED_SPEC, encoding="utf-8")
    return {
        name: directory / name for name in ("good.csv", "broken.csv", "spec.yaml", "drafted.yaml")
    }


def run(*argv: str) -> int:
    """Invoke the CLI, with the refutation tests off for an `estimate`.

    They are on by default in real use and they re-fit the estimator seven times, which took
    this file from 30 seconds to 165. Every test here is about something else, so they are
    switched off and `run_with_refutations` covers the default path explicitly.
    """
    arguments = list(argv)
    if arguments and arguments[0] == "estimate" and "--no-sensitivity" not in arguments:
        arguments.append("--no-sensitivity")
    return main(arguments)


def run_with_refutations(*argv: str) -> int:
    """Invoke the CLI as a user would, with the refutation tests running."""
    return main(list(argv))


# ---- waiver parsing ----


def test_waiver_requires_a_reason() -> None:
    with pytest.raises(SystemExit, match="a waiver needs a reason"):
        _parse_waivers(["backdoor_overlap="])


def test_waiver_parses_reason_with_equals_sign() -> None:
    parsed = _parse_waivers(["overlap=see protocol 3.2, a=b"])
    assert parsed == {"overlap": "see protocol 3.2, a=b"}


def test_no_waivers_is_empty() -> None:
    assert _parse_waivers(None) == {}


# ---- quality ----


def test_quality_returns_zero_on_clean_data(workspace, capsys) -> None:
    assert (
        run("quality", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
        == 0
    )
    assert "backdoor_overlap" in capsys.readouterr().out


def test_quality_returns_nonzero_when_blocking(workspace, capsys) -> None:
    """G3: the quality report still appears when the analysis cannot run, so quality
    requires no confirmed spec,
    but exits non-zero when a blocking issue is present, for scripts to act on.
    """
    code = run(
        "quality", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["broken.csv"])
    )
    assert code == 1
    assert "[blocking]" in capsys.readouterr().out


def test_quality_prints_evidence_addresses(workspace, capsys) -> None:
    run("quality", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
    assert "qc:backdoor_overlap.extreme_fraction" in capsys.readouterr().out


# ---- estimate's gate ----


def test_estimate_blocked_by_unconfirmed_spec(workspace, capsys) -> None:
    code = run(
        "estimate", "--spec", str(workspace["drafted.yaml"]), "--data", str(workspace["good.csv"])
    )
    assert code == 2
    assert "SPEC_NOT_CONFIRMED" in capsys.readouterr().err


def test_estimate_blocked_by_broken_overlap(workspace, capsys) -> None:
    code = run(
        "estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["broken.csv"])
    )
    assert code == 2
    assert "BLOCKING_QUALITY_ISSUES" in capsys.readouterr().err


def test_waiver_with_reason_lets_it_through(workspace, capsys) -> None:
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["broken.csv"]),
        "--waive",
        "backdoor_overlap=restricted to the sub-population with common support, see protocol 3.2",
    )
    assert code == 0
    assert "res:primary.ate" in capsys.readouterr().out


def test_estimate_succeeds_on_clean_data(workspace, capsys) -> None:
    assert (
        run("estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
        == 0
    )
    out = capsys.readouterr().out
    assert "res:primary.ate " in out
    assert "res:primary.ate_ci_method = blb" in out


def test_report_rendering_rejects_bare_numbers(workspace, tmp_path, capsys) -> None:
    narrative = tmp_path / "bad.yaml"
    narrative.write_text("primary_results: the effect is about -0.08.\n", encoding="utf-8")
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        "--narrative",
        str(narrative),
    )
    assert code == 3
    assert "Un-placeheld number" in capsys.readouterr().err


def test_report_rejects_model_written_factual_sections(workspace, tmp_path, capsys) -> None:
    """The spec table and the claim level are generated by code, out of the model's
    reach (design.md 7.1, principle 5)."""
    narrative = tmp_path / "forbidden.yaml"
    narrative.write_text("claim_level: I think causal wording is fine here.\n", encoding="utf-8")
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        "--narrative",
        str(narrative),
    )
    assert code == 3
    assert "generated by code" in capsys.readouterr().err


def test_report_renders_with_placeholders(workspace, tmp_path, capsys) -> None:
    narrative = tmp_path / "ok.yaml"
    narrative.write_text(
        "primary_results: average effect {{res:primary.ate|+.3f}}, "
        "sample {{res:sample.n}} patients.\n",
        encoding="utf-8",
    )
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        "--narrative",
        str(narrative),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "{{" not in out
    assert "800 patients" in out
    assert "## Assumptions" in out  # fixed structure


def test_report_puts_assumptions_before_results(workspace, capsys) -> None:
    """design.md 10.3: a reader sees the assumptions before the numbers."""
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
    )
    out = capsys.readouterr().out
    assert out.index("## Assumptions") < out.index("## Primary results")


# ---- argument surface ----


def test_subcommands_are_registered(capsys) -> None:
    """Both quality and estimate appear in the help text, without poking at argparse
    internals."""
    main([])
    help_text = capsys.readouterr().out
    assert "quality" in help_text
    assert "estimate" in help_text


def test_no_subcommand_prints_help(capsys) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out


# ---- claim level ----


def test_estimate_prints_the_claim_level(workspace, capsys) -> None:
    """The claim level is decided and printed by code; the model never touches it."""
    run("estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
    out = capsys.readouterr().out
    assert "Claim level: suggestive" in out
    assert "unconfoundedness" in out  # why it cannot go higher must be stated


def test_waived_analysis_is_downgraded(workspace, capsys) -> None:
    """A waiver lets the analysis run, but drops the claim level to associational."""
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["broken.csv"]),
        "--waive",
        "backdoor_overlap=restricted to the sub-population with common support",
    )
    out = capsys.readouterr().out
    assert "Claim level: associational" in out
    assert "waived, but the diagnosis is unchanged" in out


# ---- the run directory ----


def test_run_dir_persists_everything(workspace, tmp_path, capsys) -> None:
    """The run-directory layout of design.md section 14."""
    runs = tmp_path / "runs"
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        "--run-dir",
        str(runs),
    )
    assert code == 0
    capsys.readouterr()

    directory = next(runs.iterdir())
    written = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    assert written == {
        "manifest.json",
        "audit.jsonl",
        "spec.yaml",
        "claim_level.json",
        "quality/report.json",
        "results/results.json",
        "report.md",
        # The table every number above came from, after the preprocessing steps and the
        # population filters. Without it the report can be checked against the spec but never
        # against the data it describes.
        "snapshot.csv.gz",
    }


def test_run_dir_manifest_is_verifiable(workspace, tmp_path, capsys) -> None:
    runs = tmp_path / "runs"
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--run-dir",
        str(runs),
    )
    capsys.readouterr()

    directory = next(runs.iterdir())
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_mode"] == "cli"
    assert manifest["seed"] == 42
    assert manifest["claim_rules_hash"]
    for relative, digest in manifest["artifacts"].items():
        assert sha256_of(directory / relative) == digest


def test_audit_records_the_run_without_leaking_paths(workspace, tmp_path, capsys) -> None:
    runs = tmp_path / "runs"
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--run-dir",
        str(runs),
    )
    capsys.readouterr()

    directory = next(runs.iterdir())
    raw = (directory / "audit.jsonl").read_text(encoding="utf-8")
    assert "good.csv" not in raw  # only the parameter hash is recorded
    entry = json.loads(raw.splitlines()[0])
    assert entry["tool"] == "estimate"
    assert entry["meta"]["claim_level"] == "suggestive"
    assert entry["meta"]["family"] == "hte_backdoor"


def test_waivers_are_persisted(workspace, tmp_path, capsys) -> None:
    """The waiver's reason must be persisted: it is the first thing an audit would read."""
    runs = tmp_path / "runs"
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["broken.csv"]),
        "--run-dir",
        str(runs),
        "--waive",
        "backdoor_overlap=restricted to the sub-population with common support",
    )
    capsys.readouterr()

    directory = next(runs.iterdir())
    waivers = json.loads((directory / "waivers.json").read_text(encoding="utf-8"))
    assert waivers == {"backdoor_overlap": "restricted to the sub-population with common support"}


def test_no_run_dir_writes_nothing(workspace, tmp_path, capsys) -> None:
    run("estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
    capsys.readouterr()
    assert not (tmp_path / "runs").exists()


def test_report_can_reference_all_three_namespaces(workspace, tmp_path, capsys) -> None:
    """res: (estimation), qc: (quality checks) and claim: (claim level) can all be cited
    in one piece of prose."""
    narrative = tmp_path / "three.yaml"
    narrative.write_text(
        "primary_results: effect {{res:primary.ate|+.3f}}; "
        "extreme-score share {{qc:backdoor_overlap.extreme_fraction|.1%}}; "
        "level {{claim:level}}.\n",
        encoding="utf-8",
    )
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        "--narrative",
        str(narrative),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "{{" not in out
    assert "suggestive" in out


def test_the_families_interval_calibration_reaches_the_claim_level() -> None:
    """A family proved consistent without a limiting distribution cannot support a
    significance claim, and the CLI has to carry that from family.yaml to the decision.

    Without this wiring the panel family's report would print calibrated intervals it does
    not have, which is the one thing the claim level exists to prevent. A property of the
    method, so it is read from the declaration.
    """
    from causpec.cli import _interval_calibration
    from causpec.core.contracts.spec import Spec

    def calibration_of(family: str) -> str:
        return _interval_calibration(Spec(question="q", family=family))

    assert calibration_of("dynamic_lag_dml") == "exploratory"
    # The cross-sectional families say nothing, and the default is the ordinary case.
    assert calibration_of("hte_iv") == "calibrated"
    assert calibration_of("hte_backdoor") == "calibrated"


def test_a_blocking_gate_reports_the_diagnosis_it_already_computed(workspace, capsys) -> None:
    """The estimate command runs the checks before the gate, so it knows what failed and
    what to do about it. Printing only the check id sends the user to run the quality
    command again to learn what their own error message meant.
    """
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["broken.csv"]),
    )
    assert code != 0
    captured = capsys.readouterr()
    message = captured.out + captured.err
    assert "backdoor_overlap" in message
    # The summary, and the repair, not just the id.
    assert "falls outside" in message or "%" in message
    assert "Suggested:" in message


def test_the_manifest_records_both_fingerprints(workspace, tmp_path, capsys) -> None:
    """One over the file as read, one over the table analysed. They answer different
    questions: whether this is the same data, and what these particular numbers came from.
    """
    runs = tmp_path / "runs"
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--run-dir",
        str(runs),
    )
    capsys.readouterr()
    directory = next(runs.iterdir())
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["source_fingerprint"]) == 16
    assert len(manifest["snapshot_fingerprint"]) == 16
    assert manifest["prior_runs_on_this_data"] == []


def test_a_second_spec_on_the_same_data_is_reported_not_refused(
    workspace, tmp_path, capsys
) -> None:
    """design.md 7.4: the primary analysis is the first one. A second look is legitimate and
    common, so it is stated rather than blocked, and the user is told which run was first.
    """
    runs = tmp_path / "runs"
    for _ in range(1):
        assert (
            run(
                "estimate",
                "--spec",
                str(workspace["spec.yaml"]),
                "--data",
                str(workspace["good.csv"]),
                "--run-dir",
                str(runs),
            )
            == 0
        )
    capsys.readouterr()

    narrowed = yaml.safe_load(workspace["spec.yaml"].read_text(encoding="utf-8"))
    narrowed["fields"]["effect_modifiers"]["value"] = narrowed["fields"]["effect_modifiers"][
        "value"
    ][:1]
    second = tmp_path / "narrowed.yaml"
    second.write_text(yaml.safe_dump(narrowed), encoding="utf-8")

    assert (
        run(
            "estimate",
            "--spec",
            str(second),
            "--data",
            str(workspace["good.csv"]),
            "--report",
            "--run-dir",
            str(runs),
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "This data has been analysed before" in out
    assert "The primary analysis is the first one" in out


def test_the_refutation_tests_run_by_default(workspace, tmp_path, capsys) -> None:
    """The default path, exercised once here because every other test in this file turns the
    refuters off for speed. A placebo test that never runs is worth nothing, so the thing to
    pin is that it runs without being asked for."""
    assert (
        run_with_refutations(
            "estimate",
            "--spec",
            str(workspace["spec.yaml"]),
            "--data",
            str(workspace["good.csv"]),
            "--report",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Sensitivity and refutation" in out
    assert "placebo_treatment" in out
    assert "E-value" in out


def test_no_sensitivity_says_so_rather_than_leaving_the_section_blank(
    workspace, tmp_path, capsys
) -> None:
    """A blank section reads as a clean bill of health."""
    assert (
        run(
            "estimate",
            "--spec",
            str(workspace["spec.yaml"]),
            "--data",
            str(workspace["good.csv"]),
            "--report",
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "No refutation test ran" in out
    assert "not evidence that the estimate would have survived one" in out


def test_the_persisted_quality_report_carries_the_pair_it_describes(
    workspace, tmp_path, capsys
) -> None:
    """So the verdicts can be proved to be about this run later, which is what the skill form
    needs: it runs the checks and the estimation as two scripts, and a list of issues on its
    own cannot be checked against anything."""
    runs = tmp_path / "runs"
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--run-dir",
        str(runs),
    )
    capsys.readouterr()
    directory = next(runs.iterdir())
    persisted = json.loads((directory / "quality" / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert persisted["spec_hash"] == manifest["spec_hash"]
    assert persisted["snapshot_fingerprint"] == manifest["snapshot_fingerprint"]
    assert persisted["issues"]

"""Telling a second look at the same data apart from a fresh analysis of new data.

Mirrors design.md 7.4: the primary analysis is locked at confirmation, and anything changed
after seeing the results is post hoc. Applying that rule needs something `spec_hash` cannot
provide on its own, because the spec changed in both of these cases:

- the same spec on new data, which is a fresh primary analysis and entirely legitimate
- a different spec on the same data, which is a second look at numbers already seen

The source fingerprint plus the spec hash separates them. This is the one thing a data
fingerprint does that nothing else can, and the reason it is worth having at all.

The refinement in the last group is what keeps the warning honest: a user who hit a blocking
quality issue, added the step that cleared it and re-ran has changed the spec on the same data
and was reacting to nothing, because the first run produced no estimate.
"""

from __future__ import annotations

import json
from pathlib import Path

from causpec.core.runtime.snapshot import RESULTS_ARTIFACT, prior_runs

DATA = "aaaa111122223333"
OTHER_DATA = "bbbb444455556666"
SPEC = "spec00000000aaaa"
OTHER_SPEC = "spec11111111bbbb"


def write_run(
    root: Path,
    run_id: str,
    source_fingerprint: str,
    spec_hash: str,
    *,
    completed: bool = True,
) -> None:
    directory = root / run_id
    directory.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "created_at": "2026-10-12T10:00:00Z",
        "spec_hash": spec_hash,
        "source_fingerprint": source_fingerprint,
        "artifacts": {RESULTS_ARTIFACT: "deadbeef"} if completed else {"quality/report.json": "x"},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_a_second_spec_on_the_same_data_is_found(tmp_path) -> None:
    write_run(tmp_path, "run-1", DATA, SPEC)
    found = prior_runs(tmp_path, DATA, OTHER_SPEC)
    assert [run.run_id for run in found] == ["run-1"]
    assert SPEC in found[0].describe()


def test_the_same_spec_again_is_a_rerun_not_a_second_look(tmp_path) -> None:
    """Re-running an unchanged spec is how anyone checks reproducibility. Flagging it would
    make the warning meaningless."""
    write_run(tmp_path, "run-1", DATA, SPEC)
    assert prior_runs(tmp_path, DATA, SPEC) == []


def test_the_same_spec_on_new_data_is_a_fresh_analysis(tmp_path) -> None:
    """The case the fingerprint exists to protect: new data is a new study, not a second look
    at an old one."""
    write_run(tmp_path, "run-1", DATA, SPEC)
    assert prior_runs(tmp_path, OTHER_DATA, OTHER_SPEC) == []


def test_a_run_that_stopped_at_a_gate_does_not_count(tmp_path) -> None:
    """The refinement that keeps this honest. A user who cleared a blocking issue and re-ran
    changed the spec on the same data and saw no results in between, so there was nothing to
    react to. Without this the warning fires on the tool's own intended workflow."""
    write_run(tmp_path, "blocked", DATA, SPEC, completed=False)
    assert prior_runs(tmp_path, DATA, OTHER_SPEC) == []


def test_several_earlier_runs_are_all_reported(tmp_path) -> None:
    write_run(tmp_path, "run-1", DATA, SPEC)
    write_run(tmp_path, "run-2", DATA, "spec2222cccc3333")
    write_run(tmp_path, "elsewhere", OTHER_DATA, "spec3333dddd4444")
    assert len(prior_runs(tmp_path, DATA, OTHER_SPEC)) == 2


def test_a_half_written_run_directory_is_skipped(tmp_path) -> None:
    """It happens, and refusing to start because of one would cost usability for no gain in
    honesty."""
    write_run(tmp_path, "run-1", DATA, SPEC)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "no-manifest").mkdir()
    assert len(prior_runs(tmp_path, DATA, OTHER_SPEC)) == 1


def test_a_missing_root_is_not_an_error(tmp_path) -> None:
    assert prior_runs(tmp_path / "never-used", DATA, SPEC) == []


def test_a_manifest_without_a_fingerprint_is_ignored(tmp_path) -> None:
    """Runs recorded before fingerprints existed. They cannot be compared, and guessing that
    they were on the same data would invent the finding."""
    directory = tmp_path / "old"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"run_id": "old", "spec_hash": SPEC, "artifacts": {RESULTS_ARTIFACT: "x"}}),
        encoding="utf-8",
    )
    assert prior_runs(tmp_path, DATA, OTHER_SPEC) == []

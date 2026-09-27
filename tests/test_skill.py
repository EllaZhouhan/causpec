"""Skill: structural integrity, and agreement between what the docs promise and what
the code does.

Mirrors design.md section 13. This file exists because **documentation drifts**:
SKILL.md says "only hte_backdoor and hte_iv are supported", and when a third family is
added nobody will remember to update it. These tests pin the two together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from causpec.core import registry
from causpec.core.reporting.claim_level import ClaimLevel, load_rules
from causpec.core.reporting.report import MODEL_AUTHORED_SECTIONS, Section

SKILL_DIR = Path(__file__).parent.parent / "skill" / "causpec-analyst"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = SKILL_DIR / "references"


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontmatter(skill_text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", skill_text, re.DOTALL)
    assert match, "SKILL.md has no YAML frontmatter"
    return yaml.safe_load(match.group(1))


# ---- structure ----


def test_frontmatter_has_name_and_description(frontmatter) -> None:
    assert frontmatter["name"] == "causpec-analyst"
    assert len(frontmatter["description"]) > 80  # a short description triggers poorly


def test_description_mentions_what_it_is_for(frontmatter) -> None:
    description = frontmatter["description"]
    assert "causal" in description
    assert "Use for" in description


def test_every_referenced_file_exists(skill_text: str) -> None:
    """Every file listed in SKILL.md's references table must actually exist."""
    listed = set(re.findall(r"`([a-z-]+\.md)`", skill_text))
    assert listed, "SKILL.md references no reference file at all"
    missing = {name for name in listed if not (REFERENCES / name).exists()}
    assert not missing, f"references a file that does not exist: {missing}"


def test_no_reference_is_orphaned() -> None:
    """Every file in references/ must be mentioned in SKILL.md, or the model never reads it."""
    on_disk = {p.name for p in REFERENCES.glob("*.md")}
    mentioned = set(re.findall(r"`([a-z-]+\.md)`", SKILL_MD.read_text(encoding="utf-8")))
    assert on_disk <= mentioned, f"not mentioned in SKILL.md: {on_disk - mentioned}"


def test_runner_script_exists_and_is_executable() -> None:
    runner = SKILL_DIR / "scripts" / "run.py"
    assert runner.exists()
    assert runner.stat().st_mode & 0o111, "run.py should be executable"


def test_report_template_exists() -> None:
    assert (SKILL_DIR / "assets" / "report-template.md").exists()


# ---- docs agree with code ----


def test_skill_lists_exactly_the_implemented_families(skill_text: str) -> None:
    """This goes red when a family is added and the docs are forgotten."""
    implemented = {
        name
        for name in registry.declared_families()
        if registry.load_declaration(name).get("status") == "implemented"
    }
    assert implemented == {"hte_backdoor", "hte_iv"}
    for name in implemented:
        assert f"`{name}`" in skill_text


def test_skill_names_the_unsupported_designs(skill_text: str) -> None:
    """design.md 7.6: unsupported designs are refused outright, never forced into
    backdoor adjustment."""
    for design in ("difference-in-differences", "regression discontinuity", "synthetic"):
        assert design in skill_text


def test_skill_claim_levels_match_the_rules(skill_text: str) -> None:
    claim_levels = (REFERENCES / "claim-levels.md").read_text(encoding="utf-8")
    for level in ClaimLevel:
        assert level.value in skill_text or level.value in claim_levels
    assert load_rules()["code_maximum"] in claim_levels


def test_skill_lists_exactly_the_writable_sections(skill_text: str) -> None:
    """Which sections the model may write must agree between the docs and the code."""
    reporting = (REFERENCES / "reporting.md").read_text(encoding="utf-8")
    for section in MODEL_AUTHORED_SECTIONS:
        assert f"`{section.value}`" in skill_text or f"`{section.value}`" in reporting
    forbidden = set(Section) - MODEL_AUTHORED_SECTIONS
    for section in forbidden:
        assert (
            f"`{section.value}`" in reporting
        ), f"reporting.md does not say {section.value} is not writable"


def test_quality_checks_reference_covers_every_check() -> None:
    """Every check needs an explanation in the reference, or the model cannot explain it
    to the user."""
    text = (REFERENCES / "quality-checks.md").read_text(encoding="utf-8")
    for family in ("hte_backdoor", "hte_iv"):
        for check_id in registry.load_declaration(family).get("checks", {}):
            assert check_id in text, f"quality-checks.md is missing {check_id}"


def test_blocking_checks_are_marked_as_blocking_in_the_reference() -> None:
    text = (REFERENCES / "quality-checks.md").read_text(encoding="utf-8")
    for family in ("hte_backdoor", "hte_iv"):
        for check_id, config in registry.load_declaration(family).get("checks", {}).items():
            if config["severity"] == "blocking":
                line = next(line for line in text.splitlines() if check_id in line)
                assert (
                    "blocking" in line
                ), f"{check_id} is a blocking check but the reference does not say so"


# ---- the key rules ----


@pytest.mark.parametrize(
    "rule",
    [
        "One question per turn",
        "placeholders",
        "Never upgrade it",
        "Ask the user when domain knowledge is needed",
        "Never confirm on the user's behalf",
        "without looking at the data",
        "check measurement time before role",
        "say so and say why",
    ],
)
def test_key_rules_are_stated(skill_text: str, rule: str) -> None:
    """The eight key rules of design.md section 13."""
    assert rule in skill_text


def test_best_effort_belongs_in_the_report_not_the_conversation(skill_text: str) -> None:
    """design.md section 3 says only "noted in the report header", not "said up front".

    The first version phrased this as "you must tell the user this is best-effort
    mode", so the model opened with a paragraph about the tool's own limitations —
    including an unprompted "I could technically bypass the scripts and compute this
    myself" — to a user who had just asked a clinical question. That is not
    transparency but buck-passing: the user can do nothing with it. This test watches
    for the drift back.
    """
    assert "not an opening remark" in skill_text
    assert "Do not volunteer the execution mode" in skill_text


def test_skill_tells_the_model_to_match_the_user_language(skill_text: str) -> None:
    assert "Follow the user's language" in skill_text


def test_skill_bans_internal_jargon_in_conversation(skill_text: str) -> None:
    """Users come to solve their problem, not to learn CauSpec's architecture."""
    assert "Do not explain the tool's internals" in skill_text
    for word in ("deterministic", "placeholder", "gate", "best-effort"):
        assert word in skill_text  # appears in the "avoid these words" list


def test_mcp_is_not_claimed_to_exist(skill_text: str) -> None:
    """The MCP server does not exist yet. Directing a model at tools that are not there
    is worse than having no skill."""
    assert "the MCP server is not implemented yet" in skill_text

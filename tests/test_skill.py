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
    assert implemented == {"dynamic_lag_dml", "hte_backdoor", "hte_iv"}
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
        assert f"`{section.value}`" in reporting, (
            f"reporting.md does not say {section.value} is not writable"
        )


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
                assert "blocking" in line, (
                    f"{check_id} is a blocking check but the reference does not say so"
                )


# ---- the key rules ----


@pytest.mark.parametrize(
    "rule",
    [
        "One question per turn",
        "placeholders",
        "Never upgrade it",
        "Ask the user when domain knowledge is needed",
        "Never confirm on the user's behalf",
        "before showing them any columns",
        "check measurement time before role",
        "say so and say why",
    ],
)
def test_key_rules_are_stated(skill_text: str, rule: str) -> None:
    """The eight key rules of design.md section 13."""
    assert rule in skill_text


def test_the_constraint_is_on_showing_not_on_reading(skill_text: str) -> None:
    """The risk is the user seeing a menu, not the agent reading a file.

    Rule 6 first said "do not look at the data", so the model asked a clinician to
    classify their own treatment as baseline or time-varying, in the abstract, before
    establishing that the table has one row per patient. The next attempt said "read the
    shape but not the variables", which contradicted itself: naming `rrt_started` and
    its 0/1 values in the question *is* reading a variable.

    The data supplies the question two ways, the user picks off a list they were just
    shown, or the agent invents an analysis from what happens to exist. Neither comes
    from reading a file, so the constraint sits on what is shown and proposed.
    """
    assert "Read the schema freely" in skill_text
    assert "do not hand the user a menu" in skill_text
    assert "Reading a schema is not computing a result" in skill_text
    assert "never suggest a question they did not ask" in skill_text
    assert "cross-sectional" in skill_text


def test_skill_asks_about_timing_concretely_not_abstractly(skill_text: str) -> None:
    """Two options only: already on treatment at baseline, or started at some point.

    No fixed windows, landmark analysis or g-methods unless the user asks, those are
    for a colleague, not for the clinician who asked the question.
    """
    assert "already on it at admission" in skill_text.lower()
    assert "at any point during the stay" in skill_text.lower()
    assert "unless they ask" in skill_text


def test_skill_separates_justifying_the_workflow_from_stating_the_stakes(
    skill_text: str,
) -> None:
    """Two kinds of reason, one to cut and one to keep.

    Explaining why the tool works as it does lectures someone who did not ask.
    Explaining what hangs on their answer is what lets them answer correctly.
    """
    assert "Do not justify the workflow" in skill_text
    assert "Do say what hangs on the answer" in skill_text
    assert "State the consequence, not the mechanism" in skill_text


def test_skill_does_not_re_ask_what_the_user_already_said(skill_text: str) -> None:
    """Asking "which patients benefit more" already settles the estimand.

    The exploratory run asked the user to confirm that heterogeneity was the primary
    target, after they had asked for it in their opening sentence. Infer from what was
    said; ask only about what is genuinely undetermined.
    """
    assert "Do not ask again what they already told you" in skill_text
    assert "Ask only about what is genuinely undetermined" in skill_text


def test_skill_drafts_effect_modifiers_rather_than_asking_for_them(skill_text: str) -> None:
    """A user asking which patients benefit cannot also be the one to name them.

    The first version asked, per variable, whether the effect should be allowed to vary
    with it. With forty covariates that is forty questions, and it asks the user to
    answer the question they came to have answered. design.md 7.5 already rejects the
    same move for DAGs: the agent drafts from the measurement window, the user confirms.

    What the user genuinely knows, and the tool cannot infer, is which variables were
    measured after treatment started.
    """
    assert "Do not ask the user to enumerate the effect modifiers" in skill_text
    assert "Default X to every pre-treatment covariate" in skill_text
    assert "measured after" in skill_text
    assert "Offer a focus, do not require one" in skill_text


def test_no_dash_punctuation_anywhere_in_the_skill() -> None:
    """Dashes as punctuation are out, at any length.

    Hyphens inside a word (`pre-treatment`, `cross-sectional`) are spelling and stay;
    this only looks for a dash standing alone between words, and for the em and en
    dashes, which have no other use.
    """
    import re

    offenders = []
    for path in [SKILL_MD, *REFERENCES.glob("*.md"), SKILL_DIR / "assets" / "report-template.md"]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*[-*]\s", line) or line.strip().startswith("|-"):
                continue  # markdown list bullet or table rule
            if re.search(r"[\u2013\u2014]|(?<=[^\s|])\s-\s(?=[^\s|])", line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"dash used as punctuation: {offenders}"


def test_skill_opens_with_a_greeting_not_a_preamble(skill_text: str) -> None:
    assert "Open by greeting them" in skill_text


def test_best_effort_belongs_in_the_report_not_the_conversation(skill_text: str) -> None:
    """design.md section 3 says only "noted in the report header", not "said up front".

    The first version phrased this as "you must tell the user this is best-effort
    mode", so the model opened with a paragraph about the tool's own limitations,
    including an unprompted "I could technically bypass the scripts and compute this
    myself", and said it to a user who had just asked a clinical question. That is not
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


# ---- both paths are described, not just the one the skill grew up with ----


def test_the_panel_path_is_visible_in_the_step_list(skill_text: str) -> None:
    """The eight steps were written for one row per unit. A model on the panel path that
    followed step 3 literally would confirm an adjustment_set that family does not have."""
    assert "Two paths run through these steps" in skill_text
    for step in ("### 3.", "### 4.", "### 5."):
        index = skill_text.index(step)
        section = skill_text[index : index + 700]
        assert "panel" in section.lower(), f"{step} does not say which path it describes"


def test_the_panel_fields_are_documented_where_a_spec_gets_written() -> None:
    """spec-fields.md is what the model reads to write a spec. Fields missing from it are
    fields the model invents."""
    text = (REFERENCES / "spec-fields.md").read_text(encoding="utf-8")
    for field in ("unit_id", "period_index", "period_length", "state", "max_lag", "horizon"):
        assert f"`{field}`" in text or f"  {field}:" in text, field
    assert "dynamic_lag_dml" in text


def test_the_exploratory_interval_rule_reaches_the_claim_level_reference() -> None:
    """The decision carries claim:significance_claims. A model that never read about it
    would describe an interval excluding zero as a finding."""
    text = (REFERENCES / "claim-levels.md").read_text(encoding="utf-8")
    assert "significance_claims" in text
    assert "exploratory" in text


def test_the_reporting_reference_names_the_panel_addresses() -> None:
    """Otherwise the model guesses res:primary.ate, which does not exist for a profile."""
    text = (REFERENCES / "reporting.md").read_text(encoding="utf-8")
    assert "res:profile.lag1.theta" in text
    assert "res:profile.period_hours" in text


def test_no_reference_claims_only_two_designs_are_supported(skill_text: str) -> None:
    """There are three. This sentence was left behind by the third one arriving."""
    assert "Only two identification strategies" not in skill_text
    for path in REFERENCES.glob("*.md"):
        assert "Only two identification strategies" not in path.read_text(encoding="utf-8")

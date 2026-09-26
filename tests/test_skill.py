"""skill：结构完整性，以及文档里的承诺与代码行为一致。

对应 design.md 第 13 节。这个文件存在的理由是**文档会悄悄过期**——
SKILL.md 说「只支持 hte_backdoor 和 hte_iv」，代码加了第三个 family 时
没人会想起来改文档。这里把两边钉在一起。
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
    assert match, "SKILL.md 缺少 YAML frontmatter"
    return yaml.safe_load(match.group(1))


# ---- 结构 ----


def test_frontmatter_has_name_and_description(frontmatter) -> None:
    assert frontmatter["name"] == "causpec-analyst"
    assert len(frontmatter["description"]) > 80  # 太短的 description 触发不准


def test_description_mentions_what_it_is_for(frontmatter) -> None:
    description = frontmatter["description"]
    assert "因果" in description
    assert "适用于" in description


def test_every_referenced_file_exists(skill_text: str) -> None:
    """SKILL.md 的 references 表里列的文件必须真的存在。"""
    listed = set(re.findall(r"`([a-z-]+\.md)`", skill_text))
    assert listed, "SKILL.md 里没有引用任何 reference"
    missing = {name for name in listed if not (REFERENCES / name).exists()}
    assert not missing, f"引用了不存在的 reference：{missing}"


def test_no_reference_is_orphaned() -> None:
    """references 目录里的文件都应当被 SKILL.md 提到，否则模型不会去读。"""
    on_disk = {p.name for p in REFERENCES.glob("*.md")}
    mentioned = set(re.findall(r"`([a-z-]+\.md)`", SKILL_MD.read_text(encoding="utf-8")))
    assert on_disk <= mentioned, f"没被 SKILL.md 提到的 reference：{on_disk - mentioned}"


def test_runner_script_exists_and_is_executable() -> None:
    runner = SKILL_DIR / "scripts" / "run.py"
    assert runner.exists()
    assert runner.stat().st_mode & 0o111, "run.py 应当可执行"


def test_report_template_exists() -> None:
    assert (SKILL_DIR / "assets" / "report-template.md").exists()


# ---- 文档与代码一致 ----


def test_skill_lists_exactly_the_implemented_families(skill_text: str) -> None:
    """加了新 family 却忘了改文档时，这条会红。"""
    implemented = {
        name
        for name in registry.declared_families()
        if registry.load_declaration(name).get("status") == "implemented"
    }
    assert implemented == {"hte_backdoor", "hte_iv"}
    for name in implemented:
        assert f"`{name}`" in skill_text


def test_skill_names_the_unsupported_designs(skill_text: str) -> None:
    """design.md 7.6：不支持的设计要明确拒绝，不能硬塞进后门调整。"""
    for design in ("DiD", "断点回归", "合成控制"):
        assert design in skill_text


def test_skill_claim_levels_match_the_rules(skill_text: str) -> None:
    claim_levels = (REFERENCES / "claim-levels.md").read_text(encoding="utf-8")
    for level in ClaimLevel:
        assert level.value in skill_text or level.value in claim_levels
    assert load_rules()["code_maximum"] in claim_levels


def test_skill_lists_exactly_the_writable_sections(skill_text: str) -> None:
    """模型能写哪几节，文档说的必须和代码认的一致。"""
    reporting = (REFERENCES / "reporting.md").read_text(encoding="utf-8")
    for section in MODEL_AUTHORED_SECTIONS:
        assert f"`{section.value}`" in skill_text or f"`{section.value}`" in reporting
    forbidden = set(Section) - MODEL_AUTHORED_SECTIONS
    for section in forbidden:
        assert f"`{section.value}`" in reporting, f"reporting.md 没说明 {section.value} 不可写"


def test_quality_checks_reference_covers_every_check() -> None:
    """每条检查都要在 reference 里有解释，否则模型没法向用户说明。"""
    text = (REFERENCES / "quality-checks.md").read_text(encoding="utf-8")
    for family in ("hte_backdoor", "hte_iv"):
        for check_id in registry.load_declaration(family).get("checks", {}):
            assert check_id in text, f"quality-checks.md 缺少 {check_id}"


def test_blocking_checks_are_marked_as_blocking_in_the_reference() -> None:
    text = (REFERENCES / "quality-checks.md").read_text(encoding="utf-8")
    for family in ("hte_backdoor", "hte_iv"):
        for check_id, config in registry.load_declaration(family).get("checks", {}).items():
            if config["severity"] == "blocking":
                line = next(line for line in text.splitlines() if check_id in line)
                assert "阻断" in line, f"{check_id} 是阻断检验，reference 里没标出来"


# ---- 关键规则 ----


@pytest.mark.parametrize(
    "rule",
    [
        "每轮只问一个问题",
        "占位符",
        "不得升级",
        "必须问用户",
        "不得替用户确认",
        "不看数据",
        "先看测量时间",
        "明确说明不支持",
    ],
)
def test_key_rules_are_stated(skill_text: str, rule: str) -> None:
    """design.md 第 13 节的八条关键规则。"""
    assert rule in skill_text


def test_best_effort_mode_is_disclosed(skill_text: str) -> None:
    """design.md 第 3 节：skill 形态是 best-effort，必须告知用户。"""
    assert "best-effort" in skill_text
    assert "告知用户" in skill_text


def test_mcp_is_not_claimed_to_exist(skill_text: str) -> None:
    """MCP server 还没实现。指挥模型去调不存在的工具比没有 skill 更糟。"""
    assert "MCP server 尚未实现" in skill_text

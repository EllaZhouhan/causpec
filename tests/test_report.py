"""报告组装：固定结构、代码生成的事实、模型撰写的解读。

对应 design.md 10.3。锁两条性质：段落顺序不可协商；纯事实段落模型碰不到。
"""

from __future__ import annotations

import pytest

from causpec.core.contracts.manifest import ExecutionMode
from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import (
    Assumption,
    AssumptionCategory,
    Source,
    Spec,
    SpecField,
    Status,
)
from causpec.core.reporting.claim_level import determine
from causpec.core.reporting.render import RenderError
from causpec.core.reporting.report import (
    MODEL_AUTHORED_SECTIONS,
    SECTION_ORDER,
    TITLES,
    ReportError,
    Section,
    build,
)

ADDRESSES: dict[str, float | int | str] = {
    "res:primary.ate": -0.017936448014042473,
    "res:sample.n": 2000,
    "qc:backdoor_overlap.extreme_fraction": 0.002,
}


def confirmed(value: object, said: str = "确认", turn: int = 1) -> SpecField:
    return SpecField(value=value, source=Source.USER, said=said, turn=turn, status=Status.CONFIRMED)


SPEC = Spec(
    question="透析对 ICU 患者死亡率的平均效应？",
    family="hte_backdoor",
    assumptions=[
        Assumption(
            id="unconfoundedness",
            category=AssumptionCategory.UNTESTABLE,
            statement="给定调整集后处理分配与潜在结局独立",
        ),
        Assumption(
            id="positivity",
            category=AssumptionCategory.EMPIRICALLY_ASSESSED,
            statement="每个协变量取值下两种处理都有正概率",
        ),
    ],
    fields={
        "treatment": confirmed("isDialysisICU", "处理是 ICU 内开始透析", 2),
        "outcome": confirmed("death", "结局看院内死亡", 4),
        "estimand": confirmed("ate", "对，全人群平均效应", 6),
    },
)

QUALITY = QualityReport(
    issues=[
        QualityIssue(
            check_id="backdoor_overlap",
            layer=Layer.IDENTIFICATION,
            severity=Severity.INFO,
            waivable=True,
            summary="0.2% 的样本落在阈值之外",
            evidence={"passed": True},
        )
    ]
)
FAILING_QUALITY = QualityReport(
    issues=[
        QualityIssue(
            check_id="backdoor_overlap",
            layer=Layer.IDENTIFICATION,
            severity=Severity.BLOCKING,
            waivable=True,
            summary="88% 的样本落在阈值之外",
            evidence={"passed": False},
            impact_on_analysis="估计是外推出来的。",
            recommended_repair="限制人群。",
        )
    ]
)
DECISION = determine(SPEC, QUALITY, gate_passed=True)


def sections_of(markdown: str) -> list[str]:
    return [line[3:] for line in markdown.splitlines() if line.startswith("## ")]


# ---- 结构 ----


def test_assumptions_come_before_results() -> None:
    """design.md 10.3 的要点：人是先看到假设才看到数字的。"""
    order = sections_of(build(SPEC, QUALITY, DECISION, ADDRESSES))
    assert order.index(TITLES[Section.ASSUMPTIONS]) < order.index(TITLES[Section.PRIMARY_RESULTS])


def test_section_order_is_fixed_regardless_of_narrative_order() -> None:
    """模型按什么顺序交稿都不影响报告的顺序。"""
    reversed_narrative = {
        Section.LIMITATIONS: "局限文字",
        Section.PRIMARY_RESULTS: "结果文字",
        Section.ESTIMAND: "估计对象文字",
    }
    order = sections_of(build(SPEC, QUALITY, DECISION, ADDRESSES, narrative=reversed_narrative))
    expected = [TITLES[s] for s in SECTION_ORDER if s is not Section.POST_HOC]
    assert order == expected


def test_post_hoc_section_is_omitted_when_empty() -> None:
    assert TITLES[Section.POST_HOC] not in sections_of(build(SPEC, QUALITY, DECISION, ADDRESSES))


def test_post_hoc_section_appears_last_when_present() -> None:
    order = sections_of(
        build(SPEC, QUALITY, DECISION, ADDRESSES, narrative={Section.POST_HOC: "事后分析"})
    )
    assert order[-1] == TITLES[Section.POST_HOC]


def test_unimplemented_sections_say_so_rather_than_vanish() -> None:
    """读者要知道这份报告缺了什么——留空不等于通过。"""
    markdown = build(SPEC, QUALITY, DECISION, ADDRESSES)
    assert TITLES[Section.SENSITIVITY] in sections_of(markdown)
    assert "尚未实现" in markdown
    assert "留空不代表该项检查已通过" in markdown


# ---- 模型碰不到的段落 ----


@pytest.mark.parametrize("section", sorted(set(Section) - MODEL_AUTHORED_SECTIONS, key=str))
def test_factual_sections_reject_model_text(section: Section) -> None:
    with pytest.raises(ReportError, match="由代码生成"):
        build(SPEC, QUALITY, DECISION, ADDRESSES, narrative={section: "模型想写点什么"})


def test_error_lists_the_writable_sections(section: Section = Section.CLAIM_LEVEL) -> None:
    with pytest.raises(ReportError, match="limitations"):
        build(SPEC, QUALITY, DECISION, ADDRESSES, narrative={section: "x"})


def test_narrative_accepts_plain_string_keys() -> None:
    markdown = build(SPEC, QUALITY, DECISION, ADDRESSES, narrative={"limitations": "局限文字"})
    assert "局限文字" in markdown


# ---- spec 来源表 ----


def test_spec_table_shows_source_and_verbatim_words() -> None:
    """design.md 7.1 的缓解措施：把来源摆出来供人事后核查。"""
    markdown = build(SPEC, QUALITY, DECISION, ADDRESSES)
    assert "处理是 ICU 内开始透析" in markdown
    assert "无法验证用户是否真的看过" in markdown
    assert SPEC.spec_hash() in markdown


def test_skill_mode_is_flagged_as_best_effort() -> None:
    """design.md 第 3 节：skill 形态 best-effort，报告页眉注明。"""
    markdown = build(SPEC, QUALITY, DECISION, ADDRESSES, execution_mode=ExecutionMode.SKILL)
    assert "best-effort" in markdown
    assert "绕过脚本直接读取数据" in markdown


def test_cli_mode_has_no_best_effort_warning() -> None:
    assert "best-effort" not in build(SPEC, QUALITY, DECISION, ADDRESSES)


# ---- 假设分列 ----


def test_untestable_assumptions_are_marked_unjustified() -> None:
    markdown = build(SPEC, QUALITY, DECISION, ADDRESSES)
    assert "无法检验" in markdown
    assert "尚未获得论证" in markdown


def test_justified_assumption_names_who_justified_it() -> None:
    justified = SPEC.model_copy(
        update={
            "assumptions": [
                SPEC.assumptions[0].model_copy(
                    update={"justification": "方案变量已全部纳入", "justified_by": Source.USER}
                )
            ]
        }
    )
    markdown = build(justified, QUALITY, DECISION, ADDRESSES)
    assert "论证（user）：方案变量已全部纳入" in markdown
    assert "尚未获得论证" not in markdown


def test_missing_assumptions_are_called_out() -> None:
    bare = SPEC.model_copy(update={"assumptions": []})
    assert "没有假设就没有识别" in build(bare, QUALITY, DECISION, ADDRESSES)


# ---- 质量与措辞等级 ----


def test_failing_check_reports_impact_and_repair() -> None:
    decision = determine(SPEC, FAILING_QUALITY, gate_passed=True)
    markdown = build(SPEC, FAILING_QUALITY, decision, ADDRESSES)
    assert "估计是外推出来的。" in markdown
    assert "建议：限制人群。" in markdown


def test_claim_level_section_states_allowed_wording() -> None:
    markdown = build(SPEC, QUALITY, DECISION, ADDRESSES)
    assert "`suggestive`" in markdown
    assert "不断言因果" in markdown
    assert DECISION.rules_hash in markdown


def test_pipe_characters_are_escaped_in_tables() -> None:
    """|SMD| 这样的写法会把表格劈成两列。"""
    issue = QUALITY.issues[0].model_copy(update={"summary": "最大 |SMD| 为 0.04"})
    markdown = build(SPEC, QualityReport(issues=[issue]), DECISION, ADDRESSES)
    assert "\\|SMD\\|" in markdown


# ---- 解读文字走占位符渲染 ----


def test_narrative_placeholders_are_substituted() -> None:
    markdown = build(
        SPEC,
        QUALITY,
        DECISION,
        ADDRESSES,
        narrative={Section.PRIMARY_RESULTS: "共 {{res:sample.n}} 人。"},
    )
    assert "共 2000 人。" in markdown


def test_narrative_rejects_bare_numbers() -> None:
    with pytest.raises(RenderError, match="未经占位的数字"):
        build(
            SPEC,
            QUALITY,
            DECISION,
            ADDRESSES,
            narrative={Section.PRIMARY_RESULTS: "效应约为 -0.018。"},
        )


def test_narrative_can_reference_quality_addresses() -> None:
    markdown = build(
        SPEC,
        QUALITY,
        DECISION,
        ADDRESSES,
        narrative={Section.DATA_QUALITY: "落线外 {{qc:backdoor_overlap.extreme_fraction|.1%}}。"},
    )
    assert "落线外 0.2%。" in markdown

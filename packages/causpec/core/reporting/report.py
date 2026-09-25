"""报告组装：固定结构，事实由代码生成，解读由模型写。

对应 design.md 10.3 的报告结构：

    1. 问题与 spec（含每个字段的来源）
    2. estimand 及其适用人群
    3. 变量角色图
    4. 假设（按三类分列，**写在结果之前**）
    5. 数据质量
    6. 主结果
    7. 敏感性与反驳
    8. 措辞等级及理由
    9. 局限
    10. post_hoc 分析（如有）

两条由这一层强制的性质：

**顺序不可协商。** 「假设写在结果之前」是结构保证，不是提醒——段落顺序由
``SECTION_ORDER`` 决定，模型无从改变。人是先看到假设才看到数字的。

**有些段落模型碰不到。** spec 来源表与措辞等级判定由代码生成。前者是
design.md 7.1 对「无法验证用户是否真的确认过」的缓解措施——它必须如实反映
spec 里记的东西，模型经手就失去意义；后者是原则 5 的落点，模型不得自行升级。
模型只能为 ``MODEL_AUTHORED_SECTIONS`` 里的段落提供解读，且一律走占位符渲染。
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from causpec.core.contracts.manifest import ExecutionMode
from causpec.core.contracts.quality import QualityReport, Severity
from causpec.core.contracts.spec import AssumptionCategory, Spec
from causpec.core.reporting.claim_level import ClaimLevelDecision, load_rules
from causpec.core.reporting.render import render


class Section(StrEnum):
    """报告的十个段落（design.md 10.3）。"""

    QUESTION_AND_SPEC = "question_and_spec"
    ESTIMAND = "estimand"
    VARIABLE_ROLES = "variable_roles"
    ASSUMPTIONS = "assumptions"
    DATA_QUALITY = "data_quality"
    PRIMARY_RESULTS = "primary_results"
    SENSITIVITY = "sensitivity"
    CLAIM_LEVEL = "claim_level"
    LIMITATIONS = "limitations"
    POST_HOC = "post_hoc"


# 顺序即 design.md 10.3。假设（4）在主结果（6）之前是这条顺序的要点。
SECTION_ORDER: tuple[Section, ...] = tuple(Section)

TITLES: dict[Section, str] = {
    Section.QUESTION_AND_SPEC: "问题与分析规格",
    Section.ESTIMAND: "估计对象与适用人群",
    Section.VARIABLE_ROLES: "变量角色",
    Section.ASSUMPTIONS: "假设",
    Section.DATA_QUALITY: "数据质量",
    Section.PRIMARY_RESULTS: "主结果",
    Section.SENSITIVITY: "敏感性与反驳",
    Section.CLAIM_LEVEL: "措辞等级及理由",
    Section.LIMITATIONS: "局限",
    Section.POST_HOC: "事后（post hoc）分析",
}

# 模型可以为这些段落提供解读文字。其余段落纯由代码生成。
MODEL_AUTHORED_SECTIONS: frozenset[Section] = frozenset(
    {
        Section.ESTIMAND,
        Section.DATA_QUALITY,
        Section.PRIMARY_RESULTS,
        Section.SENSITIVITY,
        Section.LIMITATIONS,
        Section.POST_HOC,
    }
)

CATEGORY_TITLES: dict[AssumptionCategory, str] = {
    AssumptionCategory.EMPIRICALLY_ASSESSED: "可由数据评估",
    AssumptionCategory.REQUIRES_JUSTIFICATION: "需要论证",
    AssumptionCategory.UNTESTABLE: "无法检验",
}

SEVERITY_MARKS: dict[Severity, str] = {
    Severity.BLOCKING: "✗ 阻断",
    Severity.WARNING: "! 警告",
    Severity.INFO: "· 通过",
}


class ReportError(Exception):
    """报告组装失败。"""


def _escape(value: object) -> str:
    """Markdown 表格里的竖线要转义，否则会把一列劈成两列。"""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _spec_section(spec: Spec, execution_mode: ExecutionMode) -> str:
    """spec 全文与每个字段的来源。

    design.md 7.1：确认发生在对话中，server 无法验证用户是否真的看过 spec。
    缓解方式就是这张表——把每个字段的来源、用户原话、轮次摆出来，由人事后核查。
    所以它必须由代码从 spec 直接生成，模型不经手。
    """
    lines = [f"**问题**：{spec.question}", ""]
    if execution_mode is ExecutionMode.SKILL:
        lines += [
            "> ⚠ 本次分析以 skill 形态运行（best-effort）。agent 可能绕过脚本直接读取数据，"
            "因此下列记录的保证强度低于 MCP 形态。",
            "",
        ]
    lines += [
        "下表是 spec 中每个字段的取值与来源。**确认发生在对话中，系统无法验证用户是否"
        "真的看过这些内容**——请逐行核对，特别是标着「用户原话」的那几行是否确实出自您。",
        "",
        "| 字段 | 取值 | 来源 | 状态 | 用户原话 | 轮次 |",
        "|---|---|---|---|---|---|",
    ]
    for name, field in spec.fields.items():
        lines.append(
            f"| `{name}` | {_escape(field.value)} | {field.source.value} | "
            f"{field.status.value} | {_escape(field.said or '—')} | {field.turn or '—'} |"
        )
    lines += ["", f"spec 哈希：`{spec.spec_hash()}`"]
    return "\n".join(lines)


def _assumptions_section(spec: Spec) -> str:
    """假设按三类分列。**写在结果之前**（design.md 10.3）。"""
    if not spec.assumptions:
        return "_本次分析未声明识别假设。这本身是一个问题——没有假设就没有识别。_"

    lines: list[str] = []
    for category in AssumptionCategory:
        group = [a for a in spec.assumptions if a.category is category]
        if not group:
            continue
        lines += [f"### {CATEGORY_TITLES[category]}", ""]
        if category is AssumptionCategory.UNTESTABLE:
            lines += [
                "_以下假设**原则上无法由数据检验**。跑再多诊断也证明不了它们，"
                "只能由人给出论证并承担责任。_",
                "",
            ]
        for assumption in group:
            lines.append(f"- **{assumption.id}** —— {assumption.statement}")
            if assumption.justification:
                who = assumption.justified_by.value if assumption.justified_by else "未注明"
                lines.append(f"  - 论证（{who}）：{assumption.justification}")
            elif category is AssumptionCategory.UNTESTABLE:
                lines.append("  - ⚠ **尚未获得论证。**")
        lines.append("")
    return "\n".join(lines).rstrip()


def _quality_section(report: QualityReport) -> str:
    if not report.issues:
        return "_未运行任何质量检查。_"
    lines = ["| 检查 | 结果 | 说明 |", "|---|---|---|"]
    for issue in report.issues:
        lines.append(
            f"| `{issue.check_id}` | {SEVERITY_MARKS[issue.severity]} | {_escape(issue.summary)} |"
        )
    failing = [i for i in report.issues if i.evidence.get("passed") is False]
    if failing:
        lines += ["", "未通过的检查及其影响："]
        for issue in failing:
            lines.append(f"- **{issue.check_id}**：{issue.impact_on_analysis}")
            if issue.recommended_repair:
                lines.append(f"  - 建议：{issue.recommended_repair}")
    return "\n".join(lines)


def _claim_level_section(decision: ClaimLevelDecision) -> str:
    """措辞等级与理由。由代码生成——原则 5：模型不得自行升级。"""
    wording = load_rules()["wording"][decision.level.value]
    lines = [
        f"**本次分析的结论措辞等级：`{decision.level.value}`**",
        "",
        f"该等级允许的表述方式：{wording}",
        "",
    ]
    if decision.reasons:
        lines.append("判定理由：")
        lines += [f"- {reason}" for reason in decision.reasons]
        lines.append("")
    lines.append(f"判定规则版本 {decision.rules_version}，规则文件哈希 `{decision.rules_hash}`。")
    return "\n".join(lines)


def _not_implemented(what: str, where: str) -> str:
    """还没实现的段落如实说明，不静默省略——读者要知道这份报告缺了什么。"""
    return f"_{what}尚未实现（见 {where}）。本节留空不代表该项检查已通过。_"


def build(
    spec: Spec,
    quality: QualityReport,
    decision: ClaimLevelDecision,
    addresses: Mapping[str, float | int | str],
    *,
    narrative: Mapping[Any, str] | None = None,
    execution_mode: ExecutionMode = ExecutionMode.CLI,
    title: str | None = None,
) -> str:
    """组装完整报告。

    Args:
        narrative: 模型撰写的解读文字，按段落给出。只接受
            ``MODEL_AUTHORED_SECTIONS`` 里的段落，且一律走占位符渲染——
            正文里出现未经占位的数字会渲染失败。

    Raises:
        ReportError: 模型试图为纯事实段落提供文字。
        RenderError: 解读文字里有裸数字或不存在的地址。
    """
    provided = {Section(key): text for key, text in (narrative or {}).items()}
    forbidden = sorted(s.value for s in provided if s not in MODEL_AUTHORED_SECTIONS)
    if forbidden:
        raise ReportError(
            f"这些段落由代码生成，不接受模型撰写的文字：{'、'.join(forbidden)}。\n"
            f"spec 来源表是给人事后核查用的事实，措辞等级判定是代码的职责"
            f"（design.md 7.1、原则 5）。可撰写的段落："
            f"{'、'.join(sorted(s.value for s in MODEL_AUTHORED_SECTIONS))}。"
        )

    facts: dict[Section, str] = {
        Section.QUESTION_AND_SPEC: _spec_section(spec, execution_mode),
        Section.ASSUMPTIONS: _assumptions_section(spec),
        Section.DATA_QUALITY: _quality_section(quality),
        Section.CLAIM_LEVEL: _claim_level_section(decision),
        Section.VARIABLE_ROLES: _not_implemented("变量角色图", "plan.md Phase 1 任务 3"),
        Section.SENSITIVITY: _not_implemented("敏感性与反驳检验", "plan.md Phase 1 任务 9"),
    }

    chunks = [f"# {title or spec.question}", ""]
    for section in SECTION_ORDER:
        body_parts = [facts[section]] if section in facts else []
        if section in provided:
            body_parts.append(render(provided[section], addresses))
        if not body_parts:
            if section is Section.POST_HOC:
                continue  # 没有事后分析就不占一节
            body_parts = ["_（本节无内容）_"]
        chunks += [f"## {TITLES[section]}", "", "\n\n".join(body_parts), ""]
    return "\n".join(chunks).rstrip() + "\n"

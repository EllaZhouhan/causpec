"""门控：estimate 执行前的硬性检查。

对应 design.md 11.2。这一层是「框架设闸」的落点——它是代码里的 if，
不是 prompt 里的规则，模型绕不过去。

已实现第 1 条（spec 确认）与第 2 条（无未豁免的 blocking 质量问题）。
还差第 3 条：family.supports(spec) 通过，且 spec.estimand 在该 family 声明可识别的
范围内，以及把质量报告与 (snapshot_fingerprint, spec_hash) 绑定。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.spec import Spec


@dataclass
class GateError(Exception):
    """结构化的门控错误：code + 原因 + 修复建议。

    对应 design.md 11.2「不满足时返回结构化错误」，以及第 12 节要求的
    「错误到修复建议」注册表模式。
    """

    code: str
    reason: str
    remediation: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.reason}\n  修复：{self.remediation}"


def check_spec_confirmed(spec: Spec) -> None:
    """关键字段未全部 confirmed 时拒绝执行。"""
    unconfirmed = spec.unconfirmed_critical_fields()
    if unconfirmed:
        raise GateError(
            code="SPEC_NOT_CONFIRMED",
            reason=f"关键字段尚未确认：{'、'.join(unconfirmed)}",
            remediation="对每个字段调用 update_field 与用户逐一确认后重试。",
            details={"unconfirmed_fields": unconfirmed},
        )


def check_no_blocking_issues(
    report: QualityReport, waived: Mapping[str, str] | None = None
) -> None:
    """有未豁免的 blocking 质量问题时拒绝执行。

    ``waived`` 是 check_id → 豁免理由。豁免必须附理由（design.md 12 节
    record_waiver），没有理由的豁免不成立；不可豁免的检查即使给了理由也不放行。
    """
    waived = waived or {}
    unresolved = []
    for issue in report.blocking:
        reason = waived.get(issue.check_id, "").strip()
        if not reason or not issue.waivable:
            unresolved.append(issue)

    if unresolved:
        raise GateError(
            code="BLOCKING_QUALITY_ISSUES",
            reason="存在未处理的 blocking 质量问题：" + "、".join(i.check_id for i in unresolved),
            remediation=(
                "修复数据或改变设计；确需继续的，对可豁免的检查调用 record_waiver 并写明理由。"
            ),
            details={
                "blocking_checks": [i.check_id for i in unresolved],
                "waivable": [i.check_id for i in unresolved if i.waivable],
                "not_waivable": [i.check_id for i in unresolved if not i.waivable],
            },
        )


def check_all(
    spec: Spec,
    report: QualityReport | None = None,
    waived: Mapping[str, str] | None = None,
) -> None:
    """跑全部门控。任一不通过即抛 GateError。

    ``report`` 省略时只检查 spec 确认——这是切片路径；接入质量检查后必须传。
    """
    check_spec_confirmed(spec)
    if report is not None:
        check_no_blocking_issues(report, waived)

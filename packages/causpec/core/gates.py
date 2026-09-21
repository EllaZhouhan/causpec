"""门控：estimate 执行前的硬性检查。

对应 design.md 11.2。这一层是「框架设闸」的落点——它是代码里的 if，
不是 prompt 里的规则，模型绕不过去。

切片版本只实现第 1 条（spec 确认）。完整的三条还包括：
2. 存在针对当前 (snapshot_fingerprint, spec_hash) 的质量报告，无未处理的 blocking 问题
3. family.supports(spec) 通过，且 spec.estimand 在该 family 声明可识别的范围内
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    details: dict[str, object] = field(default_factory=dict)

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


def check_all(spec: Spec) -> None:
    """跑全部门控。任一不通过即抛 GateError。"""
    check_spec_confirmed(spec)

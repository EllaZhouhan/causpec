"""措辞等级判定。

对应 design.md 10.2、原则 5（结论措辞的强度由代码决定，模型不能自行升级）。

两条核心设计：

1. **代码只能降级，不能授予 causal。** untestable 类假设跑多少检验都验证不了，
   所以代码自动判定的上限是 suggestive。升到 causal 需要人对每条 untestable
   假设给出论证并留名，再显式确认愿意以因果措辞陈述。责任归属因此是清楚的——
   代码保证"诊断没发现问题"，人担保"假设成立"，报告里写明是谁认的。

2. **豁免不改变等级。** 豁免让分析得以进行，但不会让问题消失。被豁免的阻断
   检验仍然把上限压到 associational，且该分析永远达不到 causal。

规则与阈值都在 claim_levels.yaml 里，不写死在代码中：它们决定结论能用多强的
措辞，必须事先定死、写进报告、进 manifest。
"""

from __future__ import annotations

import hashlib
import importlib.resources as resources
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.spec import Spec

# 同 registry：走 importlib.resources，skill 形态下包是从 wheel（zip）里 import 的。
RULES_PACKAGE = "causpec.core.reporting"
RULES_NAME = "claim_levels.yaml"

# 用户显式同意以因果措辞陈述的字段名（design.md 10.2）。
CAUSAL_APPROVAL_FIELD = "causal_claim_approved"


class ClaimLevel(StrEnum):
    """四级措辞，由弱到强。"""

    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    SUGGESTIVE = "suggestive"
    CAUSAL = "causal"


_ORDER = {level: index for index, level in enumerate(ClaimLevel)}


def _rules_bytes(path: Path | None = None) -> bytes:
    if path is not None:
        return path.read_bytes()
    return resources.files(RULES_PACKAGE).joinpath(RULES_NAME).read_bytes()


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(_rules_bytes(path).decode("utf-8"))


def rules_hash(path: Path | None = None) -> str:
    """规则文件的哈希，进 manifest——半年后能复现当时的判定依据。"""
    return hashlib.sha256(_rules_bytes(path)).hexdigest()[:16]


class ClaimLevelDecision(BaseModel):
    """判定结果。

    ``reasons`` 是"为什么不能更高"的逐条说明，报告的"措辞等级及理由"一节
    直接用它——design.md 10.2 要求任何降级都写明是哪项检验、实测值多少、线在哪。
    """

    model_config = ConfigDict(frozen=True)

    level: ClaimLevel
    reasons: list[str] = Field(default_factory=list)
    failed_blocking_checks: list[str] = Field(default_factory=list)
    waived_blocking_checks: list[str] = Field(default_factory=list)
    unjustified_assumptions: list[str] = Field(default_factory=list)
    rules_version: int = 1
    rules_hash: str = ""

    def addresses(self) -> dict[str, float | int | str]:
        """供报告渲染器代入的地址。"""
        return {
            "claim:level": self.level.value,
            "claim:n_failed_blocking_checks": len(self.failed_blocking_checks),
            "claim:n_waived_blocking_checks": len(self.waived_blocking_checks),
            "claim:n_unjustified_assumptions": len(self.unjustified_assumptions),
            "claim:rules_version": self.rules_version,
            "claim:rules_hash": self.rules_hash,
        }

    def at_most(self, level: ClaimLevel) -> bool:
        return _ORDER[self.level] <= _ORDER[level]


def determine(
    spec: Spec,
    report: QualityReport,
    gate_passed: bool,
    waived: dict[str, str] | None = None,
    rules_path: Path | None = None,
) -> ClaimLevelDecision:
    """判定这次分析的结论可以使用的措辞等级。

    Args:
        spec: 已确认的 spec，要读它的 assumptions 与 causal_claim_approved。
        report: 质量检查结果。
        gate_passed: 门控是否通过（由调用方传入，因为门控还要查 spec 确认状态）。
        waived: check_id → 豁免理由。被豁免的阻断检验仍然压低等级。
        rules_path: 规则文件路径，默认用包内的 claim_levels.yaml。
    """
    rules = load_rules(rules_path)
    waived = waived or {}
    reasons: list[str] = []

    # QualityIssue 的不变量：检查通过时 severity 降为 INFO，所以 report.blocking
    # 就是"声明为阻断且确实失败"的那些。见 QualityIssue 的文档。
    failed = [issue.check_id for issue in report.blocking]
    waived_failures = [check for check in failed if check in waived]

    common = {
        "failed_blocking_checks": failed,
        "waived_blocking_checks": waived_failures,
        "rules_version": int(rules["version"]),
        "rules_hash": rules_hash(rules_path),
    }

    if not gate_passed:
        reasons.append("门控未通过：spec 未全部确认，或存在未豁免的 blocking 质量问题。")
        return ClaimLevelDecision(
            level=ClaimLevel(rules["rules"]["gate_failed"]), reasons=reasons, **common
        )

    if failed:
        for check_id in failed:
            issue = report.get(check_id)
            note = "（已豁免，但诊断结论不变）" if check_id in waived else ""
            reasons.append(f"阻断检验未通过：{check_id} —— {issue.summary}{note}")
        return ClaimLevelDecision(
            level=ClaimLevel(rules["rules"]["blocking_check_failed"]), reasons=reasons, **common
        )

    # 到这里两项阻断检验都过了，代码能给的最高级就是 suggestive。
    level = ClaimLevel(rules["rules"]["all_blocking_checks_passed"])
    requirements = rules["causal_requires"]

    unjustified = spec.unjustified_untestable_assumptions()
    approval = spec.fields.get(CAUSAL_APPROVAL_FIELD)
    approved = approval is not None and approval.status.value == "confirmed"

    blockers: list[str] = []
    if requirements["all_untestable_assumptions_justified"] and unjustified:
        blockers.append(
            f"以下 untestable 假设尚未由用户给出论证：{'、'.join(unjustified)}。"
            f"代码无法检验它们，因此也无法据此授予 causal 级措辞。"
        )
    if requirements["explicit_user_approval"] and not approved:
        blockers.append(
            f"用户尚未显式确认愿意以因果措辞陈述（spec 字段 {CAUSAL_APPROVAL_FIELD} 未确认）。"
        )
    if requirements["no_waived_blocking_checks"] and waived:
        blockers.append(
            f"本次分析豁免了检查：{'、'.join(sorted(waived))}，不得使用 causal 级措辞。"
        )

    if blockers:
        reasons.extend(blockers)
        reasons.append(f"代码自动判定的上限是 {rules['code_maximum']}。")
        return ClaimLevelDecision(
            level=level, reasons=reasons, unjustified_assumptions=unjustified, **common
        )

    reasons.append("两项阻断检验均通过；全部 untestable 假设已由用户论证并确认。")
    return ClaimLevelDecision(level=ClaimLevel.CAUSAL, reasons=reasons, **common)

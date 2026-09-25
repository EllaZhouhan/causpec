"""质量检查的产物：QualityIssue 与 QualityReport。

对应 design.md 8.3。每个检查有一个地址 ``qc:<check_id>``，供解读与报告引用
（10.1）；门控按 severity 决定放不放行（11.2）。

G3：即使分析不能运行，质量报告本身也是交付物。所以这一层不依赖估计能否完成。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Layer(StrEnum):
    """检查分层，对应 design.md 8.1 的四层。"""

    BASIC = "basic"  # 类型、范围、唯一性、缺失、NULL 编码变体
    TEMPORAL = "temporal"  # 时间一致性
    IDENTIFICATION = "identification"  # 可识别性：overlap、SMD、instrument relevance
    FEASIBILITY = "feasibility"  # 样本量、事件数、极端权重与 ESS


class Severity(StrEnum):
    """严重程度。BLOCKING 会让门控拒绝执行估计（design.md 11.2 第 2 条）。"""

    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class QualityIssue(BaseModel):
    """一条质量检查结果。

    ``INFO`` 级也是一条 issue——诊断量算出来了但没问题，同样要有地址，
    因为报告要引用它的数值（例如"一阶段 F = {{qc:iv_weak_first_stage.f_statistic}}"）。

    **不变量：``severity`` 反映的是检查的实际结果，不是它的声明。**
    检查通过时 severity 一律降为 ``INFO``，只有失败时才用 family.yaml 里声明的
    级别。因此 ``QualityReport.blocking`` 恰好是"声明为阻断且确实失败"的那些——
    门控与措辞等级判定都依赖这一点。是否通过另外记在 ``evidence["passed"]`` 里。
    """

    model_config = ConfigDict(frozen=True)

    check_id: str
    layer: Layer
    severity: Severity
    waivable: bool
    summary: str
    evidence: dict[str, float | int | str | bool] = Field(default_factory=dict)
    affected_columns: list[str] = Field(default_factory=list)
    impact_on_analysis: str = ""
    recommended_repair: str = ""

    @property
    def address(self) -> str:
        """这条检查的地址前缀。证据的地址是 ``qc:<check_id>.<key>``。"""
        return f"qc:{self.check_id}"

    def evidence_addresses(self) -> dict[str, float | int | str]:
        """把证据摊成可供报告引用的地址。布尔值转成 yes/no，便于正文直接代入。"""

        def render(value: float | int | str | bool) -> float | int | str:
            return ("yes" if value else "no") if isinstance(value, bool) else value

        return {f"{self.address}.{key}": render(v) for key, v in self.evidence.items()}


class QualityReport(BaseModel):
    """一次质量检查的全部结果。"""

    model_config = ConfigDict(frozen=True)

    issues: list[QualityIssue] = Field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity is severity]

    @property
    def blocking(self) -> list[QualityIssue]:
        """门控要看的那一批。"""
        return self.by_severity(Severity.BLOCKING)

    def get(self, check_id: str) -> QualityIssue:
        for issue in self.issues:
            if issue.check_id == check_id:
                return issue
        known = "、".join(i.check_id for i in self.issues) or "（无）"
        raise KeyError(f"没有这条检查：{check_id}。已有：{known}")

    def addresses(self) -> dict[str, float | int | str]:
        """全部证据的地址表，供报告渲染器代入。"""
        out: dict[str, float | int | str] = {}
        for issue in self.issues:
            out.update(issue.evidence_addresses())
        return out

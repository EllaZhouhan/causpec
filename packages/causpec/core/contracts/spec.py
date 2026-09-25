"""最小 Spec：字段级来源与状态。

对应 design.md 7.1。这是垂直切片版本，只包含门控需要的最少字段；
完整结构（population、variable_roles、key_non_edges、assumptions……）见 7.2，Phase 0 任务 2 补齐。
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(StrEnum):
    """字段的值从哪来。"""

    USER = "user"
    MODEL = "model"
    DATA = "data"


class Status(StrEnum):
    """字段的确认状态。

    数据与 spec 冲突不在这里表达：那由质量检查产生 blocking issue，门控第 2 条拦住
    （design.md 7.1）。多一个状态就是多一套要维护、要测试的机制，而门控已经够了。
    """

    DRAFTED = "drafted"
    CONFIRMED = "confirmed"


class SpecField(BaseModel):
    """一个 spec 字段，连同它的来源与状态。

    ``said`` 有两处必填（design.md 7.1）：

    - ``source=user`` 时——用户说的话是证据，要原样留底（原则 2）
    - ``status=confirmed`` 时——确认时用户说的那句话，与 ``source`` 无关

    第二条堵的是门控的根部漏洞：``update_field`` 由模型调用，server 无从验证用户
    是否真的确认过。要求确认必附原话，模型想跳过确认就得编造一句用户的话，而这句话
    会印在报告首页的 spec 全文里，用户一眼能认出。堵不死，但把痕迹留下了。
    """

    model_config = ConfigDict(frozen=True)

    value: Any
    source: Source
    status: Status = Status.DRAFTED
    said: str | None = None
    turn: int | None = None

    @model_validator(mode="after")
    def _quote_required(self) -> SpecField:
        if self.source is Source.USER and not self.said:
            raise ValueError("source=user 时必须记录用户原话（said）")
        if self.status is Status.CONFIRMED and not self.said:
            raise ValueError("status=confirmed 时必须记录用户确认时的原话（said）")
        return self


class AssumptionCategory(StrEnum):
    """假设的三分类（design.md 7.2）。

    分类决定了这条假设能被什么支撑：

    - ``EMPIRICALLY_ASSESSED``：数据能查。质量检查会给出证据（例如 overlap、
      instrument relevance）。
    - ``REQUIRES_JUSTIFICATION``：数据查不了，但可以论证（例如处理定义是否唯一）。
    - ``UNTESTABLE``：原则上无法由数据检验（unconfoundedness、exclusion
      restriction、monotonicity）。**跑多少检验都证明不了它们。**

    最后一类决定了代码判定的措辞等级上限：代码只能说"诊断没发现问题"，
    不能说"因果成立"。要用 causal 级措辞，必须由人对每条 untestable 假设
    给出论证并留名（design.md 10.2）。
    """

    EMPIRICALLY_ASSESSED = "empirically_assessed"
    REQUIRES_JUSTIFICATION = "requires_justification"
    UNTESTABLE = "untestable"


class Assumption(BaseModel):
    """一条识别假设。

    ``statement`` 由 family.yaml 提供，``justification`` 由用户填。
    ``justified_by`` 记谁给的论证——``source=model`` 的论证不算数，因为
    模型论证自己的假设成立是循环的（design.md 10.2）。
    """

    model_config = ConfigDict(frozen=True)

    id: str
    category: AssumptionCategory
    statement: str
    justification: str = ""
    justified_by: Source | None = None

    @property
    def is_justified_by_user(self) -> bool:
        return bool(self.justification.strip()) and self.justified_by is Source.USER


# 门控要求全部 confirmed 的关键字段（design.md 7.1）。
# 切片版本只列三个；完整清单还包括 population、variable_roles、key_non_edges、
# identification_strategy、adjustment_set、instrument 等。
CRITICAL_FIELDS = ("treatment", "outcome", "estimand")


class Spec(BaseModel):
    """分析规格。"""

    model_config = ConfigDict(frozen=True)

    spec_version: int = 1
    question: str
    family: str
    fields: dict[str, SpecField] = Field(default_factory=dict)
    # design.md 7.2 的 estimation: {family, params, seed}。
    # 估计器超参放这里而不是写死在 family 代码里——它们影响结果，
    # 因此必须随 spec 一起被确认、进 spec_hash、进 manifest。
    estimation: dict[str, Any] = Field(default_factory=dict)
    # design.md 7.2 的 assumptions：三分类 + 论证。措辞等级判定要读它。
    assumptions: list[Assumption] = Field(default_factory=list)

    def param(self, name: str, default: Any) -> Any:
        """取一个估计器超参，没有则用默认值。"""
        params = self.estimation.get("params") or {}
        return params.get(name, default)

    def unconfirmed_critical_fields(self) -> list[str]:
        """返回尚未确认的关键字段，按 CRITICAL_FIELDS 的顺序。缺失也算未确认。"""
        return [
            name
            for name in CRITICAL_FIELDS
            if (field := self.fields.get(name)) is None or field.status is not Status.CONFIRMED
        ]

    def untestable_assumptions(self) -> list[Assumption]:
        return [a for a in self.assumptions if a.category is AssumptionCategory.UNTESTABLE]

    def unjustified_untestable_assumptions(self) -> list[str]:
        """没有由用户给出论证的 untestable 假设。causal 级措辞的拦路条件。"""
        return [a.id for a in self.untestable_assumptions() if not a.is_justified_by_user]

    def spec_hash(self) -> str:
        """对 spec 内容取稳定哈希，用于锁定 primary 分析与门控比对（design.md 11.1）。"""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

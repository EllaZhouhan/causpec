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

    def unconfirmed_critical_fields(self) -> list[str]:
        """返回尚未确认的关键字段，按 CRITICAL_FIELDS 的顺序。缺失也算未确认。"""
        return [
            name
            for name in CRITICAL_FIELDS
            if (field := self.fields.get(name)) is None or field.status is not Status.CONFIRMED
        ]

    def spec_hash(self) -> str:
        """对 spec 内容取稳定哈希，用于锁定 primary 分析与门控比对（design.md 11.1）。"""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

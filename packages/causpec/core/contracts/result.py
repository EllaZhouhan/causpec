"""带地址的计算结果。

对应 design.md 10.1。所有计算产物都有地址，例如 ``res:primary.estimate``、
``qc:overlap_extreme_propensity``、``fig:cate_distribution``。
报告正文只能通过占位符引用这些地址，渲染器按地址代入。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Result(BaseModel):
    """一次估计的结果，扁平地址 -> 值。

    地址用 ``<namespace>:<path>`` 形式，namespace 目前有 res / qc / fig。
    """

    model_config = ConfigDict(frozen=True)

    family: str
    seed: int
    values: dict[str, float | int | str]

    def resolve(self, address: str) -> float | int | str:
        """按地址取值，取不到就抛错——渲染器据此拒绝不存在的地址。"""
        try:
            return self.values[address]
        except KeyError:
            known = ", ".join(sorted(self.values)) or "（空）"
            raise KeyError(f"地址不存在：{address}。可用地址：{known}") from None

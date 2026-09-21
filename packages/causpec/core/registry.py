"""Family 注册表：core 与 family 之间的唯一接口。

对应 design.md 第 4 节的分层规则。方向是单向的：

    families/hte_iv  ──import──>  core.registry        ✅ 允许
    core.*           ──import──>  families.*           ❌ import-linter 禁止

core 定义「一个 family 必须长什么样」，各 family 实现它并向这里报到。
core 永远不认识任何具体的 family，因此新增一种分析只需
增加一个 family 目录和一行注册。

尚未实现：route_family（返回候选 family 与被排除的 family 及原因，design.md 7.6）、
family 专属的质量检查挂载点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec


@runtime_checkable
class Family(Protocol):
    """一个 family 必须提供的接口。"""

    id: str

    def estimate(self, rows: list[dict[str, str]], spec: Spec, seed: int) -> Result:
        """跑估计，返回带地址的结果。"""
        ...


_REGISTRY: dict[str, Family] = {}


def register(family: Family) -> Family:
    """把一个 family 登记进来。可作装饰器用。"""
    if family.id in _REGISTRY:
        raise ValueError(f"family 已注册：{family.id}")
    _REGISTRY[family.id] = family
    return family


def get(family_id: str) -> Family:
    """按 id 取 family。"""
    try:
        return _REGISTRY[family_id]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "（无）"
        raise KeyError(f"未注册的 family：{family_id}。已注册：{known}") from None


def list_families() -> list[str]:
    """已注册的 family id。"""
    return sorted(_REGISTRY)


def load_declaration(family_id: str) -> dict[str, object]:
    """读某个 family 的 family.yaml 声明。

    声明里写着这个 family 回答什么问题、能识别哪些 estimand、需要什么、假设什么，
    是 design.md 7.6 estimand 对账的依据。
    """
    path = Path(__file__).parent.parent / "families" / family_id / "family.yaml"
    if not path.exists():
        raise FileNotFoundError(f"缺少声明文件：{path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def declared_estimands(family_id: str) -> list[str]:
    """某个 family 声明可识别的 estimand id 列表。"""
    declaration = load_declaration(family_id)
    estimands = declaration.get("estimands") or []
    assert isinstance(estimands, list)
    return [e["id"] for e in estimands]

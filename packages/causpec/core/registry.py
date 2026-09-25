"""Family 注册表：core 与 family 之间的唯一接口。

对应 design.md 第 4 节的分层规则。方向是单向的：

    families/hte_iv  ──import──>  core.registry        ✅ 允许
    core.*           ──import──>  families.*           ❌ import-linter 禁止

core 定义「一个 family 必须长什么样」，各 family 实现它并向这里报到。
core 永远不认识任何具体的 family——``get()`` 按 id 动态导入，靠的是约定
``causpec.families.<id>``，不是写死的 import。

重依赖（econml 等）放在 extra 里，core 保持轻量。family 的依赖没装时，
``get()`` 抛 ``FamilyUnavailable``，带上安装命令，而不是一个裸的 ImportError。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import yaml

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:
    import pandas as pd

FAMILIES_DIR = Path(__file__).parent.parent / "families"


@runtime_checkable
class Family(Protocol):
    """一个 family 必须提供的接口。"""

    id: str

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        """跑估计，返回带地址的结果。"""
        ...

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        """跑这个 family 的专属质量检查。

        与 estimate 分开：G3 要求即使分析不能运行，质量报告本身也是交付物。
        """
        ...


@dataclass
class FamilyUnavailable(Exception):
    """family 的依赖没装。结构化错误，带修复命令（design.md 11.2）。"""

    code: str
    reason: str
    remediation: str
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.reason}\n  修复：{self.remediation}"


_REGISTRY: dict[str, Family] = {}


def register(family: Family) -> Family:
    """把一个 family 登记进来。由 family 包自己在 import 时调用。"""
    if family.id in _REGISTRY:
        raise ValueError(f"family 已注册：{family.id}")
    _REGISTRY[family.id] = family
    return family


def declared_families() -> list[str]:
    """磁盘上声明了 family.yaml 的所有 family，与是否已导入无关。"""
    return sorted(p.parent.name for p in FAMILIES_DIR.glob("*/family.yaml"))


def load_declaration(family_id: str) -> dict[str, Any]:
    """读某个 family 的 family.yaml 声明。

    声明里写着这个 family 回答什么问题、能识别哪些 estimand、需要什么、假设什么，
    是 design.md 7.6 estimand 对账的依据。
    """
    path = FAMILIES_DIR / family_id / "family.yaml"
    if not path.exists():
        known = "、".join(declared_families()) or "（无）"
        raise FileNotFoundError(f"未知的 family：{family_id}。已声明的：{known}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def declared_estimands(family_id: str) -> list[str]:
    """某个 family 声明可识别的 estimand id 列表。"""
    estimands: list[dict[str, Any]] = load_declaration(family_id).get("estimands") or []
    return [e["id"] for e in estimands]


def get(family_id: str) -> Family:
    """按 id 取 family，必要时动态导入。

    Raises:
        FileNotFoundError: 没有这个 family 的声明。
        FamilyUnavailable: 声明存在，但它的依赖没装。
    """
    if family_id in _REGISTRY:
        return _REGISTRY[family_id]

    declaration = load_declaration(family_id)  # 顺带校验 id 存在
    try:
        importlib.import_module(f"causpec.families.{family_id}")
    except ImportError as error:
        extra = declaration.get("requires_extra")
        remediation = (
            f"安装 causpec[{extra}]：uv sync --extra {extra}（或 pip install 'causpec[{extra}]'）"
            if extra
            else f"这个 family 的依赖缺失：{error}"
        )
        raise FamilyUnavailable(
            code="FAMILY_DEPENDENCY_MISSING",
            reason=f"family {family_id} 的依赖未安装（{error.name or error}）",
            remediation=remediation,
            details={"family": family_id, "extra": extra, "missing_module": error.name},
        ) from error

    if family_id not in _REGISTRY:
        raise RuntimeError(
            f"causpec.families.{family_id} 导入成功但没有调用 register()——检查该包的 __init__.py"
        )
    return _REGISTRY[family_id]


def list_families() -> list[str]:
    """已导入并注册的 family id。想知道磁盘上有哪些用 declared_families()。"""
    return sorted(_REGISTRY)

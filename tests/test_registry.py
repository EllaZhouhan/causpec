"""注册表：动态导入、声明读取、缺依赖时的结构化错误。

对应 design.md 第 4 节（core 不认识具体 family）与 11.2（结构化错误 + 修复建议）。
"""

from __future__ import annotations

import sys

import pytest

from causpec.core import registry


def test_declared_families_reads_disk() -> None:
    """core 通过磁盘上的 family.yaml 知道有哪些 family，不靠写死的 import。"""
    assert registry.declared_families() == ["hte_backdoor", "hte_iv", "longitudinal_ipcw"]


def test_unknown_family_names_the_known_ones() -> None:
    with pytest.raises(FileNotFoundError, match="hte_backdoor、hte_iv"):
        registry.get("did")


def test_hte_iv_declares_both_instrument_kinds() -> None:
    """design.md 7.6：二值与连续 instrument 识别的对象不同，要分别声明。"""
    declaration = registry.load_declaration("hte_iv")
    by_kind = {e["instrument_kind"]: e["id"] for e in declaration["estimands"]}
    assert by_kind == {
        "binary": "conditional_late",
        "continuous": "weighted_conditional_late",
    }


def test_continuous_estimand_requires_uniformity_not_monotonicity() -> None:
    """连续 instrument 下 monotonicity 要推广成 uniformity（Angrist & Imbens 1995）。"""
    declaration = registry.load_declaration("hte_iv")
    continuous = next(e for e in declaration["estimands"] if e["instrument_kind"] == "continuous")
    assert "uniformity" in continuous["requires_assumptions"]
    assert "monotonicity" not in continuous["requires_assumptions"]


def test_missing_dependency_gives_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """装不上 econml 时报的是结构化错误 + 安装命令，不是裸 ImportError。

    把 sys.modules["econml"] 设成 None，Python 会让 ``import econml`` 抛 ImportError,
    等价于没装这个包。同时清掉 family 模块的缓存，强制走一次真的 import。
    """
    monkeypatch.delitem(registry._REGISTRY, "hte_iv", raising=False)
    for module in ("causpec.families.hte_iv", "causpec.families.hte_iv.estimator"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    for module in [m for m in sys.modules if m == "econml" or m.startswith("econml.")]:
        monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.setitem(sys.modules, "econml", None)

    with pytest.raises(registry.FamilyUnavailable) as excinfo:
        registry.get("hte_iv")

    error = excinfo.value
    assert error.code == "FAMILY_DEPENDENCY_MISSING"
    assert "econml" in error.reason or "econml" in str(error)
    assert "--extra hte" in error.remediation
    assert error.details["extra"] == "hte"

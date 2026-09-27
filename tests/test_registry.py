"""Registry: dynamic import, declaration loading, structured missing-dependency errors.

Mirrors design.md section 4 (core knows no specific family) and 11.2 (a structured
error carrying its own fix).
"""

from __future__ import annotations

import sys

import pytest

from causpec.core import registry


def test_declared_families_reads_disk() -> None:
    """Core learns which families exist from family.yaml on disk, not a hard-coded import."""
    assert registry.declared_families() == ["hte_backdoor", "hte_iv", "longitudinal_ipcw"]


def test_unknown_family_names_the_known_ones() -> None:
    with pytest.raises(FileNotFoundError, match="hte_backdoor, hte_iv"):
        registry.get("did")


def test_hte_iv_declares_both_instrument_kinds() -> None:
    """design.md 7.6: binary and continuous instruments identify different estimands."""
    declaration = registry.load_declaration("hte_iv")
    by_kind = {e["instrument_kind"]: e["id"] for e in declaration["estimands"]}
    assert by_kind == {
        "binary": "conditional_late",
        "continuous": "weighted_conditional_late",
    }


def test_continuous_estimand_requires_uniformity_not_monotonicity() -> None:
    """With a continuous instrument, monotonicity generalises to uniformity
    (Angrist & Imbens 1995)."""
    declaration = registry.load_declaration("hte_iv")
    continuous = next(e for e in declaration["estimands"] if e["instrument_kind"] == "continuous")
    assert "uniformity" in continuous["requires_assumptions"]
    assert "monotonicity" not in continuous["requires_assumptions"]


def test_missing_dependency_gives_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing econml yields a structured error with the install command, not a bare
    ImportError.

    Setting sys.modules["econml"] to None makes ``import econml`` raise ImportError,
    which is equivalent to the package being absent. The family module's cache is
    cleared too, to force a real import.
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

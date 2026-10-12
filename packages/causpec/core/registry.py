"""Family registry: the only interface between core and the families.

Mirrors design.md section 4. The dependency runs one way:

    families/hte_iv  --imports-->  core.registry        allowed
    core.*           --imports-->  families.*           forbidden (import-linter)

Core defines what a family must look like; each family implements it and registers
itself. Core never names a specific family, ``get()`` imports by id, relying on the
``causpec.families.<id>`` convention rather than a hard-coded import.

Heavy dependencies (econml and friends) live behind an extra so core stays light.
When a family's dependencies are absent, ``get()`` raises ``FamilyUnavailable`` with
the install command instead of a bare ImportError.
"""

from __future__ import annotations

import importlib
import importlib.resources as resources
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import yaml

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:
    import pandas as pd

FAMILIES_PACKAGE = "causpec.families"


@runtime_checkable
class Family(Protocol):
    """What a family must provide."""

    id: str

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        """Run the estimation and return addressed results."""
        ...

    def check(self, data: pd.DataFrame, spec: Spec) -> QualityReport:
        """Run this family's own quality checks.

        Separate from estimate: G3 requires the quality report to be a deliverable
        even when the analysis cannot run.
        """
        ...


@dataclass
class FamilyUnavailable(Exception):
    """A family's dependencies are not installed. Structured, with the fix (11.2)."""

    code: str
    reason: str
    remediation: str
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.reason}\n  Fix: {self.remediation}"


_REGISTRY: dict[str, Family] = {}


def register(family: Family) -> Family:
    """Register a family. Called by the family package itself at import time."""
    if family.id in _REGISTRY:
        raise ValueError(f"family already registered: {family.id}")
    _REGISTRY[family.id] = family
    return family


def declared_families() -> list[str]:
    """Every family that ships a family.yaml, whether or not it has been imported.

    Uses importlib.resources rather than filesystem paths: in skill form causpec is
    imported straight out of a wheel (a zip), where ``Path(__file__)`` points at no
    real file. Found by actually running skill/scripts/run.py in a clean environment.
    """
    root = resources.files(FAMILIES_PACKAGE)
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and entry.joinpath("family.yaml").is_file()
    )


def load_declaration(family_id: str) -> dict[str, Any]:
    """Read one family's family.yaml declaration.

    The declaration states what question the family answers, which estimands it can
    identify, what it needs and what it assumes, the basis for the estimand
    reconciliation of design.md 7.6.
    """
    # Navigate from the parent package and **do not import the subpackage**:
    # resources.files("causpec.families.hte_iv") executes that package's __init__ and
    # pulls in econml. Reading a declaration should not require its dependencies:
    # the whole point of `requires_extra` is telling people what to install first.
    resource = resources.files(FAMILIES_PACKAGE).joinpath(family_id).joinpath("family.yaml")
    try:
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, OSError, KeyError) as error:
        known = ", ".join(declared_families()) or "(none)"
        raise FileNotFoundError(f"Unknown family: {family_id}. Declared: {known}") from error
    return yaml.safe_load(text)


def declared_estimands(family_id: str) -> list[str]:
    """The estimand ids a family declares it can identify."""
    estimands: list[dict[str, Any]] = load_declaration(family_id).get("estimands") or []
    return [e["id"] for e in estimands]


def required_spec_fields(family_id: str) -> list[str]:
    """The spec fields a family cannot run without, from its declaration."""
    requires: dict[str, Any] = load_declaration(family_id).get("requires") or {}
    return [str(name) for name in (requires.get("spec_fields") or [])]


def estimand_assumptions(family_id: str, estimand_id: str) -> list[str]:
    """The assumption ids one estimand's identification rests on."""
    for entry in load_declaration(family_id).get("estimands") or []:
        if entry.get("id") == estimand_id:
            return [str(name) for name in (entry.get("requires_assumptions") or [])]
    return []


def families_declaring_estimand(estimand_id: str) -> list[str]:
    """Which families can identify this estimand, for an error message that helps.

    A user told only "this family cannot answer that" has to go looking. A user told
    which family can has somewhere to go.
    """
    return [family for family in declared_families() if estimand_id in declared_estimands(family)]


def get(family_id: str) -> Family:
    """Look up a family by id, importing it on demand.

    Raises:
        FileNotFoundError: no such family is declared.
        FamilyUnavailable: it is declared, but its dependencies are missing.
    """
    if family_id in _REGISTRY:
        return _REGISTRY[family_id]

    declaration = load_declaration(family_id)  # also validates that the id exists
    try:
        importlib.import_module(f"causpec.families.{family_id}")
    except ImportError as error:
        extra = declaration.get("requires_extra")
        remediation = (
            f"Install causpec[{extra}]: uv sync --extra {extra} (or pip install 'causpec[{extra}]')"
            if extra
            else f"A dependency of this family is missing: {error}"
        )
        raise FamilyUnavailable(
            code="FAMILY_DEPENDENCY_MISSING",
            reason=f"family {family_id} has an uninstalled dependency ({error.name or error})",
            remediation=remediation,
            details={"family": family_id, "extra": extra, "missing_module": error.name},
        ) from error

    if family_id not in _REGISTRY:
        raise RuntimeError(
            f"causpec.families.{family_id} imported but never called register(), "
            f"check that package's __init__.py"
        )
    return _REGISTRY[family_id]


def list_families() -> list[str]:
    """Families that have been imported and registered. For what is on disk, see
    declared_families()."""
    return sorted(_REGISTRY)

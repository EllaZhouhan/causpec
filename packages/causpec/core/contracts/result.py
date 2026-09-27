"""Addressed computation results.

Mirrors design.md 10.1. Every computed artefact has an address — ``res:primary.ate``,
``qc:overlap_extreme_propensity``, ``fig:cate_distribution``. Report prose may only
reference numbers through these addresses; the renderer substitutes them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Result(BaseModel):
    """One estimation run, as a flat address-to-value map.

    Addresses take the form ``<namespace>:<path>``; namespaces in use are res, qc,
    fig and claim.
    """

    model_config = ConfigDict(frozen=True)

    family: str
    seed: int
    values: dict[str, float | int | str]

    def resolve(self, address: str) -> float | int | str:
        """Look up one address, raising if it is unknown so callers can refuse to render."""
        try:
            return self.values[address]
        except KeyError:
            known = ", ".join(sorted(self.values)) or "(none)"
            raise KeyError(f"No such address: {address}. Available: {known}") from None

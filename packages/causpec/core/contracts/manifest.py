"""Manifest: the complete provenance record for one run.

Mirrors design.md section 14 and G5 (same inputs and seed, same results).

The manifest has to answer one question: **could I rerun this analysis six months
from now and get the same numbers?** So it records everything that can change the
result (code version, dependency versions, spec hash, data fingerprint, seed,
decision-rule hash) plus a checksum per artefact, so tampering is detectable.

**No raw rows, no credentials** (design.md section 14).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExecutionMode(StrEnum):
    """Which form produced this run (design.md section 3).

    ``SKILL`` is best-effort: the agent may bypass the scripts and read the data
    directly, which the report header notes. Recording it here lets a reader judge
    how strong the provenance guarantee actually is.
    """

    MCP = "mcp"
    CLI = "cli"
    SKILL = "skill"


class Manifest(BaseModel):
    """The manifest for one run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    created_at: datetime
    execution_mode: ExecutionMode

    # ---- code provenance ----
    causpec_version: str
    git_sha: str | None = None
    python_version: str = ""
    package_versions: dict[str, str] = Field(default_factory=dict)

    # ---- inputs ----
    spec_hash: str
    snapshot_fingerprint: str | None = None
    seed: int

    # ---- decision basis ----
    # Hash of the claim-level rules file: change the rules and the same data can earn a
    # different wording level, so it belongs with the dependency versions as something
    # that changes conclusions.
    claim_rules_hash: str = ""
    # Hash of the basic-layer thresholds. Change what counts as a placeholder value and the
    # same data can pass or block, so it belongs here for the same reason.
    basic_checks_hash: str = ""

    # ---- artefacts ----
    # Relative path -> sha256, so a run directory edited after the fact is detectable.
    artifacts: dict[str, str] = Field(default_factory=dict)

    def reproducibility_key(self) -> tuple[str, str | None, int, str]:
        """The parts that decide whether two runs should agree. Equal keys, equal results."""
        return (self.spec_hash, self.snapshot_fingerprint, self.seed, self.causpec_version)

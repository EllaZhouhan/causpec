"""Deciding how strongly a conclusion may be worded.

Mirrors design.md 10.2 and principle 5 (code decides the strength of the claim; the
model may not upgrade it).

Two ideas carry this module:

1. **Code can only downgrade; it cannot grant causal.** Untestable assumptions cannot
   be verified by any amount of data, so an automatic decision tops out at
   suggestive. Reaching causal requires a person to justify each untestable
   assumption, sign their name to it, and explicitly agree to causal wording. The
   division of responsibility is then clean, code vouches that "the diagnostics
   found nothing wrong", a person vouches that "the assumptions hold", and the
   report says who did which.

2. **A waiver does not change the diagnosis.** A waived blocking check still caps the
   level at associational, and that analysis can never reach causal. Waiving lets the
   analysis run; it does not make the problem disappear.

Both the rules and the thresholds live in claim_levels.yaml rather than in code:
they decide how strongly a conclusion may be stated, so they must be fixed in
advance, printed in the report, and recorded in the manifest.
"""

from __future__ import annotations

import hashlib
import importlib.resources as resources
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.spec import Spec

# As in registry: importlib.resources, because in skill form the package is imported
# out of a wheel (a zip).
RULES_PACKAGE = "causpec.core.reporting"
RULES_NAME = "claim_levels.yaml"

# The spec field by which the user explicitly agrees to causal wording (design.md 10.2).
CAUSAL_APPROVAL_FIELD = "causal_claim_approved"


class ClaimLevel(StrEnum):
    """The four wording levels, weakest to strongest."""

    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    SUGGESTIVE = "suggestive"
    CAUSAL = "causal"


_ORDER = {level: index for index, level in enumerate(ClaimLevel)}


def _rules_bytes(path: Path | None = None) -> bytes:
    if path is not None:
        return path.read_bytes()
    return resources.files(RULES_PACKAGE).joinpath(RULES_NAME).read_bytes()


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(_rules_bytes(path).decode("utf-8"))


def rules_hash(path: Path | None = None) -> str:
    """Hash of the rules file, for the manifest, so the decision can be reproduced."""
    return hashlib.sha256(_rules_bytes(path)).hexdigest()[:16]


class ClaimLevelDecision(BaseModel):
    """The outcome of a claim-level decision.

    ``reasons`` explains, point by point, why the level could not be higher. The
    report's "claim level and reasoning" section uses it directly, design.md 10.2
    requires every downgrade to name the check, its measured value, and the threshold.
    """

    model_config = ConfigDict(frozen=True)

    level: ClaimLevel
    reasons: list[str] = Field(default_factory=list)
    failed_blocking_checks: list[str] = Field(default_factory=list)
    waived_blocking_checks: list[str] = Field(default_factory=list)
    unjustified_assumptions: list[str] = Field(default_factory=list)
    rules_version: int = 1
    rules_hash: str = ""

    def addresses(self) -> dict[str, float | int | str]:
        """Addresses the report renderer can substitute."""
        return {
            "claim:level": self.level.value,
            "claim:n_failed_blocking_checks": len(self.failed_blocking_checks),
            "claim:n_waived_blocking_checks": len(self.waived_blocking_checks),
            "claim:n_unjustified_assumptions": len(self.unjustified_assumptions),
            "claim:rules_version": self.rules_version,
            "claim:rules_hash": self.rules_hash,
        }

    def at_most(self, level: ClaimLevel) -> bool:
        return _ORDER[self.level] <= _ORDER[level]


def determine(
    spec: Spec,
    report: QualityReport,
    gate_passed: bool,
    waived: dict[str, str] | None = None,
    rules_path: Path | None = None,
) -> ClaimLevelDecision:
    """Decide how strongly this analysis's conclusion may be worded.

    Args:
        spec: the confirmed spec; its assumptions and causal_claim_approved are read.
        report: the quality-check results.
        gate_passed: whether the gate let the run through (passed in by the caller,
            since the gate also inspects spec confirmation).
        waived: check_id -> waiver reason. A waived blocking check still lowers the level.
        rules_path: override the packaged claim_levels.yaml.
    """
    rules = load_rules(rules_path)
    waived = waived or {}
    reasons: list[str] = []

    # QualityIssue invariant: a passing check is downgraded to INFO, so report.blocking
    # is exactly "declared blocking and actually failed". See the QualityIssue docstring.
    failed = [issue.check_id for issue in report.blocking]
    waived_failures = [check for check in failed if check in waived]

    common = {
        "failed_blocking_checks": failed,
        "waived_blocking_checks": waived_failures,
        "rules_version": int(rules["version"]),
        "rules_hash": rules_hash(rules_path),
    }

    if not gate_passed:
        reasons.append(
            "The gate did not pass: the spec is not fully confirmed, or a blocking "
            "quality issue stands unwaived."
        )
        return ClaimLevelDecision(
            level=ClaimLevel(rules["rules"]["gate_failed"]), reasons=reasons, **common
        )

    if failed:
        for check_id in failed:
            issue = report.get(check_id)
            note = " (waived, but the diagnosis is unchanged)" if check_id in waived else ""
            reasons.append(f"Blocking check failed: {check_id}, {issue.summary}{note}")
        return ClaimLevelDecision(
            level=ClaimLevel(rules["rules"]["blocking_check_failed"]), reasons=reasons, **common
        )

    # Both blocking checks passed, so suggestive is the most code can grant.
    level = ClaimLevel(rules["rules"]["all_blocking_checks_passed"])
    requirements = rules["causal_requires"]

    unjustified = spec.unjustified_untestable_assumptions()
    approval = spec.fields.get(CAUSAL_APPROVAL_FIELD)
    approved = approval is not None and approval.status.value == "confirmed"

    blockers: list[str] = []
    if requirements["all_untestable_assumptions_justified"] and unjustified:
        blockers.append(
            f"These untestable assumptions carry no user justification: "
            f"{', '.join(unjustified)}. No diagnostic can verify them, so the code "
            f"cannot grant causal wording on their account."
        )
    if requirements["explicit_user_approval"] and not approved:
        blockers.append(
            f"The user has not explicitly agreed to causal wording "
            f"(spec field {CAUSAL_APPROVAL_FIELD} is unconfirmed)."
        )
    if requirements["no_waived_blocking_checks"] and waived:
        blockers.append(
            f"This analysis waived: {', '.join(sorted(waived))}. Causal wording is not "
            f"available to a waived analysis."
        )

    if blockers:
        reasons.extend(blockers)
        reasons.append(f"The ceiling for an automatic decision is {rules['code_maximum']}.")
        return ClaimLevelDecision(
            level=level, reasons=reasons, unjustified_assumptions=unjustified, **common
        )

    reasons.append(
        "Both blocking checks passed; every untestable assumption has been justified "
        "and approved by the user."
    )
    return ClaimLevelDecision(level=ClaimLevel.CAUSAL, reasons=reasons, **common)

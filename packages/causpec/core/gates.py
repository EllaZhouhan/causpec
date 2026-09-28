"""Gates: the hard checks that run before estimation.

Mirrors design.md 11.2. This is where "the framework holds the gate" lands, these
are ``if`` statements in code, not rules in a prompt, so the model cannot route
around them.

Conditions 1 (spec confirmed) and 2 (no unwaived blocking quality issues) are
implemented. Still missing: condition 3, family.supports(spec) plus the estimand
reconciliation, and binding the quality report to a specific
(snapshot_fingerprint, spec_hash) pair.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.spec import Spec


@dataclass
class GateError(Exception):
    """A structured gate failure: code, reason, and what to do about it.

    Mirrors design.md 11.2 ("return a structured error") and the remediation-registry
    pattern of section 12.
    """

    code: str
    reason: str
    remediation: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.reason}\n  Fix: {self.remediation}"


def check_spec_confirmed(spec: Spec) -> None:
    """Refuse to estimate while any critical field is unconfirmed."""
    unconfirmed = spec.unconfirmed_critical_fields()
    if unconfirmed:
        raise GateError(
            code="SPEC_NOT_CONFIRMED",
            reason=f"Critical fields are not confirmed yet: {', '.join(unconfirmed)}",
            remediation="Confirm each field with the user via update_field, then retry.",
            details={"unconfirmed_fields": unconfirmed},
        )


def check_no_blocking_issues(
    report: QualityReport, waived: Mapping[str, str] | None = None
) -> None:
    """Refuse to estimate while a blocking quality issue stands unwaived.

    ``waived`` maps check_id to the reason for the waiver. A waiver must carry a
    reason (design.md section 12, record_waiver); an empty reason is no waiver at all,
    and a check marked not waivable is never let through.
    """
    waived = waived or {}
    unresolved = []
    for issue in report.blocking:
        reason = waived.get(issue.check_id, "").strip()
        if not reason or not issue.waivable:
            unresolved.append(issue)

    if unresolved:
        # The diagnosis, not just the check id. The caller has already computed the
        # summary and the repair, so withholding them means the user has to run the
        # quality command again to learn what went wrong.
        diagnosis = "\n".join(
            f"  {issue.check_id}: {issue.summary}"
            + (f"\n    Suggested: {issue.recommended_repair}" if issue.recommended_repair else "")
            for issue in unresolved
        )
        raise GateError(
            code="BLOCKING_QUALITY_ISSUES",
            reason="Unresolved blocking quality issues:\n" + diagnosis,
            remediation=(
                "Fix the data or change the design. To proceed anyway, record a waiver "
                "with a reason for each waivable check."
            ),
            details={
                "blocking_checks": [i.check_id for i in unresolved],
                "waivable": [i.check_id for i in unresolved if i.waivable],
                "not_waivable": [i.check_id for i in unresolved if not i.waivable],
            },
        )


def check_all(
    spec: Spec,
    report: QualityReport | None = None,
    waived: Mapping[str, str] | None = None,
) -> None:
    """Run every gate. Any failure raises GateError.

    Omitting ``report`` checks spec confirmation only, the slice path. Once quality
    checks are wired up the report must be passed.
    """
    check_spec_confirmed(spec)
    if report is not None:
        check_no_blocking_issues(report, waived)

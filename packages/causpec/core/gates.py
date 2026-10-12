"""Gates: the hard checks that run before estimation.

Mirrors design.md 11.2. This is where "the framework holds the gate" lands, these
are ``if`` statements in code, not rules in a prompt, so the model cannot route
around them.

Conditions 1 (spec confirmed), 2 (no unwaived blocking quality issues) and 3
(the family can run this spec and can identify this estimand) are implemented.

Still missing: binding the quality report to a specific (snapshot_fingerprint, spec_hash)
pair. Both halves of that pair now exist and are recorded in the manifest; what is not
built is a gate refusing a report computed from a different pair.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from causpec.core import registry
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
    check_family_supports_spec(spec)
    if report is not None:
        check_no_blocking_issues(report, waived)


def check_family_supports_spec(spec: Spec) -> None:
    """Gate condition 3: the family can run this spec, and can answer this question.

    Two different failures, both of which reach the user today as something worse than a
    refusal.

    **A missing required field** currently surfaces from inside a family's own code, as a
    bare `ValueError: hte_iv's quality checks require spec.instrument` with a traceback. That
    is a precondition stated in family.yaml under `requires.spec_fields`, so it belongs here,
    phrased as what is missing and what to do.

    **An estimand the family cannot identify** currently does not surface at all. The spec
    field is a label and the estimator never reads it, so `estimand: conditional_late` on
    `hte_backdoor` runs to completion and the report describes an average over everyone using
    the words for an effect among compliers, which is a different population and a different
    number. Reconciling the label against the declaration is the only thing standing between
    those two readings (design.md 7.6).
    """
    missing = [
        name
        for name in registry.required_spec_fields(spec.family)
        if spec.fields.get(name) is None or spec.fields[name].value is None
    ]
    if missing:
        raise GateError(
            code="FAMILY_REQUIRES_FIELDS",
            reason=(
                f"{spec.family} cannot run without: {', '.join(missing)}. Its declaration "
                f"lists these under `requires.spec_fields`."
            ),
            remediation=(
                "Confirm each missing field with the user and add it to the spec, or choose a "
                "family whose requirements this spec meets."
            ),
            details={"family": spec.family, "missing_fields": missing},
        )

    entry = spec.fields.get("estimand")
    declared = registry.declared_estimands(spec.family)
    if entry is None or entry.value is None or not declared:
        return
    asked = str(entry.value)
    if asked in declared:
        return
    elsewhere = registry.families_declaring_estimand(asked)
    where = (
        f" {asked!r} is declared by: {', '.join(elsewhere)}."
        if elsewhere
        else f" No family declares {asked!r}."
    )
    raise GateError(
        code="ESTIMAND_NOT_SUPPORTED",
        reason=(
            f"{spec.family} cannot identify {asked!r}. It declares: {', '.join(declared)}." + where
        ),
        remediation=(
            "An estimand names which question the number answers, and for whom. The "
            "estimator does not read this field, so a label the family cannot support would "
            "be printed over a number that answers something else. Either pick an estimand "
            "this family identifies, or route the analysis to the family that identifies the "
            "one you want."
        ),
        details={"family": spec.family, "asked": asked, "declared": declared},
    )

"""Gates: the hard checks that run before estimation.

Mirrors design.md 11.2. This is where "the framework holds the gate" lands, these
are ``if`` statements in code, not rules in a prompt, so the model cannot route
around them.

Conditions 1 (spec confirmed), 2 (no unwaived blocking quality issues) and 3
(the family can run this spec and can identify this estimand) are implemented.

Condition 2 has two halves and both are implemented: no unwaived blocking issues, and the
report being the one computed for this run's (snapshot_fingerprint, spec_hash) pair. The
second half is what stops a report from a different extract, or from before a spec change,
being used to clear a run it never looked at.
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
    snapshot_fingerprint: str | None = None,
) -> None:
    """Run every gate. Any failure raises GateError.

    Omitting ``report`` checks spec confirmation and family support only, the slice path.

    Omitting ``snapshot_fingerprint`` skips the staleness check, because there is nothing to
    compare the report against. A caller that has the fingerprint must pass it: without it the
    gate cannot tell a report about this run from one about a different dataset, and that is
    the whole of what the check is for.
    """
    check_spec_confirmed(spec)
    check_family_supports_spec(spec)
    if report is not None:
        if snapshot_fingerprint is not None:
            check_report_matches_run(report, spec, snapshot_fingerprint)
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


def check_report_matches_run(report: QualityReport, spec: Spec, snapshot_fingerprint: str) -> None:
    """The remaining half of design.md 11.2's condition 2: the right report for this run.

    Condition 2 asks for a quality report with no unwaived blocking issues **for the current
    (snapshot_fingerprint, spec_hash) pair**. The first half was implemented; this is the
    pair.

    In the CLI it cannot currently go wrong, because the checks and the estimation happen in
    one process on one frame. It is not the CLI this defends. The skill form runs the checks
    and the estimation as two scripts, and the MCP server takes a report from a client, so in
    both a report computed on yesterday's extract, or before a preprocessing step was agreed,
    can arrive at an estimation that it says nothing about. Every check would read as passed
    and none of them would have looked at this data.

    A report with no stamp is refused here rather than accepted. Accepting it is exactly the
    hole: an unverifiable report and a verified one would be treated alike, and the one that
    matters is the one nobody stamped.
    """
    if not report.spec_hash or not report.snapshot_fingerprint:
        raise GateError(
            code="QUALITY_REPORT_UNVERIFIABLE",
            reason=(
                "The quality report does not record which spec and which table it was "
                "computed from, so it cannot be shown to describe this run."
            ),
            remediation=(
                "Stamp the report with the spec hash and the snapshot fingerprint when the "
                "checks are run (QualityReport.stamped), or run the checks and the estimation "
                "in one call."
            ),
            details={"expected_spec_hash": spec.spec_hash()},
        )
    expected = spec.spec_hash()
    if report.spec_hash != expected or report.snapshot_fingerprint != snapshot_fingerprint:
        raise GateError(
            code="QUALITY_REPORT_STALE",
            reason=(
                f"The quality report was computed for spec {report.spec_hash} on table "
                f"{report.snapshot_fingerprint}, and this run is spec {expected} on table "
                f"{snapshot_fingerprint}. Its verdicts do not describe this analysis."
            ),
            remediation=(
                "Re-run the quality checks on the data and spec being estimated. A report "
                "from before a spec change or a different extract says nothing about this one, "
                "however many of its checks passed."
            ),
            details={
                "report_spec_hash": report.spec_hash,
                "run_spec_hash": expected,
                "report_snapshot_fingerprint": report.snapshot_fingerprint,
                "run_snapshot_fingerprint": snapshot_fingerprint,
            },
        )

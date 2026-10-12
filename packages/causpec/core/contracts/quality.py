"""Quality-check output: QualityIssue and QualityReport.

Mirrors design.md 8.3. Each check has an address ``qc:<check_id>`` for interpretation
and reporting (10.1); the gate decides what to let through by severity (11.2).

G3: the quality report is a deliverable in its own right, even when the analysis
cannot run. This layer therefore does not depend on estimation succeeding.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Layer(StrEnum):
    """The four check layers of design.md 8.1."""

    BASIC = "basic"  # types, ranges, uniqueness, missingness, NULL-encoding variants
    TEMPORAL = "temporal"  # time consistency
    IDENTIFICATION = "identification"  # overlap, SMD, instrument relevance
    FEASIBILITY = "feasibility"  # sample sizes, event counts, extreme weights, ESS


class Severity(StrEnum):
    """How serious. BLOCKING makes the gate refuse to estimate (design.md 11.2)."""

    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class Suggestion(BaseModel):
    """One way forward the user can accept, with what it costs.

    `kind` says which part of the spec the answer goes into, and the two differ in what they
    do. A `preprocessing` step changes the data: a recode changes only how a value is written
    down, an imputation substitutes values nobody measured. A `population_filter` changes
    **who the answer is about**, and accepting one puts a row in the report's exclusion
    ledger.

    `cost` is the sentence to read back to the user. It exists because the agent would
    otherwise invent one, and the trade-offs here are the kind that sound reasonable in
    either direction: "we filled the gaps" and "we dropped the incomplete records" both sound
    like diligence.

    `operation` is the spec fragment, ready to write once the user has agreed in their own
    words. Nothing runs before that, which `PreprocessingStep` and `PopulationFilter`
    enforce for themselves.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    operation: dict[str, Any]
    cost: str = ""


class QualityIssue(BaseModel):
    """One quality-check result.

    ``INFO`` results are issues too: a diagnostic that computed cleanly still needs an
    address, because the report cites its value (e.g. "first-stage F =
    {{qc:iv_weak_first_stage.robust_f}}").

    **Invariant: ``severity`` reflects the check's outcome, not its declaration.**
    A check that passes is always downgraded to ``INFO``; only a failure carries the
    severity declared in family.yaml. ``QualityReport.blocking`` is therefore exactly
    the set of checks that were declared blocking *and* failed, both the gate and the
    claim-level decision rely on this. Pass/fail is recorded separately in
    ``evidence["passed"]``.
    """

    model_config = ConfigDict(frozen=True)

    check_id: str
    layer: Layer
    severity: Severity
    waivable: bool
    summary: str
    evidence: dict[str, float | int | str | bool] = Field(default_factory=dict)
    affected_columns: list[str] = Field(default_factory=list)
    impact_on_analysis: str = ""
    recommended_repair: str = ""
    # Ways forward the user can accept, in the order they are worth considering. A list
    # rather than one operation because the honest answer to missing values is a menu: fill
    # the column, exclude the units, or drop the column, and the choice is a trade the user
    # has to make rather than one a default can make for them.
    #
    # Many checks carry none, deliberately. A duplicated join, an outlier and too few events
    # have no safe automatic answer, and offering one would invite the user to make a problem
    # invisible instead of deciding about it.
    suggestions: list[Suggestion] = Field(default_factory=list)

    @property
    def address(self) -> str:
        """Address prefix for this check. Evidence lives at ``qc:<check_id>.<key>``."""
        return f"qc:{self.check_id}"

    def evidence_addresses(self) -> dict[str, float | int | str]:
        """Flatten evidence into report-citable addresses.

        Booleans render as yes/no so prose can substitute them directly.
        """

        def render(value: float | int | str | bool) -> float | int | str:
            return ("yes" if value else "no") if isinstance(value, bool) else value

        return {f"{self.address}.{key}": render(v) for key, v in self.evidence.items()}


class QualityReport(BaseModel):
    """All results from one quality-check run.

    A report can carry **what it was computed from**, as the pair design.md 11.2 names: the
    spec's hash and the fingerprint of the analysed table. Without that pair a report is a
    list of verdicts about nothing in particular, and the gate has no way to tell a report
    about this run from one about a different dataset. It matters for the forms where the
    checks and the estimation are separate calls, which is every form except the CLI: the
    skill runs two scripts, and the MCP server takes a report from a client.

    Optional because the `quality` command's report is a deliverable in its own right, with no
    estimation to gate. `stamped` is how a caller that knows the pair attaches it.
    """

    model_config = ConfigDict(frozen=True)

    issues: list[QualityIssue] = Field(default_factory=list)
    spec_hash: str = ""
    snapshot_fingerprint: str = ""

    def stamped(self, *, spec_hash: str, snapshot_fingerprint: str) -> QualityReport:
        """A copy recording which spec and which table these verdicts were computed from."""
        return self.model_copy(
            update={"spec_hash": spec_hash, "snapshot_fingerprint": snapshot_fingerprint}
        )

    def by_severity(self, severity: Severity) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity is severity]

    @property
    def blocking(self) -> list[QualityIssue]:
        """What the gate looks at."""
        return self.by_severity(Severity.BLOCKING)

    def get(self, check_id: str) -> QualityIssue:
        for issue in self.issues:
            if issue.check_id == check_id:
                return issue
        known = ", ".join(i.check_id for i in self.issues) or "(none)"
        raise KeyError(f"No such check: {check_id}. Present: {known}")

    def addresses(self) -> dict[str, float | int | str]:
        """Every piece of evidence, keyed by address, for the report renderer."""
        out: dict[str, float | int | str] = {}
        for issue in self.issues:
            out.update(issue.evidence_addresses())
        return out

"""CauSpec command-line entry point.

``quality`` runs the checks alone, G3 requires the quality report to be a
deliverable even when the analysis cannot run.
``estimate`` runs the checks, passes the gate, estimates, and optionally renders a
report.
A standalone ``report`` subcommand is still to come; ``estimate --report`` covers it
for now.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from causpec import __version__
from causpec.core import registry
from causpec.core.contracts.manifest import ExecutionMode
from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.fingerprint import fingerprint
from causpec.core.gates import GateError, check_all, check_family_supports_spec
from causpec.core.inventory import describe_columns
from causpec.core.inventory import render as render_inventory
from causpec.core.mapping import PreprocessingError, StepRecord
from causpec.core.mapping import apply as apply_preprocessing
from causpec.core.population import ExclusionRecord, PopulationError, apply_filters
from causpec.core.quality import (
    check_assumptions,
    check_basic,
    check_feasibility,
    check_population,
    check_roles,
    check_routing,
    check_temporal,
)
from causpec.core.quality import config_hash as basic_config_hash
from causpec.core.registry import FamilyUnavailable
from causpec.core.reporting import diagram
from causpec.core.reporting.claim_level import ClaimLevelDecision, determine
from causpec.core.reporting.render import RenderError
from causpec.core.reporting.report import ReportError
from causpec.core.reporting.report import build as build_report
from causpec.core.runtime import snapshot as snapshot_store
from causpec.core.runtime.context import RunContext
from causpec.core.sensitivity import SensitivityReport, e_value_from_risks, run_refutations
from causpec.core.sensitivity.evalue import EValueUndefined


def _load_spec(path: Path) -> Spec:
    if not path.exists():
        raise SystemExit(f"No spec file at {path}")
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_data(path: Path) -> pd.DataFrame:
    # A path that does not exist is a typo, not a bug, and a stack trace says neither.
    if not path.exists():
        raise SystemExit(f"No data file at {path}")
    if path.suffix.lower() == ".parquet":
        # The engine is an extra, so say which one and how to get it. pandas' own message
        # names pyarrow and fastparquet without saying what this project wants.
        try:
            return pd.read_parquet(path)
        except ImportError as error:
            raise SystemExit(
                "[PARQUET_ENGINE_MISSING] reading a parquet file needs pyarrow\n"
                "  Fix: Install causpec[parquet]: uv sync --extra parquet "
                "(or pip install 'causpec[parquet]')"
            ) from error
    # The exact float parser, not the default fast one. The default returns a different
    # float64 from the same text for most real-valued columns, which would make the data
    # depend on the parser's version and the fingerprint impossible to verify against a file
    # written from it.
    return pd.read_csv(path, float_precision="round_trip")


def _load_narrative(path: Path | None) -> dict[str, str]:
    """Read the interpretation written by the model.

    A YAML mapping of ``{section: prose}``. A single free-form document is not
    accepted: the report's structure comes from design.md 10.3, not from whoever is
    writing, least of all the rule that assumptions precede results.
    """
    if path is None:
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} should be a YAML mapping of {{section: prose}}.")
    return {str(k): str(v) for k, v in payload.items()}


def _parse_waivers(entries: list[str] | None) -> dict[str, str]:
    """Parse ``--waive check_id=reason`` into {check_id: reason}. A reason is required."""
    waivers: dict[str, str] = {}
    for entry in entries or []:
        check_id, _, reason = entry.partition("=")
        if not reason.strip():
            raise SystemExit(
                f"a waiver needs a reason: --waive {check_id}=<why this can be set aside>"
            )
        waivers[check_id.strip()] = reason.strip()
    return waivers


def _resolve_family(spec: Spec):
    try:
        return registry.get(spec.family)
    except (FamilyUnavailable, FileNotFoundError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(4) from error


def _interval_calibration(spec: Spec) -> str:
    """What the family says about its own intervals, from its declaration.

    A property of the method rather than of a run, so it is read from family.yaml. Families
    that say nothing are calibrated, which is the ordinary case; the exception is an
    estimator proved consistent with no limiting distribution.

    Imputation deliberately does **not** enter here, after an earlier version of this function
    made any filled value force `exploratory`. That rule was not defensible: excluding the
    units with a missing column also distorts the estimate, through selection rather than
    through variance, and it kept `calibrated`. Penalising one and not the other pushed users
    towards the exclusion, which is not reliably the better choice. A fill is handled the way
    this project handles every other thing the data cannot settle: as a declared untestable
    assumption that the user justifies in their own words, which `imputation_assumption_declared`
    requires and the claim level reads.
    """
    declaration = registry.load_declaration(spec.family)
    return str(declaration.get("inference", {}).get("calibration", "calibrated"))


def _sensitivity(
    family: Any,
    data: pd.DataFrame,
    spec: Spec,
    result: Result,
    seed: int,
    enabled: bool,
) -> SensitivityReport:
    """The refutation tests and the E-value, after estimation.

    After, necessarily: each refuter re-runs the estimator, and the E-value is computed from
    the estimate. So none of this can be a gate, which decides whether to estimate at all. It
    reaches the claim level and the report instead, which is where design.md 10.2 puts it.
    """
    declaration = registry.load_declaration(spec.family)
    if not enabled:
        return SensitivityReport(
            skipped_because=(
                "--no-sensitivity was passed, so no refutation test ran. That is not evidence "
                "that the estimate would have survived one."
            )
        )
    settings = declaration.get("sensitivity") or {}
    report = run_refutations(family, data, spec, result, declaration, seed=seed)

    risk_address = str(settings.get("control_risk_address", "") or "")
    primary = str(settings.get("primary_address", "") or "")
    if not risk_address:
        return replace(
            report,
            e_value_absent_because=(
                f"{spec.family} declares no control-arm risk, because its outcome is not a "
                f"binary event. An E-value is a statement about a risk ratio and there is "
                f"none here."
            ),
        )
    if risk_address not in result.values or primary not in result.values:
        return replace(
            report,
            e_value_absent_because="This run did not produce an arm risk to form a ratio from.",
        )
    try:
        computed = e_value_from_risks(
            control_risk=float(result.values[risk_address]),
            effect=float(result.values[primary]),
            ci_lower=_optional(result, settings.get("primary_ci_lower")),
            ci_upper=_optional(result, settings.get("primary_ci_upper")),
        )
    except EValueUndefined as error:
        return replace(report, e_value_absent_because=str(error))
    return replace(report, e_value_addresses=computed.addresses())


def _optional(result: Result, address: object) -> float | None:
    name = str(address or "")
    if name and name in result.values:
        return float(result.values[name])
    return None


def _persist_run(
    args: argparse.Namespace,
    spec: Spec,
    report: QualityReport,
    result: Result,
    decision: ClaimLevelDecision,
    rendered: str | None,
    elapsed_ms: float,
    waivers: dict[str, str],
    render_ok: bool,
    analysed: pd.DataFrame,
    source_fingerprint: str,
    snapshot_fingerprint: str,
    earlier: list[snapshot_store.PriorRun],
) -> Path:
    """Persist this run as a run directory (design.md section 14).

    Every artefact is written atomically, and finalize records each file's checksum.
    The audit log stores only a parameter hash, never the parameters themselves: paths
    leak directory structure (ADR-0002) and column names leak the schema.
    """
    with RunContext.create(args.run_dir, ExecutionMode.CLI) as run:
        run.write_text("spec.yaml", args.spec.read_text(encoding="utf-8"))
        # The whole report, not just its issues: it carries the spec hash and the snapshot
        # fingerprint it was computed for, and that pair is what lets whatever reads it later
        # prove the verdicts describe the run being estimated. A list of issues alone cannot
        # be checked against anything.
        run.write_json("quality/report.json", report.model_dump(mode="json"))
        run.write_json("results/results.json", result.model_dump(mode="json"))
        run.write_json("claim_level.json", decision.model_dump(mode="json"))
        if waivers:
            run.write_json("waivers.json", waivers)
        if rendered is not None:
            run.write_text("report.md", rendered)
        if spec.variable_roles:
            # The same graph the report embeds as mermaid, in DOT, for anyone who has
            # graphviz and wants an SVG. Derived from the same roles, so the two cannot
            # disagree.
            run.write_text("variable_roles.dot", diagram.dot(spec))
        # The table every number in the report came from, after the steps and the filters.
        # Without it a report can be checked against the spec but never against the data.
        run.write_snapshot(analysed)

        run.audit(
            "estimate",
            {"spec": str(args.spec), "data": str(args.data), "seed": args.seed},
            duration_ms=elapsed_ms,
            ok=render_ok,
            metadata={
                "family": spec.family,
                "n_rows": int(result.values.get("res:sample.n", 0)),
                "claim_level": decision.level.value,
                "n_blocking": len(report.blocking),
                "n_waivers": len(waivers),
            },
        )
        run.finalize(
            spec_hash=spec.spec_hash(),
            seed=args.seed,
            source_fingerprint=source_fingerprint,
            snapshot_fingerprint=snapshot_fingerprint,
            prior_runs_on_this_data=[prior.describe() for prior in earlier],
            claim_rules_hash=decision.rules_hash,
            basic_checks_hash=basic_config_hash(),
        )
    print(f"run directory: {run.directory}", file=sys.stderr)
    return run.directory


def _key_columns(spec: Spec, data: pd.DataFrame) -> list[str]:
    """The primary key, for the canonical row order a fingerprint is taken over.

    With a key, two exports of the same table in different row orders agree because they are
    sorted the same way. Without one the fingerprint sorts by every column instead, which also
    makes it order-independent, so a missing key costs nothing but a slower sort.
    """
    names = []
    for field_name in ("unit_id", "period_index"):
        entry = spec.fields.get(field_name)
        if entry is not None and entry.value is not None and str(entry.value) in data.columns:
            names.append(str(entry.value))
    return names


def _preprocess(data: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, list[StepRecord]]:
    """Apply the spec's preprocessing steps to a working copy, before anything reads the data.

    Before the checks, because a check on the raw table would report a placeholder the user
    has already agreed to recode, and before estimation for the obvious reason. The steps are
    part of the spec, so they are in spec_hash and the manifest already.
    """
    try:
        return apply_preprocessing(data, list(spec.preprocessing), spec)
    except PreprocessingError as error:
        print(f"preprocessing failed: {error}", file=sys.stderr)
        raise SystemExit(3) from error


def _select_population(
    data: pd.DataFrame, spec: Spec
) -> tuple[pd.DataFrame, list[ExclusionRecord], QualityReport]:
    """Apply the population filters, and assess them against the frame they were applied to.

    The order matters in one direction only: the population checks look at the people each
    filter removed, so they must see the frame before the removal. Everything after this point
    sees the analysis population, which is what the rest of the report is about.
    """
    before = check_population(data, spec)
    try:
        kept, ledger = apply_filters(data, spec)
    except PopulationError as error:
        print(f"population filters failed: {error}", file=sys.stderr)
        raise SystemExit(3) from error
    return kept, ledger, before


def _require_family_support(spec: Spec) -> None:
    """Gate condition 3, run before the checks rather than with the other gates.

    The other two gate conditions run after the checks, because a quality report is a
    deliverable even when the analysis cannot proceed. This one cannot wait: a family's own
    checks read the fields its declaration requires, so a spec missing one reaches the user as
    a traceback from inside that family rather than as a refusal naming the missing field.
    `check_all` calls it again, which costs nothing and keeps the gate complete on its own.
    """
    try:
        check_family_supports_spec(spec)
    except GateError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error


def _run_checks(data: pd.DataFrame, spec: Spec) -> QualityReport:
    """The core layers first, then the family's own, unless a core layer blocked.

    Overlap, instrument relevance and continuation weights are all computed from the numbers
    in these columns, so a design-level verdict on a table whose creatinine column holds -999
    is a confident statement about an export convention. When the table is not usable as a
    table, the honest report says that and stops there (design.md 8.1, and G3: it is still a
    deliverable).
    """
    core = QualityReport(
        issues=[
            *check_basic(data, spec).issues,
            *check_temporal(data, spec).issues,
            *check_feasibility(data, spec).issues,
            *check_assumptions(data, spec).issues,
            *check_roles(data, spec).issues,
            *check_routing(data, spec).issues,
        ]
    )
    if core.blocking:
        return core
    family = _resolve_family(spec).check(data, spec)
    return QualityReport(issues=[*core.issues, *family.issues])


def _coverage_line(report: QualityReport) -> str:
    """How much of the catalogue this spec reached, as a count and no names.

    A check that stood down has found nothing, and naming it says nothing: six of these are
    waiting on a column the spec does not declare, and the balance ones are answered by the
    spec itself. Listing them put nine lines of "not assessed" in front of the findings and
    invited the reader to treat an absent check as a result. The count stays because the table
    is not the whole catalogue and a reader comparing two runs should see that.
    """
    ran, total = len(report.findings), len(report.issues)
    if ran == total:
        return ""
    return f"  {ran} of {total} checks apply to this spec."


def cmd_columns(args: argparse.Namespace) -> int:
    """Describe every column, for the user to assign roles from.

    No spec required: this runs before there is one, and `--spec` only adds the roles already
    confirmed so the listing shows what is still unassigned.

    Nothing here crosses two columns. The reason is in `core/inventory.py`: a comparison
    between the arms is a diagnostic of the analysis, and the point of having this command is
    that the agent does not have to improvise one.
    """
    data = _load_data(args.data)
    spec = _load_spec(args.spec) if args.spec else None
    facts = describe_columns(data, spec)
    print(render_inventory(facts, n_rows=len(data), source=args.data.name))
    return 0


def cmd_quality(args: argparse.Namespace) -> int:
    """Run the quality checks only.

    G3: the quality report is a deliverable even when the analysis cannot run, which
    is why this subcommand stands alone and does not require a confirmed spec.
    """
    spec = _load_spec(args.spec)
    source = _load_data(args.data)
    key = _key_columns(spec, source)
    data, applied = _preprocess(source, spec)
    for record in applied:
        print(f"~ [applied  ] {record.describe()}")
    data, ledger, population = _select_population(data, spec)
    for record in ledger:
        print(f"- [excluded ] {record.describe()}")
    _require_family_support(spec)
    # Stamped here too, so a report written out by `quality` can be verified later by
    # whatever estimates from it.
    report = QualityReport(issues=[*population.issues, *_run_checks(data, spec).issues]).stamped(
        spec_hash=spec.spec_hash(), snapshot_fingerprint=fingerprint(data, key)
    )
    for issue in report.findings:
        mark = {"blocking": "✗", "warning": "!", "info": "·"}[issue.severity.value]
        print(f"{mark} [{issue.severity.value:8}] {issue.check_id}: {issue.summary}")
        for address, value in issue.evidence_addresses().items():
            print(f"      {address} = {value}")
    if line := _coverage_line(report):
        print(line)
    return 1 if report.blocking else 0


def cmd_estimate(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    source = _load_data(args.data)
    key = _key_columns(spec, source)
    # Taken on the file as read, before anything touches it: this is the fingerprint that
    # answers "is this the same data?", and so the one that tells a fresh analysis on new data
    # apart from a second look at the same numbers.
    source_fingerprint = fingerprint(source, key)
    data, applied = _preprocess(source, spec)
    data, ledger, population = _select_population(data, spec)
    snapshot_fingerprint = fingerprint(data, key)
    _require_family_support(spec)
    family = _resolve_family(spec)

    # The gate runs before estimation and stops the command if it fails, an `if` in
    # code, not a rule in a prompt. Condition 1 checks spec confirmation, condition 2
    # checks for unwaived blocking quality issues.
    waivers = _parse_waivers(args.waive)
    # Stamped with what it was computed from, so the gate can refuse a report that describes
    # a different run. Here the two cannot diverge, both being computed from `data` in one
    # process; the skill form runs two scripts and the MCP server takes a report from a
    # client, and in both they can.
    report = QualityReport(issues=[*population.issues, *_run_checks(data, spec).issues]).stamped(
        spec_hash=spec.spec_hash(), snapshot_fingerprint=snapshot_fingerprint
    )
    try:
        check_all(spec, report, waivers, snapshot_fingerprint=snapshot_fingerprint)
    except GateError as error:
        print(error, file=sys.stderr)
        return 2

    # Earlier runs that reached an estimate on this same data under a different spec. Looked
    # for before estimating, so the report can say so rather than the fact surfacing only in
    # the manifest. Not a refusal: a second look is legitimate, it has to be visible as one.
    earlier = (
        snapshot_store.prior_runs(args.run_dir, source_fingerprint, spec.spec_hash())
        if args.run_dir is not None
        else []
    )

    started = time.perf_counter()
    result = family.estimate(data, spec, seed=args.seed)
    elapsed_ms = (time.perf_counter() - started) * 1000

    sensitivity = _sensitivity(family, data, spec, result, args.seed, not args.no_sensitivity)

    # The claim level is decided by code; the model may not upgrade it (principle 5). How
    # the family's intervals are calibrated is part of that decision and comes from the
    # family's own declaration: an estimator proved consistent without a limiting
    # distribution cannot support a significance claim, however clean the data is.
    decision = determine(
        spec,
        report,
        gate_passed=True,
        waived=waivers,
        interval_calibration=_interval_calibration(spec),
        failed_refutations=[finding.test_id for finding in sensitivity.failed],
    )
    addresses: dict[str, float | int | str] = {
        **result.values,
        **report.addresses(),
        **decision.addresses(),
        **sensitivity.addresses(),
    }

    rendered: str | None = None
    render_error: RenderError | ReportError | None = None
    if args.report or args.narrative is not None:
        try:
            rendered = build_report(
                spec,
                report,
                decision,
                addresses,
                narrative=_load_narrative(args.narrative),
                # Result tables the family declares. Prose is the wrong container for a
                # result with one row per lag: the reader would see the lags a sentence
                # happened to mention.
                tables=registry.load_declaration(spec.family).get("report_tables", []),
                preprocessing=[record.describe() for record in applied],
                provenance={
                    "source_fingerprint": source_fingerprint,
                    "snapshot_fingerprint": snapshot_fingerprint,
                    "prior_runs": [prior.describe() for prior in earlier],
                },
                # As a mapping, so core renders the findings without the sensitivity
                # module's dataclasses reaching into the reporting one.
                sensitivity={
                    "findings": [
                        {
                            "test_id": finding.test_id,
                            "passed": finding.passed,
                            "summary": finding.summary,
                            "interpretation": finding.interpretation,
                        }
                        for finding in sensitivity.findings
                    ],
                    "refutation_params": sensitivity.refutation_params,
                    "skipped_because": sensitivity.skipped_because,
                    "e_value_absent_because": sensitivity.e_value_absent_because,
                },
                exclusions=[
                    {
                        "criterion": record.criterion,
                        "said": record.said,
                        "n_before": record.n_before,
                        "n_removed": record.n_removed,
                        "n_after": record.n_after,
                    }
                    for record in ledger
                ],
                execution_mode=ExecutionMode.CLI,
            )
        except (RenderError, ReportError) as error:
            render_error = error

    if args.run_dir is not None:
        _persist_run(
            args,
            spec,
            report,
            result,
            decision,
            rendered,
            elapsed_ms,
            waivers,
            render_ok=render_error is None,
            analysed=data,
            source_fingerprint=source_fingerprint,
            snapshot_fingerprint=snapshot_fingerprint,
            earlier=earlier,
        )

    if render_error is not None:
        print(f"report rendering failed:\n{render_error}", file=sys.stderr)
        return 3
    if rendered is not None:
        print(rendered)
        return 0

    for address, value in addresses.items():
        print(f"{address} = {value}")
    print(f"\nClaim level: {decision.level.value}")
    for reason in decision.reasons:
        print(f"  · {reason}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="causpec", description="Spec-gated causal analysis.")
    parser.add_argument("--version", action="version", version=f"causpec {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    columns = subparsers.add_parser(
        "columns", help="describe every column in the data, for choosing variable roles"
    )
    columns.add_argument("--data", type=Path, required=True, help="path to the CSV or Parquet")
    columns.add_argument(
        "--spec", type=Path, help="optional: mark the columns a spec already assigns"
    )
    columns.set_defaults(func=cmd_columns)

    quality = subparsers.add_parser(
        "quality", help="run the quality checks only; no confirmed spec required"
    )
    quality.add_argument("--spec", type=Path, required=True, help="path to spec.yaml")
    quality.add_argument("--data", type=Path, required=True, help="path to the CSV or Parquet")
    quality.set_defaults(func=cmd_quality)

    estimate = subparsers.add_parser(
        "estimate", help="estimate once the gate passes, optionally rendering a report"
    )
    estimate.add_argument("--spec", type=Path, required=True, help="path to spec.yaml")
    estimate.add_argument("--data", type=Path, required=True, help="path to the CSV or Parquet")
    estimate.add_argument(
        "--report",
        action="store_true",
        help="emit the report in design.md 10.3 structure; omit to print addressed results",
    )
    estimate.add_argument(
        "--narrative",
        type=Path,
        metavar="YAML",
        help="model-written interpretation as {section: prose}; numbers only via placeholders",
    )
    estimate.add_argument("--seed", type=int, default=42)
    estimate.add_argument(
        "--no-sensitivity",
        action="store_true",
        help=(
            "skip the refutation tests. They re-fit the estimator several times, so they "
            "cost minutes on a large sample; the report then says they did not run"
        ),
    )
    estimate.add_argument(
        "--run-dir",
        type=Path,
        help="persist this run under this directory (manifest, checksums, audit log)",
    )
    estimate.add_argument(
        "--waive",
        action="append",
        metavar="CHECK_ID=REASON",
        help="waive one waivable blocking check; a reason is required. May be repeated",
    )
    estimate.set_defaults(func=cmd_estimate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

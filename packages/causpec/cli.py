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
from pathlib import Path

import pandas as pd
import yaml

from causpec import __version__
from causpec.core import registry
from causpec.core.contracts.manifest import ExecutionMode
from causpec.core.contracts.quality import QualityReport
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.gates import GateError, check_all
from causpec.core.registry import FamilyUnavailable
from causpec.core.reporting.claim_level import ClaimLevelDecision, determine
from causpec.core.reporting.render import RenderError
from causpec.core.reporting.report import ReportError
from causpec.core.reporting.report import build as build_report
from causpec.core.runtime.context import RunContext


def _load_spec(path: Path) -> Spec:
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_data(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


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


def _interval_calibration(family_id: str) -> str:
    """What the family says about its own intervals, from its declaration.

    A property of the method rather than of a run, so it is read from family.yaml. Families
    that say nothing are calibrated, which is the ordinary case; the exception is an
    estimator proved consistent with no limiting distribution.
    """
    declaration = registry.load_declaration(family_id)
    return str(declaration.get("inference", {}).get("calibration", "calibrated"))


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
) -> Path:
    """Persist this run as a run directory (design.md section 14).

    Every artefact is written atomically, and finalize records each file's checksum.
    The audit log stores only a parameter hash, never the parameters themselves: paths
    leak directory structure (ADR-0002) and column names leak the schema.
    """
    with RunContext.create(args.run_dir, ExecutionMode.CLI) as run:
        run.write_text("spec.yaml", args.spec.read_text(encoding="utf-8"))
        run.write_json("quality/issues.json", [i.model_dump(mode="json") for i in report.issues])
        run.write_json("results/results.json", result.model_dump(mode="json"))
        run.write_json("claim_level.json", decision.model_dump(mode="json"))
        if waivers:
            run.write_json("waivers.json", waivers)
        if rendered is not None:
            run.write_text("report.md", rendered)

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
            claim_rules_hash=decision.rules_hash,
        )
    print(f"run directory: {run.directory}", file=sys.stderr)
    return run.directory


def cmd_quality(args: argparse.Namespace) -> int:
    """Run the quality checks only.

    G3: the quality report is a deliverable even when the analysis cannot run, which
    is why this subcommand stands alone and does not require a confirmed spec.
    """
    spec = _load_spec(args.spec)
    report = _resolve_family(spec).check(_load_data(args.data), spec)
    for issue in report.issues:
        mark = {"blocking": "✗", "warning": "!", "info": "·"}[issue.severity.value]
        print(f"{mark} [{issue.severity.value:8}] {issue.check_id}: {issue.summary}")
        for address, value in issue.evidence_addresses().items():
            print(f"      {address} = {value}")
    return 1 if report.blocking else 0


def cmd_estimate(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    data = _load_data(args.data)
    family = _resolve_family(spec)

    # The gate runs before estimation and stops the command if it fails, an `if` in
    # code, not a rule in a prompt. Condition 1 checks spec confirmation, condition 2
    # checks for unwaived blocking quality issues.
    waivers = _parse_waivers(args.waive)
    report = family.check(data, spec)
    try:
        check_all(spec, report, waivers)
    except GateError as error:
        print(error, file=sys.stderr)
        return 2

    started = time.perf_counter()
    result = family.estimate(data, spec, seed=args.seed)
    elapsed_ms = (time.perf_counter() - started) * 1000

    # The claim level is decided by code; the model may not upgrade it (principle 5). How
    # the family's intervals are calibrated is part of that decision and comes from the
    # family's own declaration: an estimator proved consistent without a limiting
    # distribution cannot support a significance claim, however clean the data is.
    decision = determine(
        spec,
        report,
        gate_passed=True,
        waived=waivers,
        interval_calibration=_interval_calibration(spec.family),
    )
    addresses: dict[str, float | int | str] = {
        **result.values,
        **report.addresses(),
        **decision.addresses(),
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

"""CauSpec 命令行入口。

``quality`` 只跑质量检查——G3 要求即使分析不能运行，质量报告本身也是交付物。
``estimate`` 先跑检查、过门控，再估计，可选渲染报告。
``report`` 作为独立子命令待补（现在由 ``estimate --report`` 承担）。
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
from causpec.core.reporting.render import RenderError, render
from causpec.core.runtime.context import RunContext


def _load_spec(path: Path) -> Spec:
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_data(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _parse_waivers(entries: list[str] | None) -> dict[str, str]:
    """``--waive check_id=理由`` 解析成 {check_id: 理由}。豁免必须附理由。"""
    waivers: dict[str, str] = {}
    for entry in entries or []:
        check_id, _, reason = entry.partition("=")
        if not reason.strip():
            raise SystemExit(f"豁免必须附理由：--waive {check_id}=<为什么可以忽略这条>")
        waivers[check_id.strip()] = reason.strip()
    return waivers


def _resolve_family(spec: Spec):
    try:
        return registry.get(spec.family)
    except (FamilyUnavailable, FileNotFoundError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(4) from error


def _persist_run(
    args: argparse.Namespace,
    spec: Spec,
    report: QualityReport,
    result: Result,
    decision: ClaimLevelDecision,
    rendered: str | None,
    elapsed_ms: float,
    waivers: dict[str, str],
) -> Path:
    """把这次运行落盘成一个 run 目录（design.md 第 14 节）。

    产物一律原子写入，最后由 finalize 记下每个文件的 checksum。
    审计日志只记参数哈希，不记参数内容——路径会泄露目录结构（ADR-0002），
    列名会泄露 schema。
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
            ok=rendered is not None or args.report is None,
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
    print(f"run 目录：{run.directory}", file=sys.stderr)
    return run.directory


def cmd_quality(args: argparse.Namespace) -> int:
    """只跑质量检查。

    G3：即使分析不能运行，质量报告本身也是交付物——所以这条子命令独立存在，
    不要求 spec 已确认。
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

    # 门控在估计之前。不通过就到此为止——这是代码里的 if，不是 prompt 里的规则。
    # 第 1 条查 spec 确认，第 2 条查有没有未豁免的 blocking 质量问题。
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

    # 措辞等级由代码判定，模型不能自行升级（design.md 原则 5）。
    decision = determine(spec, report, gate_passed=True, waived=waivers)
    addresses: dict[str, float | int | str] = {
        **result.values,
        **report.addresses(),
        **decision.addresses(),
    }

    rendered: str | None = None
    render_error: RenderError | None = None
    if args.report is not None:
        try:
            rendered = render(args.report.read_text(encoding="utf-8"), addresses)
        except RenderError as error:
            render_error = error

    if args.run_dir is not None:
        _persist_run(args, spec, report, result, decision, rendered, elapsed_ms, waivers)

    if render_error is not None:
        print(f"报告渲染失败：\n{render_error}", file=sys.stderr)
        return 3
    if rendered is not None:
        print(rendered)
        return 0

    for address, value in addresses.items():
        print(f"{address} = {value}")
    print(f"\n措辞等级：{decision.level.value}")
    for reason in decision.reasons:
        print(f"  · {reason}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="causpec", description="Spec-gated causal analysis.")
    parser.add_argument("--version", action="version", version=f"causpec {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    quality = subparsers.add_parser("quality", help="只跑质量检查，不需要 spec 已确认")
    quality.add_argument("--spec", type=Path, required=True, help="spec.yaml 路径")
    quality.add_argument("--data", type=Path, required=True, help="数据 CSV / Parquet 路径")
    quality.set_defaults(func=cmd_quality)

    estimate = subparsers.add_parser("estimate", help="门控通过后执行估计，可选渲染报告")
    estimate.add_argument("--spec", type=Path, required=True, help="spec.yaml 路径")
    estimate.add_argument("--data", type=Path, required=True, help="数据 CSV / Parquet 路径")
    estimate.add_argument("--report", type=Path, help="报告模板；省略则直接打印带地址的结果")
    estimate.add_argument("--seed", type=int, default=42)
    estimate.add_argument(
        "--run-dir",
        type=Path,
        help="把这次运行落盘到这个目录下（manifest、产物 checksum、审计日志）",
    )
    estimate.add_argument(
        "--waive",
        action="append",
        metavar="CHECK_ID=理由",
        help="豁免一条可豁免的 blocking 检查，必须附理由；可重复",
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

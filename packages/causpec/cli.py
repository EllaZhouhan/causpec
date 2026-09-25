"""CauSpec 命令行入口。

垂直切片：``estimate`` 跑门控 + 估计 + 占位符渲染，验证三层能串通。
完整的 quality / estimate / report 三条子命令见 plan.md Phase 1 任务 12。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

from causpec import __version__
from causpec.core import registry
from causpec.core.contracts.spec import Spec
from causpec.core.gates import GateError, check_all
from causpec.core.registry import FamilyUnavailable
from causpec.core.reporting.render import RenderError, render


def _load_spec(path: Path) -> Spec:
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _load_data(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def cmd_estimate(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)

    # 门控在估计之前。不通过就到此为止——这是代码里的 if，不是 prompt 里的规则。
    try:
        check_all(spec)
    except GateError as error:
        print(error, file=sys.stderr)
        return 2

    try:
        family = registry.get(spec.family)
    except (FamilyUnavailable, FileNotFoundError) as error:
        print(error, file=sys.stderr)
        return 4

    result = family.estimate(_load_data(args.data), spec, seed=args.seed)

    if args.report is None:
        for address, value in result.values.items():
            print(f"{address} = {value}")
        return 0

    try:
        print(render(args.report.read_text(encoding="utf-8"), result))
    except RenderError as error:
        print(f"报告渲染失败：\n{error}", file=sys.stderr)
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="causpec", description="Spec-gated causal analysis.")
    parser.add_argument("--version", action="version", version=f"causpec {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    estimate = subparsers.add_parser("estimate", help="门控通过后执行估计，可选渲染报告")
    estimate.add_argument("--spec", type=Path, required=True, help="spec.yaml 路径")
    estimate.add_argument("--data", type=Path, required=True, help="数据 CSV / Parquet 路径")
    estimate.add_argument("--report", type=Path, help="报告模板；省略则直接打印带地址的结果")
    estimate.add_argument("--seed", type=int, default=42)
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

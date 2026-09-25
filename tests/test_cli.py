"""CLI：quality / estimate 两条子命令与豁免解析。

锁的是用户真正会走的那条路——门控在这里是否真的拦得住。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from dataset_a import config_for, generate

from causpec.cli import _parse_waivers, main

SPEC = """\
spec_version: 1
question: 透析对 ICU 患者死亡率的平均效应？
family: hte_backdoor
estimation:
  params: {n_estimators: 52}
assumptions:
  - id: unconfoundedness
    category: untestable
    statement: 给定调整集后，处理分配与潜在结局独立
fields:
  treatment:
    {value: isDialysisICU, source: user, said: 处理就是开始透析, turn: 2, status: confirmed}
  outcome: {value: death, source: user, said: 结局看院内死亡, turn: 4, status: confirmed}
  estimand: {value: ate, source: model, said: 对，要全人群平均效应, turn: 6, status: confirmed}
  effect_modifiers:
    value: [admission_age, max_aki_stage_smoothed, max_potassium, sofa_total_24h]
    source: user
    said: 就用这几个临床变量
    turn: 8
    status: confirmed
"""

DRAFTED_SPEC = SPEC.replace(
    "estimand: {value: ate, source: model, said: 对，要全人群平均效应, turn: 6, status: confirmed}",
    "estimand: {value: ate, source: model, status: drafted}",
)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> dict[str, Path]:
    directory = tmp_path_factory.mktemp("cli")
    data = generate(config_for("high_power", seed=100, n=800))
    data.to_csv(directory / "good.csv", index=False)

    rng = np.random.default_rng(0)
    sofa = data["sofa_total_24h"].to_numpy()
    broken = data.copy()
    probability = np.where(sofa > np.median(sofa), 0.97, 0.03)
    broken["isDialysisICU"] = (rng.uniform(size=len(data)) < probability).astype(int)
    broken.to_csv(directory / "broken.csv", index=False)

    (directory / "spec.yaml").write_text(SPEC, encoding="utf-8")
    (directory / "drafted.yaml").write_text(DRAFTED_SPEC, encoding="utf-8")
    return {
        name: directory / name for name in ("good.csv", "broken.csv", "spec.yaml", "drafted.yaml")
    }


def run(*argv: str) -> int:
    return main(list(argv))


# ---- 豁免解析 ----


def test_waiver_requires_a_reason() -> None:
    with pytest.raises(SystemExit, match="豁免必须附理由"):
        _parse_waivers(["backdoor_overlap="])


def test_waiver_parses_reason_with_equals_sign() -> None:
    parsed = _parse_waivers(["overlap=见方案 3.2 节，a=b"])
    assert parsed == {"overlap": "见方案 3.2 节，a=b"}


def test_no_waivers_is_empty() -> None:
    assert _parse_waivers(None) == {}


# ---- quality ----


def test_quality_returns_zero_on_clean_data(workspace, capsys) -> None:
    assert (
        run("quality", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
        == 0
    )
    assert "backdoor_overlap" in capsys.readouterr().out


def test_quality_returns_nonzero_when_blocking(workspace, capsys) -> None:
    """G3：分析跑不了时质量报告仍要出来，所以 quality 不要求 spec 已确认，
    但有 blocking 问题时退出码非零，方便脚本判断。"""
    code = run(
        "quality", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["broken.csv"])
    )
    assert code == 1
    assert "[blocking]" in capsys.readouterr().out


def test_quality_prints_evidence_addresses(workspace, capsys) -> None:
    run("quality", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
    assert "qc:backdoor_overlap.extreme_fraction" in capsys.readouterr().out


# ---- estimate 的门控 ----


def test_estimate_blocked_by_unconfirmed_spec(workspace, capsys) -> None:
    code = run(
        "estimate", "--spec", str(workspace["drafted.yaml"]), "--data", str(workspace["good.csv"])
    )
    assert code == 2
    assert "SPEC_NOT_CONFIRMED" in capsys.readouterr().err


def test_estimate_blocked_by_broken_overlap(workspace, capsys) -> None:
    code = run(
        "estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["broken.csv"])
    )
    assert code == 2
    assert "BLOCKING_QUALITY_ISSUES" in capsys.readouterr().err


def test_waiver_with_reason_lets_it_through(workspace, capsys) -> None:
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["broken.csv"]),
        "--waive",
        "backdoor_overlap=已限制到有共同支撑的子人群，见方案 3.2 节",
    )
    assert code == 0
    assert "res:primary.ate" in capsys.readouterr().out


def test_estimate_succeeds_on_clean_data(workspace, capsys) -> None:
    assert (
        run("estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
        == 0
    )
    out = capsys.readouterr().out
    assert "res:primary.ate " in out
    assert "res:primary.ate_ci_method = blb" in out


def test_report_rendering_rejects_bare_numbers(workspace, tmp_path, capsys) -> None:
    template = tmp_path / "bad.md"
    template.write_text("效应约为 -0.08。\n", encoding="utf-8")
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        str(template),
    )
    assert code == 3
    assert "未经占位的数字" in capsys.readouterr().err


def test_report_renders_with_placeholders(workspace, tmp_path, capsys) -> None:
    template = tmp_path / "ok.md"
    template.write_text(
        "平均效应 {{res:primary.ate}}，样本 {{res:sample.n}} 人。\n", encoding="utf-8"
    )
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        str(template),
    )
    assert code == 0
    out = capsys.readouterr().out
    # 占位符被代入了：正文里不该还有 {{ }}，且数字确实出现了
    assert "{{" not in out
    assert "样本 800 人" in out


# ---- 参数表面 ----


def test_subcommands_are_registered(capsys) -> None:
    """quality 与 estimate 都在帮助里——不去翻 argparse 的私有属性。"""
    main([])
    help_text = capsys.readouterr().out
    assert "quality" in help_text
    assert "estimate" in help_text


def test_no_subcommand_prints_help(capsys) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out


# ---- 措辞等级 ----


def test_estimate_prints_the_claim_level(workspace, capsys) -> None:
    """措辞等级由代码判定并打印，模型不经手（design.md 原则 5）。"""
    run("estimate", "--spec", str(workspace["spec.yaml"]), "--data", str(workspace["good.csv"]))
    out = capsys.readouterr().out
    assert "措辞等级：suggestive" in out
    assert "unconfoundedness" in out  # 为什么不能更高，要说出来


def test_waived_analysis_is_downgraded(workspace, capsys) -> None:
    """豁免让分析跑起来，但措辞等级降到 associational。"""
    run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["broken.csv"]),
        "--waive",
        "backdoor_overlap=已限制到有共同支撑的子人群",
    )
    out = capsys.readouterr().out
    assert "措辞等级：associational" in out
    assert "已豁免，但诊断结论不变" in out


def test_report_can_reference_all_three_namespaces(workspace, tmp_path, capsys) -> None:
    """res:（估计）、qc:（质量检查）、claim:（措辞等级）在同一份报告里都能引用。"""
    template = tmp_path / "three.md"
    template.write_text(
        "效应 {{res:primary.ate}}；"
        "极端得分占比 {{qc:backdoor_overlap.extreme_fraction}}；"
        "等级 {{claim:level}}。\n",
        encoding="utf-8",
    )
    code = run(
        "estimate",
        "--spec",
        str(workspace["spec.yaml"]),
        "--data",
        str(workspace["good.csv"]),
        "--report",
        str(template),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "{{" not in out
    assert "suggestive" in out

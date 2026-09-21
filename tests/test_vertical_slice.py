"""垂直切片的回归测试：门控、渲染、注册表。

这些测试固定的是 design.md 里三个机制的**行为**，不是实现：
- 11.2 门控：关键字段未确认时拒绝估计
- 10.1 渲染：数字只能由代码填
- 第 4 节：core 不认识具体 family，family 向注册表报到
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

import causpec.families.hte_backdoor  # noqa: F401  触发注册
from causpec.core import registry
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.gates import GateError, check_all
from causpec.core.reporting.render import RenderError, render

FIXTURES = Path(__file__).parent / "fixtures"


def load_spec(name: str) -> Spec:
    return Spec.model_validate(yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8")))


@pytest.fixture
def rows() -> list[dict[str, str]]:
    with (FIXTURES / "mini_icu.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def result(rows: list[dict[str, str]]) -> Result:
    spec = load_spec("spec_confirmed.yaml")
    return registry.get(spec.family).estimate(rows, spec, seed=42)


# ---- design.md 7.1：用户话语是证据，要原样留底 ----


def test_user_sourced_field_requires_quote() -> None:
    with pytest.raises(ValueError, match="用户原话"):
        SpecField(value="rrt", source=Source.USER)


def test_model_sourced_field_needs_no_quote() -> None:
    assert SpecField(value="rrt", source=Source.MODEL).said is None


# ---- design.md 11.2：门控 ----


def test_gate_rejects_unconfirmed_spec() -> None:
    with pytest.raises(GateError) as excinfo:
        check_all(load_spec("spec_drafted.yaml"))
    error = excinfo.value
    assert error.code == "SPEC_NOT_CONFIRMED"
    assert error.details["unconfirmed_fields"] == ["outcome", "estimand"]
    assert error.remediation


def test_gate_passes_confirmed_spec() -> None:
    check_all(load_spec("spec_confirmed.yaml"))


def test_missing_critical_field_counts_as_unconfirmed() -> None:
    spec = Spec(
        question="q",
        family="hte_backdoor",
        fields={"treatment": SpecField(value="rrt", source=Source.MODEL, status=Status.CONFIRMED)},
    )
    assert spec.unconfirmed_critical_fields() == ["outcome", "estimand"]


def test_spec_hash_is_stable_and_content_sensitive() -> None:
    spec = load_spec("spec_confirmed.yaml")
    assert spec.spec_hash() == load_spec("spec_confirmed.yaml").spec_hash()
    assert spec.spec_hash() != load_spec("spec_drafted.yaml").spec_hash()


# ---- design.md 第 4 节：注册表 ----


def test_family_registered_and_declares_estimands() -> None:
    assert "hte_backdoor" in registry.list_families()
    assert set(registry.declared_estimands("hte_backdoor")) == {"ate", "att", "cate"}


def test_hte_iv_declares_only_conditional_late() -> None:
    """design.md 7.6：IV 只假设 monotonicity 时识别的是条件 LATE，不是 CATE。"""
    assert registry.declared_estimands("hte_iv") == ["conditional_late"]


def test_unknown_family_raises() -> None:
    with pytest.raises(KeyError, match="未注册的 family"):
        registry.get("did")


# ---- design.md 10.1：数字只能由代码填 ----


def test_render_substitutes_addresses(result: Result) -> None:
    assert (
        render("效应 {{res:primary.estimate}}。", result)
        == f"效应 {result.values['res:primary.estimate']}。"
    )


def test_render_rejects_bare_number(result: Result) -> None:
    with pytest.raises(RenderError, match="未经占位的数字"):
        render("效应大约是 -0.08。", result)


def test_render_rejects_unknown_address(result: Result) -> None:
    with pytest.raises(RenderError, match="地址"):
        render("置信区间 {{res:primary.ci_lower}}。", result)


def test_render_allows_literal_in_terminology(result: Result) -> None:
    assert render("{{lit:28}} 天死亡率。", result) == "28 天死亡率。"


def test_render_rejects_result_smuggled_as_literal(result: Result) -> None:
    estimate = result.values["res:primary.estimate"]
    with pytest.raises(RenderError, match="与计算结果"):
        render(f"差值 {{{{lit:{estimate}}}}}。", result)


def test_render_exempts_markdown_structure(result: Result) -> None:
    template = "## 结果\n\n1. 第一条\n2. 第二条\n\n| a | b |\n|---|---|\n| x | y |\n"
    assert render(template, result) == template


# ---- 估计 ----


def test_estimate_is_reproducible(rows: list[dict[str, str]]) -> None:
    spec = load_spec("spec_confirmed.yaml")
    family = registry.get(spec.family)
    assert family.estimate(rows, spec, seed=42) == family.estimate(rows, spec, seed=42)


def test_estimate_addresses_are_namespaced(result: Result) -> None:
    assert all(address.startswith("res:") for address in result.values)

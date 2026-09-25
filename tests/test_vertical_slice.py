"""垂直切片的回归测试：门控、渲染、注册表。

这些测试固定的是 design.md 里三个机制的**行为**，不是实现：
- 11.2 门控：关键字段未确认时拒绝估计
- 10.1 渲染：数字只能由代码填
- 第 4 节：core 不认识具体 family，family 向注册表报到
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from causpec.core import registry
from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Source, Spec, SpecField, Status
from causpec.core.gates import GateError, check_all
from causpec.core.reporting.render import RenderError, render

FIXTURES = Path(__file__).parent / "fixtures"


def load_spec(name: str) -> Spec:
    return Spec.model_validate(yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8")))


@pytest.fixture
def result() -> Result:
    """手写的结果，不跑估计器。

    这个文件锁的是门控、渲染、spec 契约——它们不该依赖任何 family 能不能跑起来，
    也不该为此付出拟合一片森林的代价。估计器本身的行为见 test_hte_iv.py 与
    test_hte_backdoor.py。
    """
    return Result(
        family="hte_backdoor",
        seed=42,
        values={
            "res:primary.estimate": 0.0289,
            "res:primary.n": 60,
            "res:primary.n_treated": 29,
            "res:primary.n_control": 31,
            "res:primary.mean_treated": 0.4483,
            "res:primary.mean_control": 0.4194,
        },
    )


# ---- design.md 7.1：用户话语是证据，要原样留底 ----


def test_user_sourced_field_requires_quote() -> None:
    with pytest.raises(ValueError, match="用户原话"):
        SpecField(value="rrt", source=Source.USER)


def test_model_sourced_draft_needs_no_quote() -> None:
    assert SpecField(value="rrt", source=Source.MODEL).said is None


def test_confirmed_field_requires_quote_even_when_model_sourced() -> None:
    """design.md 7.1：确认必附原话，堵门控的根部漏洞。

    模型可以自己调 update_field 宣布「用户确认了」。要求 confirmed 必须带上用户
    当时那句话，模型想跳过确认就得编造引语，而引语会印在报告首页供人核对。
    """
    with pytest.raises(ValueError, match="确认时的原话"):
        SpecField(value="ate", source=Source.MODEL, status=Status.CONFIRMED)


def test_model_inferred_value_can_be_confirmed_by_user() -> None:
    """值由模型推断、确认由用户给出——source 仍是 model，said 记用户认可时的原话。"""
    field = SpecField(
        value="ate", source=Source.MODEL, said="对，我想知道整体平均效应", status=Status.CONFIRMED
    )
    assert field.source is Source.MODEL and field.status is Status.CONFIRMED


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
        fields={
            "treatment": SpecField(
                value="rrt", source=Source.MODEL, said="就用 rrt 这列", status=Status.CONFIRMED
            )
        },
    )
    assert spec.unconfirmed_critical_fields() == ["outcome", "estimand"]


def test_spec_hash_is_stable_and_content_sensitive() -> None:
    spec = load_spec("spec_confirmed.yaml")
    assert spec.spec_hash() == load_spec("spec_confirmed.yaml").spec_hash()
    assert spec.spec_hash() != load_spec("spec_drafted.yaml").spec_hash()


# 注册表的行为（动态导入、声明读取、缺依赖）见 tests/test_registry.py


def test_hte_backdoor_declares_backdoor_estimands() -> None:
    assert set(registry.declared_estimands("hte_backdoor")) == {"ate", "att", "cate"}


# ---- design.md 10.1：数字只能由代码填 ----


def test_render_substitutes_addresses(result: Result) -> None:
    assert (
        render("效应 {{res:primary.estimate}}。", result.values)
        == f"效应 {result.values['res:primary.estimate']}。"
    )


def test_render_rejects_bare_number(result: Result) -> None:
    with pytest.raises(RenderError, match="未经占位的数字"):
        render("效应大约是 -0.08。", result.values)


def test_render_rejects_unknown_address(result: Result) -> None:
    with pytest.raises(RenderError, match="地址"):
        render("置信区间 {{res:primary.ci_lower}}。", result.values)


def test_render_allows_literal_in_terminology(result: Result) -> None:
    assert render("{{lit:28}} 天死亡率。", result.values) == "28 天死亡率。"


def test_render_rejects_result_smuggled_as_literal(result: Result) -> None:
    estimate = result.values["res:primary.estimate"]
    with pytest.raises(RenderError, match="与计算结果"):
        render(f"差值 {{{{lit:{estimate}}}}}。", result.values)


def test_render_exempts_markdown_structure(result: Result) -> None:
    template = "## 结果\n\n1. 第一条\n2. 第二条\n\n| a | b |\n|---|---|\n| x | y |\n"
    assert render(template, result.values) == template


def test_addresses_are_namespaced(result: Result) -> None:
    assert all(address.startswith("res:") for address in result.values)

"""Regression tests for the vertical slice: gate, rendering, registry.

These pin the **behaviour** of three mechanisms from design.md, not their implementation:
- 11.2 gate: refuse to estimate while a critical field is unconfirmed
- 10.1 rendering: only code puts numbers in the report
- section 4: core knows no specific family; families register themselves
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
    """A hand-written Result; no estimator runs.

    This file pins the gate, the renderer and the spec contract, none of which should
    depend on any family being runnable, or pay the cost of fitting a forest to find
    out. For the estimators themselves see test_hte_iv.py and
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


# ---- design.md 7.1: the user's words are the evidence, kept verbatim ----


def test_user_sourced_field_requires_quote() -> None:
    with pytest.raises(ValueError, match="user's own words"):
        SpecField(value="rrt", source=Source.USER)


def test_model_sourced_draft_needs_no_quote() -> None:
    assert SpecField(value="rrt", source=Source.MODEL).said is None


def test_confirmed_field_requires_quote_even_when_model_sourced() -> None:
    """design.md 7.1: confirmation requires a quote, which plugs the gate's root hole.

    The model can call update_field and announce that the user confirmed. Requiring a
    quote means skipping confirmation requires fabricating one, and the fabricated
    quote lands on the report's front page where the user can check it.
    """
    with pytest.raises(ValueError, match="words at confirmation"):
        SpecField(value="ate", source=Source.MODEL, status=Status.CONFIRMED)


def test_model_inferred_value_can_be_confirmed_by_user() -> None:
    """Value inferred by the model, confirmed by the user: source stays model while said
    records the user's words at confirmation."""
    field = SpecField(
        value="ate",
        source=Source.MODEL,
        said="yes, I want the overall average effect",
        status=Status.CONFIRMED,
    )
    assert field.source is Source.MODEL and field.status is Status.CONFIRMED


# ---- design.md 11.2: the gate ----


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
                value="rrt", source=Source.MODEL, said="use the rrt column", status=Status.CONFIRMED
            )
        },
    )
    assert spec.unconfirmed_critical_fields() == ["outcome", "estimand"]


def test_spec_hash_is_stable_and_content_sensitive() -> None:
    spec = load_spec("spec_confirmed.yaml")
    assert spec.spec_hash() == load_spec("spec_confirmed.yaml").spec_hash()
    assert spec.spec_hash() != load_spec("spec_drafted.yaml").spec_hash()


# Registry behaviour (dynamic import, declaration loading, missing deps) is in
# tests/test_registry.py


def test_hte_backdoor_declares_backdoor_estimands() -> None:
    assert set(registry.declared_estimands("hte_backdoor")) == {"ate", "att", "cate"}


# ---- design.md 10.1: only code puts numbers in the report ----


def test_render_substitutes_addresses(result: Result) -> None:
    assert (
        render("effect {{res:primary.estimate}}。", result.values)
        == f"effect {result.values['res:primary.estimate']}。"
    )


def test_render_rejects_bare_number(result: Result) -> None:
    with pytest.raises(RenderError, match="Un-placeheld number"):
        render("the effect is about -0.08.", result.values)


def test_render_rejects_unknown_address(result: Result) -> None:
    with pytest.raises(RenderError, match="No such address"):
        render("confidence interval {{res:primary.ci_lower}}.", result.values)


def test_render_allows_literal_in_terminology(result: Result) -> None:
    assert render("{{lit:28}}-day mortality.", result.values) == "28-day mortality."


def test_render_rejects_result_smuggled_as_literal(result: Result) -> None:
    estimate = result.values["res:primary.estimate"]
    with pytest.raises(RenderError, match="equals the computed result"):
        render(f"difference {{{{lit:{estimate}}}}}。", result.values)


# ---- format specs ----


def test_format_spec_controls_precision(result: Result) -> None:
    """Without this the report shows 17 significant digits, and a model's natural
    response is to round it to -0.018 itself, which defeats G4. Letting it declare
    precision is safer than letting it do the maths."""
    addresses = {"res:primary.ate": -0.017936448014042473}
    assert render("effect {{res:primary.ate|+.3f}}。", addresses) == "effect -0.018。"


def test_percent_format(result: Result) -> None:
    assert render("{{qc:x.frac|.1%}}", {"qc:x.frac": 0.002}) == "0.2%"


def test_format_spec_works_on_literals(result: Result) -> None:
    assert render("{{lit:95}}% confidence interval", result.values) == "95% confidence interval"


def test_invalid_format_spec_raises_instead_of_falling_back(result: Result) -> None:
    """A bad format spec must raise rather than fall back silently, or the report's
    precision becomes unpredictable."""
    with pytest.raises(RenderError, match="format spec"):
        render("{{res:primary.n|.2%x}}", result.values)


def test_format_spec_does_not_exempt_bare_numbers(result: Result) -> None:
    with pytest.raises(RenderError, match="Un-placeheld number"):
        render("effect {{res:primary.estimate|.3f}}, plus a stray 0.5.", result.values)


def test_render_exempts_markdown_structure(result: Result) -> None:
    template = "## Results\n\n1. first\n2. second\n\n| a | b |\n|---|---|\n| x | y |\n"
    assert render(template, result.values) == template


def test_addresses_are_namespaced(result: Result) -> None:
    assert all(address.startswith("res:") for address in result.values)


# ---- readability of error messages ----


def test_bare_number_error_suggests_the_fix(result: Result) -> None:
    """The trap hit during the cold-start test: when a number inside a term is caught,
    say plainly what to write instead."""
    with pytest.raises(RenderError) as excinfo:
        render("the outcome is 28-day mortality.", result.values)
    message = str(excinfo.value)
    assert "{{lit:28}}" in message
    assert "term" in message


def test_bare_number_error_points_at_a_matching_address(result: Result) -> None:
    """When a bare number equals a result, name the address to cite rather than erroring
    vaguely."""
    estimate = result.values["res:primary.estimate"]
    with pytest.raises(RenderError) as excinfo:
        render(f"the effect is {estimate}。", result.values)
    assert "{{res:primary.estimate}}" in str(excinfo.value)


def test_unknown_address_error_is_scoped_to_the_namespace(result: Result) -> None:
    """The message no longer dumps dozens of addresses; only the same namespace."""
    addresses = {**result.values, "qc:some_check.passed": "yes", "claim:level": "suggestive"}
    with pytest.raises(RenderError) as excinfo:
        render("{{res:primary.nonexistent}}", addresses)
    message = str(excinfo.value)
    assert "res:" in message
    assert "claim:level" not in message  # other namespaces must not appear


def test_address_list_is_truncated(result: Result) -> None:
    many = {f"res:x.f{i:03d}": float(i) for i in range(40)}
    with pytest.raises(RenderError) as excinfo:
        render("{{res:x.missing}}", many)
    assert "more" in str(excinfo.value)

"""Checks that compare one part of the spec with another.

Two checks. `imputation_assumption_declared` exists because of a design mistake worth
recording, below. `roles_match_adjustment` is what makes the derived diagram more than an
illustration: a picture cannot be wrong in a way anyone notices, but the declaration it is
drawn from can be compared with the variables the analysis actually conditions on. An earlier
version made any imputation force `interval_calibration: exploratory`, so no result in such a
run could be called significant. That was not defensible: excluding the units with a missing
column distorts the estimate too, through selection rather than through variance, and it kept
its calibrated interval. Penalising the fill and not the exclusion pushed users towards the
exclusion, which is not reliably the better choice, and it dressed a judgement up as
arithmetic.

What a fill actually introduces is an assumption the data cannot settle: that the values are
missing at random given whatever the fill conditioned on. This project already has one way of
handling such things, and it is the one that puts the decision where it belongs. An untestable
assumption declared and justified **by the user** permits causal wording; declared and
unjustified caps it. So a fill has to be on the record as an assumption, in the user's own
words, and then the ordinary machinery applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from causpec.core.contracts.quality import QualityIssue, QualityReport, Severity, Suggestion
from causpec.core.contracts.spec import ROLES_BARRED_FROM_ADJUSTMENT, Spec
from causpec.core.quality.basic import _issue, load_config

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# The assumption a fill introduces. One id, so the check can look for it and the report can
# cite it.
MISSINGNESS_ASSUMPTION = "missing_at_random"

# The fills whose value is approximately known from a mechanism rather than drawn from a
# model, and which therefore do not introduce the assumption on their own. A missing infusion
# rate that means no infusion is a recode wearing a fill's name; a panel value carried forward
# one period rests on "nothing was remeasured because nothing changed", which is an argument
# about the clinical process rather than about the missingness pattern.
#
# They are exempt from the *requirement*, not from being reported: both still appear in the
# applied-steps list with their counts.
MECHANISM_FILLS = ("impute_constant", "impute_locf")


def check_assumptions(
    data: pd.DataFrame, spec: Spec, config_path: Path | None = None
) -> QualityReport:
    """Whether what was done to the data is matched by what the spec admits to."""
    del data  # This check reads the spec only; the signature matches every other layer.
    config = load_config(config_path)
    return QualityReport(issues=[_imputation_assumption(spec, config)])


def _imputation_assumption(spec: Spec, config: dict) -> QualityIssue:
    check_id = "imputation_assumption_declared"
    fills = [step for step in spec.preprocessing if step.imputes]
    model_based = [step for step in fills if step.op not in MECHANISM_FILLS]
    declared = {assumption.id for assumption in spec.assumptions}
    justified = {
        assumption.id for assumption in spec.assumptions if assumption.is_justified_by_user
    }

    if not fills:
        return _issue(
            config,
            check_id,
            passed=True,
            summary="no values were filled, so no missingness assumption is needed",
            evidence={"assessed": False, "n_fills": 0},
        )

    columns = sorted({step.column for step in fills})
    evidence: dict[str, float | int | str | bool] = {
        "assessed": True,
        "n_fills": len(fills),
        "filled_columns": ", ".join(columns),
        "operations": ", ".join(sorted({step.op for step in fills})),
        "mechanism_fills_only": not model_based,
        "assumption_declared": MISSINGNESS_ASSUMPTION in declared,
        "assumption_justified_by_user": MISSINGNESS_ASSUMPTION in justified,
    }

    if not model_based:
        return _issue(
            config,
            check_id,
            passed=True,
            summary=(
                f"{len(fills)} fill(s) in {', '.join(columns)}, all from a stated mechanism "
                f"rather than from a model of the missingness"
            ),
            evidence=evidence,
            columns=columns,
            impact=(
                "A constant the user named and a value carried forward rest on an argument "
                "about the clinical process, which the report states, rather than on a "
                "pattern in the missingness. They are still fills and still printed with "
                "their counts."
            ),
        )

    if MISSINGNESS_ASSUMPTION in declared:
        return _issue(
            config,
            check_id,
            passed=True,
            summary=(
                f"{len(model_based)} model-based fill(s) in {', '.join(columns)}, with the "
                f"missingness assumption declared"
                + ("" if MISSINGNESS_ASSUMPTION in justified else " but not yet justified")
            ),
            evidence=evidence,
            columns=columns,
            impact=(
                "An undeclared justification does not block the analysis; it caps the claim "
                "level, the same as any other untestable assumption, and the report says so."
            ),
        )

    return _issue(
        config,
        check_id,
        passed=False,
        summary=(
            f"{len(model_based)} fill(s) in {', '.join(columns)} with no missingness "
            f"assumption declared in the spec"
        ),
        evidence=evidence,
        columns=columns,
        impact=(
            "Filling a value from a model of the other columns assumes the values are "
            "missing at random given those columns. No diagnostic can check that, and it is "
            "often false in exactly the way that matters: a test skipped because the patient "
            "looked fine, or because they died in the first hours, is missing *because* of "
            "something related to the outcome. The analysis can still be the right one, but "
            "the assumption has to be on the record rather than inside a preprocessing step."
        ),
        repair=(
            "Add the assumption to the spec and say in your own words why it is reasonable "
            "here: which columns carry the information about why a value is absent. Until "
            "someone justifies it the claim level stays below causal, which is the same "
            "treatment every untestable assumption gets."
        ),
        suggestions=[
            Suggestion(
                kind="assumption",
                operation={
                    "id": MISSINGNESS_ASSUMPTION,
                    "category": "untestable",
                    "statement": (
                        f"Values in {', '.join(columns)} are missing at random given the "
                        f"other analysis columns, so a value filled from them stands in for "
                        f"the one that was not recorded."
                    ),
                },
                cost=(
                    "Declaring it changes no number. Justifying it is what lets the analysis "
                    "reach causal wording, and the justification has to be yours: a model "
                    "vouching for its own assumptions is circular."
                ),
            )
        ],
    )


def check_roles(data: pd.DataFrame, spec: Spec, config_path: Path | None = None) -> QualityReport:
    """Whether the declared roles agree with the variables the analysis actually adjusts for.

    This is why the diagram is derived rather than drawn. A picture cannot be wrong in a way
    anyone notices; a declaration can, because the same roles that produce the edges can be
    compared with `adjustment_set` and `effect_modifiers`.

    The backdoor criterion over a role-derived graph needs no graph library. The graph's shape
    is fixed, so the criterion reduces to: every confounder adjusted, and nothing adjusted
    that the treatment could have caused or that the design depends on. `data` is read only to
    confirm a declared variable is present.
    """
    config = load_config(config_path)
    return QualityReport(issues=[_roles_vs_adjustment(data, spec, config)])


def _adjusted_columns(spec: Spec) -> list[str]:
    """Everything that enters a nuisance model: the adjustment set and the modifiers.

    Both are conditioned on, so both are subject to the same rule. Putting a mediator in
    `effect_modifiers` rather than `adjustment_set` does not make it safe, and that mistake
    is easier to make because the field name does not sound like adjustment.
    """
    names: list[str] = []
    for field_name in ("adjustment_set", "effect_modifiers"):
        entry = spec.fields.get(field_name)
        if entry is None or entry.value is None:
            continue
        value = entry.value
        items = value if isinstance(value, (list, tuple)) else [value]
        names.extend(str(item) for item in items)
    return names


def _roles_vs_adjustment(data: pd.DataFrame, spec: Spec, config: dict) -> QualityIssue:
    check_id = "roles_match_adjustment"
    if not spec.variable_roles:
        return _issue(
            config,
            check_id,
            passed=True,
            summary="no variable roles are declared, so there is nothing to compare",
            evidence={"assessed": False, "n_roles": 0},
            impact=(
                "Without declared roles the diagram cannot be drawn and this comparison "
                "cannot run. Its absence is not evidence that the adjustment set is right."
            ),
        )

    adjusted = set(_adjusted_columns(spec))
    barred: list[str] = []
    reasons: list[str] = []
    for variable, role in sorted(spec.variable_roles.items()):
        if variable in adjusted and role in ROLES_BARRED_FROM_ADJUSTMENT:
            barred.append(f"{variable} ({role})")
            reasons.append(f"{variable} is a {role}: {ROLES_BARRED_FROM_ADJUSTMENT[role]}")

    confounders = spec.variables_in_role("confounder")
    unadjusted = [name for name in confounders if name not in adjusted]
    missing_from_data = [name for name in spec.variable_roles if name not in data.columns]

    evidence: dict[str, float | int | str | bool] = {
        "assessed": True,
        "n_roles": len(spec.variable_roles),
        "n_adjusted": len(adjusted),
        "n_confounders": len(confounders),
        "barred_but_adjusted": ", ".join(barred) or "none",
        "confounders_not_adjusted": ", ".join(unadjusted) or "none",
        "declared_but_absent_from_data": ", ".join(sorted(missing_from_data)) or "none",
    }

    if barred:
        return _issue(
            config,
            check_id,
            passed=False,
            summary=f"the analysis adjusts for {', '.join(barred)}",
            evidence=evidence,
            columns=[name.split(" ")[0] for name in barred],
            impact=(
                "Each of these distorts the estimate in a direction the interval does not "
                "show, because the arithmetic is working correctly on the wrong quantity. "
                + " ".join(reasons)
            ),
            repair=(
                "Remove them from adjustment_set and effect_modifiers, or change the "
                "declared role if the role is what is wrong. A variable that belongs in "
                "neither place can still be reported as a descriptive characteristic."
            ),
        )

    if unadjusted:
        return _issue(
            config,
            check_id,
            passed=False,
            severity=Severity(config.get(check_id, {}).get("severity_unadjusted", "warning")),
            summary=(
                f"{len(unadjusted)} variable(s) declared as confounders are not adjusted "
                f"for: {', '.join(unadjusted)}"
            ),
            evidence=evidence,
            columns=unadjusted,
            impact=(
                "A confounder the analysis does not condition on leaves its path from the "
                "treatment to the outcome open, so the estimate keeps the bias the "
                "declaration says is there. The diagram will show the open path."
            ),
            repair=(
                "Add them to adjustment_set, or change the role if they are not confounders "
                "after all. If the column does not exist in this extract, say so: an "
                "unmeasured confounder is a limitation to report, not a field to leave blank."
            ),
        )

    return _issue(
        config,
        check_id,
        passed=True,
        summary=(
            f"{len(spec.variable_roles)} declared role(s) agree with the adjustment set: "
            f"every confounder is adjusted and nothing barred is"
        ),
        evidence=evidence,
        impact=(
            "The comparison is structural, over the graph the roles imply. It cannot speak "
            "to whether the roles themselves are right, which is what the untestable "
            "assumptions are for."
        ),
    )

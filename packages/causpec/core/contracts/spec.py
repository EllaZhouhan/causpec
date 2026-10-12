"""Pydantic contracts for the analysis spec: field-level provenance and status.

Mirrors design.md 7.1 and 7.2. This is the vertical-slice version: it carries only
the fields the gate and the two implemented families need. The full structure
(variable_roles, key_non_edges, analysis_plan) grows as consumers appear.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(StrEnum):
    """Where a field's value came from."""

    USER = "user"
    MODEL = "model"
    DATA = "data"


class Status(StrEnum):
    """Whether a field has been confirmed by the user.

    A conflict between what the user said and what the data shows is deliberately
    *not* a status here: quality checks raise a blocking issue and gate condition 2
    stops the run (design.md 7.1). One more status would mean a second mechanism
    doing the same job, with its own tests and its own ways to drift.
    """

    DRAFTED = "drafted"
    CONFIRMED = "confirmed"


class AssumptionCategory(StrEnum):
    """The three kinds of identification assumption (design.md 7.2).

    The category determines what can possibly support the assumption:

    - ``EMPIRICALLY_ASSESSED``: the data can speak to it. Quality checks produce
      the evidence (overlap, instrument relevance).
    - ``REQUIRES_JUSTIFICATION``: the data cannot settle it, but it can be argued
      (e.g. whether the treatment has a single well-defined version).
    - ``UNTESTABLE``: no amount of data can verify it (unconfoundedness, exclusion
      restriction, monotonicity). **No diagnostic will ever prove these.**

    That last category caps what the code may claim: code can only report "the
    diagnostics found nothing wrong", never "the causal claim holds". Reaching
    ``causal`` wording requires a person to justify each untestable assumption and
    put their name to it (design.md 10.2).
    """

    EMPIRICALLY_ASSESSED = "empirically_assessed"
    REQUIRES_JUSTIFICATION = "requires_justification"
    UNTESTABLE = "untestable"


class Assumption(BaseModel):
    """One identification assumption.

    ``statement`` comes from family.yaml; ``justification`` comes from the user.
    ``justified_by`` records who argued for it, a ``source=model`` justification
    does not count, because a model vouching for its own assumptions is circular
    (design.md 10.2).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    category: AssumptionCategory
    statement: str
    justification: str = ""
    justified_by: Source | None = None

    @property
    def is_justified_by_user(self) -> bool:
        return bool(self.justification.strip()) and self.justified_by is Source.USER


class SpecField(BaseModel):
    """One spec field together with its provenance and status.

    ``said`` is required in two places (design.md 7.1):

    - when ``source=user``: what the user said is the evidence, and it is kept verbatim
    - when ``status=confirmed``: the words the user used when confirming, regardless
      of who proposed the value

    The second rule plugs the gate's root hole: ``update_field`` is called by the
    model, and the server has no way to verify that the user really confirmed
    anything. Requiring a quote means a model that skips confirmation has to
    fabricate one, and the fabricated quote lands on the report's front page,
    where the user will recognise it as something they never said. It does not
    close the hole; it raises the cost and leaves a trace.
    """

    model_config = ConfigDict(frozen=True)

    value: Any
    source: Source
    status: Status = Status.DRAFTED
    said: str | None = None
    turn: int | None = None

    @model_validator(mode="after")
    def _quote_required(self) -> SpecField:
        if self.source is Source.USER and not self.said:
            raise ValueError("source=user requires the user's own words in `said`")
        if self.status is Status.CONFIRMED and not self.said:
            raise ValueError("status=confirmed requires the user's words at confirmation in `said`")
        return self


# Fields the gate requires to be confirmed (design.md 7.1). The slice version lists
# three; the full list also covers variable_roles, key_non_edges,
# identification_strategy, adjustment_set and instrument. `population` is deliberately not
# here: an analysis of everyone in the extract is a legitimate analysis, and the filters that
# exist are each confirmed individually.
CRITICAL_FIELDS = ("treatment", "outcome", "estimand")

# The operations a preprocessing step may name (design.md 6.4).
#
# The first two change how a value is written down and add no information. The rest fill
# values nobody measured, which is a different kind of act: every one of them makes the
# interval narrower than the evidence supports, so a spec containing any of them runs with
# `interval_calibration: exploratory` and cannot reach a significance claim. That is the
# price, and it is charged automatically rather than left to a reader to notice.
#
# `impute_mean` is deliberately absent: ICU labs are right-skewed, so the mean of the
# observed is a worse centre than the median and there is no case where it is the better
# choice.
PREPROCESSING_OPERATIONS = (
    "recode_null",
    "cast",
    "impute_constant",
    "impute_median",
    "impute_iterative",
    "impute_locf",
    "add_missing_indicator",
)

# The operations that substitute values nobody measured.
IMPUTATION_OPERATIONS = (
    "impute_constant",
    "impute_median",
    "impute_iterative",
    "impute_locf",
)


class PreprocessingStep(BaseModel):
    """One transformation applied to the working copy before anything is checked or estimated.

    It carries ``said`` for the same reason every spec field does, and the rule is stricter
    here: a transformation changes the numbers, so there is no version of this that the user
    merely did not object to. If they did not say yes in their own words, it does not run.

    Steps are an ordered list and the order is part of the meaning. Recoding a sentinel to
    missing and then casting a column is not the same as casting first, where a lenient cast
    would silently swallow the sentinel and no record of it would exist.
    """

    model_config = ConfigDict(frozen=True)

    op: str
    column: str
    # recode_null: the values to treat as missing. cast: ignored.
    values: list[Any] = Field(default_factory=list)
    # cast: "number". recode_null: ignored.
    to: str | None = None
    # impute_constant: the value to fill. Required there, ignored elsewhere.
    value: Any = None
    # impute_locf: how many consecutive periods a value may be carried. Required, because
    # carrying a creatinine forward twelve hours and carrying it forward five days are
    # different claims and only one of them is usually defensible.
    limit: int | None = None
    said: str
    turn: int | None = None
    # Which check asked for this, when a check suggested it. Blank for a step the user asked
    # for themselves, which is also allowed.
    suggested_by: str = ""

    @model_validator(mode="after")
    def _known_operation(self) -> PreprocessingStep:
        if self.op not in PREPROCESSING_OPERATIONS:
            raise ValueError(
                f"unknown preprocessing operation {self.op!r}; "
                f"available: {', '.join(PREPROCESSING_OPERATIONS)}"
            )
        if not self.said.strip():
            raise ValueError(
                "a preprocessing step requires the user's own words in `said`: a "
                "transformation changes the numbers, so silence is not consent"
            )
        if self.op == "recode_null" and not self.values:
            raise ValueError("recode_null requires the values to treat as missing")
        if self.op == "cast" and not self.to:
            raise ValueError("cast requires `to`")
        if self.op == "impute_constant" and self.value is None:
            raise ValueError(
                "impute_constant requires `value`: the number to fill. There is no sensible "
                "default, and a wrong one is indistinguishable from a measurement"
            )
        if self.op == "impute_locf":
            if self.limit is None:
                raise ValueError(
                    "impute_locf requires `limit`: how many consecutive periods a value may "
                    "be carried forward. Carrying one forward twelve hours and carrying it "
                    "forward five days are different claims"
                )
            if self.limit < 1:
                raise ValueError("impute_locf requires limit >= 1")
        return self

    @property
    def imputes(self) -> bool:
        """Whether this step fills values nobody measured."""
        return self.op in IMPUTATION_OPERATIONS


# Comparisons a population filter may use. No arbitrary expressions, for the same reason the
# mapping refuses them: a filter decides who the answer is about, so it has to be reviewable by
# someone who did not write it.
FILTER_OPERATORS = (
    "not_missing",
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
    "not_in",
)

# Operators that need no right-hand side.
UNARY_FILTER_OPERATORS = ("not_missing",)


class PopulationFilter(BaseModel):
    """One criterion deciding who is in the analysis.

    Separate from a preprocessing step because it does a different thing: a step changes how a
    value is written, a filter changes **who the answer is about**. Dropping the patients with
    no creatinine is not cleaning, it is redefining the population as "patients who had a
    creatinine drawn", and whether a test was ordered is itself a clinical decision. So every
    filter is counted in the report's exclusion ledger and checked for whether the people it
    removed differ from the people it kept.

    Filters are conjunctive and applied in order: the ledger reads as a sequence of
    exclusions, which is the form a reader of a study already knows how to audit.
    """

    model_config = ConfigDict(frozen=True)

    column: str
    op: str
    # Absent for `not_missing`; a scalar for the comparisons; a list for `in` / `not_in`.
    value: Any = None
    said: str
    turn: int | None = None
    suggested_by: str = ""

    @model_validator(mode="after")
    def _known_operator(self) -> PopulationFilter:
        if self.op not in FILTER_OPERATORS:
            raise ValueError(
                f"unknown filter operator {self.op!r}; available: {', '.join(FILTER_OPERATORS)}"
            )
        if not self.said.strip():
            raise ValueError(
                "a population filter requires the user's own words in `said`: it decides who "
                "the answer is about, so silence is not consent"
            )
        if self.op in UNARY_FILTER_OPERATORS:
            if self.value is not None:
                raise ValueError(f"{self.op} takes no value; got {self.value!r}")
        elif self.value is None:
            raise ValueError(f"{self.op} requires a value to compare against")
        if self.op in ("in", "not_in") and not isinstance(self.value, (list, tuple)):
            raise ValueError(f"{self.op} requires a list of values; got {self.value!r}")
        return self

    def describe(self) -> str:
        if self.op in UNARY_FILTER_OPERATORS:
            return f"{self.column} {self.op.replace('_', ' ')}"
        return f"{self.column} {self.op} {self.value!r}"


class Population(BaseModel):
    """Who the analysis is about: a description in the user's words, and the filters.

    The description is not decoration. Two analyses with the same filters and different
    descriptions mean the user and the data disagree about one of them, and the description is
    what a reader compares the ledger against.
    """

    model_config = ConfigDict(frozen=True)

    description: str = ""
    filters: list[PopulationFilter] = Field(default_factory=list)


# The roles a variable can play (design.md 7.5). The set is closed because the diagram's
# edges are derived from it: a role nobody can draw is a role that means nothing.
VARIABLE_ROLES = (
    "confounder",
    "instrument",
    "mediator",
    "effect_modifier",
    "suspected_collider",
    "post_treatment",
)

# Roles that must never enter the adjustment set, and why in one phrase each. Read by the
# structural check, so the reason reaches the user rather than living in a comment.
ROLES_BARRED_FROM_ADJUSTMENT = {
    "mediator": (
        "adjusting for a mediator removes the part of the effect that travels through it, "
        "so the total effect shrinks towards zero"
    ),
    "suspected_collider": (
        "conditioning on a common consequence of the treatment and the outcome creates an "
        "association that is not there, which can reverse the sign"
    ),
    "post_treatment": (
        "a variable the treatment could have changed is partly an outcome, so adjusting for "
        "it conditions away the thing being measured"
    ),
    "instrument": (
        "adjusting for the instrument closes the only path it has to the treatment, which "
        "is the path the design relies on"
    ),
}


class Spec(BaseModel):
    """An analysis specification."""

    model_config = ConfigDict(frozen=True)

    spec_version: int = 1
    question: str
    family: str
    fields: dict[str, SpecField] = Field(default_factory=dict)
    # design.md 7.2's `estimation: {family, params, seed}`. Estimator hyper-parameters
    # live here rather than hard-coded in family code: they change the result, so they
    # must be confirmed with the spec, enter spec_hash, and land in the manifest.
    estimation: dict[str, Any] = Field(default_factory=dict)
    # design.md 7.2's `assumptions`: three categories plus justification. The claim-level
    # decision reads this.
    assumptions: list[Assumption] = Field(default_factory=list)
    # design.md 6.4: transformations applied to the working copy, in order, before anything is
    # checked or estimated. They are part of the spec because they change the numbers, so they
    # enter spec_hash and the manifest along with everything else that does.
    preprocessing: list[PreprocessingStep] = Field(default_factory=list)
    # design.md 7.2's `population`. Applied after preprocessing and before any check, because
    # a check should describe the population being analysed rather than one nobody asked
    # about. It changes who the answer is about, so it enters spec_hash.
    population: Population = Field(default_factory=Population)
    # design.md 7.5. A role per variable or per group, drafted by the agent from the user's
    # answers and confirmed. The diagram is derived from this rather than drawn by hand: a
    # full DAG over forty ICU covariates is a formality nobody reads, and a derived one can
    # be checked against the adjustment set, which a picture cannot.
    variable_roles: dict[str, str] = Field(default_factory=dict)
    # The few "no edge" assumptions that decide whether identification holds, in words. They
    # appear as dashed crossed-out edges in the diagram, because an assumption drawn is an
    # assumption someone can object to.
    key_non_edges: list[str] = Field(default_factory=list)

    def role_of(self, variable: str) -> str | None:
        """The declared role of one variable, or None."""
        return self.variable_roles.get(variable)

    def variables_in_role(self, role: str) -> list[str]:
        """Every variable declared in one role, in declaration order."""
        return [name for name, value in self.variable_roles.items() if value == role]

    def imputed_columns(self) -> list[str]:
        """Columns holding filled values, in the order they were filled.

        Read by the claim-level decision: an interval computed over a column that is partly
        invented is narrower than the evidence supports, whatever the estimator does, so the
        run is exploratory. The alternative to charging this automatically is a report whose
        interval looks like every other interval.
        """
        return [step.column for step in self.preprocessing if step.imputes]

    @model_validator(mode="after")
    def _known_roles(self) -> Spec:
        unknown = {
            name: role for name, role in self.variable_roles.items() if role not in VARIABLE_ROLES
        }
        if unknown:
            listed = ", ".join(f"{name}={role}" for name, role in sorted(unknown.items()))
            raise ValueError(
                f"unknown variable role(s): {listed}. Available: {', '.join(VARIABLE_ROLES)}. "
                f"The diagram's edges are derived from the role, so a role that cannot be "
                f"drawn is a role that means nothing."
            )
        return self

    def param(self, name: str, default: Any) -> Any:
        """Read one estimator hyper-parameter, falling back to a default."""
        params = self.estimation.get("params") or {}
        return params.get(name, default)

    def unconfirmed_critical_fields(self) -> list[str]:
        """Critical fields not yet confirmed, in CRITICAL_FIELDS order. Missing counts."""
        return [
            name
            for name in CRITICAL_FIELDS
            if (field := self.fields.get(name)) is None or field.status is not Status.CONFIRMED
        ]

    def untestable_assumptions(self) -> list[Assumption]:
        return [a for a in self.assumptions if a.category is AssumptionCategory.UNTESTABLE]

    def unjustified_untestable_assumptions(self) -> list[str]:
        """Untestable assumptions with no user justification. These block `causal` wording."""
        return [a.id for a in self.untestable_assumptions() if not a.is_justified_by_user]

    def spec_hash(self) -> str:
        """Stable hash of the spec, used to lock the primary analysis and to gate (11.1)."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

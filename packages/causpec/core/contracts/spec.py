"""Pydantic contracts for the analysis spec: field-level provenance and status.

Mirrors design.md 7.1 and 7.2. This is the vertical-slice version: it carries only
the fields the gate and the two implemented families need. The full structure
(population, variable_roles, key_non_edges, analysis_plan) grows as consumers appear.
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
# three; the full list also covers population, variable_roles, key_non_edges,
# identification_strategy, adjustment_set and instrument.
CRITICAL_FIELDS = ("treatment", "outcome", "estimand")

# The operations a preprocessing step may name (design.md 6.4). Six are designed; two are
# implemented, because those are the two any check can currently suggest and unreachable
# operations are unreviewable ones.
PREPROCESSING_OPERATIONS = ("recode_null", "cast")


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
        return self


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

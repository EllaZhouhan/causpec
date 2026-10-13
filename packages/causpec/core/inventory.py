"""Every column in the file, described one at a time, for the user to choose roles from.

**Why this is a command and not something the agent writes itself.** At the variable-roles
step the agent has to tell the user what is in their file. Left to improvise, it summarises
from the header: "age, sex, AKI stage and the 14 labs and vitals (creatinine, urea, potassium
and so on)", which hides nine columns behind "and so on" and drops three more without saying
it. The user cannot choose from that, and the columns they were never shown are the ones they
would have had something to say about.

**The line this module draws, and the reason it is drawn here.** Describing one column is a
description of the file. Relating two columns is a diagnostic of the analysis, and those
belong in the checks, where a spec can stand them down and a report can carry them. So
everything here is per-column and nothing crosses columns: no balance between arms, no
propensity fit, no correlation with the outcome. The agent needs a complete inventory at the
roles step, and the one thing it must not be able to reach for is a comparison the spec has
already settled.

The groups are shapes rather than meanings. A file does not say which columns are labs and
which are vitals, and guessing would put a wrong word in front of the user. What the data does
say is how many distinct values a column has, whether it is one per row, and whether it varies
at all, which is exactly what decides whether it can be a covariate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd

from causpec.core.contracts.spec import Spec
from causpec.core.quality.basic import COLUMN_FIELDS, load_config

if TYPE_CHECKING:  # pragma: no cover
    from pathlib import Path

# A date written as text. Cheaper than asking pandas to parse, and quiet: `to_datetime` on a
# column of lab values either warns or succeeds on something that is not a date.
DATE_TEXT = re.compile(r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]|$)|^\s*\d{1,2}[-/]\d{1,2}[-/]\d{4}")

# How many levels are listed in full before the summary gives a count instead.
LEVELS_SHOWN = 8

GROUP_NOTES = {
    "identifier": "one value per row, so it cannot be a covariate",
    "constant": "one value throughout, so it cannot be a covariate",
    "empty": "no values at all",
    "date": "a date or a timestamp",
    "binary": "two values",
    "scale": "a code or a score, few levels",
    "code": "whole numbers with many levels, often an id or a count",
    "measurement": "a measurement on a continuum",
    "category": "text with a few levels",
    "text": "text with many levels",
}
GROUP_ORDER = (
    "binary",
    "scale",
    "measurement",
    "code",
    "category",
    "date",
    "text",
    "identifier",
    "constant",
    "empty",
)


@dataclass(frozen=True)
class ColumnFacts:
    """What one column is, and nothing about how it relates to any other."""

    name: str
    group: str
    n_distinct: int
    n_missing: int
    summary: str
    role: str | None = None


def _format(value: float) -> str:
    if not np.isfinite(value):
        return "nan"
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.4g}"


def _levels(series: pd.Series) -> str:
    values = series.dropna().unique().tolist()
    try:
        values = sorted(values)
    except TypeError:  # mixed types in one object column
        values = sorted(values, key=str)
    shown = ", ".join(_format(v) if isinstance(v, (int, float)) else str(v) for v in values)
    return shown


def _looks_like_a_date(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_numeric_dtype(series):
        return False
    sample = series.dropna().astype(str).head(200)
    return len(sample) > 0 and bool(sample.map(lambda v: bool(DATE_TEXT.match(v))).all())


def _is_whole_numbers(series: pd.Series) -> bool:
    values = np.asarray(series.dropna(), dtype=float)
    return bool(len(values)) and bool(np.all(values == np.floor(values)))


def _group_of(series: pd.Series, n_rows: int, n_distinct: int, max_levels: int) -> str:
    """Which shape this column has. Order matters: the disqualifying shapes come first.

    **All-distinct is not enough to call something an identifier.** The first version of this
    said it was, and filed two creatinine-like columns of 4,000 distinct floats under "cannot
    be a covariate", which would have removed them from the analysis silently. A measured
    quantity on a continuum is all-distinct whenever the sample is small against its
    precision. An identifier is a label: text, or a whole number.
    """
    numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    whole = numeric and _is_whole_numbers(series)
    if n_distinct == 0:
        return "empty"
    if n_distinct == 1:
        return "constant"
    if n_distinct == n_rows and n_rows > 1 and (not numeric or whole):
        return "identifier"
    if _looks_like_a_date(series):
        return "date"
    if n_distinct == 2:
        return "binary"
    if numeric:
        if n_distinct <= max_levels:
            return "scale"
        return "code" if whole else "measurement"
    return "category" if n_distinct <= max_levels else "text"


def _summary(series: pd.Series, group: str, n_distinct: int) -> str:
    if group in {"empty", "identifier", "text"}:
        return f"{n_distinct:,} distinct values"
    if group == "date":
        values = series.dropna().astype(str)
        return f"{values.min()} to {values.max()}" if len(values) else "no values"
    if n_distinct <= LEVELS_SHOWN:
        return _levels(series)
    if pd.api.types.is_numeric_dtype(series):
        values = np.asarray(series.dropna(), dtype=float)
        return (
            f"{n_distinct:,} values, {_format(float(values.min()))} to "
            f"{_format(float(values.max()))}, median {_format(float(np.median(values)))}"
        )
    return f"{n_distinct:,} distinct values"


def _roles(spec: Spec | None, data: pd.DataFrame) -> dict[str, str]:
    """Which spec field already claims each column, so the inventory shows what is left.

    The field name itself, not a prettier word for it: the user is about to see the spec, and
    two vocabularies for one field is how a confirmation step stops being a confirmation.
    """
    if spec is None:
        return {}
    claimed: dict[str, str] = {}
    for field_name in COLUMN_FIELDS:
        field = spec.fields.get(field_name)
        if field is None or field.value is None:
            continue
        values = field.value if isinstance(field.value, (list, tuple)) else [field.value]
        for value in values:
            column = str(value)
            if column in data.columns and column not in claimed:
                claimed[column] = field_name
    return claimed


def describe_columns(
    data: pd.DataFrame, spec: Spec | None = None, config_path: Path | None = None
) -> list[ColumnFacts]:
    """One `ColumnFacts` per column, in the file's own order."""
    config = load_config(config_path)
    entry: dict[str, Any] = config.get("basic_zero_spike", {})
    max_levels = int(entry.get("max_levels_for_a_scale", 20))
    claimed = _roles(spec, data)
    n_rows = len(data)
    facts: list[ColumnFacts] = []
    for name in data.columns:
        series = cast("pd.Series", data[name])
        n_distinct = int(series.nunique(dropna=True))
        group = _group_of(series, n_rows, n_distinct, max_levels)
        facts.append(
            ColumnFacts(
                name=str(name),
                group=group,
                n_distinct=n_distinct,
                n_missing=int(series.isna().sum()),
                summary=_summary(series, group, n_distinct),
                role=claimed.get(str(name)),
            )
        )
    return facts


def render(facts: list[ColumnFacts], n_rows: int, source: str | None = None) -> str:
    """The inventory as text, grouped by shape.

    Grouped rather than in file order, because the file's order is an accident of the extract
    and the shape is what decides whether a column can hold a role. Every column appears
    exactly once: a column left out of this listing is a column the user cannot ask about.
    """
    where = f" in {source}" if source else ""
    lines = [f"{len(facts)} columns{where}, {n_rows:,} rows"]
    width = max((len(f.name) for f in facts), default=0)
    for group in GROUP_ORDER:
        members = [f for f in facts if f.group == group]
        if not members:
            continue
        lines += ["", f"{group} ({len(members)}): {GROUP_NOTES[group]}"]
        for fact in members:
            marks = []
            if fact.role:
                marks.append(fact.role)
            if fact.n_missing:
                marks.append(f"{fact.n_missing / n_rows:.1%} missing" if n_rows else "missing")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            lines.append(f"  {fact.name:<{width}}  {fact.summary}{suffix}")
    unknown = {f.group for f in facts} - set(GROUP_ORDER)
    if unknown:  # pragma: no cover - a group added above and not ordered here
        raise AssertionError(f"ungrouped column shapes: {sorted(unknown)}")
    return "\n".join(lines)

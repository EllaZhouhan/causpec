"""The basic layer: is this table self-consistent?

Mirrors design.md 8.1. Every other layer asks whether a design can identify an effect, and
needs to know what the treatment and the instrument are. This one asks only whether the
table says what it appears to say, so it runs for every family and lives in core.

It also runs **first**. Overlap, instrument relevance and continuation weights are all
computed from the numbers in these columns, so assessing identification on a table whose
creatinine column contains -999 produces a confident answer about nothing. When the basic
layer blocks, the caller reports that and does not attempt the design-level checks.

The check that earns this module is NULL encoding. The others are cheap guards against a
mistake that would otherwise surface from inside a nuisance regression. A sentinel is worse
than that: it does not fail anywhere. A creatinine column with -999 for "not measured"
teaches the propensity model that patients with impossibly low creatinine are never
dialysed, and every number downstream is then a statement about a measurement artefact.

Written by hand rather than with pandera (ADR-0003): the three things it would do here are
one pandas call each, translating its failure cases into addressed issues with repairs is
most of the work, and the NULL-variant detection it does not do at all.
"""

from __future__ import annotations

import hashlib
import importlib.resources as resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

from causpec.core.contracts.quality import Layer, QualityIssue, QualityReport, Severity
from causpec.core.contracts.spec import Spec

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# As in the registry and the claim-level rules: importlib.resources, because in skill form
# causpec is imported out of a wheel, where Path(__file__) points at nothing.
CONFIG_PACKAGE = "causpec.core.quality"
CONFIG_NAME = "basic_checks.yaml"

# Spec fields whose value is a column name, or a list of them. Membership in the data decides
# the rest: a field like `estimand` holds `lag_profile`, which is no column, and `termination`
# holds either a column or the literal `last_recorded_period`.
COLUMN_FIELDS = (
    "unit_id",
    "period_index",
    "treatment",
    "outcome",
    "state",
    "effect_modifiers",
    "adjustment_set",
    "instrument",
    "termination",
)


def _config_bytes(path: Path | None = None) -> bytes:
    if path is not None:
        return path.read_bytes()
    return resources.files(CONFIG_PACKAGE).joinpath(CONFIG_NAME).read_bytes()


def load_config(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(_config_bytes(path).decode("utf-8"))


def config_hash(path: Path | None = None) -> str:
    """For the manifest, so a report's thresholds can be reproduced later."""
    return hashlib.sha256(_config_bytes(path)).hexdigest()[:16]


def analysis_columns(spec: Spec, data: pd.DataFrame) -> list[str]:
    """The columns this analysis will touch, in spec order and without repeats.

    Resolved by membership in the data rather than by trusting the spec, because a field can
    hold a value that is not a column. A spec naming a column that does not exist is the
    family's error to raise, with a message that can name the field.
    """
    found: list[str] = []
    for name in COLUMN_FIELDS:
        field = spec.fields.get(name)
        if field is None or field.value is None:
            continue
        candidates = field.value if isinstance(field.value, (list, tuple)) else [field.value]
        for candidate in candidates:
            column = str(candidate)
            if column in data.columns and column not in found:
                found.append(column)
    return found


def _threshold(config: dict[str, Any], check_id: str, key: str, default: float) -> float:
    """One threshold from the config, with the code's default as a fallback.

    The default exists so a check still runs against a config written before it, and the
    config is the authority whenever it has an opinion.
    """
    return float(config.get(check_id, {}).get(key, default))


def _issue(
    config: dict[str, Any],
    check_id: str,
    passed: bool,
    summary: str,
    evidence: dict[str, float | int | str | bool],
    columns: list[str] | None = None,
    impact: str = "",
    repair: str = "",
    severity: Severity | None = None,
    suggested_operation: dict[str, Any] | None = None,
) -> QualityIssue:
    """Build one issue, honouring the invariant that a passing check is downgraded to INFO.

    ``severity`` overrides the declared one, for a check whose sub-cases differ in how serious
    they are. It is still read from the config by the caller rather than hard-coded, so where
    the line falls stays outside the code.
    """
    entry = config.get(check_id, {})
    declared = severity or Severity(entry.get("severity", "warning"))
    return QualityIssue(
        check_id=check_id,
        layer=Layer(entry.get("layer", "basic")),
        severity=Severity.INFO if passed else declared,
        waivable=bool(entry.get("waivable", True)),
        summary=summary,
        evidence={**evidence, "passed": passed},
        affected_columns=columns or [],
        impact_on_analysis=impact,
        recommended_repair=repair,
        suggested_operation=suggested_operation,
    )


def check_basic(data: pd.DataFrame, spec: Spec, config_path: Path | None = None) -> QualityReport:
    """Every basic-layer check, over the columns this analysis uses."""
    config = load_config(config_path)
    columns = analysis_columns(spec, data)
    issues = [
        _duplicate_rows(data, spec, config),
        _column_types(data, columns, config),
        _missing_values(data, columns, config, spec),
        _null_encoding(data, columns, config),
        _zero_spike(data, columns, config),
        _isolated_extremes(data, columns, config),
        _impossible_sign(data, columns, config),
        _constant_columns(data, columns, config),
    ]
    return QualityReport(issues=issues)


# ---- the row key ----


def _duplicate_rows(data: pd.DataFrame, spec: Spec, config: dict[str, Any]) -> QualityIssue:
    """One row per unit, or per unit and period when the data is a panel."""
    key: list[str] = []
    for name in ("unit_id", "period_index"):
        field = spec.fields.get(name)
        if field is not None and field.value is not None and str(field.value) in data.columns:
            key.append(str(field.value))
    if not key:
        return _issue(
            config,
            "basic_duplicate_rows",
            passed=True,
            summary="no unit column is declared, so there is no row key to check",
            evidence={"key": "(none)"},
        )
    duplicated = int(data.duplicated(subset=key).sum())
    affected = (
        int(data.loc[data.duplicated(subset=key, keep=False), key[0]].nunique())
        if duplicated
        else 0
    )
    return _issue(
        config,
        "basic_duplicate_rows",
        passed=duplicated == 0,
        summary=(
            f"one row per {' and '.join(key)}"
            if duplicated == 0
            else f"{duplicated:,} rows repeat the key ({', '.join(key)}), across {affected:,} units"
        ),
        evidence={
            "key": ", ".join(key),
            "n_duplicate_rows": duplicated,
            "n_units_affected": affected,
        },
        columns=key,
        impact=(
            "A unit appearing twice is counted twice, which reweights the sample towards "
            "whoever was duplicated. Nothing downstream can tell that from a real second "
            "patient."
        ),
        repair=(
            "Decide what one row means and aggregate to it before the analysis. If the "
            "duplicates are an artefact of a join, fix the join rather than dropping rows at "
            "random: which copy survives changes the answer."
        ),
    )


# ---- types and missingness ----


def _column_types(data: pd.DataFrame, columns: list[str], config: dict[str, Any]) -> QualityIssue:
    """Every column the estimation uses has to be numeric."""
    import pandas as pd

    offenders: dict[str, str] = {}
    for column in columns:
        if not pd.api.types.is_numeric_dtype(data[column]):
            offenders[column] = str(data[column].dtype)
    passed = not offenders
    return _issue(
        config,
        "basic_column_types",
        passed=passed,
        summary=(
            f"all {len(columns)} analysis columns are numeric"
            if passed
            else "not numeric: "
            + ", ".join(f"{name} ({dtype})" for name, dtype in sorted(offenders.items()))
        ),
        evidence={
            "n_columns_checked": len(columns),
            "n_not_numeric": len(offenders),
            **{f"{name}_dtype": dtype for name, dtype in offenders.items()},
        },
        columns=sorted(offenders),
        impact=(
            "A column of numbers with one piece of text in it reads as text, and then every "
            "value in it is text. Arithmetic on it either fails or, worse, compares strings."
        ),
        repair=(
            "Find what is not a number in that column. It is usually a placeholder for "
            "missing, such as NA or a full stop, in which case it should be empty rather "
            "than spelled."
        ),
    )


def _final_period_mask(data: pd.DataFrame, spec: Spec) -> np.ndarray | None:
    """Which rows are a unit's last period, when the data is a panel.

    Used only to explain a pattern. Missing values sitting exclusively on final periods have
    their own cause, the outcome's measurement window running past the end of data
    collection, and their own fix, which is to record one period fewer per unit rather than to
    leave the last one blank. That hint is worth keeping in the report rather than only in an
    exception, and the spec says which column the period is.
    """
    key = []
    for name in ("unit_id", "period_index"):
        field = spec.fields.get(name)
        if field is None or field.value is None or str(field.value) not in data.columns:
            return None
        key.append(str(field.value))
    unit, period = key
    last = data.groupby(unit)[period].transform("max")
    return np.asarray(last == data[period], dtype=bool)


def _missing_values(
    data: pd.DataFrame, columns: list[str], config: dict[str, Any], spec: Spec
) -> QualityIssue:
    counts = {
        column: int(np.asarray(data[column].isna(), dtype=bool).sum())
        for column in columns
        if bool(np.asarray(data[column].isna(), dtype=bool).any())
    }
    total = sum(counts.values())
    passed = total == 0

    final_only = False
    if counts:
        is_final = _final_period_mask(data, spec)
        if is_final is not None:
            final_only = all(
                bool((missing == (missing & is_final)).all())
                for missing in (np.asarray(data[column].isna(), dtype=bool) for column in counts)
            )
    extra = (
        " Missing only on final periods usually means the outcome's measurement window runs "
        "past the end of data collection: record one period fewer per unit rather than "
        "leaving the last one blank."
        if final_only
        else ""
    )
    # A filter is offered only for a single affected column, and only when the missingness is
    # not the final-period artefact. Dropping on four columns at once compounds an exclusion
    # the user has not seen the size of yet, and each column deserves its own decision, so
    # several affected columns carry no suggestion and the prose says to take them one at a
    # time. The drop is a population decision rather than a preprocessing step: it changes who
    # the answer is about, so it belongs in the ledger.
    suggestion: dict[str, Any] | None = None
    if len(counts) == 1 and not passed and not final_only:
        suggestion = {
            "kind": "population_filter",
            "column": next(iter(counts)),
            "op": "not_missing",
        }

    return _issue(
        config,
        "basic_missing_values",
        passed=passed,
        summary=(
            "no missing values in the columns the estimation uses"
            if passed
            else f"{total:,} missing values"
            + (", all on final periods," if final_only else "")
            + " in "
            + ", ".join(f"{name} ({count:,})" for name, count in sorted(counts.items()))
        ),
        evidence={
            "n_missing": total,
            "n_columns_affected": len(counts),
            "all_on_final_periods": final_only,
            **{f"{name}_missing": count for name, count in counts.items()},
        },
        columns=sorted(counts),
        impact=(
            "The treatment, the outcome and the covariates of a row are the row. A missing "
            "one cannot be filled in without guessing at the quantity being estimated, and "
            "left alone it surfaces from inside a nuisance regression as a bare complaint "
            "about NaN."
        ),
        repair=(
            "Fix the extraction where you can. Where you cannot, there are two ways forward "
            "and they differ in what they cost: exclude those units, which keeps the column "
            "and changes who the answer is about, or leave the column out of the covariate "
            "set, which keeps the units. The exclusion is counted in the report's ledger and "
            "checked for whether the excluded differ from the kept."
            + (
                " Several columns are affected, so no single exclusion is offered: decide "
                "them one at a time, because each one compounds the last."
                if len(counts) > 1
                else ""
            )
            + extra
        ),
        suggested_operation=suggestion,
    )


# ---- the one that earns this module ----


def _null_encoding(data: pd.DataFrame, columns: list[str], config: dict[str, Any]) -> QualityIssue:
    """Placeholders that arrive as values: out-of-band numbers, and text meaning "missing".

    These are the dangerous ones precisely because nothing fails. A sentinel is a number, so
    it averages, it fits, it predicts. The report's other checks will all pass and the answer
    will be about an export convention.
    """
    import pandas as pd

    entry = config.get("basic_null_encoding", {})
    sentinels = [float(value) for value in entry.get("numeric_sentinels", [])]
    minimum = int(entry.get("min_occurrences", 3))
    string_nulls = {str(value).strip().lower() for value in entry.get("string_nulls", [])}

    evidence: dict[str, float | int | str | bool] = {
        "min_occurrences": minimum,
        "n_sentinels_searched": len(sentinels),
    }
    findings: list[str] = []
    affected: list[str] = []
    # Column -> the placeholder values found in it, so a suggested step can name them exactly
    # rather than the agent re-deriving them from the prose.
    per_column: dict[str, list[object]] = {}
    for column in columns:
        series = data[column]
        if pd.api.types.is_numeric_dtype(series):
            values = series.to_numpy(dtype=float)
            for sentinel in sentinels:
                count = int(np.sum(values == sentinel))
                if count >= minimum:
                    share = count / len(values) if len(values) else 0.0
                    findings.append(f"{column} holds {sentinel:g} {count:,} times ({share:.1%})")
                    evidence[f"{column}_sentinel"] = sentinel
                    evidence[f"{column}_sentinel_count"] = count
                    affected.append(column)
                    per_column.setdefault(column, []).append(sentinel)
        else:
            texts = {
                str(value).strip().lower()
                for value in series.dropna().unique()
                if not isinstance(value, (int, float, np.integer, np.floating))
            }
            spelled = sorted(texts & string_nulls)
            if spelled:
                findings.append(f"{column} contains the text {', '.join(repr(s) for s in spelled)}")
                evidence[f"{column}_string_nulls"] = ", ".join(spelled)
                affected.append(column)
                per_column.setdefault(column, []).extend(spelled)
    passed = not findings
    # One step per column would be the honest shape, but a check emits one issue, so the
    # suggestion names the column with the most occurrences and the agent asks about the rest.
    suggestion: dict[str, Any] | None = None
    if per_column:
        column = max(per_column, key=lambda name: len(per_column[name]))
        suggestion = {
            "kind": "preprocessing",
            "op": "recode_null",
            "column": column,
            "values": sorted(per_column[column], key=str),
        }
    return _issue(
        config,
        "basic_null_encoding",
        passed=passed,
        summary=(
            "no placeholder values found in the analysis columns" if passed else "; ".join(findings)
        ),
        evidence=evidence,
        columns=sorted(set(affected)),
        impact=(
            "A placeholder that is a number does not fail anywhere. It averages, it fits and "
            "it predicts, so every check downstream passes and the answer becomes a statement "
            "about an export convention: a creatinine of -999 teaches the model that patients "
            "with impossibly low creatinine are never treated."
        ),
        repair=(
            "Replace the placeholder with an empty value at the source, then decide what to do "
            "about the missingness, which is a different question with a different answer. If "
            "the value is real in your data, say so and waive this check. The suggested step "
            "does the replacement on the working copy, which reveals the missingness rather "
            "than repairing it: the missing-value check will then report what the placeholder "
            "was hiding."
        ),
        suggested_operation=suggestion,
    )


def _zero_spike(data: pd.DataFrame, columns: list[str], config: dict[str, Any]) -> QualityIssue:
    """Exact zeros with nothing just above them.

    The test is a gap, not a distance. Measuring how far the column's bulk starts from zero
    cannot separate an export artefact from a real pile of zeros, because a column with many
    genuine zeros also has its bulk away from zero: on the same data that statistic gives
    0.28 for creatinine with 10% of values zeroed and 0.27 for a urine output whose zeros are
    real. What distinguishes them is whether anything sits just above zero. Creatinine resumes
    at 30 with nothing below it; urine output has values at 1 and 2 ml.
    """
    import pandas as pd

    entry = config.get("basic_zero_spike", {})
    min_share = float(entry.get("min_zero_share", 0.01))
    min_gap = float(entry.get("min_gap_to_iqr", 0.05))
    evidence: dict[str, float | int | str | bool] = {
        "min_zero_share": min_share,
        "min_gap_to_iqr": min_gap,
    }
    findings: list[str] = []
    for column in columns:
        series = data[column]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        values = series.to_numpy(dtype=float)
        values = values[~np.isnan(values)]
        if len(values) == 0 or np.any(values < 0):
            # A column with negative values has no meaningful spike at zero: zero is in the
            # middle of its range, not at the edge.
            continue
        zeros = int(np.sum(values == 0.0))
        share = zeros / len(values)
        if share < min_share or zeros == len(values):
            continue
        nonzero = values[values > 0.0]
        spread = float(np.percentile(nonzero, 75) - np.percentile(nonzero, 25))
        if spread <= 0:
            continue
        smallest = float(nonzero.min())
        gap = smallest / spread
        if gap >= min_gap:
            findings.append(
                f"{column} is exactly zero in {share:.1%} of rows, and its next smallest "
                f"value is {smallest:.3g}, with nothing in between"
            )
            evidence[f"{column}_zero_share"] = round(share, 4)
            evidence[f"{column}_smallest_nonzero"] = round(smallest, 4)
            evidence[f"{column}_gap_to_iqr"] = round(gap, 3)
    passed = not findings
    return _issue(
        config,
        "basic_zero_spike",
        passed=passed,
        summary=(
            "no column has a pile of zeros separated from its real values"
            if passed
            else "; ".join(findings)
        ),
        evidence=evidence,
        columns=sorted(
            name.removesuffix("_zero_share") for name in evidence if name.endswith("_zero_share")
        ),
        impact=(
            "If those zeros are unmeasured values rather than measurements, they pull the "
            "column's mean towards zero and give the model a group that looks extreme and is "
            "simply absent."
        ),
        repair=(
            "Whether a zero is possible here is clinical knowledge, so this is a question "
            "rather than a defect: ask whether zero means zero in that column. If it means "
            "not measured, make it empty at the source."
        ),
    )


def _isolated_extremes(
    data: pd.DataFrame, columns: list[str], config: dict[str, Any]
) -> QualityIssue:
    """A value separated from the rest of its column by a gap.

    The gap is the statistic, not the distance. A plain z-score rule is useless here: on this
    project's ICU data the largest |z| per column runs from 2.9 to 4.2, so a rule at 3 or 4
    fires on nearly every column and gets ignored. Lab values are right-skewed and a long tail
    is a long tail. What a transcription error produces is an isolated point: clean columns
    have top gaps of 0.007 to 0.31 interquartile ranges, one creatinine multiplied by ten gives
    1.47, three potassiums in the wrong units give 2145.

    A warning and never blocking. In an ICU a creatinine of 900 is real and matters, and a
    check that encouraged deleting it would do more harm than the value does.
    """
    import pandas as pd

    minimum = _threshold(config, "basic_isolated_extremes", "min_gap_to_iqr", 1.0)
    # A sentinel is an isolated extreme, so without this the same -999 is reported twice: once
    # as a placeholder, with the right repair, and once as an outlier, with the wrong one.
    sentinels = {
        float(value) for value in config.get("basic_null_encoding", {}).get("numeric_sentinels", [])
    }
    evidence: dict[str, float | int | str | bool] = {"min_gap_to_iqr": minimum}
    findings: list[str] = []
    affected: list[str] = []
    for column in columns:
        series = data[column]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        values = np.asarray(series.dropna(), dtype=float)
        unique = np.unique(values)
        if len(unique) < 4:
            continue
        spread = float(np.percentile(values, 75) - np.percentile(values, 25))
        if spread <= 0:
            continue
        for end, gap, value in (
            ("highest", (unique[-1] - unique[-2]) / spread, unique[-1]),
            ("lowest", (unique[1] - unique[0]) / spread, unique[0]),
        ):
            if gap < minimum or float(value) in sentinels:
                continue
            count = int(np.sum(values == value))
            findings.append(
                f"{column}: the {end} value is {value:.6g}, {gap:.1f} interquartile ranges "
                f"away from the next one ({count:,} rows)"
            )
            evidence[f"{column}_{end}_gap_to_iqr"] = round(gap, 3)
            evidence[f"{column}_{end}_value"] = round(float(value), 6)
            affected.append(column)
    passed = not findings
    return _issue(
        config,
        "basic_isolated_extremes",
        passed=passed,
        summary=(
            "no column has a value standing apart from the rest of its distribution"
            if passed
            else "; ".join(findings)
        ),
        evidence=evidence,
        columns=sorted(set(affected)),
        impact=(
            "If the value is a transcription error it is being treated as a measurement. If it "
            "is real, it will dominate the propensity model and can put that patient in a "
            "region with no comparable controls, which the overlap check sees but cannot "
            "explain."
        ),
        repair=(
            "Look at the row. A decimal in the wrong place and a column entered in different "
            "units both look like this, and both are fixed at the source. If the value is "
            "real, keep it: say so in the report and read the overlap check with it in mind. "
            "Do not delete it to make the check pass."
        ),
    )


def _impossible_sign(
    data: pd.DataFrame, columns: list[str], config: dict[str, Any]
) -> QualityIssue:
    """A handful of values with the opposite sign to everything else in the column.

    A negative creatinine, a negative length of stay. The rule requires the column to be
    nearly all one sign, so a genuinely signed quantity is left alone: the fluid-balance
    column in this project's data is 61% negative and 39% positive and never fires.
    """
    import pandas as pd

    dominant_share = _threshold(config, "basic_impossible_sign", "min_dominant_share", 0.99)
    evidence: dict[str, float | int | str | bool] = {"min_dominant_share": dominant_share}
    findings: list[str] = []
    affected: list[str] = []
    for column in columns:
        series = data[column]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        values = np.asarray(series.dropna(), dtype=float)
        signed = values[values != 0.0]
        if len(signed) == 0:
            continue
        positive = float(np.mean(signed > 0))
        for share, odd_sign, label in ((positive, -1, "negative"), (1 - positive, 1, "positive")):
            if share < dominant_share or share >= 1.0:
                continue
            odd = signed[np.sign(signed) == odd_sign]
            findings.append(
                f"{column} is {share:.1%} {'positive' if odd_sign < 0 else 'negative'} but "
                f"{label} in {len(odd):,} rows (down to {odd.min():.6g})"
                if odd_sign < 0
                else f"{column} is {share:.1%} negative but positive in {len(odd):,} rows "
                f"(up to {odd.max():.6g})"
            )
            evidence[f"{column}_odd_sign_rows"] = len(odd)
            evidence[f"{column}_dominant_share"] = round(share, 4)
            affected.append(column)
    passed = not findings
    return _issue(
        config,
        "basic_impossible_sign",
        passed=passed,
        summary=(
            "no column mixes a dominant sign with a handful of the opposite"
            if passed
            else "; ".join(findings)
        ),
        evidence=evidence,
        columns=sorted(set(affected)),
        impact=(
            "A quantity that cannot be negative and is negative in a few rows is wrong in "
            "those rows, and nothing downstream will notice: the value is a number, so it "
            "averages and it fits."
        ),
        repair=(
            "Usually a subtraction in the wrong order, or a placeholder that is not on the "
            "sentinel list. Fix it at the source. If the sign is real for that column, say so "
            "and waive this check."
        ),
    )


def _constant_columns(
    data: pd.DataFrame, columns: list[str], config: dict[str, Any]
) -> QualityIssue:
    constant = sorted(
        column for column in columns if len(np.asarray(data[column].dropna().unique())) <= 1
    )
    passed = not constant
    return _issue(
        config,
        "basic_constant_column",
        passed=passed,
        summary=(
            "every analysis column varies" if passed else f"one value only in {', '.join(constant)}"
        ),
        evidence={"n_constant": len(constant), "columns": ", ".join(constant) or "(none)"},
        columns=constant,
        impact=(
            "A column with one value carries no information about anything. It cannot confound "
            "and it cannot modify an effect, and some learners divide by its zero variance."
        ),
        repair=(
            "Drop it from the covariate set. If it was expected to vary, the extraction "
            "probably filtered on it."
        ),
    )

"""Dataset C: dataset A with one problem injected, each mapped to the check that should catch it.

Mirrors design.md section 15 and plan.md Phase 1 task 6. Dataset A is a world where the
answer is known; this is a world where the *defect* is known, which tests a different thing.
A check suite that nobody measures drifts into a suite that reports reassuring things about
data it does not understand.

Each injector states which `check_id` should fire and at what severity, so the mapping is
data rather than prose, and `tests/test_dataset_c.py` asserts it. Two failures are then
visible and distinguishable:

- a defect that no check catches, which is a hole in the suite
- a defect that fires the *wrong* check, which is worse, because the report would send the
  user to repair something that is not broken

**Nothing here is a random perturbation.** Every injector reproduces a mistake that happens
to real extracts: a sentinel for "not measured", a join that duplicates rows, a cohort
anchored on its own exposure. The point is not to break the data, it is to break it the way
it actually breaks.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from dataset_a import config_for, generate


@dataclass(frozen=True)
class Defect:
    """One injected problem, and what the check suite is expected to say about it."""

    id: str
    description: str
    # What goes wrong in the real world, which is the reason this defect is in the set.
    provenance: str
    inject: Callable[[pd.DataFrame, np.random.Generator], pd.DataFrame]
    expect_check: str
    expect_severity: str = "blocking"
    # Columns the spec must declare for the check to have anything to read. The temporal
    # checks are skipped unless the time fields are in the spec, which is itself a property
    # worth testing, so each defect says what it needs.
    needs_timestamps: bool = False


def _sentinel_creatinine(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    out = data.copy()
    rows = rng.choice(len(out), size=max(int(0.1 * len(out)), 3), replace=False)
    out.loc[out.index[rows], "max_creatinine"] = -999.0
    return out


def _text_null_potassium(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    out = data.copy()
    out["max_potassium"] = out["max_potassium"].astype(object)
    rows = rng.choice(len(out), size=max(int(0.02 * len(out)), 3), replace=False)
    out.loc[out.index[rows], "max_potassium"] = "NA"
    return out


def _zeroed_on_export(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    out = data.copy()
    rows = rng.choice(len(out), size=max(int(0.08 * len(out)), 3), replace=False)
    out.loc[out.index[rows], "max_creatinine"] = 0.0
    return out


def _missing_urea(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    out = data.copy()
    rows = rng.choice(len(out), size=max(int(0.01 * len(out)), 3), replace=False)
    out.loc[out.index[rows], "max_urea"] = np.nan
    return out


def _duplicated_join(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = rng.choice(len(data), size=max(int(0.05 * len(data)), 3), replace=False)
    return pd.concat([data, data.iloc[rows]], ignore_index=True)


def _constant_covariate(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    del rng
    out = data.copy()
    out["max_potassium"] = 4.2
    return out


def _immortal_time(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Anchor time zero on the treatment rather than on admission.

    The mistake that produces immortal time: the cohort is "patients dialysed in the first
    24 hours", and someone sets time zero to the dialysis start, so membership requires
    surviving to it. Here it shows up as treatment dated before time zero for the untreated,
    whose anchor stays at admission.
    """
    del rng
    out = data.copy()
    treated = out["isDialysisICU"].to_numpy() == 1
    anchor = out["admission_time"].to_numpy(dtype=float).copy()
    started = out["rrt_start_time"].to_numpy(dtype=float)
    anchor[treated] = started[treated]
    out["admission_time"] = anchor
    # And the treated now have a treatment time one minute before their own anchor, which is
    # how the error surfaces when the two columns are built by different queries.
    out.loc[treated, "rrt_start_time"] = anchor[treated] - 1 / 60
    return out


def _outcome_before_treatment(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """A join on the wrong key: some events are dated from a previous admission."""
    out = data.copy()
    treated_with_event = np.flatnonzero(
        (out["isDialysisICU"].to_numpy() == 1) & (out["death"].to_numpy() == 1)
    )
    if len(treated_with_event) == 0:
        return out
    chosen = rng.choice(
        treated_with_event, size=max(len(treated_with_event) // 2, 1), replace=False
    )
    out.loc[out.index[chosen], "death_time"] = (
        out.loc[out.index[chosen], "rrt_start_time"].to_numpy(dtype=float) - 48.0
    )
    return out


def _inverted_followup(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """A default date on rows the extraction could not resolve: the epoch, before everything."""
    out = data.copy()
    rows = rng.choice(len(out), size=max(int(0.03 * len(out)), 3), replace=False)
    out.loc[out.index[rows], "followup_end_time"] = 0.0
    return out


def _short_followup(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """The extraction stops at a fixed date, so late admissions have a truncated window.

    Their outcome is unknown, not negative, and counting the close as survival biases the
    event rate down for whoever was admitted last.
    """
    del rng
    out = data.copy()
    admission = out["admission_time"].to_numpy(dtype=float)
    cutoff = float(np.percentile(admission, 90)) + 24.0
    end = out["followup_end_time"].to_numpy(dtype=float)
    no_event = np.isnan(out["death_time"].to_numpy(dtype=float))
    # Never before admission: a follow-up that ends before it starts is a different defect,
    # and an injector that produces two defects cannot test which check caught which.
    truncated = np.maximum(np.minimum(end, cutoff), admission)
    out["followup_end_time"] = np.where(no_event, truncated, end)
    return out


def _tiny_treated_arm(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """A population filter narrower than the question needed, which is how it usually happens.

    Someone restricts to a subgroup to make the comparison cleaner and leaves five treated
    patients. The estimator will still return a per-patient effect for all of them.
    """
    del rng
    treated = np.flatnonzero(np.asarray(data["isDialysisICU"], dtype=float) == 1.0)
    control = np.flatnonzero(np.asarray(data["isDialysisICU"], dtype=float) == 0.0)
    keep = np.concatenate([treated[:5], control])
    return data.iloc[np.sort(keep)].reset_index(drop=True)


DEFECTS: tuple[Defect, ...] = (
    Defect(
        id="sentinel_creatinine",
        description="creatinine is -999 for a tenth of patients",
        provenance="a lab extract where -999 means the test was not ordered",
        inject=_sentinel_creatinine,
        expect_check="basic_null_encoding",
    ),
    Defect(
        id="text_null_potassium",
        description="potassium holds the text NA for a few patients",
        provenance="a spreadsheet export that spells missing instead of leaving it empty",
        inject=_text_null_potassium,
        expect_check="basic_column_types",
    ),
    Defect(
        id="zeroed_on_export",
        description="creatinine is exactly zero for 8% of patients",
        provenance="an empty field becoming zero on export, which a numeric column accepts",
        inject=_zeroed_on_export,
        expect_check="basic_zero_spike",
        expect_severity="warning",
    ),
    Defect(
        id="missing_urea",
        description="urea is absent for 1% of patients",
        provenance="a lab that was genuinely not drawn",
        inject=_missing_urea,
        expect_check="basic_missing_values",
    ),
    Defect(
        id="duplicated_join",
        description="5% of patients appear twice",
        provenance="a join against a table with more than one row per patient",
        inject=_duplicated_join,
        expect_check="basic_duplicate_rows",
    ),
    Defect(
        id="constant_covariate",
        description="potassium is the same value for everyone",
        provenance="a covariate list built by a script, filtered upstream without anyone noticing",
        inject=_constant_covariate,
        expect_check="basic_constant_column",
        expect_severity="warning",
    ),
    Defect(
        id="tiny_treated_arm",
        description="a population filter leaves five treated patients",
        provenance="restricting to a subgroup to make the comparison cleaner, and not looking"
        " at what is left in the smaller arm",
        inject=_tiny_treated_arm,
        expect_check="feasibility_arm_sizes",
    ),
    Defect(
        id="immortal_time",
        description="time zero is anchored on the treatment instead of on admission",
        provenance="the classic: a cohort defined as treated within a window, anchored on the"
        " treatment, so joining it requires surviving to it",
        inject=_immortal_time,
        expect_check="temporal_treatment_before_time_zero",
        needs_timestamps=True,
    ),
    Defect(
        id="outcome_before_treatment",
        description="half the treated patients who died have the death dated before the treatment",
        provenance="a join on the wrong key, pulling an event from a previous admission",
        inject=_outcome_before_treatment,
        expect_check="temporal_outcome_before_treatment",
        needs_timestamps=True,
    ),
    Defect(
        id="inverted_followup",
        description="3% of patients have follow-up ending before admission",
        provenance="a default date on rows the extraction could not resolve",
        inject=_inverted_followup,
        expect_check="temporal_inversion",
        needs_timestamps=True,
    ),
    Defect(
        id="short_followup",
        description="late admissions are followed for less than the outcome window",
        provenance="an extraction with a fixed end date, so the last admissions are truncated",
        inject=_short_followup,
        expect_check="temporal_insufficient_followup",
        needs_timestamps=True,
    ),
)

BY_ID = {defect.id: defect for defect in DEFECTS}


def clean_frame(n: int = 2000, seed: int = 11, timestamps: bool = True) -> pd.DataFrame:
    """The table every defect is injected into: dataset A, optionally with its time columns.

    The high_power preset rather than the realistic one, and the reason is the feasibility
    layer. At the realistic scale, 10% treated and a 3.8% event rate, a 2,000-row table has
    about six events in the treated arm, so the clean table itself would block on event
    counts. That is a true finding about that scale and a useless baseline: if the clean table
    does not pass, no defect's effect can be attributed to the defect.

    So this is deliberately not realistic. Dataset C exists to exercise the checks; the
    realistic scale is what the demos and the manual workflow test use, where the thin-events
    warning is part of what a user should see.
    """
    return generate(config_for("high_power", n=n, seed=seed, emit_timestamps=timestamps))


def inject(defect_id: str, data: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    if defect_id not in BY_ID:
        raise ValueError(f"unknown defect {defect_id!r}; available: {', '.join(sorted(BY_ID))}")
    return BY_ID[defect_id].inject(data, np.random.default_rng(seed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write dataset C: one file per injected defect, plus the clean table."
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="output directory (never committed)"
    )
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    clean = clean_frame(n=args.n, seed=args.seed)
    clean.to_csv(args.out / "clean.csv", index=False)
    print(f"wrote clean.csv: {len(clean):,} rows")
    for defect in DEFECTS:
        frame = defect.inject(clean, np.random.default_rng(args.seed))
        frame.to_csv(args.out / f"{defect.id}.csv", index=False)
        print(
            f"wrote {defect.id}.csv: {len(frame):,} rows, "
            f"expect {defect.expect_check} ({defect.expect_severity})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

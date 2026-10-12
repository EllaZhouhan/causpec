#!/usr/bin/env python3
"""Build the files `evals/manual-workflow-test.md` uses, from the two generators.

The test needs six files. Three come straight from a generator; three are derived, each one
carrying a defect the workflow is supposed to catch, and those three are what this script
exists for. They were built by hand once and the recipe lived in a session, which means the
three scenarios that use them stopped being runnable the moment the files were deleted, and
they are gitignored like all generated data.

**The truth columns are stripped from every file.** A session under test that can read
`tau_true` is not being tested on anything, and the generators emit those columns by design
because the numerical evals check estimates against them. The answer key goes in a separate
file that stays out of the repository.

The three derived files:

- `panel_truncated.csv`: the cohort trap. Keeps only the patients who lasted eight buckets,
  and only those buckets, so the population is conditioned on surviving. No analysis of it
  recovers the profile, and the right outcome is a refusal rather than a number.
- `panel_gap.csv`: a bucket index with holes, so the lag structure cannot be trusted. Lags
  are counted in periods, and a missing period silently makes lag 2 mean three periods for
  some patients.
- `wide_ever_treated.csv`: one row per patient with an `rrt_started` flag meaning "ever on
  dialysis". A flattened time-varying treatment, which has no valid cross-sectional analysis:
  anyone who was ever treated is counted as treated from the start.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# What a session under test must never see. Matched by substring, because a generator may add
# a column later and the default has to be to withhold it.
TRUTH_MARKERS = ("_true", "tau", "complier", "beta_")

# How many buckets a patient must have lasted to enter the truncated cohort. Eight is long
# enough that the survivors are visibly selected and short enough to leave a usable number.
TRUNCATION_LENGTH = 8


def strip_truth(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop every column that reveals the answer."""
    keep = [
        name
        for name in frame.columns
        if not any(marker in str(name).lower() for marker in TRUTH_MARKERS)
    ]
    # Any because pandas types a list-of-labels selection as a union that includes a Series;
    # what comes back from a list is a frame, and asserting otherwise would be the lie.
    selected: Any = frame[keep]
    return selected


def truncated_cohort(panel: pd.DataFrame) -> pd.DataFrame:
    """Scenario 6: the patients who lasted, and only the buckets they shared.

    This is the trap the paper's simulation is about. Selecting the units that survived to a
    fixed length and then analysing those periods conditions the population on the outcome of
    the treatment, so the lag profile it produces is wrong in a direction nothing in the
    numbers reveals.
    """
    lengths: Any = panel.groupby("patient_id")["bucket"].max()
    survivors = lengths[lengths >= TRUNCATION_LENGTH - 1].index
    cohort: Any = panel[panel["patient_id"].isin(survivors)]
    cohort = cohort[cohort["bucket"] < TRUNCATION_LENGTH]
    # The exit column would give the selection away, and a real truncated extract does not
    # carry one: whoever truncated it kept the rows they wanted and dropped the rest.
    return cohort.drop(columns=["exit_reason"], errors="ignore")


def gapped_index(panel: pd.DataFrame, seed: int = 5) -> pd.DataFrame:
    """Scenario 7: holes in the bucket index.

    One bucket removed from a third of the patients, chosen at random, with the remaining
    buckets left at their original numbers. The index therefore skips, which is what the check
    looks for; renumbering them would hide it and produce a different defect.
    """
    rng = np.random.default_rng(seed)
    patients = np.asarray(panel["patient_id"].unique())
    chosen = rng.choice(patients, size=len(patients) // 3, replace=False)
    drop_index: list[int] = []
    for patient in chosen:
        rows = panel.index[panel["patient_id"] == patient]
        if len(rows) < 4:
            continue
        # Never the first or last bucket: a missing end looks like a shorter stay, which is
        # not a gap and is not what this file is for.
        drop_index.append(int(rng.choice(rows[1:-1])))
    return panel.drop(index=drop_index)


def ever_treated(panel: pd.DataFrame) -> pd.DataFrame:
    """Scenario 3: the panel flattened to one row per patient.

    Baseline covariates from the first bucket, an ever-treated flag, and the length of stay.
    This is what an extract looks like when someone has already aggregated a time-varying
    treatment, and the shape gives no sign of it: the columns look like an ordinary
    cross-sectional table.
    """
    first: Any = panel.sort_values(["patient_id", "bucket"]).groupby("patient_id").first()
    flags: Any = panel.groupby("patient_id")["on_rrt"].max()
    counts: Any = panel.groupby("patient_id")["bucket"].count()
    wide = pd.DataFrame(
        {
            "max_creatinine": first["max_creatinine"],
            "max_potassium": first["max_potassium"],
            "max_urea": first["max_urea"],
            "max_lactate": first["max_lactate"],
            "min_ArterialPressure": first["min_ArterialPressure"],
            "min_urine_output": first["min_urine_output"],
            # Named for the window it came from, because that is the one honest thing about
            # this file and the workflow should be able to ask about it.
            "instability_first_12h": first["instability_score"],
            "rrt_started": flags,
            "icu_buckets": counts,
        }
    )
    return wide.reset_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE.parent / "testdata")
    args = parser.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    from dataset_a import config_for, generate
    from dataset_a_panel import PanelConfig
    from dataset_a_panel import generate as generate_panel

    cross = strip_truth(generate(config_for("realistic", n=4000, seed=7)))
    cross.to_csv(out / "cross_sectional.csv", index=False)

    good = strip_truth(generate_panel(PanelConfig(n_units=5000, seed=31)))
    good.to_csv(out / "panel_good.csv", index=False)

    small = strip_truth(generate_panel(PanelConfig(n_units=900, seed=12)))
    small.to_csv(out / "panel_small.csv", index=False)

    truncated_cohort(good).to_csv(out / "panel_truncated.csv", index=False)
    gapped_index(good).to_csv(out / "panel_gap.csv", index=False)
    ever_treated(good).to_csv(out / "wide_ever_treated.csv", index=False)

    for path in sorted(out.glob("*.csv")):
        frame = pd.read_csv(path, nrows=1)
        leaked = [c for c in frame.columns if any(m in str(c).lower() for m in TRUTH_MARKERS)]
        assert not leaked, f"{path.name} still carries {leaked}"
        print(f"{path.name:28} {sum(1 for _ in path.open()) - 1:>7,} rows")
    print("\nThe answer key is not written here. See evals/manual-workflow-test.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

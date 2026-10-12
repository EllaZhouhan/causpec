"""The derived snapshot, and finding the earlier runs on the same data.

Mirrors design.md 6.5. Two things that only make sense together.

**The snapshot.** Preprocessing and the population filters now change the analysed table
materially: a sentinel becomes missing, two hundred patients leave. Without a snapshot the
table every number came from exists only in memory for the length of one process, so a report
can be checked against the spec but never against the data it describes. The snapshot is that
table, written once, after the steps and the filters and before the checks.

Written as gzipped CSV rather than parquet, which is where this departs from design.md 6.5's
default implementation. Parquet needs pyarrow, a forty-megabyte wheel, for one artefact, and
the thing it would buy, dtype preservation across the round trip, is exactly what the
fingerprint normalises away: an integer stored as a float is the same content. CSV is also
readable by a person looking for one patient, which a parquet file is not. Switching is a
one-line change if a reader ever needs typed round-trips.

**The earlier runs.** This is what the source fingerprint is for, and it is the one thing
nothing else can do. design.md 7.4 says the primary analysis is locked at confirmation and
anything changed after seeing the results is post hoc. To apply that rule, something has to
tell these two cases apart:

- the same spec on new data, which is a fresh primary analysis and entirely legitimate
- a different spec on the same data, which is a second look at the same numbers

`spec_hash` alone cannot: the spec changed in both. The source fingerprint plus the spec hash
can.

One refinement matters, because without it the warning fires on honest work. A user who hits a
blocking quality issue and adds the preprocessing step that clears it has changed the spec on
the same data, and that is not a second look at anything: the first run produced no estimate.
So only runs that **produced results** count, which the manifest already records, since
`results/results.json` is one of its checksummed artefacts.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

SNAPSHOT_NAME = "snapshot.csv.gz"

# The artefact whose presence means a run reached an estimate rather than stopping at a gate.
RESULTS_ARTIFACT = "results/results.json"


def write_snapshot(directory: Path, data: pd.DataFrame) -> Path:
    """Write the analysed table into a run directory, returning its path.

    `float_format` is the whole point of this function, and it was found by checking rather
    than assumed. Pandas writes floats at sixteen significant digits by default, which is one
    short of a lossless float64 round trip, so a snapshot written that way read back with 32
    of 41 columns differing in their last bit, and its own recorded fingerprint could not be
    recomputed from it. A snapshot whose fingerprint does not verify against the snapshot is
    not a record of anything.

    Rounding the fingerprint instead would be the obvious alternative and it does not work.
    One ulp is about 2e-16 in relative terms and the rounding boundaries at fifteen
    significant digits are spaced 1e-15 apart, so a perturbed value crosses a boundary roughly
    a fifth of the time. Rounding moves the instability rather than removing it, and spreads
    it over every value instead of the few that a reader might notice.
    """
    path = directory / SNAPSHOT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        data.to_csv(handle, index=False, float_format="%.17g")
    return path


def read_snapshot(path: Path) -> pd.DataFrame:
    """Read a snapshot back, for anyone verifying a report against the table it describes.

    `float_precision="round_trip"` is the other half of the lossless write, and it is the half
    that is easy to miss. With seventeen digits in the file, the default CSV parser still
    returned a different float for thirty-two of forty-one columns: its fast path does not
    round correctly, while `float(text)` on the same string does. The exact parser costs a
    little speed and is the difference between a snapshot that verifies and one that does not.
    """
    import pandas as pd

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return pd.read_csv(handle, float_precision="round_trip")


@dataclass(frozen=True)
class PriorRun:
    """One earlier run that reached an estimate on the same source data."""

    run_id: str
    spec_hash: str
    created_at: str

    def describe(self) -> str:
        return f"{self.run_id} (spec {self.spec_hash}, {self.created_at})"


def prior_runs(root: Path, source_fingerprint: str, spec_hash: str) -> list[PriorRun]:
    """Earlier runs on this same data, under a different spec, that produced results.

    A missing or unreadable manifest is skipped rather than raised on: a half-written run
    directory is a thing that happens, and refusing to start because of one would make the
    tool less usable for no gain in honesty.
    """
    if not root.exists():
        return []
    found: list[PriorRun] = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("source_fingerprint") != source_fingerprint:
            continue
        if manifest.get("spec_hash") == spec_hash:
            continue  # the same analysis again, which is a re-run, not a second look
        if RESULTS_ARTIFACT not in (manifest.get("artifacts") or {}):
            continue  # stopped at a gate, so there were no results to react to
        found.append(
            PriorRun(
                run_id=str(manifest.get("run_id", manifest_path.parent.name)),
                spec_hash=str(manifest.get("spec_hash", "")),
                created_at=str(manifest.get("created_at", "")),
            )
        )
    return found

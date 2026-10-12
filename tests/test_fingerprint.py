"""Fingerprinting a table by its content, and the snapshot that content came from.

Mirrors design.md 6.5. The question is "is this the same data?", and it has to be answered the
way a person means it: the same numbers in a different column order are the same data. A hash
of the file's bytes answers a different question and answers it with false alarms, and a
warning that fires on a harmless re-export is one people learn to ignore.

Each test below is a thing that would otherwise give a different hash for the same data, or a
thing that must give a different hash because the data really did change. The last group is
the round trip, which is the property that makes the snapshot a record rather than a file:
its own recorded fingerprint has to be recomputable from it.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from causpec.core.fingerprint import fingerprint, normalised_rows
from causpec.core.runtime.snapshot import read_snapshot, write_snapshot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data" / "generators"))

from dataset_a import config_for, generate  # noqa: E402


@pytest.fixture
def table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pid": [1, 2, 3],
            "creat": [1.5, 2.0, np.nan],
            "arm": ["a", "b", "a"],
        }
    )


@pytest.fixture(scope="module")
def real() -> pd.DataFrame:
    """The project's own generator: 2,000 rows, 41 columns, mostly float64."""
    return generate(config_for("high_power", n=2000, seed=7))


# ---- what must not change the fingerprint ----


def test_column_order_does_not_matter(table) -> None:
    assert fingerprint(table) == fingerprint(table[["arm", "creat", "pid"]])


def test_row_order_does_not_matter(table) -> None:
    assert fingerprint(table) == fingerprint(table.iloc[[2, 0, 1]])


def test_row_order_does_not_matter_with_a_declared_key(table) -> None:
    key = ["pid"]
    assert fingerprint(table, key) == fingerprint(table.iloc[[1, 2, 0]], key)


def test_an_integer_column_read_as_float_is_the_same_data(table) -> None:
    """A parquet int64 and a CSV float64 holding 1, 2, 3 are the same numbers."""
    assert fingerprint(table) == fingerprint(table.assign(pid=table.pid.astype(float)))


def test_negative_zero_is_zero() -> None:
    assert fingerprint(pd.DataFrame({"x": [0.0]})) == fingerprint(pd.DataFrame({"x": [-0.0]}))


def test_booleans_and_zero_one_integers_agree() -> None:
    assert fingerprint(pd.DataFrame({"x": [True, False]})) == fingerprint(
        pd.DataFrame({"x": [1, 0]})
    )


def test_every_flavour_of_missing_agrees() -> None:
    """NaN, None and pd.NA are one fact, so they hash as one token."""
    first = fingerprint(pd.DataFrame({"x": [1.0, np.nan]}))
    second = fingerprint(pd.DataFrame({"x": [1.0, None]}))
    assert first == second


def test_the_index_is_ignored(table) -> None:
    assert fingerprint(table) == fingerprint(table.set_index("pid").reset_index())


def test_a_large_integer_keeps_its_value() -> None:
    """Beyond 2^53 a float64 cannot hold consecutive integers, so an id of that size must not
    be put through one. Hospital numbers reach this size."""
    big = 9007199254740993  # 2^53 + 1, not representable as a float64
    rows = normalised_rows(pd.DataFrame({"mrn": [big]}))
    assert str(big) in rows[-1]


# ---- what must change it ----


def test_a_changed_value_changes_the_fingerprint(table) -> None:
    assert fingerprint(table) != fingerprint(table.assign(creat=[1.5, 2.0001, np.nan]))


def test_a_difference_in_the_last_digit_changes_it() -> None:
    """Exact by design. The cost of this is documented: a table re-serialised by something
    that writes fewer than seventeen digits will not match."""
    first = pd.DataFrame({"x": [0.1234567890123456]})
    second = pd.DataFrame({"x": [0.1234567890123457]})
    assert fingerprint(first) != fingerprint(second)


def test_a_renamed_column_changes_it(table) -> None:
    assert fingerprint(table) != fingerprint(table.rename(columns={"creat": "creatinine"}))


def test_an_extra_row_changes_it(table) -> None:
    extra = pd.concat([table, table.iloc[:1]], ignore_index=True)
    assert fingerprint(table) != fingerprint(extra)


def test_strings_are_not_stripped_or_case_folded() -> None:
    """ "A" and " A" are different values, and a fingerprint that said otherwise would be
    making an editorial decision about the data."""
    assert fingerprint(pd.DataFrame({"x": ["A"]})) != fingerprint(pd.DataFrame({"x": [" A"]}))
    assert fingerprint(pd.DataFrame({"x": ["A"]})) != fingerprint(pd.DataFrame({"x": ["a"]}))


# ---- it is the same whoever asks ----


def test_the_fingerprint_is_stable_across_calls(real) -> None:
    assert fingerprint(real, ["unit_id"]) == fingerprint(real, ["unit_id"])


def test_what_is_hashed_can_be_inspected(table) -> None:
    """A number nobody can see the input to is a number people either trust blindly or
    ignore."""
    rows = normalised_rows(table)
    assert rows[0] == "arm\x1ecreat\x1epid"
    assert len(rows) == len(table) + 1


# ---- the snapshot, and the round trip that makes it a record ----


def test_the_snapshot_fingerprint_is_recomputable_from_the_snapshot(real, tmp_path) -> None:
    """The property this feature stands on, and the one that failed first.

    Pandas writes floats at sixteen significant digits by default, one short of a lossless
    float64, and its default CSV parser does not round correctly even when the file has
    seventeen. Either one alone left 32 of 41 columns differing in the last bit, so a
    snapshot's own recorded fingerprint could not be recomputed from it, which makes it a
    file rather than a record.
    """
    path = write_snapshot(tmp_path, real)
    assert fingerprint(real, ["unit_id"]) == fingerprint(read_snapshot(path), ["unit_id"])


def test_the_snapshot_keeps_every_row_and_column(real, tmp_path) -> None:
    back = read_snapshot(write_snapshot(tmp_path, real))
    assert back.shape == real.shape
    assert sorted(back.columns) == sorted(real.columns)


def test_the_default_csv_parser_is_not_good_enough() -> None:
    """Pinned because it is surprising and because it would silently come back if someone
    simplified the read. `float()` on the same text is exact; the parser's fast path is not.
    """
    value = 81.10322868331801
    text = f"x\n{value:.17g}\n"
    assert float(f"{value:.17g}") == value
    default = pd.read_csv(io.StringIO(text))
    exact = pd.read_csv(io.StringIO(text), float_precision="round_trip")
    assert float(default.x.iloc[0]) != value
    assert float(exact.x.iloc[0]) == value

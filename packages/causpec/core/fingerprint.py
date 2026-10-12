"""Fingerprinting a table by its content, not by its bytes.

Mirrors design.md 6.5. The question a fingerprint answers is "is this the same data?", and it
has to answer it the way a person would: the same numbers in a different column order, a
different row order or a different dtype are the same data. A hash of the file's bytes answers
a different and much less useful question, and it answers it with false alarms. A warning that
fires on a harmless re-export is a warning people learn to ignore, which is worse than no
warning.

So the content is normalised first, and every rule below exists because something would
otherwise produce a different hash for the same data:

- **Row order.** Sorted by the declared key when there is one, otherwise by every column.
  A re-export in a different order is the same data.
- **Column order.** Sorted by name. Likewise.
- **Integers against floats.** 1 read from parquet as int64 and 1.0 read from CSV as float64
  are the same number, so an integral value is written as an integer whatever its dtype.
  Values beyond 2^53 keep their integer form rather than going through a float.
- **Float formatting.** 17 significant digits, which round-trips float64 exactly. Rounding
  would hide real differences, and the default `str` differs between dtypes.
- **Negative zero.** Normalised to zero, because -0.0 == 0.0 but formats differently.
- **Missing values.** One token, so NaN, None and pandas NA agree.
- **Booleans.** Written as 1 and 0, so a bool column and a 0/1 integer column agree.

Strings are deliberately **not** stripped or case-folded: " A" and "A" are different values,
and a fingerprint that said otherwise would be making an editorial decision about the data.

**What this is exact about, and what it therefore cannot forgive.** Float comparison is at
full precision, so a table re-serialised by something that writes fewer than seventeen
significant digits will not match the original. That is a real limitation: the same database
query exported once to CSV at sixteen digits and once to parquet gives two fingerprints. It is
not fixed by rounding, which is the obvious idea and the wrong one. One ulp is about 2e-16 in
relative terms and the boundaries at fifteen significant digits are spaced 1e-15 apart, so a
perturbed value crosses a rounding boundary roughly a fifth of the time: rounding would move
the instability onto every value instead of removing it. The snapshot this project writes is
therefore written losslessly, so that its own fingerprint verifies against it, and a
fingerprint mismatch between two files in different formats means exactly what it says, that
the bytes decode to different numbers.

What this does not do is prove the data is correct, or let anyone else reproduce the analysis:
real patient data never leaves its environment, so this is a detection mechanism for the
people who already have the file, not a sharing mechanism.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# One token for every flavour of absent, so NaN, None and pd.NA agree.
MISSING = "\x00NA"

# Beyond this a float64 cannot hold consecutive integers, so an integral value is written in
# its integer form rather than through a float.
EXACT_INTEGER_LIMIT = 2**53

# Enough digits to round-trip a float64 exactly.
FLOAT_DIGITS = 17

# How many rows go into one hash update. Large enough that the per-call overhead disappears,
# small enough that a million-row table does not become a million-row string.
CHUNK = 2048


def _format_number(value: Any) -> str:
    if value is None:
        return MISSING
    number = float(value)
    if np.isnan(number):
        return MISSING
    if np.isinf(number):
        return "inf" if number > 0 else "-inf"
    if number == 0.0:
        return "0"  # also catches -0.0, which formats differently but is the same number
    if number.is_integer() and abs(number) < EXACT_INTEGER_LIMIT:
        return str(int(number))
    return f"{number:.{FLOAT_DIGITS}g}"


def _normalise_column(column: Any) -> list[str]:
    """One column as strings, with everything that is incidental to the content removed."""
    import pandas as pd

    missing = np.asarray(column.isna(), dtype=bool)

    if pd.api.types.is_bool_dtype(column.dtype):
        values = ["1" if bool(value) else "0" for value in column]
    elif pd.api.types.is_integer_dtype(column.dtype):
        # Straight through, so an id beyond 2^53 is not distorted by a float round trip.
        values = [
            str(int(value)) if not gap else MISSING
            for value, gap in zip(column, missing, strict=True)
        ]
    elif pd.api.types.is_numeric_dtype(column.dtype):
        values = [_format_number(value) for value in column]
    else:
        values = [
            MISSING if gap else str(value) for value, gap in zip(column, missing, strict=True)
        ]

    return [MISSING if gap else value for value, gap in zip(values, missing, strict=True)]


def normalised_rows(data: pd.DataFrame, key_columns: list[str] | None = None) -> list[str]:
    """The table as canonical lines: a header, then one line per row.

    Exposed so a test can see what is being hashed. A fingerprint whose input nobody can
    inspect is a number people either trust blindly or ignore.
    """
    columns = sorted(data.columns)
    if not columns:
        return ["\x1e".join([])]
    key = [name for name in (key_columns or []) if name in data.columns]
    # Sorting by every column when no key is declared is what makes the hash independent of
    # row order. It is deterministic because the sort is over the normalised strings, not over
    # dtypes that compare differently.
    ordered = data[columns]
    normalised = {name: _normalise_column(ordered[name]) for name in columns}
    sort_by = key if key else columns
    order = sorted(range(len(ordered)), key=lambda i: tuple(normalised[c][i] for c in sort_by))

    lines = ["\x1e".join(columns)]
    lines.extend("\x1e".join(normalised[name][i] for name in columns) for i in order)
    return lines


def fingerprint(data: pd.DataFrame, key_columns: list[str] | None = None) -> str:
    """A sha256 over the normalised content, truncated to sixteen hex characters.

    Sixteen characters is 64 bits, which is far more than enough to notice that a file
    changed. It is short enough to read out and compare by eye, which is what it is for.
    """
    digest = hashlib.sha256()
    lines = normalised_rows(data, key_columns)
    for start in range(0, len(lines), CHUNK):
        chunk = "\n".join(lines[start : start + CHUNK]) + "\n"
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()[:16]

#!/usr/bin/env python3
"""Stop data files from entering a commit.

The rule: no real data in the repository at all, and synthetic data generated on
demand by data/generators/ rather than committed. This hook is a second gate behind
.gitignore, covering `git add -f` and any gap in the ignore rules.
"""

from __future__ import annotations

import sys
from pathlib import Path

DATA_SUFFIXES = {
    ".csv",
    ".tsv",
    ".parquet",
    ".xlsx",
    ".xls",
    ".duckdb",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".feather",
    ".pkl",
    ".h5",
    ".dta",
    ".sav",
}

# The largest file allowed through as a fixture, in bytes. Anything larger belongs in
# a generator.
MAX_FIXTURE_BYTES = 4096
FIXTURE_DIRS = ("tests/fixtures/",)


def main(argv: list[str]) -> int:
    offenders: list[str] = []
    for name in argv:
        path = Path(name)
        if path.suffix.lower() not in DATA_SUFFIXES:
            continue
        posix = path.as_posix()
        if (
            posix.startswith(FIXTURE_DIRS)
            and path.exists()
            and path.stat().st_size <= MAX_FIXTURE_BYTES
        ):
            continue
        offenders.append(posix)

    if not offenders:
        return 0

    print("Refusing the commit: data files detected.", file=sys.stderr)
    for name in offenders:
        print(f"  - {name}", file=sys.stderr)
    print(
        "\nData files are not committed. Generate synthetic data on demand with the "
        "generators under data/generators/;\n"
        f"a fixture that genuinely must be committed goes in tests/fixtures/ and must "
        f"be at most {MAX_FIXTURE_BYTES} bytes.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

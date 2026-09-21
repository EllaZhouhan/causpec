#!/usr/bin/env python3
"""阻止数据文件进入提交。

设计原则：任何真实数据都不得入库，合成数据由 data/generators/ 现场生成、不入库。
这个钩子在 .gitignore 之外再设一道闸，防止 `git add -f` 或 .gitignore 疏漏。
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

# 允许作为 fixture 的极小文件（字节）。超过则必须改用生成器。
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

    print("拒绝提交：检测到数据文件。", file=sys.stderr)
    for name in offenders:
        print(f"  - {name}", file=sys.stderr)
    print(
        "\n数据文件不入库。合成数据请用 data/generators/ 下的生成器现场生成；\n"
        f"确需入库的极小 fixture 放在 tests/fixtures/ 且不超过 {MAX_FIXTURE_BYTES} 字节。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

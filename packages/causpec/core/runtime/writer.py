"""Atomic writes and checksums.

Mirrors design.md section 14: "writes use a temporary file plus an atomic rename".

Why atomicity is required: when a run is interrupted, half a results.json is worse
than no results.json — it looks like a result but its contents are truncated. A
temporary file plus ``os.replace`` guarantees a reader sees either the complete old
version or the complete new one, never an intermediate state.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256_of(path: Path) -> str:
    """sha256 of a file's contents, read in chunks so large files stay cheap."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, content: str | bytes) -> Path:
    """Write atomically.

    The temporary file is created in the **same directory** as the target: an
    ``os.replace`` across filesystems is not atomic, and ``/tmp`` is often a different
    filesystem. Write, fsync, then replace, so a power loss cannot leave an empty file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content

    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def write_json_atomic(path: Path, payload: Any) -> Path:
    """Write JSON atomically, with sorted keys so identical content yields identical
    bytes — otherwise the checksum means nothing."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    return write_atomic(path, text + "\n")


def append_atomic(path: Path, line: str) -> None:
    """Append one line.

    The audit log grows line by line, so it cannot use read-modify-atomic-replace —
    that loses lines under concurrency. POSIX guarantees that a single write smaller
    than PIPE_BUF to a file opened in append mode does not interleave, and audit lines
    are far below that bound.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())

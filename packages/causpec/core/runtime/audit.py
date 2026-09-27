"""Audit log: one line per tool or CLI call.

Mirrors design.md section 14: timestamp, tool, parameter hash, input fingerprints,
output hash, whether it errored.

**No raw rows and no credentials in the log.** Enforced by code rather than by
discipline: parameters are hashed, never stored, and extra metadata passes a
sensitive-key check that raises on a hit. Better that a developer hits the error
while writing the code than that someone finds a leak in the log afterwards.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from causpec.core.runtime.writer import append_atomic

# Keys matching these fragments may not enter the audit log. False positives are
# acceptable: renaming a key costs far less than writing a DSN to disk.
SENSITIVE_KEY_PATTERN = re.compile(
    r"password|passwd|secret|token|credential|api_?key|dsn|conn(ection)?_?str|private_?key",
    re.IGNORECASE,
)


class SensitiveValueError(ValueError):
    """An attempt to write something credential-shaped into the audit log."""


def assert_no_sensitive_keys(payload: dict[str, Any], where: str = "audit metadata") -> None:
    """Check key names recursively. A hit raises."""
    for key, value in payload.items():
        if SENSITIVE_KEY_PATTERN.search(str(key)):
            raise SensitiveValueError(
                f"the key {key!r} in {where} looks like a credential and may not be "
                f"logged. If it is genuinely harmless, rename it so it does not contain "
                f"password/token/dsn and similar."
            )
        if isinstance(value, dict):
            assert_no_sensitive_keys(value, where)


def params_hash(params: dict[str, Any]) -> str:
    """Hash of the parameters.

    Only the hash is recorded, never the content: parameters carry file paths (which
    leak directory structure, see ADR-0002), column names, and potentially connection
    strings. A hash is enough to answer "were these two calls made with the same
    parameters?", which is what an audit log needs to answer.
    """
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def record(
    path: Path,
    tool: str,
    params: dict[str, Any] | None = None,
    *,
    input_fingerprints: dict[str, str] | None = None,
    output_hash: str | None = None,
    ok: bool = True,
    error_code: str | None = None,
    duration_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one audit record and return the line that was written.

    Args:
        metadata: a small amount of data the caller explicitly deems safe to persist
            (row counts, family id). It passes the sensitive-key check.
    """
    metadata = metadata or {}
    assert_no_sensitive_keys(metadata)

    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "tool": tool,
        "params_hash": params_hash(params or {}),
        "ok": ok,
    }
    if input_fingerprints:
        entry["inputs"] = dict(sorted(input_fingerprints.items()))
    if output_hash:
        entry["output_hash"] = output_hash
    if error_code:
        entry["error_code"] = error_code
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 2)
    if metadata:
        entry["meta"] = metadata

    append_atomic(path, json.dumps(entry, ensure_ascii=False, sort_keys=True))
    return entry


def read(path: Path) -> list[dict[str, Any]]:
    """Read the audit log back."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

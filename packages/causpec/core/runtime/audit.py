"""审计日志：每次工具或 CLI 调用一行。

对应 design.md 第 14 节：时间、工具、参数 hash、输入指纹、输出 hash、是否出错。

**日志中不记录原始行，也不记录凭据。** 这条由代码强制，不靠自觉：
参数只记哈希不记内容；额外元数据过一道敏感键名检查，命中就抛错。
宁可让开发者在写代码时撞上这个错误，也不要在事后从日志里发现泄露。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from causpec.core.runtime.writer import append_atomic

# 命中这些片段的键名不得进入审计日志。宁可误报——改个键名的成本，
# 远低于把一个 DSN 写进磁盘上的日志。
SENSITIVE_KEY_PATTERN = re.compile(
    r"password|passwd|secret|token|credential|api_?key|dsn|conn(ection)?_?str|private_?key",
    re.IGNORECASE,
)


class SensitiveValueError(ValueError):
    """试图把疑似凭据写进审计日志。"""


def assert_no_sensitive_keys(payload: dict[str, Any], where: str = "audit metadata") -> None:
    """递归检查键名。命中即抛错。"""
    for key, value in payload.items():
        if SENSITIVE_KEY_PATTERN.search(str(key)):
            raise SensitiveValueError(
                f"{where} 中的键 {key!r} 疑似凭据，不得写入日志。"
                f"如果它确实无害，请换一个不含 password/token/dsn 等字样的键名。"
            )
        if isinstance(value, dict):
            assert_no_sensitive_keys(value, where)


def params_hash(params: dict[str, Any]) -> str:
    """参数的哈希。

    只记哈希不记内容——参数里可能有文件路径（泄露目录结构，见 ADR-0002）、
    列名，甚至连接串。哈希足以回答「这两次调用的参数一样吗」，
    而这正是审计日志需要回答的。
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
    """追加一行审计记录，返回写进去的那一行。

    Args:
        metadata: 调用方明确认为可以落盘的少量元数据（例如行数、family id）。
            会过一遍敏感键名检查。
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
    """读回审计日志。"""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

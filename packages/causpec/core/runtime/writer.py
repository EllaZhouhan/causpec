"""原子写入与 checksum。

对应 design.md 第 14 节「写文件采用临时文件加原子 rename」。

为什么必须原子：一次运行被中断时，半个 results.json 比没有 results.json 更糟——
它看起来像一份结果，但内容是残缺的。临时文件 + ``os.replace`` 保证读到的
要么是完整的旧版本，要么是完整的新版本，不存在中间态。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256_of(path: Path) -> str:
    """文件内容的 sha256。分块读，大文件也不占内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, content: str | bytes) -> Path:
    """原子写入。

    临时文件建在**同一个目录**下——跨文件系统的 ``os.replace`` 不是原子的，
    而 ``/tmp`` 常常是另一个文件系统。写完 fsync 再 replace，
    保证断电时不会留下空文件。
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
    """原子写入 JSON。排序键，这样同样的内容产出同样的字节——checksum 才有意义。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    return write_atomic(path, text + "\n")


def append_atomic(path: Path, line: str) -> None:
    """追加一行。

    审计日志是逐行追加的，不能用「读-改-写」的原子替换——那会在并发时丢行。
    单次 ``write`` 小于 PIPE_BUF 时 POSIX 保证以 append 模式打开的写入不交错，
    审计行远小于这个界限。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())

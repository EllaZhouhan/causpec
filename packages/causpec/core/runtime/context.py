"""RunContext：一次运行的目录、产物与审计。

对应 design.md 第 14 节的 run 目录布局：

    runs/<run_id>/
     ├─ manifest.json    来源记录与产物 checksum
     ├─ spec.yaml
     ├─ quality/issues.json
     ├─ results/results.json
     ├─ report.md
     └─ audit.jsonl

所有写入都是原子的。``finalize()`` 收尾时把每个产物的 sha256 记进 manifest——
事后有人改了 run 目录里的文件，checksum 对不上就能发现。
"""

from __future__ import annotations

import json
import platform
import secrets
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from causpec import __version__
from causpec.core.contracts.manifest import ExecutionMode, Manifest
from causpec.core.runtime import audit
from causpec.core.runtime.writer import sha256_of, write_atomic, write_json_atomic

# 会影响数值结果的依赖。版本变了，同一份数据可能得到不同的估计，
# 所以它们属于 manifest 该记的东西（G5）。
TRACKED_PACKAGES = ("econml", "scikit-learn", "numpy", "pandas", "scipy", "statsmodels")


def new_run_id() -> str:
    """可排序的 run id：UTC 时间戳 + 随机后缀（同一秒内多次运行不会撞）。"""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def git_sha(start: Path | None = None) -> str | None:
    """当前代码的 git sha。装成 wheel 后没有 git，返回 None——不是错误。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=start or Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def package_versions(names: tuple[str, ...] = TRACKED_PACKAGES) -> dict[str, str]:
    """已安装的依赖版本。没装的不记——它对这次运行没有影响。"""
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


class RunContext:
    """一次运行。

    典型用法::

        with RunContext.create(Path("runs")) as run:
            run.write_text("spec.yaml", spec_yaml)
            run.audit("estimate", params, duration_ms=elapsed)
            run.finalize(spec_hash=..., seed=42)
    """

    def __init__(self, directory: Path, run_id: str, execution_mode: ExecutionMode) -> None:
        self.directory = directory
        self.run_id = run_id
        self.execution_mode = execution_mode
        self.audit_path = directory / "audit.jsonl"
        self._artifacts: list[Path] = []

    @classmethod
    def create(
        cls,
        root: Path,
        execution_mode: ExecutionMode = ExecutionMode.CLI,
        run_id: str | None = None,
    ) -> RunContext:
        run_id = run_id or new_run_id()
        directory = root / run_id
        directory.mkdir(parents=True, exist_ok=False)
        return cls(directory, run_id, execution_mode)

    # ---- 产物 ----

    def write_text(self, relative: str, content: str) -> Path:
        path = write_atomic(self.directory / relative, content)
        self._artifacts.append(path)
        return path

    def write_json(self, relative: str, payload: Any) -> Path:
        path = write_json_atomic(self.directory / relative, payload)
        self._artifacts.append(path)
        return path

    # ---- 审计 ----

    def audit(self, tool: str, params: dict[str, Any] | None = None, **kwargs: Any) -> None:
        audit.record(self.audit_path, tool, params, **kwargs)

    def audit_entries(self) -> list[dict[str, Any]]:
        return audit.read(self.audit_path)

    # ---- 收尾 ----

    def finalize(
        self,
        *,
        spec_hash: str,
        seed: int,
        snapshot_fingerprint: str | None = None,
        claim_rules_hash: str = "",
    ) -> Manifest:
        """写 manifest。必须最后调用——它要给所有产物算 checksum。"""
        checksums = {
            str(path.relative_to(self.directory)): sha256_of(path)
            for path in sorted(set(self._artifacts))
            if path.exists()
        }
        manifest = Manifest(
            run_id=self.run_id,
            created_at=datetime.now(UTC),
            execution_mode=self.execution_mode,
            causpec_version=__version__,
            git_sha=git_sha(),
            python_version=platform.python_version(),
            package_versions=package_versions(),
            spec_hash=spec_hash,
            snapshot_fingerprint=snapshot_fingerprint,
            seed=seed,
            claim_rules_hash=claim_rules_hash,
            artifacts=checksums,
        )
        # manifest 自己不进 artifacts——它记的是别人的 checksum。
        write_json_atomic(self.directory / "manifest.json", manifest.model_dump(mode="json"))
        return manifest

    def verify(self) -> list[str]:
        """按 manifest 里的 checksum 核对产物，返回对不上的相对路径。"""
        manifest_path = self.directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"没有 manifest：{manifest_path}")
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))["artifacts"]
        mismatched = []
        for relative, expected in recorded.items():
            path = self.directory / relative
            if not path.exists() or sha256_of(path) != expected:
                mismatched.append(relative)
        return mismatched

    def __enter__(self) -> RunContext:
        return self

    def __exit__(self, *exc: object) -> None:
        del exc

    def __repr__(self) -> str:
        return f"RunContext({self.run_id!r}, {self.directory}, {self.execution_mode.value})"

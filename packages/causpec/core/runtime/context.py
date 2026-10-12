"""RunContext: one run's directory, artefacts and audit trail.

Mirrors the run-directory layout of design.md section 14:

    runs/<run_id>/
      manifest.json    provenance record and artefact checksums
      spec.yaml
      quality/issues.json
      results/results.json
      report.md
      audit.jsonl

Every write is atomic. ``finalize()`` records each artefact's sha256 in the manifest,
so a file edited in the run directory afterwards will fail its checksum.
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
from causpec.core.runtime import audit, snapshot
from causpec.core.runtime.writer import sha256_of, write_atomic, write_json_atomic

# Dependencies that can change the numbers. A version bump can change the estimate
# for the same data, which is why the manifest records them (G5).
TRACKED_PACKAGES = ("econml", "scikit-learn", "numpy", "pandas", "scipy", "statsmodels")


def new_run_id() -> str:
    """A sortable run id: UTC timestamp plus a random suffix, so runs within the same
    second do not collide."""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def git_sha(start: Path | None = None) -> str | None:
    """The git sha of the current code. Installed from a wheel there is no git, so
    None is a normal answer, not an error."""
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
    """Installed versions of the tracked dependencies. Absent ones are omitted: they
    had no influence on this run."""
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


class RunContext:
    """One run.

    Typical use::

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

    # ---- artefacts ----

    def write_text(self, relative: str, content: str) -> Path:
        path = write_atomic(self.directory / relative, content)
        self._artifacts.append(path)
        return path

    def write_json(self, relative: str, payload: Any) -> Path:
        path = write_json_atomic(self.directory / relative, payload)
        self._artifacts.append(path)
        return path

    def write_snapshot(self, data: Any) -> Path:
        """Write the analysed table, so the report can be checked against it.

        Not atomic in the write_atomic sense: it streams through gzip rather than building
        the whole file in memory first, because a snapshot is the one artefact that can be
        large. It is still checksummed into the manifest like every other artefact, so a
        truncated write is detectable.
        """
        path = snapshot.write_snapshot(self.directory, data)
        self._artifacts.append(path)
        return path

    # ---- audit ----

    def audit(self, tool: str, params: dict[str, Any] | None = None, **kwargs: Any) -> None:
        audit.record(self.audit_path, tool, params, **kwargs)

    def audit_entries(self) -> list[dict[str, Any]]:
        return audit.read(self.audit_path)

    # ---- finalisation ----

    def finalize(
        self,
        *,
        spec_hash: str,
        seed: int,
        source_fingerprint: str | None = None,
        snapshot_fingerprint: str | None = None,
        prior_runs_on_this_data: list[str] | None = None,
        claim_rules_hash: str = "",
        basic_checks_hash: str = "",
    ) -> Manifest:
        """Write the manifest. Must be called last: it checksums every artefact."""
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
            source_fingerprint=source_fingerprint,
            snapshot_fingerprint=snapshot_fingerprint,
            prior_runs_on_this_data=prior_runs_on_this_data or [],
            seed=seed,
            claim_rules_hash=claim_rules_hash,
            basic_checks_hash=basic_checks_hash,
            artifacts=checksums,
        )
        # The manifest is not itself an artefact, it records everyone else's checksums.
        write_json_atomic(self.directory / "manifest.json", manifest.model_dump(mode="json"))
        return manifest

    def verify(self) -> list[str]:
        """Verify artefacts against the manifest's checksums; return mismatching paths."""
        manifest_path = self.directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"no manifest at {manifest_path}")
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

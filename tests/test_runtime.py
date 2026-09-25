"""runtime：原子写入、manifest、审计日志。

对应 design.md 第 14 节与 G5。这个文件锁两条最难靠人工保证的性质：
写入是原子的；凭据进不了日志。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from causpec.core.contracts.manifest import ExecutionMode, Manifest
from causpec.core.runtime import audit
from causpec.core.runtime.audit import SensitiveValueError, params_hash
from causpec.core.runtime.context import RunContext, new_run_id, package_versions
from causpec.core.runtime.writer import (
    append_atomic,
    sha256_of,
    write_atomic,
    write_json_atomic,
)

# ---- 原子写入 ----


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    path = write_atomic(tmp_path / "a" / "b" / "c.txt", "内容")
    assert path.read_text(encoding="utf-8") == "内容"


def test_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    write_atomic(tmp_path / "x.json", "{}")
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_failed_write_does_not_clobber_the_old_file(tmp_path: Path, monkeypatch) -> None:
    """替换失败时旧文件必须原样保留——半个结果比没有结果更糟。"""
    path = tmp_path / "results.json"
    write_atomic(path, "原来的内容")

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("磁盘满了")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="磁盘满了"):
        write_atomic(path, "新内容")

    assert path.read_text(encoding="utf-8") == "原来的内容"
    assert [p.name for p in tmp_path.iterdir()] == ["results.json"]  # 临时文件被清掉了


def test_temporary_file_lives_beside_the_target(tmp_path: Path, monkeypatch) -> None:
    """临时文件必须和目标同目录：跨文件系统的 os.replace 不是原子的。"""
    seen: list[Path] = []
    real_replace = os.replace

    def spy(src: object, dst: object) -> None:
        seen.append(Path(str(src)).parent)
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", spy)
    target = tmp_path / "nested" / "out.txt"
    write_atomic(target, "x")
    assert seen == [target.parent]


def test_json_is_byte_stable(tmp_path: Path) -> None:
    """同样的内容要产出同样的字节，否则 checksum 没有意义。"""
    first = write_json_atomic(tmp_path / "a.json", {"b": 2, "a": 1})
    digest = sha256_of(first)
    write_json_atomic(tmp_path / "a.json", {"a": 1, "b": 2})  # 键序不同
    assert sha256_of(tmp_path / "a.json") == digest


def test_append_preserves_existing_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    for i in range(3):
        append_atomic(path, f'{{"n": {i}}}')
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 3


# ---- 凭据防护 ----


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "PASSWORD",
        "db_passwd",
        "api_key",
        "apiKey",
        "CAUSPEC_ICU_DSN",
        "connection_string",
        "private_key",
        "auth_token",
        "client_secret",
    ],
)
def test_sensitive_keys_are_rejected(tmp_path: Path, key: str) -> None:
    """design.md 第 14 节：日志不记录凭据。由代码强制，不靠自觉。"""
    with pytest.raises(SensitiveValueError, match="疑似凭据"):
        audit.record(tmp_path / "audit.jsonl", "estimate", metadata={key: "值"})


def test_sensitive_keys_are_rejected_when_nested(tmp_path: Path) -> None:
    with pytest.raises(SensitiveValueError):
        audit.record(
            tmp_path / "audit.jsonl", "estimate", metadata={"source": {"dsn": "postgres://..."}}
        )


def test_ordinary_metadata_passes(tmp_path: Path) -> None:
    entry = audit.record(
        tmp_path / "audit.jsonl", "estimate", metadata={"family": "hte_iv", "n_rows": 100}
    )
    assert entry["meta"] == {"family": "hte_iv", "n_rows": 100}


def test_params_are_hashed_not_stored(tmp_path: Path) -> None:
    """参数里可能有路径（泄露目录结构，ADR-0002）与列名，只记哈希。"""
    path = tmp_path / "audit.jsonl"
    audit.record(path, "estimate", {"data": "/Users/someone/私人病历.csv", "seed": 42})
    raw = path.read_text(encoding="utf-8")
    assert "私人病历" not in raw
    assert "params_hash" in raw


def test_params_hash_is_order_independent() -> None:
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})


def test_params_hash_distinguishes_different_params() -> None:
    assert params_hash({"seed": 1}) != params_hash({"seed": 2})


# ---- RunContext ----


def test_run_ids_are_sortable_and_unique() -> None:
    ids = [new_run_id() for _ in range(5)]
    assert len(set(ids)) == 5
    assert ids == sorted(ids) or all(len(i) == len(ids[0]) for i in ids)


def test_create_refuses_to_reuse_a_run_id(tmp_path: Path) -> None:
    run = RunContext.create(tmp_path, run_id="fixed")
    with pytest.raises(FileExistsError):
        RunContext.create(tmp_path, run_id="fixed")
    assert run.directory.exists()


def test_manifest_records_everything_that_affects_the_result(tmp_path: Path) -> None:
    with RunContext.create(tmp_path) as run:
        run.write_text("spec.yaml", "question: q\n")
        manifest = run.finalize(spec_hash="abc", seed=7, claim_rules_hash="rules123")

    assert manifest.spec_hash == "abc"
    assert manifest.seed == 7
    assert manifest.claim_rules_hash == "rules123"
    assert manifest.causpec_version
    # 会影响数值的依赖必须记下来（G5）
    assert {"econml", "numpy", "pandas"} <= set(manifest.package_versions)


def test_manifest_is_readable_back(tmp_path: Path) -> None:
    with RunContext.create(tmp_path) as run:
        run.write_json("results/results.json", {"res:primary.ate": -0.01})
        run.finalize(spec_hash="abc", seed=7)
    payload = json.loads((run.directory / "manifest.json").read_text(encoding="utf-8"))
    assert Manifest.model_validate(payload).run_id == run.run_id


def test_checksums_cover_every_artifact(tmp_path: Path) -> None:
    with RunContext.create(tmp_path) as run:
        run.write_text("spec.yaml", "a")
        run.write_json("quality/issues.json", [])
        manifest = run.finalize(spec_hash="abc", seed=7)
    assert set(manifest.artifacts) == {"spec.yaml", "quality/issues.json"}
    assert run.verify() == []


def test_verify_detects_tampering(tmp_path: Path) -> None:
    """事后有人改了 run 目录里的文件，checksum 对不上就能发现。"""
    with RunContext.create(tmp_path) as run:
        run.write_text("report.md", "原始报告")
        run.finalize(spec_hash="abc", seed=7)
    (run.directory / "report.md").write_text("被改过的报告", encoding="utf-8")
    assert run.verify() == ["report.md"]


def test_verify_detects_deletion(tmp_path: Path) -> None:
    with RunContext.create(tmp_path) as run:
        run.write_text("report.md", "报告")
        run.finalize(spec_hash="abc", seed=7)
    (run.directory / "report.md").unlink()
    assert run.verify() == ["report.md"]


def test_verify_without_manifest_raises(tmp_path: Path) -> None:
    run = RunContext.create(tmp_path)
    with pytest.raises(FileNotFoundError, match="manifest"):
        run.verify()


def test_execution_mode_is_recorded(tmp_path: Path) -> None:
    """skill 形态是 best-effort，读者要知道这份结果的保证有多强（design.md 第 3 节）。"""
    with RunContext.create(tmp_path, ExecutionMode.SKILL) as run:
        manifest = run.finalize(spec_hash="abc", seed=7)
    assert manifest.execution_mode is ExecutionMode.SKILL


def test_reproducibility_key_ignores_incidental_fields(tmp_path: Path) -> None:
    """run_id、时间戳不影响结果是否应当相同。"""
    manifests = []
    for run_id in ("run-a", "run-b"):
        with RunContext.create(tmp_path, run_id=run_id) as run:
            manifests.append(run.finalize(spec_hash="same", seed=7))
    assert manifests[0].reproducibility_key() == manifests[1].reproducibility_key()


def test_package_versions_skip_missing_packages() -> None:
    assert package_versions(("definitely-not-installed-xyz",)) == {}

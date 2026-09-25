"""Manifest：一次运行的完整来源记录。

对应 design.md 第 14 节与 G5（输入与 seed 固定时结果可复现）。

manifest 要能回答的问题是：**半年后我能不能原样重跑这次分析？**
所以它记的是全部会影响结果的东西——代码版本、依赖版本、spec 哈希、
数据指纹、seed、判定规则哈希——以及每个产物的 checksum，用来验证
产物没被改过。

**不记录原始行，也不记录凭据**（design.md 第 14 节）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExecutionMode(StrEnum):
    """哪种形态跑的（design.md 第 3 节）。

    ``SKILL`` 形态是 best-effort——agent 可能绕过脚本直接读数据，
    报告页眉要注明。记在 manifest 里，读者才知道这份结果的保证有多强。
    """

    MCP = "mcp"
    CLI = "cli"
    SKILL = "skill"


class Manifest(BaseModel):
    """一次运行的 manifest。"""

    model_config = ConfigDict(frozen=True)

    run_id: str
    created_at: datetime
    execution_mode: ExecutionMode

    # ---- 代码来源 ----
    causpec_version: str
    git_sha: str | None = None
    python_version: str = ""
    package_versions: dict[str, str] = Field(default_factory=dict)

    # ---- 输入 ----
    spec_hash: str
    snapshot_fingerprint: str | None = None
    seed: int

    # ---- 判定依据 ----
    # 措辞等级的规则文件哈希：规则变了，同一份数据可能得到不同的等级，
    # 所以它和依赖版本一样属于「会影响结论的东西」。
    claim_rules_hash: str = ""

    # ---- 产物 ----
    # 相对路径 -> sha256。用来验证 run 目录里的文件没被事后改动。
    artifacts: dict[str, str] = Field(default_factory=dict)

    def reproducibility_key(self) -> tuple[str, str | None, int, str]:
        """决定结果是否应当相同的那几样东西。两次运行这个元组相同则结果应相同。"""
        return (self.spec_hash, self.snapshot_fingerprint, self.seed, self.causpec_version)

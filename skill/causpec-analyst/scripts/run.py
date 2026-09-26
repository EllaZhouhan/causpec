#!/usr/bin/env python3
"""skill 形态下调用 causpec 的入口。

对应 design.md 第 3 节。claude.ai 上没有 MCP server，skill 通过这个脚本调 causpec。
两种形态调用同一套函数，产出同样结构的 run 目录；manifest 中 execution_mode 记为 skill。

**这条路径是 best-effort。** agent 在技术上可以绕过这个脚本直接读数据自己算，
所以「数字只由代码产生」这条保证在 skill 形态下依赖 agent 遵守规则，而不是
由框架强制。报告页眉会注明这一点。MCP 形态没有这个问题——那边模型只能通过
声明过的工具与数据交互。

这个脚本要解决的实际问题是：沙箱里不一定装了 causpec。处理顺序是

1. 已经能 import → 直接用
2. 同级 ``assets/`` 下有 wheel → 加进 sys.path（纯 Python wheel 就是个 zip，
   可以直接 import），不动系统环境
3. 还不行 → pip 安装那个 wheel
4. 仍然不行 → 说清楚缺什么、怎么装，而不是抛一个 ImportError 栈

用法与 causpec CLI 完全一致::

    python scripts/run.py quality  --spec spec.yaml --data cohort.csv
    python scripts/run.py estimate --spec spec.yaml --data cohort.csv --report
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"

INSTALL_HINT = """\
无法加载 causpec。

skill 包里应当有一个 wheel（assets/causpec-*.whl）。如果没有，从仓库根目录构建：

    uv build --wheel
    cp dist/causpec-*.whl skill/causpec-analyst/assets/

估计功能还需要 causpec[hte]（econml、scikit-learn）。沙箱里装不上时，
质量检查与报告渲染仍然可用，但估计跑不了——这种情况要如实告诉用户，
不要改用别的方式算一个数出来。
"""


def _bundled_wheel() -> Path | None:
    wheels = sorted(ASSETS.glob("causpec-*.whl"))
    return wheels[-1] if wheels else None


def _importable() -> bool:
    try:
        import causpec  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_causpec() -> None:
    """让 ``causpec`` 可导入。失败时给出能照做的说明，而不是一个栈。"""
    if _importable():
        return

    wheel = _bundled_wheel()
    if wheel is None:
        raise SystemExit(INSTALL_HINT)

    # 纯 Python wheel 就是一个 zip，放进 sys.path 即可 import，不碰系统环境。
    sys.path.insert(0, str(wheel))
    if _importable():
        return

    # 依赖不全时才真的装。--no-input 避免在非交互环境里卡住。
    sys.path.pop(0)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-input", "--quiet", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not _importable():
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"{INSTALL_HINT}\npip 的输出：\n{detail[-2000:]}")


def main(argv: list[str] | None = None) -> int:
    ensure_causpec()
    from causpec.cli import main as cli_main

    return cli_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())

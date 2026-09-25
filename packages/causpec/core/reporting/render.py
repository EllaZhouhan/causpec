"""占位符渲染：报告里的数字只能由代码填。

对应 design.md 10.1、G4。规则有三条，全部由代码强制：

1. 正文只能用 ``{{res:primary.estimate}}`` 这样的占位符引用数字；
   引用不存在的地址，渲染失败。
2. 正文中出现**未经占位的数字**，渲染失败。
3. 术语里的数字（「28 天死亡率」「95% 置信区间」「AKI-3 期」）写成
   ``{{lit:28}}``，显式声明这不是计算结果。**但如果一个 lit 的数值与任何
   计算结果相同，同样拒绝**——防止模型用 lit 夹带结果。

失败时把错误返回给模型重写，模型没有别的路径能把数字写进报告。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

PLACEHOLDER = re.compile(r"\{\{([a-z]+):([A-Za-z0-9_.\-]+)\}\}")

# 裸数字：先把占位符和 Markdown 结构挖掉，剩下的数字都算正文数字。
BARE_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")

# lit 与结果比对时的相对容差：模型可能写 0.029 而结果是 0.0289。
_LITERAL_MATCH_RTOL = 0.02


class RenderError(Exception):
    """渲染失败。消息要能直接交给模型去改写。"""


def _strip_exempt(text: str) -> str:
    """挖掉不该当作正文数字看待的部分，换成等长空白以保持位置信息。

    豁免：占位符本身、Markdown 标题层级、列表序号、表格分隔线、代码块。
    """
    out = text
    for pattern in (
        PLACEHOLDER,
        re.compile(r"^#{1,6} ", re.MULTILINE),
        re.compile(r"^\s*\d+\. ", re.MULTILINE),
        re.compile(r"^\s*\|[-: |]+\|\s*$", re.MULTILINE),
        re.compile(r"```.*?```", re.DOTALL),
    ):
        out = pattern.sub(lambda m: " " * len(m.group(0)), out)
    return out


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _check_literals_are_not_results(
    literals: list[str], addresses: Mapping[str, float | int | str]
) -> None:
    """lit 里夹带计算结果 → 拒绝。"""
    numeric_results = {
        address: number
        for address, value in addresses.items()
        if (number := _as_float(value)) is not None
    }
    for literal in literals:
        written = _as_float(literal)
        if written is None:
            continue
        for address, number in numeric_results.items():
            if abs(written - number) <= _LITERAL_MATCH_RTOL * max(abs(number), 1e-9):
                raise RenderError(
                    f"lit:{literal} 与计算结果 {address}（{number}）相同。\n"
                    f"计算结果必须用地址引用，写成 {{{{{address}}}}}；\n"
                    f"lit 只用于术语里的固定数字，例如 {{{{lit:28}}}} 天死亡率。"
                )


def render(template: str, addresses: Mapping[str, float | int | str]) -> str:
    """把正文中的占位符替换成地址表里的数值。

    ``addresses`` 是各来源合并后的地址表：估计结果（``res:``）、质量检查
    （``qc:``）、措辞等级（``claim:``）。渲染器不认识任何一个来源的类型，
    只认识地址——这样加一种产物不需要动它。

    Raises:
        RenderError: 引用了不存在的地址、正文出现未经占位的数字，
            或 lit 里夹带了计算结果。
    """
    unknown: list[str] = []
    literals: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        namespace, path = match.group(1), match.group(2)
        if namespace == "lit":
            literals.append(path)
            return path
        address = f"{namespace}:{path}"
        if address not in addresses:
            unknown.append(address)
            return match.group(0)
        return str(addresses[address])

    rendered = PLACEHOLDER.sub(substitute, template)

    if unknown:
        raise RenderError(
            f"引用了不存在的地址：{'、'.join(unknown)}。\n"
            f"可用地址：{', '.join(sorted(addresses))}。\n"
            f"请只引用上述地址，不要自己写数字。"
        )

    bare = BARE_NUMBER.findall(_strip_exempt(template))
    if bare:
        raise RenderError(
            f"正文中出现未经占位的数字：{'、'.join(bare)}。\n"
            f"计算结果写成 {{{{res:...}}}}，术语里的固定数字写成 {{{{lit:28}}}}。\n"
            f"可用地址：{', '.join(sorted(addresses))}。"
        )

    _check_literals_are_not_results(literals, addresses)
    return rendered

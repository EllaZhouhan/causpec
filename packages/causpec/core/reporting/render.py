"""Placeholder rendering: only code puts numbers in the report.

Mirrors design.md 10.1 and G4. Three rules, all enforced by code:

1. Prose may reference numbers only through placeholders such as
   ``{{res:primary.estimate}}``; an unknown address fails the render. A format spec
   may follow the address to control precision, e.g. ``{{res:primary.ate|.3f}}`` or
   ``{{qc:...extreme_fraction|.1%}}``.
2. A **bare number** anywhere in the prose fails the render.
3. Numbers that are part of a term ("28-day mortality", "95% confidence interval",
   "AKI stage 3") are written ``{{lit:28}}``, declaring explicitly that they are not
   results. **But a lit whose value matches any computed result is also refused** —
   that would be smuggling.

On failure the error goes back to the model to rewrite. There is no other path by
which a number reaches the report.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable, Mapping

# {{res:primary.ate}} or {{res:primary.ate|.3f}} — after the pipe is a Python format spec.
# Format specs are not a nicety: without them the report shows
# -0.017936448014042473, and a model's natural response to that is to round it itself,
# which defeats G4. Letting it declare precision is safer than letting it do the maths.
PLACEHOLDER = re.compile(r"\{\{([a-z]+):([A-Za-z0-9_.\-]+?)(?:\|([^}]+))?\}\}")

# Bare numbers: placeholders and Markdown scaffolding are blanked out first, so
# whatever digits remain are prose.
#
# The trailing lookahead is `(?!\d)`, not `(?![\w.])`. The stricter form refuses to
# match a number followed by a period, which in Chinese prose was harmless (sentences
# end in a full-width period) but in English silently exempts every number at the end
# of a sentence — "the effect is about -0.08." would have passed. Found while
# translating the project; the leading lookbehind still prevents matching a fragment
# of a longer number.
BARE_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\d)")

# Relative tolerance when comparing a lit against results: a model might write 0.029
# where the result is 0.0289.
_LITERAL_MATCH_RTOL = 0.02


class RenderError(Exception):
    """Rendering failed. The message must be directly actionable by the model."""


def _strip_exempt(text: str) -> str:
    """Blank out the parts that are not prose numbers, preserving offsets.

    Exempt: placeholders themselves, Markdown heading markers, ordered-list numbers,
    table separator rows, fenced code blocks.
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


def _format(value: object, spec: str | None, *, address: str) -> str:
    """Render a value with a format spec, raising rather than silently falling back."""
    if not spec:
        return str(value)
    target: object = value
    if spec[-1] in "eEfFgGn%" and isinstance(value, str):
        # A numeric format applied to a string (lit:95 and friends): coerce first,
        # and let format() report the problem if it cannot be coerced.
        with contextlib.suppress(ValueError):
            target = float(value)
    try:
        return format(target, spec)
    except (ValueError, TypeError) as error:
        raise RenderError(
            f"format spec {spec!r} cannot be applied to {address} (value {value!r}): {error}"
        ) from error


def _format_address_list(addresses: Iterable[str], limit: int = 12) -> str:
    """Lay out addresses so a person can read them.

    Listing every address inline produces dozens on one line and buries the actual
    fix — that is how the cold-start test went wrong. Group by namespace, truncate.
    """
    grouped: dict[str, list[str]] = {}
    for address in sorted(addresses):
        grouped.setdefault(address.split(":", 1)[0], []).append(address)
    lines = []
    for namespace, items in grouped.items():
        shown = ", ".join(items[:limit])
        more = f" … ({len(items) - limit} more)" if len(items) > limit else ""
        lines.append(f"  {namespace}: {shown}{more}")
    return "\n".join(lines)


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _addresses_near(
    number: float, addresses: Mapping[str, float | int | str], tolerance: float = 0.05
) -> list[str]:
    """Addresses whose value is close to a given number — a bare number is usually
    meant to be one of them."""
    near = []
    for address, value in addresses.items():
        candidate = _as_float(value)
        if candidate is not None and abs(candidate - number) <= tolerance * max(abs(number), 1e-9):
            near.append(address)
    return sorted(near)


def _check_literals_are_not_results(
    literals: list[str], addresses: Mapping[str, float | int | str]
) -> None:
    """Refuse a lit that smuggles in a computed result."""
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
                    f"lit:{literal} equals the computed result {address} ({number}).\n"
                    f"Computed results must be cited by address, as {{{{{address}}}}};\n"
                    f"lit is only for numbers inside a term, e.g. {{{{lit:28}}}}-day mortality."
                )


def render(template: str, addresses: Mapping[str, float | int | str]) -> str:
    """Substitute placeholders in the prose with values from the address table.

    ``addresses`` is the merged table from every source: estimation (``res:``),
    quality checks (``qc:``) and the claim level (``claim:``). The renderer knows
    nothing about any source's type, only about addresses — so adding a new kind of
    artefact does not touch this function.

    Raises:
        RenderError: unknown address, bare number in the prose, or a lit that
            smuggles in a computed result.
    """
    unknown: list[str] = []
    literals: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        namespace, path, spec = match.group(1), match.group(2), match.group(3)
        if namespace == "lit":
            literals.append(path)
            return _format(path, spec, address=f"lit:{path}")
        address = f"{namespace}:{path}"
        if address not in addresses:
            unknown.append(address)
            return match.group(0)
        return _format(addresses[address], spec, address=address)

    rendered = PLACEHOLDER.sub(substitute, template)

    if unknown:
        # Show only addresses in the same namespace: the intended one is probably there.
        namespaces = {address.split(":", 1)[0] for address in unknown}
        candidates = [a for a in addresses if a.split(":", 1)[0] in namespaces] or list(addresses)
        raise RenderError(
            f"No such address: {', '.join(unknown)}.\n\n"
            f"Available in the same namespace:\n{_format_address_list(candidates)}\n\n"
            f"Cite only these addresses; do not write numbers yourself."
        )

    bare = BARE_NUMBER.findall(_strip_exempt(template))
    if bare:
        lines = [f"Un-placeheld number(s) in the prose: {', '.join(bare)}.", ""]
        for text in dict.fromkeys(bare):  # de-duplicate, keep order of appearance
            number = _as_float(text)
            matches = _addresses_near(number, addresses) if number is not None else []
            if matches:
                lines.append(
                    f"  {text} -> you probably meant {', '.join(f'{{{{{a}}}}}' for a in matches)}"
                )
            else:
                lines.append(
                    f'  {text} -> if this is part of a term (e.g. "{text}-day mortality"), '
                    f"write {{{{lit:{text}}}}}"
                )
        lines += [
            "",
            "Computed results go in {{res:...}}; fixed numbers inside a term go in {{lit:28}}.",
            "To control precision, append a format spec: {{res:primary.ate|.3f}}.",
        ]
        raise RenderError("\n".join(lines))

    _check_literals_are_not_results(literals, addresses)
    return rendered

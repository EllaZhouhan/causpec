"""Cutting a covariate into the groups an effect is reported for.

Mirrors design.md 7.7. The point of this module is small and the reason for it is not: a
conditional effect reported as a per-patient cloud says the effect varies and names nobody,
while a grouping says what the effect was among patients over 65, with an interval. One of
those a clinician can act on or dispute.

Two ways to cut, and the difference is who is responsible for the threshold. `cuts` are
numbers the user can defend, which is the better kind when they have one: 65 for frailty, 10
for a SOFA score. `quantiles` are equal-sized bins for when they do not, which at least cannot
be chosen to flatter the result.

Groups are never dropped for being small. A group of eleven patients with an interval four
times wider than the others is the finding, and silently merging it away would be the tool
deciding what the user is allowed to see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from causpec.core.contracts.spec import EffectGroup

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


class GroupingError(Exception):
    """A grouping could not be formed, with the reason."""


def _format_edge(value: float) -> str:
    """A threshold as a reader would write it, so the label reads like the question."""
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.4g}"


def group_masks(data: pd.DataFrame, group: EffectGroup) -> list[tuple[str, np.ndarray]]:
    """The groups one declared dimension produces, as (label, row mask) pairs.

    Missing values form no group and are excluded from every one: a patient whose age is
    unknown is not known to be over 65 and not known to be under it, the same rule the
    population filters use. The label says so when it happens, because a group table whose
    counts do not add up to the sample is a table a reader will mistrust for the wrong reason.
    """
    if group.variable not in data.columns:
        raise GroupingError(f"effect_groups names {group.variable!r}, which is not in the data")
    column: Any = data[group.variable]
    values = np.asarray(column, dtype=float)
    present = ~np.isnan(values)
    if not present.any():
        raise GroupingError(f"{group.variable!r} has no observed values to group by")

    if group.cuts:
        edges = [float(edge) for edge in group.cuts]
    else:
        count = int(group.quantiles or 0)
        quantiles = np.linspace(0.0, 1.0, count + 1)[1:-1]
        edges = [float(np.nanquantile(values, q)) for q in quantiles]
        if len(set(edges)) != len(edges):
            raise GroupingError(
                f"{group.variable!r} cannot be split into {count} equal bins: its quantiles "
                f"coincide, which means most of its values are the same number. Use explicit "
                f"cuts, or group by something else."
            )

    masks: list[tuple[str, np.ndarray]] = []
    lower: float | None = None
    for edge in [*edges, None]:
        if lower is None and edge is not None:
            label, mask = f"< {_format_edge(edge)}", values < edge
        elif edge is None and lower is not None:
            label, mask = f">= {_format_edge(lower)}", values >= lower
        elif lower is not None and edge is not None:
            label = f"{_format_edge(lower)} to < {_format_edge(edge)}"
            mask = (values >= lower) & (values < edge)
        else:  # a single group, which the contract already refuses
            raise GroupingError(f"{group.variable!r} produced no cut points")
        masks.append((label, mask & present))
        lower = edge if edge is not None else lower
    return masks

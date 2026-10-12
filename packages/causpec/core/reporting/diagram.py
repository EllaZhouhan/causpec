"""The variable-role diagram, derived from the declared roles.

Mirrors design.md 7.5. The user is not asked to draw a DAG. Over forty ICU covariates a
full diagram is a formality nobody reads, and the parts of it that decide identification are
few. So the roles are declared, in the user's own words at confirmation, and the diagram is
**derived** from them.

Deriving rather than drawing buys the thing a picture cannot give: the same declaration that
produces the edges can be checked against the adjustment set, so a diagram that contradicts
the analysis is an error rather than a bad illustration. `check_roles` is that check.

The covariates are drawn as **one node** carrying a count and two examples, never as one node
per column. A box reading "7 confounders (max_creatinine, max_urea, ...)" says everything the
reader needs about a group whose members all play the same role, and an honest diagram that
fits on a screen is worth more than a complete one that does not.

Output is mermaid, which renders in GitHub, VS Code and most markdown viewers with no
dependency and no binary, plus the same graph as DOT for anyone who has graphviz. Both are
strings; nothing here imports a graph library, because the derived graph has a fixed shape and
the backdoor criterion over it reduces to the rules in ROLES_BARRED_FROM_ADJUSTMENT.

Only one non-edge is drawn: the exclusion restriction, instrument to outcome, because it joins
two nodes that are both on the diagram and a dashed arrow between them says something a reader
can object to. The free-text assumptions in `key_non_edges` are listed beneath the diagram
instead. Drawn as arrows from nowhere they read as edges that exist, which is the opposite of
what they mean.

What a derived diagram cannot express: causal relations **among** the covariates, for example
a declared confounder that is really a mediator of another confounder. That needs a full DAG,
which is the thing this design declines to ask for. The limitation is stated in the report
rather than hidden.
"""

from __future__ import annotations

from causpec.core.contracts.spec import Spec

# How many group members to name before trailing off. Two, because one looks like the whole
# group and three starts to be the list this exists to avoid.
EXAMPLES = 2

# The nodes every analysis has, with the labels the diagram uses.
TREATMENT = "A"
OUTCOME = "Y"


def _field_columns(spec: Spec, field: str) -> list[str]:
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _label(spec: Spec, field: str, fallback: str) -> str:
    columns = _field_columns(spec, field)
    return columns[0] if columns else fallback


def _group_label(role: str, members: list[str]) -> str:
    """One node for a group: how many, what they are, and two of them by name."""
    plural = role.replace("_", " ") + ("s" if len(members) != 1 else "")
    if len(members) <= EXAMPLES:
        return f"{len(members)} {plural}: {', '.join(members)}"
    shown = ", ".join(members[:EXAMPLES])
    return f"{len(members)} {plural}: {shown}, ..."


def _groups(spec: Spec) -> dict[str, list[str]]:
    """Declared variables by role, dropping the roles nobody declared."""
    grouped: dict[str, list[str]] = {}
    for name, role in spec.variable_roles.items():
        grouped.setdefault(role, []).append(name)
    return grouped


def mermaid(spec: Spec) -> str:
    """The diagram as mermaid source, ready to embed in markdown."""
    treatment = _label(spec, "treatment", "treatment")
    outcome = _label(spec, "outcome", "outcome")
    groups = _groups(spec)

    lines = ["```mermaid", "graph LR"]
    lines.append(f'  {TREATMENT}["{treatment}"]')
    lines.append(f'  {OUTCOME}["{outcome}"]')

    modifiers = _modifiers(spec, groups)
    edge_label = f'|"varies by {_group_label("effect modifier", modifiers)}"|' if modifiers else ""
    lines.append(f"  {TREATMENT} -->{edge_label} {OUTCOME}")

    for index, (role, members) in enumerate(sorted(groups.items())):
        if role == "effect_modifier":
            continue  # drawn on the treatment-outcome edge, not as a node
        node = f"N{index}"
        lines.append(f'  {node}["{_group_label(role, members)}"]')
        lines += _edges_for(role, node)

    if "instrument" in groups:
        # The exclusion restriction, and the only non-edge worth drawing: it joins two nodes
        # that are both on the diagram, so a dashed crossed arrow says something a reader can
        # object to. A free-text assumption drawn as an arrow from nowhere reads as an edge
        # that exists, which is the opposite of what it means, so those stay in the list the
        # report prints underneath.
        # `-. text .->` is already a dashed link. A linkStyle index would also work and was
        # tried, but it addresses edges by position, so adding a role above it silently
        # restyles the wrong arrow.
        instrument_node = _node_name(groups, "instrument")
        lines.append(f'  {instrument_node} -. "assumed absent" .-> {OUTCOME}')
    lines.append("```")
    return "\n".join(lines)


def _node_name(groups: dict[str, list[str]], role: str) -> str:
    """The node id a role was drawn with, matching the loop that drew it."""
    drawn = [name for name in sorted(groups) if name != "effect_modifier"]
    return f"N{sorted(groups).index(role)}" if role in drawn else role


def _modifiers(spec: Spec, groups: dict[str, list[str]]) -> list[str]:
    """What the effect is allowed to vary over, from both places it can be said.

    The `effect_modifiers` field is what the estimator actually consumes, so it decides the
    label. A variable declared `effect_modifier` in the roles but absent from the field is
    still drawn, because something declared should not disappear from the picture; the
    mismatch is the kind of thing `roles_match_adjustment` is there to notice.
    """
    declared = groups.get("effect_modifier", [])
    used = _field_columns(spec, "effect_modifiers")
    return used + [name for name in declared if name not in used]


def _edges_for(role: str, node: str) -> list[str]:
    """The edges a role implies. No freedom here, which is the point of deriving them."""
    if role == "confounder":
        return [f"  {node} --> {TREATMENT}", f"  {node} --> {OUTCOME}"]
    if role == "instrument":
        return [f"  {node} --> {TREATMENT}"]
    if role == "mediator":
        return [f"  {TREATMENT} --> {node}", f"  {node} --> {OUTCOME}"]
    if role == "suspected_collider":
        return [f"  {TREATMENT} --> {node}", f"  {OUTCOME} --> {node}"]
    if role == "post_treatment":
        return [f"  {TREATMENT} --> {node}"]
    return []


def dot(spec: Spec) -> str:
    """The same graph as DOT, for anyone who has graphviz.

    Derived from the same roles as the mermaid version, so the two cannot disagree.
    """
    treatment = _label(spec, "treatment", "treatment")
    outcome = _label(spec, "outcome", "outcome")
    groups = _groups(spec)

    lines = ["digraph roles {", "  rankdir=LR;", "  node [shape=box];"]
    lines.append(f'  A [label="{treatment}"];')
    lines.append(f'  Y [label="{outcome}"];')
    modifiers = _modifiers(spec, groups)
    if modifiers:
        lines.append(f'  A -> Y [label="varies by {_group_label("effect modifier", modifiers)}"];')
    else:
        lines.append("  A -> Y;")
    for index, (role, members) in enumerate(sorted(groups.items())):
        if role == "effect_modifier":
            continue
        node = f"N{index}"
        lines.append(f'  {node} [label="{_group_label(role, members)}"];')
        for edge in _edges_for(role, node):
            left, arrow, right = edge.strip().split(" ")
            del arrow
            lines.append(f"  {left} -> {right};")
    if "instrument" in groups:
        node = _node_name(groups, "instrument")
        lines.append(f'  {node} -> Y [style=dashed, label="assumed absent"];')
    lines.append("}")
    return "\n".join(lines)

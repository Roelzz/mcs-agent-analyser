"""Topic-settings explainer.

Walks a parsed topic's dialog action tree and produces a structured tree of
human-readable explanations sourced from `data/topic_explainer.yaml`.

Hard rule: every `summary` and `doc_url` returned by this module traces to a
primary Microsoft source (Microsoft Learn or `microsoft/skills-for-copilot-studio`).
When a kind/property isn't in the curated KB, the walker emits a visible
`not_yet_documented = True` sentinel so authors can see the gap and add it —
nothing is silently filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from models import ComponentSummary


_NOT_DOCUMENTED_SUMMARY = "Not yet documented in the explainer KB — add an entry to `data/topic_explainer.yaml`."

# Keys we walk into recursively or handle separately. Everything else on an
# action dict is treated as a property to look up.
_STRUCTURAL_KEYS: frozenset[str] = frozenset({"kind", "id", "actions", "elseActions", "conditions"})


@dataclass
class ExplainerProperty:
    """One property on an action/component, with its KB-sourced explanation."""

    path: str
    """Dot-notation property path, e.g. `knowledgeSources.kind`."""

    value: str
    """Rendered value (Power Fx expression, enum value, or scalar)."""

    summary: str | None
    """Human-readable description from the KB. None when not documented."""

    doc_url: str | None
    """Primary Microsoft source URL. None when not documented."""

    documented: bool


@dataclass
class ExplainerNode:
    """One action / trigger / component node in the explainer tree."""

    kind: str
    node_id: str | None
    category: str | None  # action | trigger | component | dialog | None
    summary: str | None
    doc_url: str | None
    documented: bool
    properties: list[ExplainerProperty] = field(default_factory=list)
    children: list[ExplainerNode] = field(default_factory=list)


# ── Loading ─────────────────────────────────────────────────────────────────


def load_kb(path: str | Path | None = None) -> dict:
    """Load the curated explainer KB from disk.

    Defaults to `data/topic_explainer.yaml` at the repo root.
    """
    if path is None:
        path = Path(__file__).resolve().parent.parent / "data" / "topic_explainer.yaml"
    with open(path, encoding="utf-8") as f:
        kb = yaml.safe_load(f) or {}
    if not isinstance(kb, dict) or "kinds" not in kb:
        raise ValueError(f"Invalid explainer KB at {path}: missing top-level `kinds`.")
    return kb


# ── Property flattening ─────────────────────────────────────────────────────


def _flatten_props(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten an action's property dict to dot-notation paths.

    The structural-keys filter (`kind`, `id`, `actions`, `conditions`,
    `elseActions`) only applies at the top level — those are interpreted as
    structure of the action itself, not properties to look up. At nested
    levels the filter does NOT apply, because a property dict like
    `knowledgeSources: { kind: SearchAllKnowledgeSources }` carries its
    own `kind` that we DO want to surface as `knowledgeSources.kind`.

    Lists of scalars join for display; lists of dicts render as a count.
    """
    out: dict[str, Any] = {}
    is_top_level = prefix == ""
    for key, value in d.items():
        if is_top_level and key in _STRUCTURAL_KEYS:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten_props(value, path))
        elif isinstance(value, list):
            if all(isinstance(item, (str, int, float, bool)) for item in value):
                out[path] = ", ".join(str(v) for v in value)
            else:
                out[path] = f"[{len(value)} item(s)]"
        else:
            out[path] = value
    return out


def _render_value(value: Any) -> str:
    """Render a property value for display."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Power Fx expressions begin with `=`; surface them verbatim.
        if len(value) > 200:
            return value[:200] + "…"
        return value
    return str(value)


# ── Lookup ──────────────────────────────────────────────────────────────────


def _lookup_kind(kind: str, kb: dict) -> dict | None:
    """Get the KB entry for a kind, or None when undocumented."""
    return (kb.get("kinds") or {}).get(kind)


def _lookup_property(
    path: str,
    value: Any,
    kind_entry: dict | None,
) -> tuple[str | None, str | None, bool]:
    """Resolve a property path → (summary, doc_url, documented).

    For enum properties, looks up the specific value's entry too and returns
    the enum-value's summary when available.
    """
    if kind_entry is None:
        return (None, None, False)
    props = kind_entry.get("properties") or {}
    entry = props.get(path)
    if entry is None:
        return (None, None, False)
    summary = entry.get("summary")
    doc = entry.get("doc")
    # Enum-value resolution
    if entry.get("type") == "enum":
        values = entry.get("values") or {}
        v_entry = values.get(value)
        if isinstance(v_entry, dict):
            v_summary = v_entry.get("summary")
            v_doc = v_entry.get("doc") or doc
            if v_summary:
                # Prepend the property-level summary as context for the enum value.
                if summary:
                    summary = f"{summary} — Value `{value}`: {v_summary}"
                else:
                    summary = f"Value `{value}`: {v_summary}"
                doc = v_doc
    return (summary, doc, True)


# ── Walker ──────────────────────────────────────────────────────────────────


def _walk_action(action: dict, kb: dict) -> ExplainerNode:
    """Convert one action dict into an ExplainerNode (recursive)."""
    kind = action.get("kind") or "Unknown"
    kind_entry = _lookup_kind(kind, kb)
    documented = kind_entry is not None

    summary = (kind_entry or {}).get("summary") if documented else None
    doc_url = (kind_entry or {}).get("doc") if documented else None
    category = (kind_entry or {}).get("category") if documented else None

    # Properties
    flat = _flatten_props(action)
    properties: list[ExplainerProperty] = []
    for path in sorted(flat.keys()):
        value = flat[path]
        prop_summary, prop_doc, prop_documented = _lookup_property(path, value, kind_entry)
        properties.append(
            ExplainerProperty(
                path=path,
                value=_render_value(value),
                summary=prop_summary,
                doc_url=prop_doc,
                documented=prop_documented,
            )
        )

    # Recurse into children: `actions`, `elseActions`, and condition branches.
    children: list[ExplainerNode] = []
    for sub in action.get("actions") or []:
        if isinstance(sub, dict):
            children.append(_walk_action(sub, kb))
    for cond in action.get("conditions") or []:
        if not isinstance(cond, dict):
            continue
        for sub in cond.get("actions") or []:
            if isinstance(sub, dict):
                children.append(_walk_action(sub, kb))
    for sub in action.get("elseActions") or []:
        if isinstance(sub, dict):
            children.append(_walk_action(sub, kb))

    return ExplainerNode(
        kind=kind,
        node_id=action.get("id"),
        category=category,
        summary=summary,
        doc_url=doc_url,
        documented=documented,
        properties=properties,
        children=children,
    )


def explain_topic(component: ComponentSummary, kb: dict) -> ExplainerNode | None:
    """Walk a topic component's dialog tree.

    Returns None when the component isn't a topic (no `raw_dialog`) so callers
    can cleanly skip non-topic components.
    """
    if component.kind != "DialogComponent" or not component.raw_dialog:
        return None
    raw = component.raw_dialog
    begin = raw.get("beginDialog")
    if not isinstance(begin, dict):
        # Topic without a beginDialog (rare — probably a malformed export).
        return ExplainerNode(
            kind="DialogComponent",
            node_id=component.schema_name,
            category="component",
            summary=f"Topic `{component.display_name}` has no `beginDialog` — cannot walk action tree.",
            doc_url=None,
            documented=False,
        )
    return _walk_action(begin, kb)


def explain_component(component: ComponentSummary, kb: dict) -> ExplainerNode:
    """Build an ExplainerNode for a non-topic component (knowledge source, GPT, etc).

    Uses the component's parsed properties (source_kind, trigger_condition_raw,
    etc) — not a raw YAML walk, since for non-DialogComponent kinds the parser
    already extracts what we need into ComponentSummary fields.
    """
    kind = component.kind
    kind_entry = _lookup_kind(kind, kb)
    documented = kind_entry is not None
    properties: list[ExplainerProperty] = []
    if kind == "KnowledgeSourceComponent":
        # Surface the well-known properties through dot-notation paths so they
        # match the KB entries.
        if component.source_kind:
            s, d, doc_ok = _lookup_property("configuration.source.kind", component.source_kind, kind_entry)
            properties.append(
                ExplainerProperty(
                    path="configuration.source.kind",
                    value=component.source_kind,
                    summary=s,
                    doc_url=d,
                    documented=doc_ok,
                )
            )
        if component.trigger_condition_raw is not None:
            s, d, doc_ok = _lookup_property(
                "configuration.source.triggerCondition",
                component.trigger_condition_raw,
                kind_entry,
            )
            properties.append(
                ExplainerProperty(
                    path="configuration.source.triggerCondition",
                    value=component.trigger_condition_raw,
                    summary=s,
                    doc_url=d,
                    documented=doc_ok,
                )
            )
        if component.source_site:
            s, d, doc_ok = _lookup_property("configuration.source.site", component.source_site, kind_entry)
            properties.append(
                ExplainerProperty(
                    path="configuration.source.site",
                    value=component.source_site,
                    summary=s,
                    doc_url=d,
                    documented=doc_ok,
                )
            )
    elif kind == "GlobalVariableComponent" and component.variable_scope:
        s, d, doc_ok = _lookup_property("variable.scope", component.variable_scope, kind_entry)
        properties.append(
            ExplainerProperty(
                path="variable.scope",
                value=component.variable_scope,
                summary=s,
                doc_url=d,
                documented=doc_ok,
            )
        )

    return ExplainerNode(
        kind=kind,
        node_id=component.schema_name,
        category=(kind_entry or {}).get("category") if documented else None,
        summary=(kind_entry or {}).get("summary") if documented else None,
        doc_url=(kind_entry or {}).get("doc") if documented else None,
        documented=documented,
        properties=properties,
    )


# ── Coverage helpers (used by tests) ────────────────────────────────────────


def collect_kinds(node: ExplainerNode) -> set[str]:
    """All `kind` strings encountered in the tree, for coverage assertions."""
    kinds = {node.kind}
    for child in node.children:
        kinds |= collect_kinds(child)
    return kinds


def collect_undocumented(node: ExplainerNode) -> list[ExplainerNode]:
    """Walk the tree and return every node where `documented=False`."""
    out: list[ExplainerNode] = []
    if not node.documented:
        out.append(node)
    for child in node.children:
        out.extend(collect_undocumented(child))
    return out


# ── Flattening for UI consumption ───────────────────────────────────────────


def flatten_to_rows(node: ExplainerNode, depth: int = 0) -> list[dict]:
    """Flatten an ExplainerNode tree into a list of UI-friendly row dicts.

    Each row is one of two shapes:

    - **kind row** (the action / trigger / component itself)
        ``{"row_type": "kind", "depth", "kind", "node_id", "summary", "doc_url",
           "documented"}``

    - **prop row** (one property under a kind)
        ``{"row_type": "prop", "depth", "path", "value", "summary", "doc_url",
           "documented"}``

    The depth indicates nesting. Properties get `depth + 1` relative to their
    owning kind, so the renderer can indent them once. Children of a kind
    get `depth + 1` relative to that kind too.

    Stable ordering: kind row → its properties (alphabetical by path) → its
    children (in walk order). This keeps the UI predictable.
    """
    rows: list[dict] = [
        {
            "row_type": "kind",
            "depth": depth,
            "kind": node.kind,
            "node_id": node.node_id or "",
            "summary": node.summary or "",
            "doc_url": node.doc_url or "",
            "documented": "true" if node.documented else "",
            # Filled below for the kind row's "value" placeholder; UI renders blank.
            "path": "",
            "value": "",
        }
    ]
    for prop in node.properties:
        rows.append(
            {
                "row_type": "prop",
                "depth": depth + 1,
                "kind": node.kind,
                "node_id": node.node_id or "",
                "path": prop.path,
                "value": prop.value,
                "summary": prop.summary or "",
                "doc_url": prop.doc_url or "",
                "documented": "true" if prop.documented else "",
            }
        )
    for child in node.children:
        rows.extend(flatten_to_rows(child, depth + 1))
    return rows


def settings_rows_for_topic(component: ComponentSummary, kb: dict) -> list[dict]:
    """Produce a flat list of UI rows for a topic component.

    Returns an empty list when the component isn't a topic.
    """
    root = explain_topic(component, kb)
    if root is None:
        return []
    return flatten_to_rows(root)


# ── Markdown rendering ──────────────────────────────────────────────────────


def render_explainer_node_markdown(node: ExplainerNode, depth: int = 0) -> list[str]:
    """Render an ExplainerNode (and its children) as markdown lines.

    Used by both the report renderer and as the canonical text representation
    in tests.
    """
    indent = "  " * depth
    icon = "🟢" if node.documented else "⚪"
    title_id = f" `({node.node_id})`" if node.node_id else ""
    lines: list[str] = []
    lines.append(f"{indent}- {icon} **{node.kind}**{title_id}")
    if node.documented and node.summary:
        lines.append(f"{indent}  {node.summary}")
    elif not node.documented:
        lines.append(f"{indent}  *{_NOT_DOCUMENTED_SUMMARY}*")
    if node.doc_url:
        lines.append(f"{indent}  [Microsoft docs ↗]({node.doc_url})")
    for prop in node.properties:
        prop_icon = "•" if prop.documented else "?"
        value_disp = f"`{prop.value}`" if prop.value not in ("—", "") else "—"
        lines.append(f"{indent}  - {prop_icon} `{prop.path}`: {value_disp}")
        if prop.summary:
            lines.append(f"{indent}    {prop.summary}")
        elif not prop.documented:
            lines.append(f"{indent}    *Property not documented in KB.*")
        if prop.doc_url:
            lines.append(f"{indent}    [docs ↗]({prop.doc_url})")
    for child in node.children:
        lines.extend(render_explainer_node_markdown(child, depth + 1))
    return lines


def render_explainer_for_topic(component: ComponentSummary, kb: dict) -> str:
    """Top-level entry point: render a topic's settings-explained markdown block."""
    root = explain_topic(component, kb)
    if root is None:
        return ""
    lines = [f"### Settings explained — {component.display_name or component.schema_name}\n"]
    lines.extend(render_explainer_node_markdown(root))
    return "\n".join(lines) + "\n"

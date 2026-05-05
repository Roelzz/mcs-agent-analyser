"""Shared utilities for constraint modules.

Includes a topic / knowledge-source / tool lookup so each rule can build
`ComponentRef` lists without re-scanning the BotProfile.
"""

from __future__ import annotations

from typing import Iterable

from diagnosis.models import ComponentRef
from models import BotProfile, ComponentSummary


_KIND_MAP = {
    "TaskDialog": "tool",
    "AgentDialog": "agent",
    "DialogComponent": "topic",
    "GptComponent": "agent",
    "KnowledgeSource": "knowledge_source",
    "Variable": "global_variable",
}


def _resolve_kind(comp: ComponentSummary) -> str:
    return _KIND_MAP.get(comp.kind, comp.kind.lower())


def component_ref_for_schema(profile: BotProfile, schema_name: str | None) -> list[ComponentRef]:
    """Return a single-item ComponentRef list for the named schema_name, or
    empty list if not found. Empty list is fine — recommendations gracefully
    handle the no-ref case."""
    if not schema_name:
        return []
    for comp in profile.components:
        if comp.schema_name == schema_name:
            return [
                ComponentRef(
                    kind=_resolve_kind(comp),  # type: ignore[arg-type]
                    schema_name=comp.schema_name,
                    display_name=comp.display_name,
                )
            ]
    return []


def component_refs_by_kind(profile: BotProfile, kinds: Iterable[str]) -> list[ComponentRef]:
    """All components whose `kind` is in the given set, as ComponentRefs."""
    target = set(kinds)
    return [
        ComponentRef(
            kind=_resolve_kind(comp),  # type: ignore[arg-type]
            schema_name=comp.schema_name,
            display_name=comp.display_name,
        )
        for comp in profile.components
        if comp.kind in target
    ]

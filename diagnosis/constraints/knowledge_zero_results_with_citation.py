"""Rule: knowledge_zero_results_with_citation

A knowledge search returned 0 results and the next bot turn cites a URL or
numbered citation. Strong invention-of-information signal.
"""

from __future__ import annotations

from diagnosis.constraints._helpers import component_refs_by_kind
from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline, EventType


RULE_ID = "knowledge_zero_results_with_citation"

_CITATION_TOKENS = ("http://", "https://", "[1]", "[2]", "according to", "source:")


def check(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    bot_messages = [e for e in timeline.events if e.event_type == EventType.BOT_MESSAGE]
    knowledge_refs = component_refs_by_kind(profile, ["KnowledgeSource"])

    for ks in timeline.knowledge_searches or []:
        if ks.search_results:
            continue
        following = [m for m in bot_messages if m.position >= ks.position]
        if not following:
            continue
        text = (following[0].summary or "").lower()
        if not any(tok in text for tok in _CITATION_TOKENS):
            continue
        out.append(
            ConstraintViolation(
                rule_id=RULE_ID,
                step_index=following[0].position,
                severity="critical",
                description=(
                    "Knowledge search returned zero results, but the bot's next reply "
                    "cited a source — likely fabricated."
                ),
                evidence={
                    "search_position": ks.position,
                    "search_query": ks.search_query,
                    "knowledge_sources": ks.knowledge_sources,
                    "bot_reply_excerpt": (following[0].summary or "")[:200],
                },
                component_refs=knowledge_refs,
                default_category_seed=FailureCategory.INVENTION,
            )
        )
    return out

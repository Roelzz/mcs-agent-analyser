"""Rule: fallback_when_match_plausible

The orchestrator redirected to a fallback / system-fallback topic while a
non-fallback topic had a plausible trigger-phrase match against the user's
query. Uses a cheap difflib ratio rather than embeddings.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from diagnosis.constraints._helpers import component_ref_for_schema
from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline, EventType


RULE_ID = "fallback_when_match_plausible"
PLAUSIBLE_MATCH_THRESHOLD = 0.6
_FALLBACK_NAME_TOKENS = ("fallback", "default", "no_match", "system_fallback")


def _looks_like_fallback(name: str | None) -> bool:
    if not name:
        return False
    lower = name.lower()
    return any(tok in lower for tok in _FALLBACK_NAME_TOKENS)


def _best_match(query: str, profile: BotProfile) -> tuple[str | None, float]:
    """Highest trigger-phrase similarity to `query`, ignoring fallback topics."""
    best_schema: str | None = None
    best_score = 0.0
    q = query.lower().strip()
    if not q:
        return None, 0.0
    for comp in profile.components:
        if comp.kind != "DialogComponent":
            continue
        if _looks_like_fallback(comp.schema_name) or _looks_like_fallback(comp.display_name):
            continue
        for phrase in comp.trigger_queries or []:
            score = SequenceMatcher(None, q, (phrase or "").lower()).ratio()
            if score > best_score:
                best_score = score
                best_schema = comp.schema_name
    return best_schema, best_score


def check(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []

    # Pair each user message with the topic that triggered after it.
    user_msgs = [e for e in timeline.events if e.event_type == EventType.USER_MESSAGE]
    for user_ev in user_msgs:
        # Find the next DIALOG_REDIRECT or STEP_TRIGGERED that lands in a fallback topic
        for ev in timeline.events:
            if ev.position <= user_ev.position:
                continue
            if ev.event_type not in (EventType.DIALOG_REDIRECT, EventType.STEP_TRIGGERED):
                continue
            if not _looks_like_fallback(ev.topic_name):
                # First non-fallback trigger means the orchestrator made a
                # non-fallback choice — stop scanning for this user turn.
                break
            best_schema, score = _best_match(user_ev.summary or "", profile)
            if score < PLAUSIBLE_MATCH_THRESHOLD or best_schema is None:
                break
            out.append(
                ConstraintViolation(
                    rule_id=RULE_ID,
                    step_index=ev.position,
                    severity="warn",
                    description=(
                        f"Routed to fallback topic '{ev.topic_name}' but topic "
                        f"'{best_schema}' had a {score:.0%} trigger-phrase match."
                    ),
                    evidence={
                        "fallback_topic": ev.topic_name,
                        "user_message": user_ev.summary,
                        "best_alternative_schema": best_schema,
                        "match_score": round(score, 3),
                    },
                    component_refs=component_ref_for_schema(profile, best_schema),
                    default_category_seed=FailureCategory.PLAN_ADHERENCE,
                )
            )
            break
    return out

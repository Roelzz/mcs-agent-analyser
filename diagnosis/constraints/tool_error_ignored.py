"""Rule: tool_error_ignored

A tool call failed (state == "failed") AND the next bot turn doesn't
acknowledge the error or quote any of its content. Strong tool-misinterpretation
signal — the agent saw the failure and proceeded as if it succeeded.
"""

from __future__ import annotations

from diagnosis.constraints._helpers import component_ref_for_schema
from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline, EventType


RULE_ID = "tool_error_ignored"

_ACK_TOKENS = (
    "couldn't",
    "could not",
    "wasn't able",
    "was not able",
    "unable",
    "sorry",
    "apolog",
    "error",
    "failed",
    "issue",
    "problem",
    "try again",
)


def _ack_substring_present(text: str, error_str: str) -> bool:
    lower = (text or "").lower()
    if any(tok in lower for tok in _ACK_TOKENS):
        return True
    if error_str and len(error_str) > 8:
        # Quote of any meaningful chunk of the error counts as acknowledgement.
        return any(chunk in lower for chunk in error_str.lower().split() if len(chunk) > 6)
    return False


def check(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    bot_messages = [e for e in timeline.events if e.event_type == EventType.BOT_MESSAGE]

    for tc in timeline.tool_calls:
        if tc.state != "failed":
            continue
        following = [m for m in bot_messages if m.position > tc.position]
        if not following:
            # No reply at all → SYSTEM_FAILURE territory rather than ignored.
            continue
        first_reply = following[0]
        if _ack_substring_present(first_reply.summary or "", tc.error or ""):
            continue
        out.append(
            ConstraintViolation(
                rule_id=RULE_ID,
                step_index=first_reply.position,
                severity="critical",
                description=(
                    f"Tool '{tc.display_name or tc.task_dialog_id}' failed but the bot's "
                    "next reply did not acknowledge the error."
                ),
                evidence={
                    "tool_position": tc.position,
                    "tool_display_name": tc.display_name,
                    "task_dialog_id": tc.task_dialog_id,
                    "tool_error": tc.error,
                    "bot_reply_excerpt": (first_reply.summary or "")[:200],
                },
                component_refs=component_ref_for_schema(profile, tc.task_dialog_id),
                default_category_seed=FailureCategory.TOOL_MISINTERPRETATION,
            )
        )
    return out

"""Rule: automatic_retry_after_misinterpretation

A generative-answer attempt failed with `previous_attempt_state in
{Not Found, Wrong}` AND the previous attempt had ≥ 1 search result.
The orchestrator retried automatically and may have succeeded, but the first
attempt's behaviour is a tool-misinterpretation signal worth recording even
when recovery happens — flaky knowledge sources surface this way.
"""

from __future__ import annotations

from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline


RULE_ID = "automatic_retry_after_misinterpretation"

_MISREAD_STATES = {"answer not found in search results", "answer not found", "not found", "wrong"}


def check(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    traces = list(timeline.generative_answer_traces or [])

    for idx, trace in enumerate(traces):
        if not trace.is_retry:
            continue
        prev_state = (trace.previous_attempt_state or "").strip().lower()
        if prev_state not in _MISREAD_STATES:
            continue
        # Find the attempt this retry replaces — the immediately-preceding trace
        # for the same activity_id, or by position if activity_id unset.
        prev_trace = None
        for candidate in reversed(traces[:idx]):
            if trace.activity_id and candidate.activity_id == trace.activity_id:
                prev_trace = candidate
                break
            if candidate.position < trace.position:
                prev_trace = candidate
                break
        prev_hits = len(prev_trace.search_results) if prev_trace else 0
        if prev_hits == 0:
            # No results to misread — UNDERSPECIFIED_INTENT, not this rule.
            continue
        out.append(
            ConstraintViolation(
                rule_id=RULE_ID,
                step_index=prev_trace.position if prev_trace else trace.position,
                severity="warn",
                description=(
                    "First attempt produced 'Not Found / Wrong' despite "
                    f"{prev_hits} search hits; orchestrator auto-retried."
                ),
                evidence={
                    "topic_name": trace.topic_name,
                    "previous_state": trace.previous_attempt_state,
                    "previous_search_hits": prev_hits,
                    "retry_attempt_index": trace.attempt_index,
                    "retry_succeeded": (trace.gpt_answer_state or "").strip().lower() == "answered",
                },
                default_category_seed=FailureCategory.TOOL_MISINTERPRETATION,
            )
        )
    return out

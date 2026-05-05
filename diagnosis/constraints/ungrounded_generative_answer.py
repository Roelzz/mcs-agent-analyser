"""Rule: ungrounded_generative_answer

A generative-answer node either fell back to GPT defaults (`triggered_fallback`)
or produced an answer with state="Answered" but zero citations. Both indicate
the bot returned ungrounded content despite a grounded-only configuration.
"""

from __future__ import annotations

from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline


RULE_ID = "ungrounded_generative_answer"


def check(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for trace in timeline.generative_answer_traces or []:
        state = (trace.gpt_answer_state or "").strip().lower()
        if trace.triggered_fallback:
            out.append(
                ConstraintViolation(
                    rule_id=RULE_ID,
                    step_index=trace.position,
                    severity="critical",
                    description="Generative answer fell back to GPT default response — no grounding.",
                    evidence={
                        "topic_name": trace.topic_name,
                        "attempt_index": trace.attempt_index,
                        "search_result_count": len(trace.search_results),
                    },
                    default_category_seed=FailureCategory.INVENTION,
                )
            )
        elif state == "answered" and not trace.citations:
            out.append(
                ConstraintViolation(
                    rule_id=RULE_ID,
                    step_index=trace.position,
                    severity="warn",
                    description=(
                        "Generative answer claimed Answered but produced no citations — "
                        "may indicate ungrounded output under grounded-only config."
                    ),
                    evidence={
                        "topic_name": trace.topic_name,
                        "attempt_index": trace.attempt_index,
                        "search_result_count": len(trace.search_results),
                    },
                    default_category_seed=FailureCategory.GUARDRAILS,
                )
            )
    return out

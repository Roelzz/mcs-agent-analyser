"""Critical-step localization.

Verbatim port of AgentRx's root-cause detection algorithm:

    1. Locate the first failure: scan trajectory step-by-step from start.
    2. Check if that failure was resolved: look ahead for evidence.
    3. If resolved, continue scanning. If not resolved, treat this step as
       the root-cause failure.

Recovery evidence in Copilot Studio:

- A later `GenerativeAnswerTrace.gpt_answer_state == "Answered"` resolves
  any prior unanswered / wrong-answer violation.
- A later `ToolCall.state == "completed"` for the same `task_dialog_id`
  resolves a prior tool-failure violation on that tool.
- A final bot turn that delivers a grounded reply (after at least one
  successful knowledge or tool grounding event) resolves softer issues.
"""

from __future__ import annotations

from diagnosis.models import ConstraintViolation
from models import ConversationTimeline


def _has_later_answered(timeline: ConversationTimeline, after_position: int) -> bool:
    for trace in timeline.generative_answer_traces or []:
        if trace.position > after_position and (trace.gpt_answer_state or "").strip().lower() == "answered":
            return True
    return False


def _has_later_successful_tool_for(
    timeline: ConversationTimeline, after_position: int, task_dialog_id: str | None
) -> bool:
    for tc in timeline.tool_calls:
        if tc.position <= after_position:
            continue
        if tc.state != "completed":
            continue
        if task_dialog_id is None or tc.task_dialog_id == task_dialog_id:
            return True
    return False


def _violation_recovered(violation: ConstraintViolation, timeline: ConversationTimeline) -> bool:
    after = violation.step_index

    # Generative-answer recovery covers most knowledge / answer-shaped failures.
    if _has_later_answered(timeline, after):
        return True

    # Tool-shaped failures: prefer matching by task_dialog_id when the rule
    # captured one in evidence; otherwise any later success counts.
    task_dialog_id = None
    evidence = violation.evidence or {}
    if isinstance(evidence, dict):
        task_dialog_id = evidence.get("task_dialog_id")
    if _has_later_successful_tool_for(timeline, after, task_dialog_id):
        return True

    return False


def pick_critical_step(
    violations: list[ConstraintViolation],
    timeline: ConversationTimeline,
) -> ConstraintViolation | None:
    """Return the first critical/warn violation that the agent did not
    later recover from. None means the conversation succeeded."""
    for v in sorted(violations, key=lambda x: x.step_index):
        if v.severity not in ("critical", "warn"):
            continue
        if not _violation_recovered(v, timeline):
            return v
    return None

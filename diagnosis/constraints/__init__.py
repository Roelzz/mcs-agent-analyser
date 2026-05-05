"""Constraint registry — one file per rule for diff-ability.

Each rule module exposes a `check(profile, timeline) -> list[ConstraintViolation]`
function. The registry aggregates them and exposes `run_constraints` as the
single entry point used by `diagnosis.orchestrator`.
"""

from __future__ import annotations

from diagnosis.constraints import (
    automatic_retry_after_misinterpretation,
    fallback_when_match_plausible,
    knowledge_zero_results_with_citation,
    slot_loop_no_progress,
    tool_error_ignored,
    ungrounded_generative_answer,
)
from diagnosis.models import ConstraintViolation
from models import BotProfile, ConversationTimeline


_RULES = (
    knowledge_zero_results_with_citation,
    fallback_when_match_plausible,
    slot_loop_no_progress,
    tool_error_ignored,
    ungrounded_generative_answer,
    automatic_retry_after_misinterpretation,
)


def run_constraints(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    """Run every registered rule, aggregate violations, sort by step_index."""
    out: list[ConstraintViolation] = []
    for module in _RULES:
        out.extend(module.check(profile, timeline))
    out.sort(key=lambda v: (v.step_index, v.rule_id))
    return out


__all__ = ["run_constraints"]

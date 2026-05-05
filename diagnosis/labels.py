"""Shared label / colour-group lookups for the AgentRx failure taxonomy.

Used by the Markdown renderer, the Reflex state projector, and any future
surface that needs to display category metadata. Keeping these in one place
prevents drift (e.g. UI showing "Tool Misinterpretation" while the report
says "Misinterpretation of Tool Output").
"""

from __future__ import annotations

from diagnosis.models import FailureCategory


CATEGORY_LABELS: dict[FailureCategory, str] = {
    FailureCategory.PLAN_ADHERENCE: "Plan Adherence Failure",
    FailureCategory.INVENTION: "Invention of New Information",
    FailureCategory.INVALID_INVOCATION: "Invalid Invocation",
    FailureCategory.TOOL_MISINTERPRETATION: "Misinterpretation of Tool Output",
    FailureCategory.INTENT_PLAN_MISALIGNMENT: "Intent-Plan Misalignment",
    FailureCategory.UNDERSPECIFIED_INTENT: "Underspecified User Intent",
    FailureCategory.INTENT_NOT_SUPPORTED: "Intent Not Supported",
    FailureCategory.GUARDRAILS: "Guardrails Triggered",
    FailureCategory.SYSTEM_FAILURE: "System Failure",
    FailureCategory.INCONCLUSIVE: "Inconclusive",
}


# Colour groups follow the AgentRx integration plan §11:
#   red    — agent-side failures (the agent itself misbehaved)
#   amber  — user/agent gap (intent mismatches, scope, ambiguity)
#   gray   — environmental (guardrails, infrastructure)
#   white  — unclassified (Inconclusive)
GROUP_BADGES: dict[FailureCategory, str] = {
    FailureCategory.PLAN_ADHERENCE: "🔴",
    FailureCategory.INVENTION: "🔴",
    FailureCategory.INVALID_INVOCATION: "🔴",
    FailureCategory.TOOL_MISINTERPRETATION: "🔴",
    FailureCategory.INTENT_PLAN_MISALIGNMENT: "🟠",
    FailureCategory.UNDERSPECIFIED_INTENT: "🟠",
    FailureCategory.INTENT_NOT_SUPPORTED: "🟠",
    FailureCategory.GUARDRAILS: "⚫",
    FailureCategory.SYSTEM_FAILURE: "⚫",
    FailureCategory.INCONCLUSIVE: "⚪",
}


def label_for(category: FailureCategory | None) -> str:
    if category is None:
        return ""
    return CATEGORY_LABELS.get(category, category.value)


def badge_for(category: FailureCategory | None) -> str:
    if category is None:
        return ""
    return GROUP_BADGES.get(category, "⚪")

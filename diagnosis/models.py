"""AgentRx-style failure-diagnosis data model.

Lifts the 10-category taxonomy from microsoft/AgentRx (the article that
inspired this work cited 9; the repo lists 10, with `Inconclusive` as the 10th —
included so the judge can decline rather than guess).

The Pydantic models live here so they can be re-exported from the top of
the analyser without cycles, and so the diagnosis subpackage doesn't have
to depend on anything outside its own directory.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    """10-category failure taxonomy (verbatim from microsoft/AgentRx)."""

    PLAN_ADHERENCE = "plan_adherence_failure"
    INVENTION = "invention_of_new_information"
    INVALID_INVOCATION = "invalid_invocation"
    TOOL_MISINTERPRETATION = "misinterpretation_of_tool_output"
    INTENT_PLAN_MISALIGNMENT = "intent_plan_misalignment"
    UNDERSPECIFIED_INTENT = "underspecified_user_intent"
    INTENT_NOT_SUPPORTED = "intent_not_supported"
    GUARDRAILS = "guardrails_triggered"
    SYSTEM_FAILURE = "system_failure"
    INCONCLUSIVE = "inconclusive"


# Stable ordering — `failure_case` int returned by the judge is 1-based and
# follows this declaration order. Keep in sync with prompts/judge.md.
FAILURE_CATEGORY_ORDER: list[FailureCategory] = list(FailureCategory)


def category_from_index(failure_case: int) -> FailureCategory:
    """Map the judge's 1..10 `failure_case` integer to a category."""
    if not 1 <= failure_case <= len(FAILURE_CATEGORY_ORDER):
        raise ValueError(f"failure_case must be 1..{len(FAILURE_CATEGORY_ORDER)}, got {failure_case}")
    return FAILURE_CATEGORY_ORDER[failure_case - 1]


class ComponentRef(BaseModel):
    """Pointer back to the originating botContent.yml entry. Designed in
    from day one so canned and AI recommendations can reference exact
    artefacts (topic schema_name, knowledge source, tool, etc.) instead of
    abstract step numbers."""

    kind: Literal["topic", "knowledge_source", "tool", "agent", "global_variable"]
    schema_name: str
    display_name: str
    action_id: str | None = None  # for sub-action pinpoints inside a topic dialog


class ConstraintViolation(BaseModel):
    rule_id: str
    step_index: int
    severity: Literal["info", "warn", "critical"]
    description: str
    evidence: dict = Field(default_factory=dict)
    component_refs: list[ComponentRef] = Field(default_factory=list)
    # Default category seed used when the LLM judge is offline — lets the
    # heuristic-only path pick a category from the highest-severity rule.
    default_category_seed: FailureCategory | None = None


class Recommendation(BaseModel):
    source: Literal["canned", "llm"]
    title: str
    body_md: str
    component_refs: list[ComponentRef] = Field(default_factory=list)


class SecondaryFailure(BaseModel):
    """A failure step the LLM judge identified beyond the primary critical
    step. AgentRx's `failure_case` is per-trajectory, but trajectories
    typically contain multiple failures (~68% per the AgentRx benchmark);
    secondaries surface those without diluting the primary verdict."""

    step_index: int
    category: FailureCategory
    reason: str
    severity: Literal["low", "medium", "high"] = "medium"


class DiagnosisReport(BaseModel):
    """End-to-end diagnosis output. One per (transcript, judge_model, redaction) tuple."""

    transcript_id: str
    bot_id: str
    outcome: str
    critical_step_index: int | None
    category: FailureCategory
    confidence: Literal["low", "medium", "high"]

    # Lifted from AgentRx judge schema — preserved verbatim for fidelity.
    taxonomy_checklist_reasoning: str = ""
    reason_for_failure: str = ""
    reason_for_index: str = ""

    # Local additions on top of AgentRx's schema.
    summary: str = ""
    violations: list[ConstraintViolation] = Field(default_factory=list)
    secondary_failures: list[SecondaryFailure] = Field(default_factory=list)
    canned_recommendations: list[Recommendation] = Field(default_factory=list)
    llm_recommendations: list[Recommendation] = Field(default_factory=list)

    generated_at: datetime
    judge_model: str = ""  # empty when run offline / heuristic-only
    redaction_summary: dict = Field(default_factory=dict)
    # Raw JSON the judge returned. Cached so the chat-with-judge feature can
    # rebuild the same conversation context without re-paying for a judge
    # call. Empty when no judge ran (heuristic-only path).
    judge_verdict_raw: dict | None = None

    # True when the judge call itself failed (parse error, network, etc.). The
    # UI must render this differently from a real Inconclusive verdict so users
    # don't mistake a crash for a diagnosis.
    error_state: bool = False
    error_message: str = ""

    @property
    def succeeded(self) -> bool:
        """No critical violation found and no error → conversation looks clean."""
        return (
            not self.error_state
            and self.critical_step_index is None
            and not any(v.severity == "critical" for v in self.violations)
        )

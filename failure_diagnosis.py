"""AgentRx-style failure diagnostics for Copilot Studio conversations.

Walks a `ConversationTimeline` step by step, applies a registry of constraints
to each event, and produces a `FailureDiagnosisReport` containing:

- a violation log (every constraint that fired, in position order),
- a critical-step pick (the first violation that the agent does not later
  recover from), and
- an optional LLM judge verdict that maps the critical step to one of the nine
  `FailureCategory` values plus a root-cause step.

The constraint set deliberately reuses signals already extracted by
`timeline.build_timeline` (ToolCall.state, GenerativeAnswerTrace.gpt_answer_state,
KnowledgeSearchInfo.search_results, plan thrashing) — there's no new parsing.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Iterable

from loguru import logger

from conversation_analysis import analyze_plan_diffs
from models import (
    BotProfile,
    ConversationTimeline,
    EventType,
    FailureCategory,
    TimelineEvent,
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConstraintViolation:
    position: int
    constraint_id: str
    severity: str  # "fail", "warning", "info"
    evidence: str
    suggested_category: FailureCategory | None = None
    related_event_position: int | None = None


@dataclass
class FailureDiagnosis:
    critical_step_position: int | None = None
    category: FailureCategory | None = None
    confidence: float = 0.0
    root_cause_position: int | None = None
    contributing_violations: list[ConstraintViolation] = field(default_factory=list)
    summary: str = ""
    fix_suggestion: str = ""
    judge_used: bool = False


@dataclass
class FailureDiagnosisReport:
    succeeded: bool = False
    diagnosis: FailureDiagnosis | None = None
    violations: list[ConstraintViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constraint synthesis (programmatic layer)
# ---------------------------------------------------------------------------

# Substrings inside a ToolCall.error that point at infrastructure rather than
# bad arguments. Keep the list short and accumulate via real fixtures.
_SYSTEM_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "5xx",
    "502 ",
    "503 ",
    "504 ",
    "network",
    "connection reset",
    "rate limit",
    "rate-limit",
)


def _tool_call_violations(timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for tc in timeline.tool_calls:
        if tc.state != "failed":
            continue
        err = (tc.error or "").lower()
        is_system = any(m in err for m in _SYSTEM_ERROR_MARKERS)
        category = FailureCategory.SYSTEM_FAILURE if is_system else FailureCategory.INVALID_INVOCATION
        out.append(
            ConstraintViolation(
                position=tc.position,
                constraint_id=("tool.system_error" if is_system else "tool.failed_invocation"),
                severity="fail",
                evidence=(f"Tool '{tc.display_name or tc.task_dialog_id}' failed: {tc.error or 'no error message'}")[
                    :240
                ],
                suggested_category=category,
            )
        )
    return out


def _generative_answer_violations(
    timeline: ConversationTimeline,
) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    traces = timeline.generative_answer_traces or []
    for trace in traces:
        state = (trace.gpt_answer_state or "").strip().lower()
        if trace.triggered_fallback:
            out.append(
                ConstraintViolation(
                    position=trace.position,
                    constraint_id="generative_answer.fallback",
                    severity="fail",
                    evidence="Generative answer fell back to GPT default response (no grounding).",
                    suggested_category=FailureCategory.INVENTED_INFO,
                )
            )
        elif state and state not in {"answered", ""}:
            # "Answer not Found in Search Results" with non-empty results means the
            # bot misread the search output → MISINTERPRETED_TOOL_OUTPUT. With no
            # results it's UNDERSPECIFIED_INTENT (or genuinely missing knowledge,
            # which we leave to the LLM judge to disambiguate).
            if any(s in state for s in ("not found", "wrong", "avoided")):
                if trace.search_results:
                    suggested = FailureCategory.MISINTERPRETED_TOOL_OUTPUT
                else:
                    suggested = FailureCategory.UNDERSPECIFIED_INTENT
                out.append(
                    ConstraintViolation(
                        position=trace.position,
                        constraint_id="generative_answer.unanswered",
                        severity="fail",
                        evidence=(
                            f"Generative answer state: {trace.gpt_answer_state} "
                            f"(attempt {trace.attempt_index}, "
                            f"{len(trace.search_results)} search hits)."
                        ),
                        suggested_category=suggested,
                    )
                )
        if trace.contains_confidential:
            out.append(
                ConstraintViolation(
                    position=trace.position,
                    constraint_id="generative_answer.confidential_filtered",
                    severity="warning",
                    evidence="Answer contained confidential content and was suppressed by guardrails.",
                    suggested_category=FailureCategory.GUARDRAILS_TRIGGERED,
                )
            )
    return out


def _knowledge_search_violations(
    timeline: ConversationTimeline,
) -> list[ConstraintViolation]:
    """Zero-result search followed by a bot message that quotes a URL = invented info."""
    out: list[ConstraintViolation] = []
    bot_messages = [e for e in timeline.events if e.event_type == EventType.BOT_MESSAGE]
    for ks in timeline.knowledge_searches or []:
        if ks.search_results:
            continue
        # Look for a bot message after the search that looks like it cites something.
        following = [m for m in bot_messages if m.position >= ks.position]
        if not following:
            continue
        first_msg = following[0]
        text = first_msg.summary or ""
        looks_cited = any(
            tok in text.lower() for tok in ("http://", "https://", "[1]", "[2]", "according to", "source:")
        )
        if looks_cited:
            out.append(
                ConstraintViolation(
                    position=first_msg.position,
                    constraint_id="knowledge.zero_result_with_citation",
                    severity="fail",
                    evidence=(
                        f"Knowledge search at position {ks.position} returned 0 hits, "
                        f"but the following bot message cites a source."
                    ),
                    suggested_category=FailureCategory.INVENTED_INFO,
                    related_event_position=ks.position,
                )
            )
    return out


def _plan_violations(timeline: ConversationTimeline) -> list[ConstraintViolation]:
    """Plan thrashing detection — reuses analyze_plan_diffs."""
    out: list[ConstraintViolation] = []
    report = analyze_plan_diffs(timeline)
    for diff in report.diffs:
        if diff.is_thrashing:
            anchor = _first_plan_event_for_turn(timeline, diff.turn_index)
            out.append(
                ConstraintViolation(
                    position=anchor.position if anchor else 0,
                    constraint_id="plan.thrashing",
                    severity="warning",
                    evidence=(
                        f"Turn {diff.turn_index}: orchestrator re-planned with the same "
                        f"step set (no progress). ask='{(diff.orchestrator_ask or '')[:80]}'"
                    ),
                    suggested_category=FailureCategory.PLAN_ADHERENCE,
                )
            )
    return out


def _first_plan_event_for_turn(timeline: ConversationTimeline, turn_index: int) -> TimelineEvent | None:
    user_msgs = [e for e in timeline.events if e.event_type == EventType.USER_MESSAGE]
    if turn_index <= 0 or turn_index > len(user_msgs):
        return None
    start = user_msgs[turn_index - 1].position
    for ev in timeline.events:
        if ev.position >= start and ev.event_type in (
            EventType.PLAN_RECEIVED,
            EventType.PLAN_RECEIVED_DEBUG,
        ):
            return ev
    return None


def _system_error_violations(
    timeline: ConversationTimeline,
) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for ev in timeline.events:
        if ev.event_type != EventType.ERROR:
            continue
        out.append(
            ConstraintViolation(
                position=ev.position,
                constraint_id="event.error",
                severity="fail",
                evidence=(ev.error or ev.summary or "Unknown error event")[:240],
                suggested_category=FailureCategory.SYSTEM_FAILURE,
            )
        )
    return out


def synthesize_violations(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    """Run every constraint over the timeline; return violations sorted by position."""
    violations: list[ConstraintViolation] = []
    violations.extend(_tool_call_violations(timeline))
    violations.extend(_generative_answer_violations(timeline))
    violations.extend(_knowledge_search_violations(timeline))
    violations.extend(_plan_violations(timeline))
    violations.extend(_system_error_violations(timeline))
    violations.sort(key=lambda v: (v.position, v.constraint_id))
    return violations


# ---------------------------------------------------------------------------
# Recovery + critical-step localization
# ---------------------------------------------------------------------------


def _violation_was_recovered(
    violation: ConstraintViolation,
    timeline: ConversationTimeline,
) -> bool:
    """A violation is recovered if a later generative-answer trace on the same turn
    reaches state == 'Answered', or if a later successful tool call resolves the
    same task_dialog_id, or if the agent ultimately produced a grounded reply.
    """
    after_pos = violation.position
    # Recovery via successful generative answer on the same turn / later turn
    for trace in timeline.generative_answer_traces or []:
        if trace.position <= after_pos:
            continue
        if (trace.gpt_answer_state or "").strip().lower() == "answered":
            return True
    # Recovery via a successful tool call later
    for tc in timeline.tool_calls:
        if tc.position <= after_pos:
            continue
        if tc.state == "completed":
            return True
    return False


def _pick_critical_step(
    violations: list[ConstraintViolation],
    timeline: ConversationTimeline,
) -> ConstraintViolation | None:
    for v in violations:
        if v.severity != "fail":
            continue
        if not _violation_was_recovered(v, timeline):
            return v
    return None


# ---------------------------------------------------------------------------
# LLM judge integration (uses the failure_diagnosis audit mode)
# ---------------------------------------------------------------------------


def _violations_payload(violations: Iterable[ConstraintViolation]) -> list[dict]:
    return [
        {
            "position": v.position,
            "constraint_id": v.constraint_id,
            "severity": v.severity,
            "evidence": v.evidence,
            "suggested_category": v.suggested_category.value if v.suggested_category else None,
            "related_event_position": v.related_event_position,
        }
        for v in violations
    ]


def _parse_judge_json(raw: str) -> dict:
    """Tolerate ```json fences and stray prose around the JSON object."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -len("```")]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Judge response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def _apply_judge_verdict(
    diagnosis: FailureDiagnosis,
    verdict: dict,
    violations: list[ConstraintViolation],
) -> None:
    cat_raw = (verdict.get("category") or "").strip()
    if cat_raw:
        try:
            diagnosis.category = FailureCategory(cat_raw)
        except ValueError:
            logger.debug(f"Judge returned unknown category: {cat_raw!r}")
    crit = verdict.get("critical_step")
    if isinstance(crit, int):
        diagnosis.critical_step_position = crit
    root = verdict.get("root_cause_step")
    if isinstance(root, int):
        diagnosis.root_cause_position = root
    conf = verdict.get("confidence")
    if isinstance(conf, (int, float)):
        diagnosis.confidence = float(conf)
    diagnosis.summary = (verdict.get("summary") or "").strip()
    diagnosis.fix_suggestion = (verdict.get("fix") or verdict.get("fix_suggestion") or "").strip()
    diagnosis.judge_used = True
    if diagnosis.critical_step_position is not None:
        diagnosis.contributing_violations = [v for v in violations if v.position <= diagnosis.critical_step_position]


async def _run_llm_judge_async(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
) -> dict | None:
    """Invoke the failure_diagnosis audit mode. Returns parsed verdict or None on error."""
    try:
        from linter import load_audit_modes, run_audits
    except ImportError:
        logger.warning("linter module unavailable; skipping LLM judge")
        return None

    catalogue = load_audit_modes()
    if not any(m.id == "failure_diagnosis" for m in catalogue):
        logger.warning("failure_diagnosis audit mode not configured")
        return None

    # Inject the violation log into the timeline payload via the bot's errors
    # field, where the prompt expects to find it.
    augmented = timeline.model_copy(deep=True)
    augmented.errors = [json.dumps(_violations_payload(violations), default=str)] + list(augmented.errors or [])

    try:
        results = await run_audits(
            profile=profile,
            timeline=augmented,
            mode_ids=["failure_diagnosis"],
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            modes=catalogue,
        )
    except Exception as exc:  # noqa: BLE001 — judge errors must not fail the report
        logger.warning(f"failure_diagnosis judge failed: {exc}")
        return None
    if not results:
        return None
    result = results[0]
    if result.error:
        logger.warning(f"failure_diagnosis judge error: {result.error}")
        return None
    try:
        return _parse_judge_json(result.markdown)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"failure_diagnosis judge returned non-JSON: {exc}")
        return None


def _run_llm_judge(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
) -> dict | None:
    """Sync wrapper around the async judge. Used by the CLI / tests."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_llm_judge_async(profile, timeline, violations))
    logger.warning(
        "diagnose_failure called from inside an event loop; use diagnose_failure_async() instead. Skipping LLM judge."
    )
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _build_heuristic_diagnosis(
    critical: ConstraintViolation,
    violations: list[ConstraintViolation],
) -> FailureDiagnosis:
    return FailureDiagnosis(
        critical_step_position=critical.position,
        category=critical.suggested_category,
        confidence=0.5 if critical.suggested_category else 0.0,
        root_cause_position=critical.related_event_position or critical.position,
        contributing_violations=[v for v in violations if v.position <= critical.position],
        summary=critical.evidence,
    )


def diagnose_failure(
    profile: BotProfile,
    timeline: ConversationTimeline,
    *,
    llm_enabled: bool = False,
) -> FailureDiagnosisReport:
    """Synchronous diagnosis. Use `diagnose_failure_async` from inside an event loop."""
    violations = synthesize_violations(profile, timeline)
    critical = _pick_critical_step(violations, timeline)
    if critical is None:
        return FailureDiagnosisReport(succeeded=True, violations=violations)
    diagnosis = _build_heuristic_diagnosis(critical, violations)
    if llm_enabled:
        verdict = _run_llm_judge(profile, timeline, violations)
        if verdict is not None:
            _apply_judge_verdict(diagnosis, verdict, violations)
    return FailureDiagnosisReport(succeeded=False, diagnosis=diagnosis, violations=violations)


async def diagnose_failure_async(
    profile: BotProfile,
    timeline: ConversationTimeline,
    *,
    llm_enabled: bool = False,
) -> FailureDiagnosisReport:
    """Async-friendly variant for use inside an existing event loop (e.g. Reflex)."""
    violations = synthesize_violations(profile, timeline)
    critical = _pick_critical_step(violations, timeline)
    if critical is None:
        return FailureDiagnosisReport(succeeded=True, violations=violations)
    diagnosis = _build_heuristic_diagnosis(critical, violations)
    if llm_enabled:
        verdict = await _run_llm_judge_async(profile, timeline, violations)
        if verdict is not None:
            _apply_judge_verdict(diagnosis, verdict, violations)
    return FailureDiagnosisReport(succeeded=False, diagnosis=diagnosis, violations=violations)


# ---------------------------------------------------------------------------
# Re-exports used by tests / web layer
# ---------------------------------------------------------------------------

__all__ = [
    "ConstraintViolation",
    "FailureDiagnosis",
    "FailureDiagnosisReport",
    "diagnose_failure",
    "diagnose_failure_async",
    "synthesize_violations",
]

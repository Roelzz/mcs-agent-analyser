"""Public entry point: assemble a `DiagnosisReport` end-to-end.

Pipeline (per the integration plan §4):

    1. run_constraints(profile, timeline)
    2. pick_critical_step(...)
    3. run_judge(...)         optional, llm=False skips
    4. attach canned recs
    5. compose DiagnosisReport
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from diagnosis.constraints import run_constraints
from diagnosis.judge import DEFAULT_JUDGE_MODEL, run_judge_async
from diagnosis.models import (
    ConstraintViolation,
    DiagnosisReport,
    FailureCategory,
    Recommendation,
    SecondaryFailure,
)
from diagnosis.recommendations import canned_for
from diagnosis.recovery import pick_critical_step
from models import BotProfile, ConversationTimeline


def _seed_category_from_violations(
    violations: list[ConstraintViolation], critical: ConstraintViolation | None
) -> FailureCategory:
    """Heuristic-only path: pick a category seed from the critical violation
    (or the highest-severity violation when there's no critical step). Returns
    INCONCLUSIVE if there's nothing to seed from."""
    if critical and critical.default_category_seed:
        return critical.default_category_seed
    severity_rank = {"critical": 3, "warn": 2, "info": 1}
    ranked = sorted(violations, key=lambda v: severity_rank.get(v.severity, 0), reverse=True)
    for v in ranked:
        if v.default_category_seed:
            return v.default_category_seed
    return FailureCategory.INCONCLUSIVE


def _outcome_label(timeline: ConversationTimeline, has_critical: bool) -> str:
    if has_critical:
        return "failed"
    if timeline.errors:
        return "errored"
    return "succeeded"


def _diagnose_heuristic(profile: BotProfile, timeline: ConversationTimeline) -> DiagnosisReport:
    """Pure-sync heuristic-only diagnosis. No LLM call, no async, safe to call
    from inside an event loop (the Reflex upload pipeline does this when it
    bakes the diagnosis section into the Markdown report)."""
    violations = run_constraints(profile, timeline)
    critical = pick_critical_step(violations, timeline)
    has_critical = critical is not None
    seed_category = _seed_category_from_violations(violations, critical)
    summary = critical.description if critical else "Conversation completed without unrecoverable failure."
    canned: list[Recommendation] = canned_for(seed_category) if has_critical else []
    return DiagnosisReport(
        transcript_id=timeline.conversation_id or "",
        bot_id=profile.bot_id or profile.schema_name or "",
        outcome=_outcome_label(timeline, has_critical),
        critical_step_index=critical.step_index if critical else None,
        category=seed_category,
        confidence="medium" if has_critical else "high",
        summary=summary,
        reason_for_failure=critical.description if critical else "",
        violations=violations,
        canned_recommendations=canned,
        generated_at=datetime.now(tz=timezone.utc),
    )


async def diagnose_async(
    profile: BotProfile,
    timeline: ConversationTimeline,
    *,
    llm: bool = True,
    judge_model: str | None = None,
    redact_pii: bool = True,
) -> DiagnosisReport:
    """Run the full diagnosis pipeline. Async-friendly for Reflex."""
    if not llm:
        return _diagnose_heuristic(profile, timeline)

    judge_model = judge_model or DEFAULT_JUDGE_MODEL
    violations = run_constraints(profile, timeline)
    critical = pick_critical_step(violations, timeline)
    has_critical = critical is not None

    seed_category = _seed_category_from_violations(violations, critical)
    confidence: str = "medium" if has_critical else "high"
    summary = critical.description if critical else "Conversation completed without unrecoverable failure."
    taxonomy_reasoning = ""
    reason_for_failure = critical.description if critical else ""
    reason_for_index = ""
    crit_index = critical.step_index if critical else None
    error_state = False
    error_message = ""
    judge_model_used = ""
    redaction_summary: dict = {}
    secondary_failures: list[SecondaryFailure] = []
    judge_verdict_raw: dict | None = None

    # Always run the judge when llm=True. The judge gets a second opinion even
    # when heuristics are clean (our 6 rules don't catch every failure shape;
    # the user clicking Diagnose means "look harder"). The judge can return
    # `Inconclusive` (failure_case=10) for genuinely successful conversations.
    judge_result = await run_judge_async(
        profile,
        timeline,
        violations,
        judge_model=judge_model,
        redact_pii=redact_pii,
    )
    judge_model_used = judge_result.model_used
    redaction_summary = judge_result.redaction_summary or {}
    if judge_result.ok:
        v = judge_result.verdict
        seed_category = v.category
        confidence = v.confidence
        summary = v.summary or summary
        taxonomy_reasoning = v.taxonomy_checklist_reasoning
        reason_for_failure = v.reason_for_failure or reason_for_failure
        reason_for_index = v.reason_for_index
        if v.critical_step_index is not None:
            crit_index = v.critical_step_index
            has_critical = True  # judge promoted this to a real failure
        secondary_failures = list(v.secondary_failures)
        judge_verdict_raw = dict(v.raw)
    else:
        error_state = True
        error_message = judge_result.error
        logger.warning(f"Judge failed; falling back to heuristic verdict: {judge_result.error}")

    # Canned recs are always relevant when the verdict isn't INCONCLUSIVE — even
    # if the heuristic engine missed it, the judge's category drives the recs.
    show_canned = has_critical or (seed_category != FailureCategory.INCONCLUSIVE and not error_state)
    canned: list[Recommendation] = canned_for(seed_category) if show_canned else []

    return DiagnosisReport(
        transcript_id=timeline.conversation_id or "",
        bot_id=profile.bot_id or profile.schema_name or "",
        outcome=_outcome_label(timeline, has_critical),
        critical_step_index=crit_index,
        category=seed_category,
        confidence=confidence,  # type: ignore[arg-type]
        taxonomy_checklist_reasoning=taxonomy_reasoning,
        reason_for_failure=reason_for_failure,
        reason_for_index=reason_for_index,
        summary=summary,
        violations=violations,
        secondary_failures=secondary_failures,
        canned_recommendations=canned,
        generated_at=datetime.now(tz=timezone.utc),
        judge_model=judge_model_used,
        redaction_summary=redaction_summary,
        error_state=error_state,
        error_message=error_message,
        judge_verdict_raw=judge_verdict_raw,
    )


def diagnose(
    profile: BotProfile,
    timeline: ConversationTimeline,
    *,
    llm: bool = True,
    judge_model: str | None = None,
    redact_pii: bool = True,
) -> DiagnosisReport:
    """Synchronous entry point.

    - `llm=False`: pure-sync, safe inside an event loop (used by the CLI
      Markdown report integration when called from the Reflex upload pipeline).
    - `llm=True`: spins up an asyncio.run loop. Raises if already inside one;
      callers in async contexts must use `diagnose_async` instead.
    """
    if not llm:
        return _diagnose_heuristic(profile, timeline)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(diagnose_async(profile, timeline, llm=llm, judge_model=judge_model, redact_pii=redact_pii))
    raise RuntimeError("diagnose(llm=True) called from inside an event loop; use diagnose_async() instead")

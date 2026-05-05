"""AgentRx-style per-transcript failure diagnosis for Copilot Studio.

Public API:

    diagnose(profile, timeline, *, llm=True, judge_model=None, redact_pii=True)
        -> DiagnosisReport

Run the heuristic constraint pass, the recovery / critical-step algorithm,
optionally the LLM judge, then attach canned recommendations.

Re-exports the model classes so callers don't have to know the subpackage layout.
"""

from diagnosis.models import (
    ComponentRef,
    ConstraintViolation,
    DiagnosisReport,
    FailureCategory,
    Recommendation,
    category_from_index,
)


# The orchestrator function is imported lazily to avoid pulling in the
# constraint registry / judge module on simple model usage.
def diagnose(*args, **kwargs):  # type: ignore[no-untyped-def]
    from diagnosis.orchestrator import diagnose as _diagnose

    return _diagnose(*args, **kwargs)


async def diagnose_async(*args, **kwargs):  # type: ignore[no-untyped-def]
    from diagnosis.orchestrator import diagnose_async as _diagnose_async

    return await _diagnose_async(*args, **kwargs)


__all__ = [
    "ComponentRef",
    "ConstraintViolation",
    "DiagnosisReport",
    "FailureCategory",
    "Recommendation",
    "category_from_index",
    "diagnose",
    "diagnose_async",
]

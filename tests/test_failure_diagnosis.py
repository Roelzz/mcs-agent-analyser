"""Tests for the AgentRx-style failure diagnostics in `failure_diagnosis.py`.

Covers:
- per-constraint synthesis on synthetic timelines,
- recovery logic (a transient failure that's later recovered must NOT become
  the critical step), and
- integration against the Bluebot success fixture and the bot2 retry fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from failure_diagnosis import (
    ConstraintViolation,
    FailureDiagnosisReport,
    diagnose_failure,
    synthesize_violations,
)
from models import (
    BotProfile,
    ComponentSummary,
    ConversationTimeline,
    EventType,
    FailureCategory,
    GenerativeAnswerTrace,
    GptInfo,
    KnowledgeSearchInfo,
    SearchResult,
    TimelineEvent,
    ToolCall,
)
from parser import parse_dialog_json
from timeline import build_timeline


FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers (mirrors test_conversation_analysis.py)
# ---------------------------------------------------------------------------


def _ev(
    event_type: EventType,
    position: int,
    *,
    summary: str = "",
    state: str | None = None,
    error: str | None = None,
    plan_steps: list[str] | None = None,
    orchestrator_ask: str | None = None,
) -> TimelineEvent:
    return TimelineEvent(
        event_type=event_type,
        timestamp=f"2024-01-01T00:00:{position:02d}Z",
        summary=summary,
        position=position,
        state=state,
        error=error,
        plan_steps=plan_steps or [],
        orchestrator_ask=orchestrator_ask,
    )


def _timeline(
    events: list[TimelineEvent] | None = None,
    *,
    tool_calls: list[ToolCall] | None = None,
    knowledge_searches: list[KnowledgeSearchInfo] | None = None,
    generative_answer_traces: list[GenerativeAnswerTrace] | None = None,
) -> ConversationTimeline:
    return ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        events=events or [],
        tool_calls=tool_calls or [],
        knowledge_searches=knowledge_searches or [],
        generative_answer_traces=generative_answer_traces or [],
    )


def _profile() -> BotProfile:
    return BotProfile(
        display_name="TestBot",
        schema_name="cr_test_bot",
        components=[ComponentSummary(kind="Bot", display_name="TestBot", schema_name="cr_test_bot")],
        gpt_info=GptInfo(display_name="TestBot"),
    )


# ---------------------------------------------------------------------------
# Trivial cases
# ---------------------------------------------------------------------------


class TestSuccessfulConversations:
    def test_empty_timeline_succeeds(self):
        report = diagnose_failure(_profile(), _timeline())
        assert report.succeeded is True
        assert report.diagnosis is None
        assert report.violations == []

    def test_happy_path_user_then_bot(self):
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary='User: "hi"'),
            _ev(EventType.BOT_MESSAGE, 2, summary="Bot: Hello there"),
        ]
        report = diagnose_failure(_profile(), _timeline(events))
        assert report.succeeded is True


# ---------------------------------------------------------------------------
# Tool-call constraints
# ---------------------------------------------------------------------------


class TestToolCallConstraints:
    def test_failed_tool_marks_invalid_invocation(self):
        tc = ToolCall(
            step_id="s1",
            task_dialog_id="td.SearchFlights",
            display_name="SearchFlights",
            state="failed",
            error="HTTP 400: passenger_count must be a positive integer",
            position=5,
        )
        report = diagnose_failure(_profile(), _timeline(tool_calls=[tc]))
        assert report.succeeded is False
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.INVALID_INVOCATION
        assert report.diagnosis.critical_step_position == 5
        assert any(v.constraint_id == "tool.failed_invocation" for v in report.violations)

    def test_failed_tool_with_timeout_marks_system_failure(self):
        tc = ToolCall(
            step_id="s1",
            display_name="SlowAPI",
            state="failed",
            error="Request timed out after 30s",
            position=4,
        )
        report = diagnose_failure(_profile(), _timeline(tool_calls=[tc]))
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.SYSTEM_FAILURE
        assert any(v.constraint_id == "tool.system_error" for v in report.violations)

    def test_recovered_tool_failure_marks_conversation_succeeded(self):
        failed = ToolCall(state="failed", error="HTTP 500", display_name="A", position=3)
        recovered = ToolCall(state="completed", display_name="B", position=7)
        report = diagnose_failure(_profile(), _timeline(tool_calls=[failed, recovered]))
        assert report.succeeded is True
        # The violation is still recorded in the log even though it was recovered.
        assert any(v.constraint_id.startswith("tool.") for v in report.violations)


# ---------------------------------------------------------------------------
# Generative-answer constraints
# ---------------------------------------------------------------------------


class TestGenerativeAnswerConstraints:
    def test_not_found_with_results_marks_misinterpretation(self):
        trace = GenerativeAnswerTrace(
            position=10,
            attempt_index=1,
            search_results=[SearchResult(name="hit1", url="https://x"), SearchResult(name="hit2")],
            gpt_answer_state="Answer not Found in Search Results",
        )
        report = diagnose_failure(_profile(), _timeline(generative_answer_traces=[trace]))
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.MISINTERPRETED_TOOL_OUTPUT

    def test_not_found_with_no_results_marks_underspecified(self):
        trace = GenerativeAnswerTrace(
            position=10,
            search_results=[],
            gpt_answer_state="Answer not Found in Search Results",
        )
        report = diagnose_failure(_profile(), _timeline(generative_answer_traces=[trace]))
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.UNDERSPECIFIED_INTENT

    def test_fallback_marks_invented_info(self):
        trace = GenerativeAnswerTrace(position=8, triggered_fallback=True)
        report = diagnose_failure(_profile(), _timeline(generative_answer_traces=[trace]))
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.INVENTED_INFO

    def test_confidential_content_marks_guardrails(self):
        trace = GenerativeAnswerTrace(
            position=8,
            contains_confidential=True,
            gpt_answer_state="Answered",
        )
        violations = synthesize_violations(_profile(), _timeline(generative_answer_traces=[trace]))
        assert any(v.suggested_category == FailureCategory.GUARDRAILS_TRIGGERED for v in violations)


# ---------------------------------------------------------------------------
# Knowledge-search constraints
# ---------------------------------------------------------------------------


class TestKnowledgeConstraints:
    def test_zero_result_then_citation_flags_invented_info(self):
        ks = KnowledgeSearchInfo(position=5, search_results=[])
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary='User: "find docs"'),
            _ev(EventType.KNOWLEDGE_SEARCH, 5, summary="Searched"),
            _ev(EventType.BOT_MESSAGE, 8, summary="See https://example.com [1]"),
        ]
        report = diagnose_failure(_profile(), _timeline(events, knowledge_searches=[ks]))
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.INVENTED_INFO

    def test_zero_result_without_citation_no_violation(self):
        ks = KnowledgeSearchInfo(position=5, search_results=[])
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary='User: "find docs"'),
            _ev(EventType.KNOWLEDGE_SEARCH, 5, summary="Searched"),
            _ev(EventType.BOT_MESSAGE, 8, summary="I couldn't find anything on that."),
        ]
        violations = synthesize_violations(_profile(), _timeline(events, knowledge_searches=[ks]))
        assert all(v.constraint_id != "knowledge.zero_result_with_citation" for v in violations)


# ---------------------------------------------------------------------------
# Plan-adherence constraints
# ---------------------------------------------------------------------------


class TestPlanConstraints:
    def test_plan_thrashing_emits_violation(self):
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary='User: "do stuff"'),
            _ev(EventType.PLAN_RECEIVED, 2, plan_steps=["A", "B"], orchestrator_ask="task"),
            _ev(EventType.PLAN_RECEIVED, 3, plan_steps=["A", "B"], orchestrator_ask="task"),
            _ev(EventType.PLAN_RECEIVED, 4, plan_steps=["A", "B"], orchestrator_ask="task"),
        ]
        violations = synthesize_violations(_profile(), _timeline(events))
        thrashing = [v for v in violations if v.constraint_id == "plan.thrashing"]
        assert thrashing, "expected plan.thrashing violation when plan repeats"
        assert thrashing[0].suggested_category == FailureCategory.PLAN_ADHERENCE


# ---------------------------------------------------------------------------
# System errors
# ---------------------------------------------------------------------------


class TestSystemErrors:
    def test_error_event_flagged_as_system_failure(self):
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary='User: "hi"'),
            _ev(EventType.ERROR, 2, summary="Pipeline error", error="HTTP 503 from upstream"),
        ]
        report = diagnose_failure(_profile(), _timeline(events))
        assert report.diagnosis is not None
        assert report.diagnosis.category == FailureCategory.SYSTEM_FAILURE


# ---------------------------------------------------------------------------
# Serialization (LLM-judge payload)
# ---------------------------------------------------------------------------


class TestViolationPayload:
    def test_violations_are_json_serializable(self):
        violations = [
            ConstraintViolation(
                position=4,
                constraint_id="tool.failed_invocation",
                severity="fail",
                evidence="Tool 'X' failed: bad arg",
                suggested_category=FailureCategory.INVALID_INVOCATION,
            )
        ]
        payload = [
            {
                "position": v.position,
                "constraint_id": v.constraint_id,
                "severity": v.severity,
                "evidence": v.evidence,
                "suggested_category": v.suggested_category.value if v.suggested_category else None,
            }
            for v in violations
        ]
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded[0]["suggested_category"] == "InvalidInvocation"


# ---------------------------------------------------------------------------
# Integration against the real fixtures
# ---------------------------------------------------------------------------


class TestRealFixtures:
    def test_bluebot_success_path_yields_clean_report(self):
        activities = parse_dialog_json(FIXTURE_DIR / "bluebot_dialog.json")
        timeline = build_timeline(activities, schema_lookup={})
        report = diagnose_failure(_profile(), timeline)
        assert isinstance(report, FailureDiagnosisReport)
        assert report.succeeded is True, (
            f"Bluebot's CT7500 happy path must diagnose as succeeded; "
            f"got violations: {[v.constraint_id for v in report.violations]}"
        )

    def test_bot2_retry_recovers_marks_succeeded(self):
        """The first SearchAndSummarizeContent attempt fails with 'Answer not
        Found' but the orchestrator's automatic retry succeeds. AgentRx's
        critical-step rule says a recovered failure is NOT critical."""
        activities = parse_dialog_json(FIXTURE_DIR / "bot2_dialog.json")
        timeline = build_timeline(activities, schema_lookup={})
        report = diagnose_failure(_profile(), timeline)
        assert report.succeeded is True, (
            "bot2's failed first attempt is recovered by the second; the report should NOT flag a critical step"
        )
        # But the first attempt must still appear as a (non-critical) violation
        # so the audit trail remains complete.
        assert any(v.constraint_id == "generative_answer.unanswered" for v in report.violations), (
            "bot2 should still record the failed first attempt in the violation log"
        )

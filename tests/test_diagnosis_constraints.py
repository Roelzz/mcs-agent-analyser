"""Tests for diagnosis/constraints/* — each rule with synthetic timelines."""

from __future__ import annotations

from diagnosis.constraints import run_constraints
from diagnosis.constraints.automatic_retry_after_misinterpretation import (
    RULE_ID as RETRY_RULE,
)
from diagnosis.constraints.fallback_when_match_plausible import (
    PLAUSIBLE_MATCH_THRESHOLD,
    RULE_ID as FALLBACK_RULE,
)
from diagnosis.constraints.knowledge_zero_results_with_citation import (
    RULE_ID as ZERO_RULE,
)
from diagnosis.constraints.slot_loop_no_progress import (
    RULE_ID as SLOT_RULE,
)
from diagnosis.constraints.tool_error_ignored import (
    RULE_ID as TOOL_RULE,
)
from diagnosis.constraints.ungrounded_generative_answer import (
    RULE_ID as UNGROUNDED_RULE,
)
from diagnosis.models import FailureCategory
from models import (
    BotProfile,
    ComponentSummary,
    ConversationTimeline,
    EventType,
    GenerativeAnswerCitation,
    GenerativeAnswerTrace,
    GptInfo,
    KnowledgeSearchInfo,
    SearchResult,
    TimelineEvent,
    ToolCall,
)


def _ev(event_type: EventType, position: int, **kw) -> TimelineEvent:
    kw.setdefault("timestamp", f"2024-01-01T00:00:{position:02d}Z")
    return TimelineEvent(event_type=event_type, position=position, **kw)


def _profile(extra_components: list[ComponentSummary] | None = None) -> BotProfile:
    components = [ComponentSummary(kind="Bot", display_name="X", schema_name="cr_x")]
    if extra_components:
        components.extend(extra_components)
    return BotProfile(
        display_name="X",
        schema_name="cr_x",
        components=components,
        gpt_info=GptInfo(display_name="X"),
    )


def _timeline(
    events=None, *, tool_calls=None, knowledge_searches=None, generative_answer_traces=None
) -> ConversationTimeline:
    return ConversationTimeline(
        bot_name="X",
        events=events or [],
        tool_calls=tool_calls or [],
        knowledge_searches=knowledge_searches or [],
        generative_answer_traces=generative_answer_traces or [],
    )


# ---------------------------------------------------------------------------


class TestKnowledgeZeroResultsWithCitation:
    def test_zero_results_then_citation_flags(self):
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="User: find docs"),
            _ev(EventType.KNOWLEDGE_SEARCH, 5, summary="searched"),
            _ev(EventType.BOT_MESSAGE, 8, summary="See https://example.com [1]"),
        ]
        ks = KnowledgeSearchInfo(position=5, search_results=[])
        violations = run_constraints(_profile(), _timeline(events, knowledge_searches=[ks]))
        match = [v for v in violations if v.rule_id == ZERO_RULE]
        assert match, "expected zero_results_with_citation violation"
        assert match[0].default_category_seed == FailureCategory.INVENTION

    def test_zero_results_no_citation_does_not_flag(self):
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="User: find docs"),
            _ev(EventType.KNOWLEDGE_SEARCH, 5, summary="searched"),
            _ev(EventType.BOT_MESSAGE, 8, summary="I couldn't find that — sorry."),
        ]
        ks = KnowledgeSearchInfo(position=5, search_results=[])
        violations = run_constraints(_profile(), _timeline(events, knowledge_searches=[ks]))
        assert not [v for v in violations if v.rule_id == ZERO_RULE]


class TestFallbackWhenMatchPlausible:
    def test_fallback_with_plausible_match_flags(self):
        # A real topic with a trigger phrase close to the user query
        topic = ComponentSummary(
            kind="DialogComponent",
            display_name="Order Status",
            schema_name="topic_OrderStatus",
            trigger_queries=["where is my order", "track my order"],
        )
        profile = _profile([topic])
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="where is my order?"),
            _ev(EventType.STEP_TRIGGERED, 3, topic_name="system_fallback"),
        ]
        violations = run_constraints(profile, _timeline(events))
        match = [v for v in violations if v.rule_id == FALLBACK_RULE]
        assert match
        assert match[0].evidence["match_score"] >= PLAUSIBLE_MATCH_THRESHOLD

    def test_fallback_without_plausible_match_does_not_flag(self):
        topic = ComponentSummary(
            kind="DialogComponent",
            display_name="Weather",
            schema_name="topic_weather",
            trigger_queries=["what's the weather", "forecast today"],
        )
        profile = _profile([topic])
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="how do I cancel my subscription?"),
            _ev(EventType.STEP_TRIGGERED, 3, topic_name="system_fallback"),
        ]
        violations = run_constraints(profile, _timeline(events))
        assert not [v for v in violations if v.rule_id == FALLBACK_RULE]


class TestSlotLoopNoProgress:
    def test_three_triggers_without_assignment_warns(self):
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="hi"),
            _ev(EventType.STEP_TRIGGERED, 5, topic_name="ask_email"),
            _ev(EventType.STEP_TRIGGERED, 10, topic_name="ask_email"),
            _ev(EventType.STEP_TRIGGERED, 15, topic_name="ask_email"),
        ]
        violations = run_constraints(_profile(), _timeline(events))
        match = [v for v in violations if v.rule_id == SLOT_RULE]
        assert match
        assert match[0].severity == "warn"

    def test_five_plus_triggers_critical(self):
        events = [_ev(EventType.STEP_TRIGGERED, i * 5, topic_name="ask_email") for i in range(1, 7)]
        violations = run_constraints(_profile(), _timeline(events))
        match = [v for v in violations if v.rule_id == SLOT_RULE]
        assert match and match[0].severity == "critical"

    def test_assignment_resets_loop(self):
        events = [
            _ev(EventType.STEP_TRIGGERED, 5, topic_name="ask_email"),
            _ev(EventType.STEP_TRIGGERED, 10, topic_name="ask_email"),
            _ev(EventType.VARIABLE_ASSIGNMENT, 12, topic_name="ask_email"),
            _ev(EventType.STEP_TRIGGERED, 15, topic_name="ask_email"),
        ]
        violations = run_constraints(_profile(), _timeline(events))
        assert not [v for v in violations if v.rule_id == SLOT_RULE]


class TestToolErrorIgnored:
    def test_failed_tool_followed_by_unacknowledged_reply_flags(self):
        tc = ToolCall(
            display_name="GetOrderDetails",
            task_dialog_id="td.GetOrderDetails",
            state="failed",
            error="ORDER_NOT_FOUND",
            position=10,
        )
        events = [
            _ev(EventType.STEP_TRIGGERED, 9),
            _ev(EventType.STEP_FINISHED, 11, state="failed"),
            _ev(EventType.BOT_MESSAGE, 12, summary="Your order is on its way!"),
        ]
        violations = run_constraints(_profile(), _timeline(events, tool_calls=[tc]))
        match = [v for v in violations if v.rule_id == TOOL_RULE]
        assert match
        assert match[0].default_category_seed == FailureCategory.TOOL_MISINTERPRETATION

    def test_failed_tool_with_apology_reply_does_not_flag(self):
        tc = ToolCall(
            display_name="GetOrderDetails",
            state="failed",
            error="ORDER_NOT_FOUND",
            position=10,
        )
        events = [_ev(EventType.BOT_MESSAGE, 12, summary="Sorry — I couldn't find that order.")]
        violations = run_constraints(_profile(), _timeline(events, tool_calls=[tc]))
        assert not [v for v in violations if v.rule_id == TOOL_RULE]


class TestUngroundedGenerativeAnswer:
    def test_fallback_flags(self):
        trace = GenerativeAnswerTrace(position=10, triggered_fallback=True)
        violations = run_constraints(_profile(), _timeline(generative_answer_traces=[trace]))
        match = [v for v in violations if v.rule_id == UNGROUNDED_RULE]
        assert match and match[0].severity == "critical"

    def test_answered_without_citations_warns(self):
        trace = GenerativeAnswerTrace(
            position=10,
            gpt_answer_state="Answered",
            citations=[],  # empty
            search_results=[SearchResult(name="x", url="https://x")],
        )
        violations = run_constraints(_profile(), _timeline(generative_answer_traces=[trace]))
        match = [v for v in violations if v.rule_id == UNGROUNDED_RULE]
        assert match and match[0].severity == "warn"

    def test_answered_with_citations_does_not_flag(self):
        trace = GenerativeAnswerTrace(
            position=10,
            gpt_answer_state="Answered",
            citations=[GenerativeAnswerCitation(url="https://x", snippet="...")],
        )
        violations = run_constraints(_profile(), _timeline(generative_answer_traces=[trace]))
        assert not [v for v in violations if v.rule_id == UNGROUNDED_RULE]


class TestAutomaticRetryAfterMisinterpretation:
    def test_retry_after_not_found_with_results_flags(self):
        first = GenerativeAnswerTrace(
            position=10,
            attempt_index=1,
            search_results=[SearchResult(name="hit1"), SearchResult(name="hit2")],
            gpt_answer_state="Answer not Found in Search Results",
        )
        retry = GenerativeAnswerTrace(
            position=20,
            attempt_index=2,
            is_retry=True,
            previous_attempt_state="Answer not Found in Search Results",
            gpt_answer_state="Answered",
            search_results=[SearchResult(name="hit1")],
        )
        violations = run_constraints(_profile(), _timeline(generative_answer_traces=[first, retry]))
        match = [v for v in violations if v.rule_id == RETRY_RULE]
        assert match
        assert match[0].evidence["retry_succeeded"] is True

    def test_retry_after_not_found_without_results_does_not_flag(self):
        first = GenerativeAnswerTrace(
            position=10,
            attempt_index=1,
            search_results=[],  # no hits to misread
            gpt_answer_state="Answer not Found in Search Results",
        )
        retry = GenerativeAnswerTrace(
            position=20,
            attempt_index=2,
            is_retry=True,
            previous_attempt_state="Answer not Found in Search Results",
            gpt_answer_state="Answered",
        )
        violations = run_constraints(_profile(), _timeline(generative_answer_traces=[first, retry]))
        assert not [v for v in violations if v.rule_id == RETRY_RULE]

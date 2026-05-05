"""Tests for the richer `build_transcript_payload`.

Issue A from the AgentRx false-positive plan: STEP_FINISHED events used to
arrive at the judge with no observation data, so the judge couldn't tell a
grounded answer from a fabrication. Verify the new payload carries
`tool_observation`, `search_summary`, and `generative_answer_summary` for
the right event types, plus the truncation behaviour.
"""

from __future__ import annotations

import json

from linter import _truncate_json, build_transcript_payload
from models import (
    ConversationTimeline,
    EventType,
    GenerativeAnswerCitation,
    GenerativeAnswerTrace,
    KnowledgeSearchInfo,
    SearchResult,
    TimelineEvent,
    ToolCall,
    ToolCallObservation,
)


def _ev(event_type: EventType, position: int, **kw) -> TimelineEvent:
    kw.setdefault("timestamp", f"2024-01-01T00:00:{position:02d}Z")
    return TimelineEvent(event_type=event_type, position=position, **kw)


# ---------------------------------------------------------------------------
# Tool observations (Issue A's smoking gun)
# ---------------------------------------------------------------------------


class TestToolObservation:
    def test_step_finished_carries_observation(self):
        """The bug we're fixing: tool observation reaches the judge."""
        tc = ToolCall(
            step_id="s1",
            display_name="human_in_the_loop_request_for_information",
            state="completed",
            position=10,
            observation=ToolCallObservation(
                structured_content={
                    "merchant_name": "Contoso",
                    "expense_date": "2026-03-05",
                    "attendee_count": "4",
                }
            ),
            arguments={"title": "Customer Dinner Expense Details Needed"},
        )
        timeline = ConversationTimeline(
            events=[_ev(EventType.STEP_FINISHED, 10, step_id="s1", state="completed")],
            tool_calls=[tc],
        )

        payload = build_transcript_payload(timeline)
        assert len(payload["events"]) == 1
        ev = payload["events"][0]
        assert "tool_observation" in ev
        # The whole point — the judge can now see "Contoso" without re-deriving it
        assert "Contoso" in json.dumps(payload, default=str)
        assert "2026-03-05" in json.dumps(payload, default=str)
        assert ev["tool_observation"]["display_name"].startswith("human_in_the_loop")

    def test_step_finished_without_matching_tool_call_has_no_observation(self):
        timeline = ConversationTimeline(
            events=[_ev(EventType.STEP_FINISHED, 10, step_id="orphan", state="completed")],
            tool_calls=[],
        )
        payload = build_transcript_payload(timeline)
        assert "tool_observation" not in payload["events"][0]

    def test_oversized_observation_is_truncated(self):
        big_blob = {"x": "a" * 5000}
        tc = ToolCall(
            step_id="s1",
            display_name="X",
            position=10,
            observation=ToolCallObservation(structured_content=big_blob),
        )
        timeline = ConversationTimeline(
            events=[_ev(EventType.STEP_FINISHED, 10, step_id="s1")],
            tool_calls=[tc],
        )
        payload = build_transcript_payload(timeline, max_observation_chars=200)
        obs_str = payload["events"][0]["tool_observation"]["observation"]
        assert len(obs_str) <= 200
        assert obs_str.endswith("<truncated>")

    def test_total_budget_marks_late_events_as_truncated(self):
        """After the running budget is hit, later events get the marker."""
        # Three big observations; budget < first one's full size means the
        # second + third land as the marker.
        big_blob = {"x": "a" * 1000}
        tool_calls = [
            ToolCall(
                step_id=f"s{i}",
                display_name=f"T{i}",
                position=10 * i,
                observation=ToolCallObservation(structured_content=big_blob),
            )
            for i in range(1, 4)
        ]
        events = [_ev(EventType.STEP_FINISHED, 10 * i, step_id=f"s{i}") for i in range(1, 4)]
        timeline = ConversationTimeline(events=events, tool_calls=tool_calls)
        payload = build_transcript_payload(timeline, max_observation_chars=2000, max_total_chars=1500)
        # First event keeps its observation; later events are tagged.
        assert isinstance(payload["events"][0]["tool_observation"], dict)
        assert payload["events"][2]["tool_observation"] == "<truncated>"


# ---------------------------------------------------------------------------
# Knowledge search summary
# ---------------------------------------------------------------------------


class TestKnowledgeSearchSummary:
    def test_top_three_results_attached(self):
        results = [SearchResult(name=f"doc{i}", url=f"https://x/{i}", text=f"snippet{i}") for i in range(5)]
        ks = KnowledgeSearchInfo(
            position=20,
            search_query="expense policy",
            knowledge_sources=["Zava Expense policy.txt"],
            search_results=results,
        )
        timeline = ConversationTimeline(
            events=[_ev(EventType.KNOWLEDGE_SEARCH, 20)],
            knowledge_searches=[ks],
        )
        payload = build_transcript_payload(timeline)
        summary = payload["events"][0]["search_summary"]
        assert summary["search_query"] == "expense policy"
        assert summary["result_count"] == 5
        # Cap at top-3
        assert len(summary["results"]) == 3
        assert summary["results"][0]["snippet"] == "snippet0"
        assert summary["knowledge_sources"] == ["Zava Expense policy.txt"]

    def test_late_knowledge_search_marked_truncated_when_budget_exhausted(self):
        """The total-budget cap doesn't only affect tool observations —
        knowledge searches landing after the running total is exhausted
        also get the marker."""
        big_blob = {"x": "a" * 1000}
        # First a fat tool observation that consumes the budget...
        tc = ToolCall(
            step_id="s1",
            display_name="Big",
            position=10,
            observation=ToolCallObservation(structured_content=big_blob),
        )
        # ...then a knowledge search that lands LATE in the stream.
        ks = KnowledgeSearchInfo(
            position=30,
            search_query="late query",
            search_results=[SearchResult(name="x")],
        )
        timeline = ConversationTimeline(
            events=[
                _ev(EventType.STEP_FINISHED, 10, step_id="s1"),
                _ev(EventType.KNOWLEDGE_SEARCH, 30),
            ],
            tool_calls=[tc],
            knowledge_searches=[ks],
        )
        payload = build_transcript_payload(timeline, max_observation_chars=2000, max_total_chars=500)
        # First event: structured observation, eats the budget.
        assert isinstance(payload["events"][0]["tool_observation"], dict)
        # Second event: search summary tagged as truncated.
        assert payload["events"][1]["search_summary"] == "<truncated>"


# ---------------------------------------------------------------------------
# Generative answer summary
# ---------------------------------------------------------------------------


class TestGenerativeAnswerSummary:
    def test_summary_text_and_citation_count_attached(self):
        ga = GenerativeAnswerTrace(
            position=30,
            gpt_answer_state="Answered",
            summary_text="The CT 7500 is a flagship product." * 5,
            citations=[
                GenerativeAnswerCitation(url="https://x", snippet="..."),
                GenerativeAnswerCitation(url="https://y", snippet="..."),
            ],
            search_results=[SearchResult(name="r1"), SearchResult(name="r2")],
        )
        timeline = ConversationTimeline(
            events=[_ev(EventType.GENERATIVE_ANSWER, 30)],
            generative_answer_traces=[ga],
        )
        payload = build_transcript_payload(timeline)
        gas = payload["events"][0]["generative_answer_summary"]
        assert gas["gpt_answer_state"] == "Answered"
        assert gas["citation_count"] == 2
        assert gas["search_result_count"] == 2
        assert "CT 7500" in gas["summary_text"]
        assert len(gas["summary_text"]) <= 500

    def test_late_generative_answer_marked_truncated_when_budget_exhausted(self):
        """Same budget cap applies to generative-answer events arriving
        after the running total is spent."""
        big_blob = {"x": "a" * 1000}
        tc = ToolCall(
            step_id="s1",
            display_name="Big",
            position=10,
            observation=ToolCallObservation(structured_content=big_blob),
        )
        ga = GenerativeAnswerTrace(
            position=40,
            gpt_answer_state="Answered",
            summary_text="late answer",
        )
        timeline = ConversationTimeline(
            events=[
                _ev(EventType.STEP_FINISHED, 10, step_id="s1"),
                _ev(EventType.GENERATIVE_ANSWER, 40),
            ],
            tool_calls=[tc],
            generative_answer_traces=[ga],
        )
        payload = build_transcript_payload(timeline, max_observation_chars=2000, max_total_chars=500)
        assert payload["events"][1]["generative_answer_summary"] == "<truncated>"


# ---------------------------------------------------------------------------
# Backwards compatibility — existing call sites pass no kwargs
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_default_caps_apply(self):
        """Existing audit-mode call sites pass no kwargs; defaults apply."""
        timeline = ConversationTimeline(
            events=[_ev(EventType.USER_MESSAGE, 1, summary='User: "hello"')],
        )
        payload = build_transcript_payload(timeline)
        assert payload["events"][0]["event_type"] == "UserMessage"
        # Top-level shape unchanged.
        assert "bot_name" in payload
        assert "events" in payload
        assert "user_query" in payload


# ---------------------------------------------------------------------------
# _truncate_json helper
# ---------------------------------------------------------------------------


class TestTruncateJson:
    def test_short_value_unchanged(self):
        out = _truncate_json({"a": 1}, max_chars=100)
        assert out == '{"a":1}'

    def test_long_value_marked(self):
        out = _truncate_json({"a": "x" * 500}, max_chars=50)
        assert len(out) <= 50
        assert out.endswith("<truncated>")

    def test_unserialisable_falls_back_to_str(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        # default=str catches most things, but a TypeError-raising encoder
        # path would still fall back. Just confirm we don't crash.
        out = _truncate_json(Weird(), max_chars=100)
        assert "weird" in out.lower()

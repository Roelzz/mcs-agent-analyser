"""Topic-level SearchAndSummarizeContent diagnostic extraction.

Bluebot's CT7500 topic uses inline `SearchAndSummarizeContent` (not the
orchestrator's UniversalSearchTool), so its rich diagnostic event arrives as
`name='GenerativeAnswersSupportData'` with empty valueType. These tests pin
down the parser path that captures it.
"""

from pathlib import Path

from models import EventType
from parser import parse_dialog_json
from timeline import build_timeline


FIXTURE = Path(__file__).parent / "fixtures" / "bluebot_dialog.json"


def test_topic_level_search_summarize_extracted():
    activities = parse_dialog_json(FIXTURE)
    timeline = build_timeline(activities, schema_lookup={})

    assert len(timeline.generative_answer_traces) == 1, "Bluebot dialog.json activity 11 must produce one trace"
    trace = timeline.generative_answer_traces[0]

    assert trace.gpt_answer_state == "Answered"
    assert trace.completion_state == "Answered"
    assert trace.triggered_fallback is False

    assert trace.original_message == "Give me information about CT 7500?"
    assert trace.rewritten_message == "Please provide information about the CT 7500."
    assert trace.rewritten_keywords == "CT 7500 information"

    assert trace.rewrite_model == "gpt-41-2025-04-14"
    assert trace.rewrite_prompt_tokens == 1048
    assert trace.rewrite_completion_tokens == 132

    assert len(trace.search_results) == 11
    assert trace.search_type == "SharepointSiteSearch"
    # Verified scores should be attached for matching URLs
    assert any(r.verified_rank_score is not None for r in trace.search_results)
    # Rank scores are between the bot's observed range (0.71..0.81)
    for r in trace.search_results:
        assert r.rank_score is not None
        assert 0.5 < r.rank_score < 1.0

    assert len(trace.citations) == 2
    assert all(c.url for c in trace.citations)
    assert all(c.snippet for c in trace.citations)

    assert trace.performed_content_moderation is True
    assert trace.performed_content_provenance is True
    assert trace.contains_confidential is False

    assert trace.summary_text and len(trace.summary_text) > 100
    assert len(trace.endpoints) == 2


def test_generative_answer_event_emitted():
    """A summary event should land in the timeline so the conversation tab can show it."""
    activities = parse_dialog_json(FIXTURE)
    timeline = build_timeline(activities, schema_lookup={})

    gen_events = [e for e in timeline.events if e.event_type == EventType.GENERATIVE_ANSWER]
    assert len(gen_events) == 1
    assert "Answered" in gen_events[0].summary
    assert "11 hits" in gen_events[0].summary
    assert "2 citations" in gen_events[0].summary


# ---------------------------------------------------------------------------
# Bot2: failed attempt followed by an automatic retry on the same turn
# ---------------------------------------------------------------------------

BOT2_FIXTURE = Path(__file__).parent / "fixtures" / "bot2_dialog.json"


def test_failed_attempt_then_retry_extracted():
    """Bot2 contains a type=message GenerativeAnswersSupportData (Attempt 1, failed)
    followed by a type=event GenerativeAnswersSupportData (Attempt 2, succeeded).
    Both must be captured as separate traces with retry metadata.
    """
    activities = parse_dialog_json(BOT2_FIXTURE)
    timeline = build_timeline(activities, schema_lookup={})

    assert len(timeline.generative_answer_traces) == 2

    first, second = timeline.generative_answer_traces

    # Attempt 1 — failed
    assert first.attempt_index == 1
    assert first.is_retry is False
    assert first.previous_attempt_state is None
    assert first.gpt_answer_state == "Answer not Found in Search Results"
    assert len(first.search_results) == 3
    assert len(first.citations) == 0
    assert first.summary_text in (None, "")

    # Attempt 2 — automatic retry that succeeded
    assert second.attempt_index == 2
    assert second.is_retry is True
    assert second.previous_attempt_state == "Answer not Found in Search Results"
    assert second.gpt_answer_state == "Answered"
    assert len(second.search_results) == 3
    assert len(second.citations) == 2
    assert second.summary_text and "CT 7500" in second.summary_text

    # Two GENERATIVE_ANSWER timeline events, both labelled distinctly
    gen_events = [e for e in timeline.events if e.event_type == EventType.GENERATIVE_ANSWER]
    assert len(gen_events) == 2
    assert "#1" in gen_events[0].summary
    assert "#2 (retry)" in gen_events[1].summary
    # Failed attempt should be marked failed so the chat UI tones it red
    assert gen_events[0].state == "failed"
    assert gen_events[1].state is None

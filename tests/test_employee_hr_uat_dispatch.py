"""Regression tests for the trace-event dispatcher fixes.

Locks in eight count assertions from the audit of the Employee AI Agent (UAT)
export: knowledge-attribution recovery, USTD flush-on-overwrite, IntentRecognition
trace-type routing, ErrorTraceData camelCase, GPTAnswer / UnknownIntent /
signin/tokenExchange handlers, and the renderer header pivot.
"""

from pathlib import Path

import pytest

from models import EventType
from parser import parse_dialog_json, parse_yaml
from renderer import render_report
from renderer.knowledge import render_knowledge_search_section
from timeline import build_timeline


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "employee_hr_uat"


@pytest.fixture(scope="module")
def timeline():
    profile, lookup = parse_yaml(FIXTURE_DIR / "botContent.yml")
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    return profile, build_timeline(activities, lookup)


def test_knowledge_attribution_recovers_per_turn_events(timeline) -> None:
    _, tl = timeline
    assert len(tl.knowledge_attributions) == 20
    first = tl.knowledge_attributions[0]
    assert first.completion_state == "Answered"
    assert first.is_searched is True
    assert "HRDocumentNL" in first.cited_source_names


def test_universal_search_flush_recovers_all_events(timeline) -> None:
    _, tl = timeline
    # Pre-fix the dialog produced 1 committed search because every USTD event
    # overwrote the previous pending row. The flush-on-overwrite recovers all 13.
    assert len(tl.knowledge_searches) == 13


def test_intent_recognition_routed_for_trace_type_events(timeline) -> None:
    _, tl = timeline
    ir_events = [e for e in tl.events if e.event_type == EventType.INTENT_RECOGNITION]
    # 12 matched IntentRecognition events (trace) + 4 UnknownIntent events (trace).
    assert len(ir_events) == 16
    matched = [e for e in ir_events if e.topic_name and e.topic_name != "UnknownIntent"]
    assert len(matched) == 12


def test_error_trace_data_camelcase_field_names(timeline) -> None:
    _, tl = timeline
    assert len(tl.errors) == 2
    joined = " ".join(tl.errors)
    assert "OpenAIModelTokenLimit" in joined
    assert "OpenAIMaxTokenLengthExceeded" in joined


def test_gpt_answer_events(timeline) -> None:
    _, tl = timeline
    gpt_events = [e for e in tl.events if e.event_type == EventType.GENERATIVE_ANSWER]
    # 4 trace-type GPTAnswer events.
    assert len(gpt_events) == 4


def test_signin_token_exchange_handled(timeline) -> None:
    _, tl = timeline
    auth_events = [e for e in tl.events if e.summary == "OAuth token exchange"]
    assert len(auth_events) == 2


def test_parser_audit_table_recognises_new_signatures(timeline) -> None:
    _, tl = timeline
    by_name = {row["name"]: row for row in tl.raw_event_index["value_types"]}
    for sig in (
        "KnowledgeTraceData",
        "ErrorTraceData",
        "GPTAnswer",
        "UnknownIntent",
        "signin/tokenExchange",
    ):
        assert sig in by_name, f"{sig} missing from raw_event_index"
        assert by_name[sig]["recognised"] is True, f"{sig} still flagged ❌"


def test_knowledge_search_section_header_pivot(timeline) -> None:
    profile, tl = timeline
    out = render_knowledge_search_section(tl, profile)
    assert "20 turns used knowledge" in out
    assert "19 answered" in out
    assert "13 orchestrator searches" in out
    # The pre-fix bug rendered "1 search" — must be gone.
    assert "**1 search**" not in out


def test_full_report_includes_recovered_signals(timeline) -> None:
    profile, tl = timeline
    report = render_report(profile, tl)
    # The new knowledge header.
    assert "20 turns used knowledge" in report
    # The error code from ErrorTraceData (was dropped).
    assert "OpenAIModelTokenLimit" in report

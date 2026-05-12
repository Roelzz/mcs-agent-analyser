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


def test_citation_sources_extracted_from_cbresponse(timeline) -> None:
    """`Global.CBResponse.Text.CitationSources[]` carries the actual grounded
    snippet text — the orchestrator-search trace ships empty `fullResults` in
    this export, so this is the only path snippets survive."""
    _, tl = timeline
    citations = tl.citation_sources
    assert len(citations) >= 3, f"Expected ≥3 citations from CBResponse, got {len(citations)}"
    first = next((c for c in citations if c.name == "FAQ-Parking-EN.pdf"), None)
    assert first is not None, "FAQ-Parking-EN.pdf citation must be present"
    assert first.url.startswith("https://ing.sharepoint.com/")
    assert first.text is not None and len(first.text) > 1000, (
        f"Snippet must be >1000 chars; got {len(first.text or '')}"
    )


def test_citation_sources_bound_to_user_turn(timeline) -> None:
    _, tl = timeline
    turns = {c.triggering_user_message for c in tl.citation_sources}
    assert any(t and "parking" in t.lower() for t in turns), (
        "At least one citation must be tied to a parking-related turn"
    )
    assert any(t and "parental" in t.lower() for t in turns), (
        "At least one citation must be tied to a parental-leave turn"
    )
    assert all(c.triggering_user_message for c in tl.citation_sources)


def test_full_report_renders_citation_snippets(timeline) -> None:
    profile, tl = timeline
    report = render_report(profile, tl)
    # Citations header + a distinctive snippet fragment must both appear.
    assert "📎 Citations" in report
    assert "FAQ-Parking-EN.pdf" in report
    assert "parental-leave.aspx" in report


def test_dashboard_state_exposes_citations(timeline) -> None:
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _StateStub:
        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)

    stub = _StateStub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)  # type: ignore[arg-type]

    assert len(stub.mcs_knowledge_citations) == len(tl.citation_sources)
    first = stub.mcs_knowledge_citations[0]
    assert first["url"].startswith("https://")
    assert int(first["char_count"]) > 1000
    # Preview is truncated for snippets >400 chars.
    assert first["snippet_preview"].endswith(" …") or len(first["snippet_full"]) <= 400
    # Citation count surfaces in the attribution summary suffix.
    assert "citation" in stub.mcs_knowledge_attribution_summary


def test_dashboard_state_exposes_knowledge_attributions(timeline) -> None:
    """The dashboard Knowledge tab pulls from `mcs_knowledge_attributions`.
    If the timeline has the data but the state copy is empty, the tab
    silently undercounts — exactly the bug we just hit. Lock the bridge.

    Calls `_populate_knowledge_data` directly so we don't have to stub
    every sibling helper the parent dispatcher invokes."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _StateStub:
        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)

    stub = _StateStub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)  # type: ignore[arg-type]

    assert len(stub.mcs_knowledge_attributions) == 20
    first = stub.mcs_knowledge_attributions[0]
    assert "HRDocumentNL" in first["cited_sources_str"]
    assert first["completion_state"] == "Answered"
    assert first["is_searched"] == "Yes"
    # KPI rework: previous "Searches" tile is now split into two.
    kpi_labels = {kpi["label"]: kpi["value"] for kpi in stub.mcs_knowledge_kpis}
    assert kpi_labels["Turns w/ Knowledge"] == "20"
    assert kpi_labels["Orchestrator Searches"] == "13"
    assert "20 turns used knowledge" in stub.mcs_knowledge_attribution_summary

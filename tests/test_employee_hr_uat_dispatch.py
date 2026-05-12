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
    return profile, build_timeline(activities, lookup, profile=profile)


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


def test_citations_attached_to_matching_searches(timeline) -> None:
    """Tier 1: a knowledge search whose triggering turn also produced
    CBResponse citations should carry those citations (with full snippet
    body) as `search_results`, tagged `result_type='citation'`."""
    _, tl = timeline
    with_citations = [
        ks
        for ks in tl.knowledge_searches
        if any(r.result_type == "citation" for r in ks.search_results)
    ]
    # 3 of 13 search turns have CBResponse data; the other 10 took the
    # AI-Builder-only code path and have no snippet body to recover.
    assert len(with_citations) == 3, f"Expected 3 searches with citation rows, got {len(with_citations)}"

    parking_searches = [ks for ks in with_citations if "parking" in (ks.triggering_user_message or "").lower()]
    assert len(parking_searches) >= 1
    parking_result = next(
        (r for r in parking_searches[0].search_results if r.name == "FAQ-Parking-EN.pdf"),
        None,
    )
    assert parking_result is not None
    assert parking_result.text is not None and len(parking_result.text) > 1000
    assert parking_result.result_type == "citation"


def test_kt_attribution_resolves_to_urls(timeline) -> None:
    """Tier 2: every cited source name from KTD gets a clickable SharePoint
    root URL via lookup against profile.components. Turn 1 (parental leave)
    has no CBResponse but does have KTD attribution for HR Document NL +
    NewHRKnowledge_Ap."""
    _, tl = timeline
    # Find turn 1's search.
    turn1 = next(
        ks
        for ks in tl.knowledge_searches
        if "How does the parental leave" in (ks.triggering_user_message or "")
    )
    kt_rows = [r for r in turn1.search_results if r.result_type == "kt_attribution"]
    assert len(kt_rows) >= 2, f"Turn 1 should have ≥2 KT-attribution rows, got {len(kt_rows)}"
    urls = {r.url for r in kt_rows}
    assert any(u and "intranet-001-hr/INGDocuments" in u for u in urls), (
        f"HR Document NL root URL missing; got {urls}"
    )
    # Tier 2 rows carry no snippet body.
    assert all(not r.text for r in kt_rows)


def test_bot_reply_links_extracted(timeline) -> None:
    """Tier 3: markdown links inside the bot's reply text are extracted
    as `result_type='bot_reply_link'` rows. Turn 1's bot reply contains
    `[Parental Leave Policy – ING](https://www.rijksoverheid.nl/...)` —
    that URL must surface."""
    _, tl = timeline
    turn1 = next(
        ks
        for ks in tl.knowledge_searches
        if "How does the parental leave" in (ks.triggering_user_message or "")
    )
    link_rows = [r for r in turn1.search_results if r.result_type == "bot_reply_link"]
    assert len(link_rows) >= 1, f"Turn 1 should have ≥1 bot-reply-link row, got {len(link_rows)}"
    urls = {r.url for r in link_rows}
    assert any("rijksoverheid.nl" in (u or "") for u in urls), (
        f"rijksoverheid.nl URL missing from bot-reply extraction; got {urls}"
    )


def test_tools_tab_ai_builder_summary(timeline) -> None:
    """Tools tab gains an AI Builder Calls section: one row per
    aIModelDefinitions entry, plus runtime totals harvested from
    TurnPromptMetrics."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_topics_data(stub, profile, tl)

    # Four aIModelDefinitions in the fixture; every one gets a row.
    assert len(stub.mcs_tools_ai_builder_summary) == 4
    names = {r["name"] for r in stub.mcs_tools_ai_builder_summary}
    assert "Ticket Eligibility Checker" in names
    assert "Response Structure" in names

    # The Ticket Eligibility Checker fires once per Path A turn (10 such
    # turns) + Path B (3 turns × CB variant) ≈ 13–16 runtime calls.
    tec = next(r for r in stub.mcs_tools_ai_builder_summary if r["name"] == "Ticket Eligibility Checker")
    assert int(tec["runtime_call_count"]) >= 13
    assert int(tec["call_site_count"]) == 3
    assert "Topic.TicketEligiblePromptKN" not in tec["topics_text"]  # topics_text uses host display names, not vars


def test_tools_tab_ai_builder_per_call(timeline) -> None:
    """Per-call detail surfaces each runtime invocation that maps to an
    AI Builder model via the variable_name → call-site mapping."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_topics_data(stub, profile, tl)

    # At least 26 runtime calls (matches what we observed earlier).
    assert len(stub.mcs_tools_ai_builder_calls) >= 26
    # Spot-check one TicketEligibility row.
    tec_row = next(
        r
        for r in stub.mcs_tools_ai_builder_calls
        if r["variable_name"] == "Topic.TicketEligiblePromptKN"
    )
    assert tec_row["model_display"] == "Ticket Eligibility Checker"
    assert tec_row["model_id"].startswith("b030db4e")
    # The TicketEligibility classifier's output is always "Eligible" or "Not Eligible".
    assert tec_row["output_preview"].strip() in {"Eligible", "Not Eligible"}


def test_path_label_per_card(timeline) -> None:
    """Each search card carries a path classifier: B = CBResponse-driven,
    A = orchestrator + AI Builder (no snippets in export), C = inferred
    from bot reply only."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    searches = [r for r in stub.mcs_knowledge_searches if r.get("kind") == "search"]

    parking_cards = [r for r in searches if "parking policy" in r["query"].lower()]
    assert parking_cards, "expected at least one parking-policy search card"
    assert any("Path B" in r["path_label"] for r in parking_cards), (
        "at least one parking card should classify as Path B (CBResponse)"
    )

    parental_first = next(r for r in searches if "parental leave policy" in r["query"].lower())
    assert "Path A" in parental_first["path_label"], (
        f"first parental-leave card should be Path A; got {parental_first['path_label']}"
    )
    assert parental_first["path_color_scheme"] == "amber"


def test_rewrite_strip_populated(timeline) -> None:
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    card = next(
        r
        for r in stub.mcs_knowledge_searches
        if r.get("kind") == "search" and "parental leave policy" in r["query"].lower()
    )
    rewrite = card["rewrite_html"]
    # Both the user's literal question AND the orchestrator's derived
    # search query must appear in the rewrite-strip block.
    assert "How does parental leave work" in rewrite
    assert "parental leave policy at ING" in rewrite


def test_data_flow_html_mentions_missing_snippet_cause(timeline) -> None:
    """Path A cards must explain in plain language that snippet bodies
    aren't preserved in this export."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    card = next(
        r
        for r in stub.mcs_knowledge_searches
        if r.get("kind") == "search" and "parental leave policy" in r["query"].lower()
    )
    flow = card["data_flow_html"]
    assert "fullResults" in flow
    assert "not preserved" in flow or "not in export" in flow
    # The KTD attribution + the answer composer should both appear.
    assert "KnowledgeTraceData" in flow
    assert "AI Builder" in flow


def test_raw_trace_html_lists_step_events(timeline) -> None:
    """Raw-trace accordion content should include the key activities for
    a Path A card: plan step trigger, USTD/KTD, variable assignments,
    bot message."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    card = next(
        r
        for r in stub.mcs_knowledge_searches
        if r.get("kind") == "search" and "parental leave policy" in r["query"].lower()
    )
    trace = card["raw_trace_html"]
    # Each event type ends up rendered with its name in the trace.
    assert "StepTriggered" in trace
    assert "KnowledgeSearch" in trace
    assert "BotMessage" in trace
    assert "VariableAssignment" in trace


def test_empty_row_cause_subline_present(timeline) -> None:
    """Every ⚫ (no snippet body) row gets an inline cause subline so the
    user doesn't have to hover the icon to learn why."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _Stub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _Stub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    card = next(
        r
        for r in stub.mcs_knowledge_searches
        if r.get("kind") == "search" and "parental leave policy" in r["query"].lower()
    )
    html = card["results_html"]
    # Subline marker "↳" appears whenever a row has no snippet body.
    assert "↳" in html
    low = html.lower()
    assert "no snippet body" in low or "from the export" in low


def test_prompt_response_text_harvested(timeline) -> None:
    """Every PromptResponse-shaped variable assignment in the fixture
    carries a `text` field — that's the AI Builder model's actual output
    for that LLM invocation. Locked at 27 entries (one per metrics row)."""
    _, tl = timeline
    with_text = [m for m in tl.turn_prompt_metrics if m.text]
    assert len(with_text) >= 27, f"expected ≥27 metrics with text, got {len(with_text)}"
    # Find a chat-model metric with a substantive text body.
    chat_metric = next((m for m in with_text if m.model_name and m.model_name.startswith("gpt-5-chat")), None)
    assert chat_metric is not None
    assert chat_metric.text and len(chat_metric.text) > 0


def test_composed_answers_extracted(timeline) -> None:
    """`CBResponse.Text.MarkdownContent` per turn — the bot's final composed
    answer. 3 entries in the fixture (the 3 turns that went through the
    Conversational boosting topic)."""
    _, tl = timeline
    assert len(tl.composed_answers) == 3
    md = " ".join((a.markdown_content or "") for a in tl.composed_answers)
    assert "Summary" in md
    # is_sydney_summarised should be False for every entry in this fixture.
    assert all(a.is_sydney_summarised is False for a in tl.composed_answers)


def test_citation_filename_metadata_extracted(timeline) -> None:
    """Citation snippet tails ("Filename: …, File Type: …") are regex-
    parsed into structured fields."""
    _, tl = timeline
    faq = next((c for c in tl.citation_sources if c.name == "FAQ-Parking-EN.pdf"), None)
    assert faq is not None
    assert faq.filename == "FAQ-Parking-EN.pdf"
    assert faq.file_type == "pdf"


def test_turn_context_harvested(timeline) -> None:
    """Per-turn auxiliary signals (language, queries, ticket eligibility)
    aggregate into `TurnContext` rows."""
    _, tl = timeline
    assert len(tl.turn_contexts) >= 10
    # At least one row should carry a language signal.
    assert any(tc.language for tc in tl.turn_contexts)
    # At least one row should carry a keyword search query.
    assert any(tc.keyword_search_query for tc in tl.turn_contexts)


def test_inline_prompt_extra_fields(timeline) -> None:
    """The Conversational boosting InlinePrompt now carries moderation,
    latency, and file-search-mode configuration from the SAS node."""
    profile, _ = timeline
    cb = next(
        ip
        for ip in profile.inline_prompts
        if ip.host_topic_display == "Conversational boosting"
    )
    assert cb.moderation_level == "Medium"
    assert cb.latency_message is not None and "moment" in cb.latency_message.lower()
    assert cb.file_search_mode == "DoNotSearchFiles"


def test_knowledge_source_extra_fields(timeline) -> None:
    """KnowledgeSourceComponent rows now carry modified_at + (when present)
    additional_search_terms."""
    profile, _ = timeline
    ks_comps = [c for c in profile.components if c.kind == "KnowledgeSourceComponent"]
    # Every KS in this fixture has a modifiedTimeUtc audit timestamp.
    assert all(c.modified_at for c in ks_comps)


def test_dashboard_state_exposes_composed_answers(timeline) -> None:
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _StateStub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _StateStub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    assert len(stub.mcs_knowledge_composed_answers) == 3
    first = stub.mcs_knowledge_composed_answers[0]
    assert first["preview"]
    assert int(first["char_count"]) > 100
    # Turn-context rows surface too.
    assert len(stub.mcs_knowledge_turn_contexts) >= 10
    # Citation rows now carry filename + file_type.
    faq_row = next(r for r in stub.mcs_knowledge_citations if r["name"] == "FAQ-Parking-EN.pdf")
    assert faq_row["file_type"] == "pdf"


def test_dashboard_knowledge_ux_overhaul_fields(timeline) -> None:
    """Lock the new state-row fields powering the Knowledge tab redesign:
    outcome border, bot-reply inline, metrics strip, anchor href, turn
    strip, clusters, and heatmap rows."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _StateStub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _StateStub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)

    # Phase 1d — every search row has a tone + pre-rendered border CSS.
    searches = [r for r in stub.mcs_knowledge_searches if r.get("kind") == "search"]
    assert all(r.get("outcome_tone") in {"good", "info", "warn", "bad", "neutral"} for r in searches)
    assert all("solid" in r.get("border_left_css", "") for r in searches)
    # Phase 1c — bot reply text is attached when a bot reply exists for the turn.
    parking_rows = [r for r in searches if "parking" in r["query"].lower()]
    assert any(r.get("bot_reply_text") for r in parking_rows), (
        "At least one parking turn should carry inline bot-reply text"
    )

    # Phase 1e — citation dedup collapses 6 raw → 4 unique entries; FAQ row
    # records that it was cited in at least 1 turn.
    assert len(stub.mcs_knowledge_citations) == 4
    faq = next(r for r in stub.mcs_knowledge_citations if r["name"] == "FAQ-Parking-EN.pdf")
    assert int(faq["cited_turn_count"]) >= 1

    # Phase 1f — attribution rows carry anchor hrefs so click-through works.
    attr_rows = stub.mcs_knowledge_attributions
    assert any(r.get("anchor_href", "").startswith("#search-") for r in attr_rows)

    # Phase 2a — metrics strip is non-empty on at least one search/turn.
    assert any(r.get("metrics_strip") for r in attr_rows)

    # Phase 2c — turn strip has one chip per unique answered turn (≤ 13).
    assert 1 <= len(stub.mcs_knowledge_turn_strip) <= 13
    assert all("tone" in c and "anchor_href" in c for c in stub.mcs_knowledge_turn_strip)

    # Phase 3a — clusters: at least the parking question (asked 7 times in the
    # fixture) collapses to one cluster row.
    cluster_repr = " ".join(c["representative_turn"].lower() for c in stub.mcs_knowledge_clusters)
    assert "parking" in cluster_repr or "parental" in cluster_repr or "internal" in cluster_repr

    # Phase 3b — heatmap row per knowledge source, with a pre-rendered emoji
    # string for the cells (no nested foreach).
    assert len(stub.mcs_knowledge_heatmap) == 11  # 11 KnowledgeSourceComponents
    assert all("cells_str" in r and "summary" in r for r in stub.mcs_knowledge_heatmap)


def test_tier_badges_in_dashboard_rows(timeline) -> None:
    """Dashboard `results_text` strings carry tier prefixes (📎/📚/🔗) so
    users can distinguish snippet-backed citations from inferred ones."""
    profile, tl = timeline
    from web.state._upload import UploadMixin

    class _StateStub:
        def __setattr__(self, n, v):
            object.__setattr__(self, n, v)

    stub = _StateStub()
    UploadMixin._populate_knowledge_data(stub, profile, tl)
    search_rows = [r for r in stub.mcs_knowledge_searches if r.get("kind") == "search"]
    # Find a parking-turn row (Tier-1 citation territory).
    parking_row = next(r for r in search_rows if "parking" in r["query"].lower())
    assert "📎" in parking_row["results_text"], (
        f"Tier-1 badge missing from parking row: {parking_row['results_text'][:200]!r}"
    )
    # Turn 1: parental-leave Path A — Tier 2 + Tier 3 only.
    parental_row = next(r for r in search_rows if "parental leave" in r["query"].lower())
    assert "📚" in parental_row["results_text"] or "🔗" in parental_row["results_text"], (
        f"Tier-2/3 badges missing from parental-leave row: {parental_row['results_text'][:200]!r}"
    )


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

    # Phase 1e: citation rows are deduped by (name, url) — the 6 raw
    # CitationSources collapse to 4 unique cards (FAQ-Parking-EN.pdf and
    # ING-employee-parking.aspx each appear in 2 turns).
    assert len(stub.mcs_knowledge_citations) <= len(tl.citation_sources)
    assert len(stub.mcs_knowledge_citations) == 4
    # Find the FAQ-Parking-EN.pdf entry — it appears in turns 15 + 18 in the
    # fixture; the deduped row should record both.
    faq_row = next(r for r in stub.mcs_knowledge_citations if r["name"] == "FAQ-Parking-EN.pdf")
    assert int(faq_row["cited_turn_count"]) >= 1
    assert faq_row["url"].startswith("https://")
    assert int(faq_row["char_count"]) > 1000
    # Citation count surfaces in the attribution summary suffix.
    assert "citation" in stub.mcs_knowledge_attribution_summary


def test_turn_prompt_metrics_extracted(timeline) -> None:
    _, tl = timeline
    assert len(tl.turn_prompt_metrics) >= 7, (
        f"Expected ≥7 turn-prompt-metrics rows, got {len(tl.turn_prompt_metrics)}"
    )
    first = tl.turn_prompt_metrics[0]
    assert first.model_name == "gpt-5-chat-2025-07-14"
    assert first.prompt_tokens is not None and first.prompt_tokens > 1000
    assert first.completion_tokens is not None and first.completion_tokens >= 1
    assert first.copilot_credits is not None and first.copilot_credits >= 0


def test_turn_prompt_metrics_bound_to_turn(timeline) -> None:
    _, tl = timeline
    assert all(
        m.triggering_user_message is None or m.triggering_user_message
        for m in tl.turn_prompt_metrics
    )
    assert any(
        m.triggering_user_message and "parental leave" in m.triggering_user_message.lower()
        for m in tl.turn_prompt_metrics
    )


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

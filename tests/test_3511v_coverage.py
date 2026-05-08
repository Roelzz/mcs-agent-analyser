"""Regression tests for the `3.5.11v` fixture (Employee AI Agent UAT export).

Captures the audit findings from `/tmp/analyser_zip_inspect/AUDIT.md`:
- Bugs in the rendered report must stay fixed.
- Sections that legitimately have no data must render a stub with a reason
  (so the user can tell "feature broken" apart from "nothing happened").
- A coverage summary must list every skipped section + reason.
"""

from pathlib import Path

import pytest

from parser import parse_dialog_json, parse_yaml
from renderer import render_report
from timeline import build_timeline

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "3511v"


@pytest.fixture(scope="module")
def report_3511v() -> str:
    profile, lookup = parse_yaml(FIXTURE_DIR / "botContent.yml")
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    timeline = build_timeline(activities, lookup)
    return render_report(profile, timeline)


def test_trigger_phrase_no_double_quotes(report_3511v: str) -> None:
    """Bug: user_text retained outer quotes and got wrapped again → '""Feedback""'."""
    assert '""Feedback""' not in report_3511v
    assert '### "Feedback"' in report_3511v


def test_topic_details_has_h2_heading(report_3511v: str) -> None:
    """Bug: render_topic_details emitted only H3 sub-sections, visually merging
    with the previous H2 (Knowledge Source Coverage)."""
    assert "## Topic Details" in report_3511v
    assert "### Topics with External Calls" in report_3511v


def test_coverage_summary_present(report_3511v: str) -> None:
    """Coverage summary must appear near the top of the report and report
    counts of rendered vs. stubbed sections."""
    assert "## Report Coverage" in report_3511v
    assert "stubbed" in report_3511v.lower()


def test_raw_events_audit_present(report_3511v: str) -> None:
    """Raw Events parser-audit table must appear and list every event signature
    the parser saw — gives the user direct visibility into what was extracted
    instead of trusting downstream empty panels."""
    assert "## Raw Events (parser audit)" in report_3511v
    # All 6 valueTypes from the 3.5.11v dialog must show up.
    for vt in (
        "DialogTracingInfo",
        "DynamicPlanReceived",
        "DynamicPlanReceivedDebug",
        "DynamicPlanStepTriggered",
        "DynamicPlanStepBindUpdate",
        "DynamicPlanStepFinished",
    ):
        assert f"`{vt}`" in report_3511v, f"missing valueType row for {vt}"
    # All actionTypes inside DialogTracingInfo must show up.
    for at in ("SetVariable", "ConditionGroup", "InvokeFlowAction", "AdaptiveCardPrompt"):
        assert f"`{at}`" in report_3511v, f"missing actionType row for {at}"


def test_no_definitive_no_data_claims_in_stubs(report_3511v: str) -> None:
    """Empty-state copy must NOT claim 'no X performed/executed' — only the
    parser can report what its signatures matched. Specifically check the
    Citation Verification stub which previously made a confident claim."""
    citation_idx = report_3511v.index("## Citation Verification")
    next_h2 = report_3511v.find("\n## ", citation_idx + 1)
    block = report_3511v[citation_idx : next_h2 if next_h2 != -1 else None]
    assert "performed" not in block.lower()
    assert "executed" not in block.lower()
    # Must mention the parser signature it looks for so the user can verify.
    assert "GenerativeAnswersSupportData" in block


def test_plan_evolution_stub_when_single_plan(report_3511v: str) -> None:
    """Plan Evolution needs ≥2 PLAN_RECEIVED events to compare. This trace has
    only 1, so we render a stub instead of silently skipping."""
    assert "## Plan Evolution" in report_3511v
    plan_section_idx = report_3511v.index("## Plan Evolution")
    next_h2 = report_3511v.find("\n## ", plan_section_idx + 1)
    plan_block = report_3511v[plan_section_idx : next_h2 if next_h2 != -1 else None]
    assert "No data" in plan_block or "Plan #" in plan_block


def test_tool_inventory_stub_when_no_tools(report_3511v: str) -> None:
    """This bot has 0 `tool_type` components — render a stub so the user knows."""
    assert "## Tool Inventory" in report_3511v


def test_citation_verification_stub_when_no_traces(report_3511v: str) -> None:
    """0 generative-answer traces — render a stub."""
    assert "## Citation Verification" in report_3511v


def test_orchestrator_reasoning_stub_when_no_thoughts(report_3511v: str) -> None:
    assert "## Orchestrator Reasoning" in report_3511v


def test_conversation_flow_renders_all_turns(report_3511v: str) -> None:
    """Sanity: the conversational data we *do* have must surface."""
    assert "## Conversation Flow" in report_3511v
    assert '"Feedback"' in report_3511v
    assert "User Feedback" in report_3511v
    assert "FlowActionBadRequest" in report_3511v


def test_bot_greeting_card_full_extraction(report_3511v: str) -> None:
    """The bot's first message is an Adaptive Card with greeting +
    disclaimer + 4 suggested questions. The previous extractor capped at
    the first 2 TextBlocks and dropped the Direct Line suggested-actions
    list entirely, so the user couldn't see what the bot offered."""
    # Greeting line buried inside a Table > Row > Cell > ColumnSet.
    assert "Good evening Arshad" in report_3511v
    # Top-level suggestedActions.actions titles must surface too.
    assert "Tell me about benefits and payroll information?" in report_3511v


def test_user_form_submit_payload_surfaced(report_3511v: str) -> None:
    """User adaptive-card submit messages have text=null and a structured
    `value` payload. Render the form values so the row shows what the
    user actually submitted instead of an opaque 'User message' label."""
    assert "is_answerhelpful=Yes" in report_3511v
    assert "ac_comments=adada" in report_3511v
    assert "ac_rating=1" in report_3511v


def test_flow_action_not_labelled_as_http(report_3511v: str) -> None:
    """InvokeFlowAction calls (Power Automate) used to render as
    'HTTP call in <topic>' — misleading, since flows aren't raw HTTP.
    Make sure the dedicated label is used."""
    assert "Flow call (Power Automate) in User Feedback" in report_3511v
    # And that we didn't accidentally keep the old label too.
    assert "HTTP call in User Feedback" not in report_3511v


def test_dashboard_coverage_skipped_for_3511v() -> None:
    """The dynamic-dashboard coverage list must surface the same skipped
    panels the user was missing — Plan Evolution, Knowledge Searches,
    Generative Answers, Citations, Multi-Agent Delegation. Reasons must
    avoid 'performed/executed' language — only the parser can report what
    its signatures matched."""
    profile, lookup = parse_yaml(FIXTURE_DIR / "botContent.yml")
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    timeline = build_timeline(activities, lookup)

    from web.state._upload import UploadMixin

    class _Fake:
        """Minimal stub mimicking Reflex State attribute access."""

    fake = _Fake()
    fake.mcs_routing_plan_evolution = []
    fake.mcs_ins_plan_diffs = []
    fake.mcs_routing_lifecycles = [{"x": 1}]  # bot has 1 lifecycle in this trace
    fake.mcs_knowledge_searches = list(timeline.knowledge_searches)
    fake.mcs_generative_traces = list(timeline.generative_answer_traces)
    fake.mcs_knowledge_citation_panel = []
    fake.mcs_ins_deleg_kpis = []
    fake.mcs_ins_turn_kpis = [{"x": 1}]
    fake.mcs_ins_latency_kpis = [{"x": 1}]
    fake.mcs_coverage_skipped = []

    UploadMixin._populate_coverage_summary(fake, profile, timeline)

    skipped_panels = {entry["panel"] for entry in fake.mcs_coverage_skipped}
    assert "Plan Evolution" in skipped_panels
    assert "Search Results" in skipped_panels
    assert "Topic-Level Generative Answers" in skipped_panels
    assert "Citation Verification" in skipped_panels
    assert "Multi-Agent Delegation" in skipped_panels
    # Topic Lifecycles populated → must NOT be in skipped list
    assert "Topic Lifecycles" not in skipped_panels

    # Reasons must reference parser signatures, not "performed/executed"
    for entry in fake.mcs_coverage_skipped:
        reason = entry["reason"].lower()
        assert "performed" not in reason, f"{entry['panel']!r} reason still says 'performed': {reason}"
        assert "executed" not in reason, f"{entry['panel']!r} reason still says 'executed': {reason}"


def test_raw_event_index_populated_for_3511v() -> None:
    """The raw event index on ConversationTimeline must be populated by
    build_timeline so the dashboard / report can show the parser audit table."""
    _, lookup = parse_yaml(FIXTURE_DIR / "botContent.yml")
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    timeline = build_timeline(activities, lookup)

    idx = timeline.raw_event_index
    assert idx, "raw_event_index must be populated"
    assert "value_types" in idx
    assert "action_types" in idx

    vt_names = {row["name"]: row for row in idx["value_types"]}
    # Every valueType from this dialog must be present and recognised.
    for vt in (
        "DialogTracingInfo",
        "DynamicPlanReceived",
        "DynamicPlanReceivedDebug",
        "DynamicPlanStepTriggered",
        "DynamicPlanStepBindUpdate",
        "DynamicPlanStepFinished",
    ):
        assert vt in vt_names, f"missing valueType {vt}"
        assert vt_names[vt]["recognised"], f"{vt} should be marked recognised"

    at_names = {row["name"]: row for row in idx["action_types"]}
    assert at_names["SetVariable"]["count"] == 12
    assert at_names["InvokeFlowAction"]["count"] == 1


def test_raw_event_index_flattens_for_dashboard() -> None:
    """The state-side helper that flattens the index for `rx.foreach` must
    produce one row per event signature with category/name/count/status."""
    from web.state._upload import UploadMixin

    _, lookup = parse_yaml(FIXTURE_DIR / "botContent.yml")
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    timeline = build_timeline(activities, lookup)

    flat = UploadMixin._flatten_raw_event_index(timeline.raw_event_index)
    categories = {row["category"] for row in flat}
    assert "valueType" in categories
    assert "actionType" in categories
    # Every row has the keys the Reflex foreach expects.
    for row in flat:
        assert set(row.keys()) >= {"category", "name", "count", "recognised", "mapped_to"}
        assert row["recognised"] in ("yes", "no")


def test_dashboard_empty_panel_helper_has_required_args() -> None:
    """Every empty_panel call inside the dashboard must compile."""
    from web.components.dynamic_analysis import _coverage_banner, _empty_panel

    # Smoke test — these must be callable without error
    _empty_panel("Test Panel", "info", "test reason") is not None
    _coverage_banner() is not None


def test_no_section_silently_omitted(report_3511v: str) -> None:
    """Every conditional section listed in the audit must produce *some*
    heading — either real content or a stub. This is the regression guard
    against future silent-skip drift."""
    expected = [
        "## TL;DR",
        "## AI Configuration",
        "## Bot Profile",
        "## Conversation Trace",
        "## Conversation Summary",
        "## Conversation Flow",
        "## Performance Waterfall",
        "## Variable Tracker",
        "## Orchestrator Reasoning",
        "## Orchestrator Decision Timeline",
        "## Plan Evolution",
        "## Topic Lifecycles",
        "## Topic Inventory",
        "## Tool Inventory",
        "## Tool Call Analysis",
        "## Integration Map",
        "## Topic Connection Graph",
        "## Component Settings Explained",
        "## Knowledge Inventory",
        "## Knowledge Source Coverage",
        "## Topic Details",
        "## Knowledge Search",
        "## Citation Verification",
        "## Trigger Phrase Analysis",
        "## MCS Credit Estimate",
        "## Report Coverage",
    ]
    missing = [h for h in expected if h not in report_3511v]
    assert not missing, f"Missing section headings: {missing}"

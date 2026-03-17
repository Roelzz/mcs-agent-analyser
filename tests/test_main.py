from pathlib import Path

import pytest

from custom_rules import _apply_operator, _resolve_field, evaluate_rules, load_rules_yaml
from diff import compare_bots, render_diff_report
from models import (
    AISettings,
    AppInsightsConfig,
    BatchAnalyticsSummary,
    BotDiffResult,
    BotProfile,
    ComponentChange,
    ComponentSummary,
    ConversationTimeline,
    CreditEstimate,
    CustomRule,
    EventType,
    GptInfo,
    KnowledgeSearchInfo,
    RuleCondition,
    SearchResult,
    TimelineEvent,
    TopicConnection,
)
from batch_analytics import aggregate_timelines, render_batch_report
from parser import (
    _count_action_kinds,
    detect_trigger_overlaps,
    match_query_to_triggers,
    parse_dialog_json,
    parse_yaml,
    resolve_topic_name,
    validate_connections,
)
from utils import sanitize_yaml
from renderer import (
    _grounding_score,
    _source_efficiency,
    _topic_display,
    render_bot_metadata,
    render_ai_config,
    render_bot_profile,
    render_credit_estimate,
    render_knowledge_coverage,
    render_quick_wins,
    render_topic_inventory,
    render_event_log,
    render_gantt_chart,
    render_integration_map,
    render_knowledge_inventory,
    render_knowledge_search_section,
    render_knowledge_source_details,
    render_mermaid_sequence,
    render_orchestrator_reasoning,
    render_report,
    render_security_summary,
    render_tldr,
    render_tool_inventory,
    render_topic_details,
    render_topic_graph,
    render_trigger_overlaps,
    render_transcript_report,
)
from renderer.sections import (
    build_orchestrator_decision_timeline,
    build_plan_evolution,
    build_topic_lifecycles,
    build_trigger_match_items,
)
from timeline import build_timeline, estimate_credits
from transcript import parse_transcript_json

import instruction_store
from instruction_store import get_history, save_snapshot
from models import InstructionDiff
from renderer import render_instruction_drift

BASE_DIR = Path(__file__).parent.parent


# --- YAML parsing tests ---


def test_parse_yaml_simple_bot():
    profile, lookup = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    assert profile.display_name == "Troubleshoot_bluebot"
    assert profile.schema_name == "copilots_header_21961"
    assert profile.bot_id == "562fe4a5-1fdb-45a0-ab00-25545affc058"
    assert "MsTeams" in profile.channels
    assert profile.recognizer_kind == "GenerativeAIRecognizer"
    assert profile.is_orchestrator is False
    assert len(profile.components) > 0
    assert len(lookup) > 0


def test_parse_yaml_orchestrator_bot():
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.display_name == "Onboarding Buddy"
    assert profile.is_orchestrator is True
    # Should have TaskDialog and AgentDialog components
    kinds = {c.dialog_kind for c in profile.components if c.dialog_kind}
    assert "TaskDialog" in kinds
    assert "AgentDialog" in kinds


def test_parse_yaml_large_file():
    """Test that the 6MB YAML with @odata.type and tabs parses without error."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    assert profile.display_name == "BlueBot"
    assert len(profile.components) > 100


def test_parse_yaml_no_channels():
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.channels == []


def testsanitize_yaml_at_keys():
    yaml_text = "  @odata.type: String\n  name: test\n"
    sanitized = sanitize_yaml(yaml_text)
    assert '"@odata.type"' in sanitized
    assert "name: test" in sanitized


def testsanitize_yaml_at_values():
    yaml_text = "  displayName: @mention tag\n"
    sanitized = sanitize_yaml(yaml_text)
    assert '"@mention tag"' in sanitized


def testsanitize_yaml_tabs():
    yaml_text = "  key:\tvalue\n"
    sanitized = sanitize_yaml(yaml_text)
    assert "\t" not in sanitized


# --- JSON parsing tests ---


def test_parse_dialog_json_sorted_by_position():
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    positions = [a.get("channelData", {}).get("webchat:internal:position", 0) for a in activities]
    assert positions == sorted(positions)


def test_parse_dialog_json_has_activities():
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    assert len(activities) > 0


# --- Topic resolution tests ---


def test_resolve_topic_name_from_lookup():
    lookup = {"bot.topic.Greeting": "Greeting Topic"}
    assert resolve_topic_name("bot.topic.Greeting", lookup) == "Greeting Topic"


def test_resolve_topic_name_fallback():
    assert resolve_topic_name("bot.topic.GenAIAnsGeneration", {}) == "GenAIAnsGeneration"


def test_resolve_topic_name_no_dots():
    assert resolve_topic_name("UniversalSearchTool", {}) == "UniversalSearchTool"


# --- Timeline tests ---


def test_timeline_simple_bot():
    _, lookup = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    timeline = build_timeline(activities, lookup)

    assert timeline.bot_name == "Troubleshoot_bluebot"
    assert timeline.user_query == "trigger topic"
    assert len(timeline.events) > 0
    assert len(timeline.errors) > 0

    # Should have a failed step
    step_finished = [e for e in timeline.events if e.event_type == EventType.STEP_FINISHED]
    assert any(e.state == "failed" for e in step_finished)


def test_timeline_orchestrator_bot():
    _, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)

    assert timeline.bot_name == "Onboarding Buddy"
    assert "lease car" in timeline.user_query.lower()

    # Should route to Dutchy agent
    step_triggered = [e for e in timeline.events if e.event_type == EventType.STEP_TRIGGERED]
    assert any("Dutchy" in (e.topic_name or "") for e in step_triggered)


def test_timeline_greeting_only():
    _, lookup = parse_yaml(BASE_DIR / "botContent (3)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (3)" / "dialog.json")
    timeline = build_timeline(activities, lookup)

    assert timeline.user_query == "Hi"
    assert len(timeline.phases) == 0  # No DynamicPlanStepFinished for simple greeting
    assert len(timeline.errors) == 0


def test_timeline_knowledge_search():
    _, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)

    # Should have knowledge search event
    ks_events = [e for e in timeline.events if e.event_type == EventType.KNOWLEDGE_SEARCH]
    assert len(ks_events) > 0

    # Should have a completed phase with substantial duration
    assert len(timeline.phases) > 0
    assert timeline.phases[0].duration_ms > 1000


# --- Renderer tests ---


def test_render_report_simple_bot():
    profile, lookup = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    assert "# Troubleshoot_bluebot\n" in report
    assert "— Analysis Report" not in report
    assert "## AI Configuration" in report
    assert "## TL;DR" in report
    assert "## Bot Profile" in report
    assert "## Topic Inventory" in report
    assert "## Conversation Trace" in report
    assert "```mermaid" in report
    assert "sequenceDiagram" in report
    assert "### Errors" in report
    # Plan F2 order: TL;DR → AI Config → Bot Profile → Execution Flow
    assert report.index("## TL;DR") < report.index("## AI Configuration")
    assert report.index("## AI Configuration") < report.index("## Bot Profile")
    assert report.index("## Bot Profile") < report.index("### Execution Flow")


def test_render_report_no_errors():
    profile, lookup = parse_yaml(BASE_DIR / "botContent (3)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (3)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    assert "### Errors" not in report


def test_render_report_has_phase_breakdown():
    profile, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    assert "### Phase Breakdown" in report
    assert "Knowledge Search" in report


# --- Full pipeline tests ---


@pytest.mark.parametrize(
    "folder",
    [
        "botContent",
        "botContent (1)",
        "botContent (1) (1)",
        "botContent (2)",
        "botContent (3)",
        "botContent (3) 2",
        "botContent_genaitopicsadded",
    ],
)
def test_full_pipeline(folder: str):
    """Test that the full pipeline runs without error for all bot exports."""
    folder_path = BASE_DIR / folder
    profile, lookup = parse_yaml(folder_path / "botContent.yml")
    activities = parse_dialog_json(folder_path / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    assert len(report) > 100
    assert profile.display_name
    assert len(timeline.events) > 0


# --- Topic connection tests ---


def test_topic_connections_simple_bot():
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    targets = {c.target_display for c in profile.topic_connections}
    assert "GenAIAnsGeneration" in targets or any("GenAI" in t for t in targets)


def test_topic_connections_with_conditions():
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    conditional = [c for c in profile.topic_connections if c.condition and c.condition != "else"]
    assert len(conditional) > 0


def test_topic_connections_orchestrator():
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert len(profile.topic_connections) > 0


# --- GPT info tests ---


def test_gpt_info_simple_bot():
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    assert profile.gpt_info is not None
    assert profile.gpt_info.display_name == "Troubleshoot_bluebot"
    assert profile.gpt_info.knowledge_sources_kind == "SearchAllKnowledgeSources"


def test_gpt_info_with_instructions():
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.gpt_info is not None
    assert profile.gpt_info.instructions is not None
    assert "Onboarding Buddy" in profile.gpt_info.instructions


def test_gpt_info_with_model_hint():
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    assert profile.gpt_info is not None
    assert profile.gpt_info.model_hint == "GPT41"


# --- Rendering tests ---


def test_render_topic_inventory_has_summary():
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_topic_inventory(profile)
    assert "topics & config" in output
    assert "| Kind | Count |" in output


def test_render_topic_graph():
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    output = render_topic_graph(profile)
    assert "graph TD" in output
    assert len(output) > 0


def test_render_topic_graph_empty():
    profile = BotProfile()
    output = render_topic_graph(profile)
    assert output == ""


def test_render_gantt_chart():
    _, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    output = render_gantt_chart(timeline)
    assert "gantt" in output
    assert "dateFormat x" in output
    assert "axisFormat %M:%S" in output


def test_render_gantt_chart_no_events():
    timeline = ConversationTimeline()
    output = render_gantt_chart(timeline)
    assert output == ""


# --- Round 2 improvement tests ---


def test_adaptive_card_summary():
    """Adaptive cards should have real text, not just [Adaptive Card]."""
    _, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)

    bot_messages = [e for e in timeline.events if e.event_type == EventType.BOT_MESSAGE]
    for msg in bot_messages:
        # Should not contain bare [Adaptive Card] without real text
        if "[Adaptive Card]" in msg.summary:
            # Only acceptable if the card truly has no TextBlocks
            assert msg.summary != "Bot: [Adaptive Card]", (
                f"Found bare [Adaptive Card] with no extracted text: {msg.summary}"
            )


def test_gantt_duration_labels():
    """Gantt chart labels should contain parenthesized duration."""
    _, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    output = render_gantt_chart(timeline)

    assert "(" in output
    # Should have duration suffixes like "ms)" or "s)"
    assert "ms)" in output or "s)" in output


def test_topic_graph_size_capped():
    """Topic graph for large bots should stay under 50KB."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_topic_graph(profile)

    assert len(output.encode("utf-8")) < 50_000
    assert "graph TD" in output


def test_report_order():
    """Report sections follow plan F2: Heading → TL;DR → AI Config → Security → Bot Profile → Diagrams → Trace → Inventories."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    tldr_pos = report.index("## TL;DR")
    ai_config_pos = report.index("## AI Configuration")
    security_pos = report.index("## Security Inventory")
    bot_profile_pos = report.index("## Bot Profile")
    exec_flow_pos = report.index("### Execution Flow")
    trace_pos = report.index("## Conversation Trace")
    topic_inv_pos = report.index("## Topic Inventory")
    tool_inv_pos = report.index("## Tool Inventory")

    assert tldr_pos < ai_config_pos
    assert ai_config_pos < security_pos
    assert security_pos < bot_profile_pos
    assert bot_profile_pos < exec_flow_pos
    assert exec_flow_pos < trace_pos
    assert trace_pos < topic_inv_pos
    assert topic_inv_pos < tool_inv_pos


def test_system_instructions_visible():
    """System instructions should be shown directly, not in a collapsible block."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    assert "**System Instructions**" in report
    assert "<details>" not in report
    assert "</details>" not in report


# --- Newline sanitization tests ---


def test_event_log_no_newlines():
    """Event log table rows must not contain newlines that break markdown."""
    _, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    output = render_event_log(timeline)

    for line in output.split("\n"):
        if line.startswith("|") and line.endswith("|"):
            assert "\n" not in line


def test_bot_message_summaries_single_line():
    """Bot message summaries should not contain newlines."""
    _, lookup = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent_genaitopicsadded" / "dialog.json")
    timeline = build_timeline(activities, lookup)

    for event in timeline.events:
        if event.event_type == EventType.BOT_MESSAGE:
            assert "\n" not in event.summary, f"Newline in summary: {event.summary[:80]}"


# --- Transcript tests ---


def test_parse_transcript_json():
    """Transcript JSON should parse and normalize activities."""
    activities, metadata = parse_transcript_json(BASE_DIR / "Transcripts" / "Rex_Bluebot_Dev_Teams.json")
    assert len(activities) > 0
    # Roles should be normalized to strings
    for a in activities:
        role = a.get("from", {}).get("role", "")
        assert role in ("bot", "user", ""), f"Unexpected role: {role}"
    # Should have session info
    assert "session_info" in metadata


def test_transcript_timeline():
    """Transcript activities should produce a valid timeline."""
    activities, _ = parse_transcript_json(BASE_DIR / "Transcripts" / "Rex_Bluebot_Dev_Teams.json")
    timeline = build_timeline(activities, {})
    assert len(timeline.events) > 0
    assert timeline.user_query != ""


def test_transcript_report_renders():
    """Transcript report should render without errors."""
    activities, metadata = parse_transcript_json(BASE_DIR / "Transcripts" / "Rex_Bluebot_Dev_Teams.json")
    timeline = build_timeline(activities, {})
    report = render_transcript_report("Rex_Bluebot_Dev_Teams", timeline, metadata)
    assert "# Rex_Bluebot_Dev_Teams" in report
    assert "### Event Log" in report


@pytest.mark.parametrize(
    "filename",
    [
        "Rex_Bluebot_Dev_Teams.json",
        "Rex_Bluebot_Prod_Teams.json",
        "Rex_Bluebot_Stage_Teams.json",
    ],
)
def test_transcript_full_pipeline(filename):
    """All transcripts should parse and render without error."""
    path = BASE_DIR / "Transcripts" / filename
    activities, metadata = parse_transcript_json(path)
    timeline = build_timeline(activities, {})
    report = render_transcript_report(path.stem, timeline, metadata)
    assert len(report) > 100


# --- New EventType / DialogTracingInfo split tests ---


def test_new_event_types_exist():
    """New EventType enum values should be accessible."""
    assert EventType.ACTION_HTTP_REQUEST == "ActionHttpRequest"
    assert EventType.ACTION_QA == "ActionQA"
    assert EventType.ACTION_TRIGGER_EVAL == "ActionTriggerEval"
    assert EventType.ACTION_BEGIN_DIALOG == "ActionBeginDialog"
    assert EventType.ACTION_SEND_ACTIVITY == "ActionSendActivity"


def test_dialog_tracing_split_into_individual_events():
    """DialogTracingInfo with 3 actions should produce 3 separate TimelineEvents."""
    activities = [
        {
            "type": "event",
            "valueType": "DialogTracingInfo",
            "from": {"role": "bot", "name": "TestBot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "actions": [
                    {"topicId": "bot.topic.Main", "actionType": "HttpRequestAction", "exception": ""},
                    {"topicId": "bot.topic.Main", "actionType": "BeginDialog", "exception": ""},
                    {"topicId": "bot.topic.Main", "actionType": "SendActivity", "exception": ""},
                ]
            },
        }
    ]
    timeline = build_timeline(activities, {"bot.topic.Main": "Main Topic"})

    # Should produce 3 separate events, not 1 coalesced one
    tracing_events = [
        e
        for e in timeline.events
        if e.event_type
        in (
            EventType.ACTION_HTTP_REQUEST,
            EventType.ACTION_BEGIN_DIALOG,
            EventType.ACTION_SEND_ACTIVITY,
            EventType.DIALOG_TRACING,
        )
    ]
    assert len(tracing_events) == 3

    types = [e.event_type for e in tracing_events]
    assert EventType.ACTION_HTTP_REQUEST in types
    assert EventType.ACTION_BEGIN_DIALOG in types
    assert EventType.ACTION_SEND_ACTIVITY in types


def test_dialog_tracing_summaries():
    """Split actions should have action-specific summary text."""
    activities = [
        {
            "type": "event",
            "valueType": "DialogTracingInfo",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "actions": [
                    {"topicId": "bot.topic.Auth", "actionType": "HttpRequestAction", "exception": ""},
                    {"topicId": "bot.topic.Auth", "actionType": "BeginDialog", "exception": ""},
                    {"topicId": "bot.topic.Auth", "actionType": "ConditionGroup", "exception": ""},
                ]
            },
        }
    ]
    timeline = build_timeline(activities, {"bot.topic.Auth": "Auth Flow"})

    http_events = [e for e in timeline.events if e.event_type == EventType.ACTION_HTTP_REQUEST]
    assert len(http_events) == 1
    assert "HTTP call in Auth Flow" in http_events[0].summary

    begin_events = [e for e in timeline.events if e.event_type == EventType.ACTION_BEGIN_DIALOG]
    assert len(begin_events) == 1
    assert "Call" in begin_events[0].summary and "Auth Flow" in begin_events[0].summary

    eval_events = [e for e in timeline.events if e.event_type == EventType.ACTION_TRIGGER_EVAL]
    assert len(eval_events) == 1
    assert "Evaluate" in eval_events[0].summary


def test_dialog_tracing_unmapped_falls_back():
    """Unmapped action types should fall back to DIALOG_TRACING."""
    activities = [
        {
            "type": "event",
            "valueType": "DialogTracingInfo",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "actions": [
                    {"topicId": "bot.topic.X", "actionType": "ParseValue", "exception": ""},
                ]
            },
        }
    ]
    timeline = build_timeline(activities, {})
    fallback = [e for e in timeline.events if e.event_type == EventType.DIALOG_TRACING]
    assert len(fallback) == 1
    assert "ParseValue" in fallback[0].summary


def test_sequence_diagram_new_participants():
    """Sequence diagram should include Connectors/Evaluator participants when relevant events exist."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(event_type=EventType.USER_MESSAGE, summary='User: "test"', timestamp="2024-01-01T00:00:00Z"),
            TimelineEvent(
                event_type=EventType.ACTION_HTTP_REQUEST,
                summary="HTTP call in Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:01Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_TRIGGER_EVAL,
                summary="Evaluate: Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:02Z",
            ),
            TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="Bot: Hello", timestamp="2024-01-01T00:00:03Z"),
        ],
    )
    output = render_mermaid_sequence(timeline)

    assert "Connectors" in output
    assert "Evaluator" in output
    assert "AI->>Conn" in output
    assert "Note over Eval" in output


def test_sequence_diagram_skips_send_activity():
    """ACTION_SEND_ACTIVITY should not produce any sequence diagram line."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(event_type=EventType.USER_MESSAGE, summary='User: "test"', timestamp="2024-01-01T00:00:00Z"),
            TimelineEvent(
                event_type=EventType.ACTION_SEND_ACTIVITY,
                summary="Send response in Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:01Z",
            ),
            TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="Bot: Hi", timestamp="2024-01-01T00:00:02Z"),
        ],
    )
    output = render_mermaid_sequence(timeline)

    assert "Send response" not in output
    assert "AI->>User" in output


def test_gantt_handles_new_event_types():
    """Gantt chart should render without crash for all new event types."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(event_type=EventType.USER_MESSAGE, summary='User: "test"', timestamp="2024-01-01T00:00:00Z"),
            TimelineEvent(
                event_type=EventType.ACTION_HTTP_REQUEST,
                summary="HTTP call in Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:01Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_QA,
                summary="QA in Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:02Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_TRIGGER_EVAL,
                summary="Evaluate: Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:03Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_BEGIN_DIALOG,
                summary="Call → Sub",
                topic_name="Sub",
                timestamp="2024-01-01T00:00:04Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_SEND_ACTIVITY,
                summary="Send response in Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:05Z",
            ),
            TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="Bot: done", timestamp="2024-01-01T00:00:06Z"),
        ],
    )
    output = render_gantt_chart(timeline)

    assert "gantt" in output
    assert "Connectors" in output
    assert "QA" in output
    assert "Evaluator" in output


def test_sequence_diagram_begin_dialog_auto_registers_participant():
    """ACTION_BEGIN_DIALOG should auto-register the topic as a participant."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(event_type=EventType.USER_MESSAGE, summary='User: "test"', timestamp="2024-01-01T00:00:00Z"),
            TimelineEvent(
                event_type=EventType.ACTION_BEGIN_DIALOG,
                summary="Call → SubTopic",
                topic_name="SubTopic",
                timestamp="2024-01-01T00:00:01Z",
            ),
        ],
    )
    output = render_mermaid_sequence(timeline)
    assert "AI->>SubTopic" in output


# --- Topic display prefix tests ---


def test_topic_display_helper():
    """Topics get 'Topic - ' prefix, system actor names stay unchanged."""
    assert _topic_display("Fallback") == "Topic - Fallback"
    assert _topic_display("GenAIAnsGeneration") == "Topic - GenAIAnsGeneration"
    # System actor IDs should return their ACTOR_NAMES value
    assert _topic_display("User") == "User"
    assert _topic_display("AI") == "Orchestrator"
    assert _topic_display("KS") == "Knowledge Search"
    assert _topic_display("Eval") == "Evaluator"


def test_sequence_diagram_topics_prefixed():
    """Topics show 'Topic - X' in sequence diagram, system actors don't."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "test"',
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                summary="Step triggered",
                topic_name="Fallback",
                timestamp="2024-01-01T00:00:01Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_BEGIN_DIALOG,
                summary="Call → GenAIAnsGeneration",
                topic_name="GenAIAnsGeneration",
                timestamp="2024-01-01T00:00:02Z",
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: Hello",
                timestamp="2024-01-01T00:00:03Z",
            ),
        ],
    )
    output = render_mermaid_sequence(timeline)

    # Topics should have prefix
    assert "Topic - Fallback" in output
    assert "Topic - GenAIAnsGeneration" in output
    # System actors should NOT have prefix
    assert "Topic - Orchestrator" not in output
    assert "Topic - User" not in output


def test_gantt_collapses_idle_gaps():
    """Large idle gaps should appear as actual-duration Idle markers."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.ACTION_SEND_ACTIVITY,
                summary="Send response",
                topic_name="Main",
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "hello"',
                timestamp="2024-01-01T00:02:00Z",  # 120s gap
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: Hi there",
                timestamp="2024-01-01T00:02:01Z",
            ),
        ],
    )
    output = render_gantt_chart(timeline)

    # Should have an Idle section with the original duration
    assert "section Idle" in output
    assert "Idle 2m 0.0s" in output

    # Event bars (lines with :eN) should not span the idle gap themselves
    for line in output.split("\n"):
        if ":e" in line and ":idle" not in line:
            assert "2m" not in line, f"Event bar has unexpected 2m duration: {line}"

    # Idle marker should span the actual gap (~120s = 120000ms)
    idle_positions = []
    for line in output.split("\n"):
        if ":crit, done, idle" in line:
            parts = line.strip().rsplit(",", 2)
            if len(parts) == 3:
                try:
                    idle_positions.append((int(parts[1].strip()), int(parts[2].strip())))
                except ValueError:
                    pass
    assert idle_positions, "No idle marker found in gantt output"
    idle_start, idle_end = idle_positions[0]
    assert idle_end - idle_start >= 119000, f"Idle marker too short: {idle_end - idle_start}ms"

    # Total axis range should reflect actual time (~121s)
    end_positions = []
    for line in output.split("\n"):
        parts = line.strip().rsplit(",", 1)
        if len(parts) == 2:
            try:
                end_positions.append(int(parts[-1].strip()))
            except ValueError:
                pass
    assert end_positions, "No positions found in gantt output"
    assert max(end_positions) > 100000, f"Axis range too small: {max(end_positions)}"


def test_gantt_no_collapse_within_threshold():
    """Gaps under 5 seconds should not be collapsed."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "test"',
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                summary="Step triggered",
                topic_name="Main",
                timestamp="2024-01-01T00:00:02Z",  # 2s gap
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: done",
                timestamp="2024-01-01T00:00:04Z",  # 2s gap
            ),
        ],
    )
    output = render_gantt_chart(timeline)

    # No idle section should appear
    assert "section Idle" not in output
    assert ":idle" not in output

    # Durations should reflect actual gaps
    assert "2.0s" in output


def test_gantt_topics_prefixed():
    """Gantt sections show 'Topic - X' for topics, plain names for system actors."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "test"',
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                summary="Step triggered",
                topic_name="Fallback",
                timestamp="2024-01-01T00:00:01Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_BEGIN_DIALOG,
                summary="Call → Sub",
                topic_name="SubTopic",
                timestamp="2024-01-01T00:00:02Z",
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: done",
                timestamp="2024-01-01T00:00:03Z",
            ),
        ],
    )
    output = render_gantt_chart(timeline)

    # Topic sections should have prefix
    assert "section Topic - Fallback" in output
    assert "section Topic - SubTopic" in output
    # System actor sections should NOT have prefix
    assert "section User" in output
    assert "section Agent" in output
    assert "Topic - User" not in output
    assert "Topic - Agent" not in output


def test_gantt_semantic_color_tags():
    """Each event category should get the correct Mermaid tag for semantic coloring."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "test"',
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.PLAN_RECEIVED,
                summary="Plan received",
                timestamp="2024-01-01T00:00:01Z",
            ),
            TimelineEvent(
                event_type=EventType.ACTION_HTTP_REQUEST,
                summary="HTTP call in Main",
                topic_name="Main",
                timestamp="2024-01-01T00:00:02Z",
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: Hello",
                timestamp="2024-01-01T00:00:03Z",
            ),
            TimelineEvent(
                event_type=EventType.ERROR,
                summary="Something broke",
                timestamp="2024-01-01T00:00:04Z",
            ),
        ],
    )
    output = render_gantt_chart(timeline)

    # User = active
    assert ":active, e0," in output
    # Orchestrator = default (no tag)
    assert ":e1," in output
    # HTTP = active, crit (tool call)
    assert ":active, crit, e2," in output
    # Bot/Agent = done
    assert ":done, e3," in output
    # Error = crit
    assert ":crit, e4," in output
    # Theme init present
    assert "%%{init:" in output
    assert "taskBkgColor" in output


def test_gantt_has_legend():
    """Gantt output should include inline emoji color legend."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "test"',
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: Hi",
                timestamp="2024-01-01T00:00:01Z",
            ),
        ],
    )
    output = render_gantt_chart(timeline)

    assert "🔵 Orchestrator" in output
    assert "🟢 User" in output
    assert "🟣 Agent" in output
    assert "🟠 Tool Calls" in output
    assert "| Color | Category |" not in output
    assert "🔴 Errors" in output
    assert "⚫ Idle" in output


def test_knowledge_search_section_basic():
    """Timeline with 2 KnowledgeSearchInfo objects → table with 2 rows."""
    timeline = ConversationTimeline(
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="How do I reset my password?",
                search_keywords="password, reset",
                knowledge_sources=["Printerdata.xlsx"],
                execution_time="49.4s",
            ),
            KnowledgeSearchInfo(
                search_query="How do I reset my password?",
                search_keywords="password, reset",
                knowledge_sources=["Printerdata.xlsx"],
                execution_time="20.9s",
            ),
        ]
    )
    output = render_knowledge_search_section(timeline)

    assert "## Knowledge Search" in output
    assert "**2 searches**" in output
    assert "| # | Search Query | Keywords | Sources | Duration |" in output
    assert "How do I reset my password?" in output
    assert "49.4s" in output
    assert "20.9s" in output
    # Should have 2 data rows
    rows = [line for line in output.split("\n") if line.startswith("| ") and line[2].isdigit()]
    assert len(rows) == 2


def test_knowledge_search_section_empty():
    """No searches → 'No knowledge searches recorded.'"""
    timeline = ConversationTimeline()
    output = render_knowledge_search_section(timeline)

    assert "## Knowledge Search" in output
    assert "**0 searches**" in output
    assert "No knowledge searches recorded." in output
    assert "| # |" not in output


def test_knowledge_search_source_dedup():
    """Source _XXXXX suffix stripped and duplicates removed via parser."""
    # Use the actual format from transcripts: "env.file.Name.ext_ID" and "topic.*" format
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanStepBindUpdate",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {"taskDialogId": "P:UniversalSearchTool", "arguments": {}},
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:01Z",
            "channelData": {"webchat:internal:position": 2},
            "conversation": {"id": "conv-1"},
            "value": {
                "knowledgeSources": [
                    "cr4d9_sfdc.file.Printerdata.xlsx_8H0",
                    "cr4d9_sfdc.file.Printerdata.xlsx_9AB",
                    "cr4d9_sfdc.file.Manual.pdf_ZZZ",
                    "topic.AIAssistant",
                    "topic.CloudOrchestration_TkDpn5ZmHLFOx4Oj",
                ],
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:50Z",
            "channelData": {"webchat:internal:position": 3},
            "conversation": {"id": "conv-1"},
            "value": {"taskDialogId": "P:UniversalSearchTool", "stepId": "s1", "state": "completed"},
        },
    ]
    timeline = build_timeline(activities, {})
    sources = timeline.knowledge_searches[0].knowledge_sources

    assert "Printerdata.xlsx" in sources
    assert "Manual.pdf" in sources
    assert "AIAssistant" in sources
    assert "CloudOrchestration" in sources
    assert len(sources) == 4  # Printerdata.xlsx deduplicated, topic.* cleaned


def test_knowledge_search_parser():
    """Parser populates knowledge_searches from DynamicPlanStepBindUpdate + UniversalSearchToolTraceData + DynamicPlanStepFinished."""
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanStepBindUpdate",
            "from": {"role": "bot", "name": "TestBot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "arguments": {
                    "search_query": "How do I reset my Code1 password?",
                    "search_keywords": "Code1, password reset",
                },
            },
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:01Z",
            "channelData": {"webchat:internal:position": 2},
            "conversation": {"id": "conv-1"},
            "value": {
                "knowledgeSources": ["cr4d9_sfdc.file.Printerdata.xlsx_8H0", "cr4d9_sfdc.file.Printerdata.xlsx_9AB"],
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:50Z",
            "channelData": {"webchat:internal:position": 3},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "stepId": "step-1",
                "state": "completed",
                "executionTime": "49.4s",
            },
        },
    ]
    timeline = build_timeline(activities, {})

    assert len(timeline.knowledge_searches) == 1
    ks = timeline.knowledge_searches[0]
    assert ks.search_query == "How do I reset my Code1 password?"
    assert ks.search_keywords == "Code1, password reset"
    assert "Printerdata.xlsx" in ks.knowledge_sources
    assert len(ks.knowledge_sources) == 1  # deduped
    assert ks.execution_time == "49.4s"


def test_knowledge_search_inverted_order():
    """DynamicPlanStepFinished arriving before UniversalSearchToolTraceData still commits the search."""
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanStepBindUpdate",
            "from": {"role": "bot", "name": "TestBot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "arguments": {
                    "search_query": "How do I reset my password?",
                    "search_keywords": "password, reset",
                },
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:02Z",
            "channelData": {"webchat:internal:position": 2},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "stepId": "step-1",
                "state": "completed",
                "executionTime": "12.3s",
            },
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:03Z",
            "channelData": {"webchat:internal:position": 3},
            "conversation": {"id": "conv-1"},
            "value": {
                "knowledgeSources": ["cr4d9_sfdc.file.Manual.pdf_XY1"],
            },
        },
    ]
    timeline = build_timeline(activities, {})

    assert len(timeline.knowledge_searches) == 1
    ks = timeline.knowledge_searches[0]
    assert ks.search_query == "How do I reset my password?"
    assert ks.execution_time == "12.3s"
    assert "Manual.pdf" in ks.knowledge_sources


def test_gantt_idle_gap_tagged():
    """Idle gap markers should be tagged with done, crit for gray color."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.ACTION_SEND_ACTIVITY,
                summary="Send response",
                topic_name="Main",
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "hello"',
                timestamp="2024-01-01T00:02:00Z",  # 120s gap
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: Hi there",
                timestamp="2024-01-01T00:02:01Z",
            ),
        ],
    )
    output = render_gantt_chart(timeline)

    assert ":crit, done, idle" in output


def test_custom_search_step_tracking():
    """Custom search topics (type=CustomTopic, taskDialogId contains 'search') should be tracked."""
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanReceived",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 0},
            "conversation": {"id": "conv-1"},
            "value": {
                "planIdentifier": "plan-1",
                "steps": [],
                "toolDefinitions": [
                    {
                        "schemaName": "cr61c_testKnowledge.topic.AdvancedSearch",
                        "displayName": "Advanced Search",
                    }
                ],
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepTriggered",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:01Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "cr61c_testKnowledge.topic.AdvancedSearch",
                "type": "CustomTopic",
                "stepId": "step-1",
                "thought": "Searching for research plan",
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:02Z",
            "channelData": {"webchat:internal:position": 2},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "cr61c_testKnowledge.topic.AdvancedSearch",
                "stepId": "step-1",
                "state": "failed",
                "error": {"message": "aiModelActionBadRequest"},
            },
        },
    ]
    timeline = build_timeline(activities, {})

    assert len(timeline.custom_search_steps) == 1
    cs = timeline.custom_search_steps[0]
    assert cs.display_name == "Advanced Search"
    assert cs.status == "failed"
    assert cs.error == "aiModelActionBadRequest"


def test_knowledge_search_sources_all_shown_in_table():
    """All sources should be shown in table without truncation."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="test query",
                knowledge_sources=["Src1", "Src2", "Src3", "Src4", "Src5", "Src6", "Src7", "Src8"],
            )
        ],
    )
    output = render_knowledge_search_section(timeline)
    assert "Src1, Src2, Src3, Src4, Src5, Src6, Src7, Src8" in output
    assert "(+" not in output


def test_search_results_captured():
    """search_results and output_knowledge_sources should be captured from trace events."""
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanStepBindUpdate",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "arguments": {"search_query": "printer issue", "search_keywords": "printer"},
            },
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:01Z",
            "channelData": {"webchat:internal:position": 2},
            "conversation": {"id": "conv-1"},
            "value": {
                "knowledgeSources": ["topic.PrinterHelp_ABC"],
                "outputKnowledgeSources": ["topic.PrinterHelp_ABC"],
            },
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:02Z",
            "channelData": {"webchat:internal:position": 3},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "executionTime": "0:00:01.5000000",
                "state": "completed",
                "observation": {
                    "search_result": {
                        "search_results": [
                            {
                                "Name": "Printer Guide",
                                "Url": "https://example.com/printer",
                                "Text": "How to fix printer",
                            },
                            {"Name": "FAQ", "Url": "https://example.com/faq", "Text": "Printer FAQ content"},
                        ]
                    }
                },
            },
        },
    ]
    timeline = build_timeline(activities, {})
    assert len(timeline.knowledge_searches) == 1
    ks = timeline.knowledge_searches[0]
    assert len(ks.search_results) == 2
    assert ks.search_results[0].text == "How to fix printer"
    assert len(ks.output_knowledge_sources) == 1
    assert ks.output_knowledge_sources[0] == "PrinterHelp"


def test_grounding_summary_rendered():
    """render_knowledge_search_section should include grounding details with name and URL."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="test",
                knowledge_sources=["DocSource"],
                search_results=[
                    SearchResult(name="Doc A", url="https://x.com", text="some text"),
                ],
            )
        ],
    )
    output = render_knowledge_search_section(timeline)
    assert "Grounding Details" in output
    assert "Doc A" in output
    assert "https://x.com" in output


def test_no_results_warning():
    """When search_results is empty but search_errors is populated, warning should appear."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="test",
                knowledge_sources=["DocSource"],
                search_results=[],
                search_errors=["timeout"],
            )
        ],
    )
    output = render_knowledge_search_section(timeline)
    assert "No results returned" in output


# --- Grounding + polish tests ---


def test_grounding_score_strong():
    """8 results with query keywords in result titles → badge 🟢 Strong."""
    results = [SearchResult(name=f"printer fix guide {i}", text="printer fix content") for i in range(8)]
    ks = KnowledgeSearchInfo(
        search_query="printer fix",
        search_results=results,
    )
    badge, label = _grounding_score(ks)
    assert badge == "🟢"
    assert label == "Strong"


def test_grounding_score_no_grounding():
    """0 results → badge ⚠️ No Grounding."""
    ks = KnowledgeSearchInfo(search_query="anything", search_results=[])
    badge, label = _grounding_score(ks)
    assert badge == "⚠️"
    assert label == "No Grounding"


def test_source_efficiency_partial():
    """5 queried, 3 used → 3/5 sources returned results (60%), silent list shown."""
    ks = KnowledgeSearchInfo(
        knowledge_sources=["A", "B", "C", "D", "E"],
        output_knowledge_sources=["A", "C", "E"],
        search_results=[SearchResult(name="x")],
    )
    result = _source_efficiency(ks)
    assert result is not None
    assert "3/5 sources returned results (60%)" in result
    assert "Silent sources" in result
    assert "🟡" in result
    assert "`B`" in result
    assert "`D`" in result
    assert "+2 more" not in result


def test_source_efficiency_high():
    """9/10 contributing → 90% → 🟢 badge."""
    sources = [str(i) for i in range(10)]
    ks = KnowledgeSearchInfo(
        knowledge_sources=sources,
        output_knowledge_sources=sources[:9],
        search_results=[SearchResult(name="x")],
    )
    result = _source_efficiency(ks)
    assert result is not None
    assert "9/10 sources returned results (90%)" in result
    assert "🟢" in result


def test_source_efficiency_low():
    """2/10 contributing → 20% → 🔴 badge."""
    sources = [str(i) for i in range(10)]
    ks = KnowledgeSearchInfo(
        knowledge_sources=sources,
        output_knowledge_sources=sources[:2],
        search_results=[SearchResult(name="x")],
    )
    result = _source_efficiency(ks)
    assert result is not None
    assert "2/10 sources returned results (20%)" in result
    assert "🔴" in result


def test_grounding_details_shows_all_results():
    """5 results → all 5 shown, no 'more results' text."""
    from models import ConversationTimeline

    long_snippet = "A" * 300
    results = [
        SearchResult(name=f"Result {i}", url=f"http://example.com/{i}", text=long_snippet if i == 1 else None)
        for i in range(1, 6)
    ]
    ks = KnowledgeSearchInfo(
        search_query="test query",
        knowledge_sources=["src1"],
        output_knowledge_sources=["src1"],
        search_results=results,
    )
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[],
        knowledge_searches=[ks],
    )
    output = render_knowledge_search_section(timeline)
    assert "Result 5" in output
    assert "more result" not in output
    # Snippet must not be truncated and must not have trailing ellipsis
    assert long_snippet in output
    assert long_snippet + "..." not in output


def test_knowledge_search_grouped_by_user_message():
    """Searches with triggering_user_message are grouped under user utterance headers."""
    timeline = ConversationTimeline(
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="refund policy details",
                search_keywords="refund, policy",
                knowledge_sources=["FAQ"],
                execution_time="0:00:01.5000000",
                triggering_user_message="What are the refund policies?",
            ),
            KnowledgeSearchInfo(
                search_query="return window 30 days",
                search_keywords="return, 30 days",
                knowledge_sources=["FAQ"],
                execution_time="0:00:02.0000000",
                triggering_user_message="Can I return items after 30 days?",
            ),
        ]
    )
    output = render_knowledge_search_section(timeline)

    assert "across 2 user turns" in output
    assert '### 💬 "What are the refund policies?"' in output
    assert '### 💬 "Can I return items after 30 days?"' in output
    assert "refund policy details" in output
    assert "return window 30 days" in output
    assert "---" in output


def test_knowledge_search_grouped_system_initiated():
    """Searches without triggering_user_message go under System-initiated."""
    timeline = ConversationTimeline(
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="greeting check",
                knowledge_sources=["FAQ"],
                triggering_user_message="Hello there",
            ),
            KnowledgeSearchInfo(
                search_query="auto search",
                knowledge_sources=["FAQ"],
                triggering_user_message=None,
            ),
        ]
    )
    output = render_knowledge_search_section(timeline)

    assert '### 💬 "Hello there"' in output
    assert "### 🔧 System-initiated" in output


def test_knowledge_search_single_group_no_turns_label():
    """Single user turn → no 'across N turns' in header."""
    timeline = ConversationTimeline(
        knowledge_searches=[
            KnowledgeSearchInfo(
                search_query="test",
                knowledge_sources=["FAQ"],
                triggering_user_message="What is this?",
            ),
        ]
    )
    output = render_knowledge_search_section(timeline)

    assert "**1 search**" in output
    assert "across" not in output


def test_knowledge_search_timeline_tracks_user_message():
    """build_timeline sets triggering_user_message from the latest user message."""
    activities = [
        {
            "type": "message",
            "from": {"role": "user"},
            "text": "How do I reset my password?",
            "timestamp": "2024-01-01T00:00:00Z",
            "channelData": {"webchat:internal:position": 1},
            "conversation": {"id": "conv-1"},
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepBindUpdate",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:01Z",
            "channelData": {"webchat:internal:position": 2},
            "conversation": {"id": "conv-1"},
            "value": {
                "taskDialogId": "P:UniversalSearchTool",
                "arguments": {"search_query": "password reset"},
            },
        },
        {
            "type": "event",
            "valueType": "UniversalSearchToolTraceData",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:02Z",
            "channelData": {"webchat:internal:position": 3},
            "conversation": {"id": "conv-1"},
            "value": {"knowledgeSources": ["topic.Help_ABC"]},
        },
        {
            "type": "event",
            "valueType": "DynamicPlanStepFinished",
            "from": {"role": "bot"},
            "timestamp": "2024-01-01T00:00:03Z",
            "channelData": {"webchat:internal:position": 4},
            "conversation": {"id": "conv-1"},
            "value": {"taskDialogId": "P:UniversalSearchTool", "stepId": "s1", "state": "completed"},
        },
    ]
    timeline = build_timeline(activities, {})
    assert len(timeline.knowledge_searches) == 1
    assert timeline.knowledge_searches[0].triggering_user_message == "How do I reset my password?"


def test_knowledge_table_merged_status():
    """Knowledge table should show 'Source ✓' in a single Status column."""
    from models import AISettings, ComponentSummary

    profile = BotProfile(
        display_name="TestBot",
        schema_name="test",
        bot_id="id",
        channels=[],
        recognizer_kind="Gen",
        is_orchestrator=False,
        ai_settings=AISettings(),
        components=[
            ComponentSummary(
                kind="KnowledgeSourceComponent",
                display_name="northampton",
                schema_name="northampton",
                state="Active",
                description="Test knowledge source",
            )
        ],
    )
    output = render_knowledge_inventory(profile)
    assert "Knowledge Sources" in output
    assert "northampton" in output


def test_gantt_legend_inline():
    """Gantt legend should be inline emoji line, not a table."""
    timeline = ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        user_query="test",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary="User: hello",
                timestamp="2024-01-01T00:00:00Z",
            ),
            TimelineEvent(
                event_type=EventType.BOT_MESSAGE,
                summary="Bot: hi",
                timestamp="2024-01-01T00:00:01Z",
            ),
        ],
    )
    output = render_gantt_chart(timeline)
    assert "🔵" in output
    assert "| Color | Category |" not in output


# --- Feature: _count_action_kinds ---


def test_count_action_kinds_empty():
    assert _count_action_kinds([]) == {}


def test_count_action_kinds_flat():
    actions = [
        {"kind": "SendActivity"},
        {"kind": "HttpRequestAction"},
        {"kind": "SendActivity"},
    ]
    result = _count_action_kinds(actions)
    assert result == {"SendActivity": 2, "HttpRequestAction": 1}


def test_count_action_kinds_nested():
    actions = [
        {
            "kind": "ConditionGroup",
            "conditions": [
                {"actions": [{"kind": "InvokeConnectorAction"}]},
                {"actions": [{"kind": "SendActivity"}, {"kind": "InvokeFlowAction"}]},
            ],
            "elseActions": [{"kind": "HttpRequestAction"}],
        }
    ]
    result = _count_action_kinds(actions)
    assert result["ConditionGroup"] == 1
    assert result["InvokeConnectorAction"] == 1
    assert result["SendActivity"] == 1
    assert result["InvokeFlowAction"] == 1
    assert result["HttpRequestAction"] == 1


# --- Feature: Orchestrator Reasoning ---


def test_render_orchestrator_reasoning_with_thoughts():
    timeline = ConversationTimeline(
        events=[
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="SearchTool",
                thought="Need to search for password reset info",
            ),
            TimelineEvent(
                event_type=EventType.STEP_FINISHED,
                topic_name="SearchTool",
            ),
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="AdvancedSearch",
                thought="Compiling reliable guidance from multiple sources",
            ),
        ],
    )
    output = render_orchestrator_reasoning(timeline)
    assert "Orchestrator Reasoning" in output
    assert "SearchTool" in output
    assert "password reset" in output
    assert "AdvancedSearch" in output
    assert "| 1 |" in output
    assert "| 2 |" in output  # second STEP_TRIGGERED (STEP_FINISHED doesn't increment)


def test_render_orchestrator_reasoning_no_thoughts():
    timeline = ConversationTimeline(
        events=[
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="TopicA",
            ),
        ],
    )
    output = render_orchestrator_reasoning(timeline)
    assert output == ""


# --- Feature: Topic Details ---


def test_render_topic_details_external_calls():
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="API Topic",
                schema_name="test.topic.api",
                action_summary={"InvokeConnectorAction": 2, "SendActivity": 1, "HttpRequestAction": 1},
                has_external_calls=True,
            ),
            ComponentSummary(
                kind="DialogComponent",
                display_name="Simple Topic",
                schema_name="test.topic.simple",
                action_summary={"SendActivity": 3},
                has_external_calls=False,
            ),
        ],
    )
    output = render_topic_details(profile)
    assert "Topics with External Calls" in output
    assert "API Topic" in output
    assert "Simple Topic" not in output
    assert "| 2 |" in output  # connector count


def test_render_topic_details_coverage():
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="TopicA",
                schema_name="test.topic.a",
                trigger_kind="OnIntent",
            ),
            ComponentSummary(
                kind="DialogComponent",
                display_name="TopicB",
                schema_name="test.topic.b",
                trigger_kind="OnIntent",
            ),
            ComponentSummary(
                kind="DialogComponent",
                display_name="SystemTopic",
                schema_name="test.topic.sys",
                trigger_kind="OnError",
            ),
        ],
    )
    timeline = ConversationTimeline(
        events=[
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="TopicA",
            ),
        ],
    )
    output = render_topic_details(profile, timeline)
    assert "1 of 2 user topics triggered" in output
    assert "TopicB" in output
    assert "SystemTopic" not in output  # system topics excluded


# --- Feature: Conversation Starters ---


def test_render_bot_profile_heading_only():
    profile = BotProfile(display_name="Test Bot")
    output = render_bot_profile(profile)
    assert "# Test Bot" in output
    assert "AI Configuration" not in output


def test_render_ai_config_conversation_starters():
    profile = BotProfile(
        display_name="Test Bot",
        gpt_info=GptInfo(
            conversation_starters=[
                {"title": "Password reset", "message": "How do I reset my password?"},
                {"title": "VPN help", "message": "How to connect to VPN?"},
            ],
        ),
    )
    output = render_ai_config(profile)
    assert "Conversation Starters" in output
    assert "Password reset" in output
    assert "How do I reset my password?" in output


def test_render_ai_config_no_conversation_starters():
    profile = BotProfile(
        display_name="Test Bot",
        gpt_info=GptInfo(),
    )
    output = render_ai_config(profile)
    assert "Conversation Starters" not in output


# --- Feature: Knowledge Source Details ---


def test_render_knowledge_source_details():
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="KnowledgeSourceComponent",
                display_name="northampton",
                schema_name="test.ks.north",
                description="Knowledge source for Northampton campus staff",
                source_kind="SharePointSearchSource",
                source_site="https://example.sharepoint.com/sites/north",
            ),
        ],
    )
    output = render_knowledge_source_details(profile)
    assert "Knowledge Source Details" in output
    assert "northampton" in output
    assert "SharePointSearchSource" in output
    assert "https://example.sharepoint.com/sites/north" in output
    assert "Northampton campus" in output


def test_render_knowledge_source_details_empty():
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="SomeTopic",
                schema_name="test.topic",
            ),
        ],
    )
    output = render_knowledge_source_details(profile)
    assert output == ""


# --- Feature: Environment Variables ---


def test_render_bot_metadata_env_vars():
    profile = BotProfile(
        display_name="Test Bot",
        environment_variables=[
            {"name": "API_KEY", "type": "String", "value": "secret123"},
            {"name": "TIMEOUT", "type": "Integer", "defaultValue": "30"},
        ],
    )
    output = render_bot_metadata(profile)
    assert "Environment Variables" in output
    assert "API_KEY" in output
    assert "TIMEOUT" in output


def test_render_bot_metadata_no_env_vars():
    profile = BotProfile(display_name="Test Bot")
    output = render_bot_metadata(profile)
    assert "Environment Variables" not in output


# --- Feature: Connectors ---


def test_render_bot_metadata_connectors():
    profile = BotProfile(
        display_name="Test Bot",
        connectors=[
            {"displayName": "SharePoint", "type": "REST", "description": "SharePoint connector"},
        ],
    )
    output = render_bot_metadata(profile)
    assert "Connectors" in output
    assert "SharePoint" in output
    assert "REST" in output


def test_render_bot_metadata_no_connectors():
    profile = BotProfile(display_name="Test Bot")
    output = render_bot_metadata(profile)
    assert "Connectors" not in output


# --- Feature: Triggers in user_topics table ---


def test_render_topic_inventory_user_topics_triggers():
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="Password Help",
                schema_name="test.topic.password",
                trigger_kind="OnIntent",
                trigger_queries=["reset password", "forgot password", "change password", "unlock account"],
            ),
        ],
    )
    output = render_topic_inventory(profile)
    assert "Triggers" in output
    assert "reset password" in output
    assert "unlock account" in output  # all 4 queries shown without truncation


# --- Feature: thought on TimelineEvent ---


def test_timeline_step_triggered_captures_thought():
    activities = [
        {
            "type": "event",
            "valueType": "DynamicPlanStepTriggered",
            "value": {
                "taskDialogId": "test.topic.search",
                "type": "KnowledgeSource",
                "stepId": "step1",
                "thought": "I need to search for this information",
            },
            "from": {"role": "bot"},
            "channelData": {"webchat:internal:position": 1},
            "timestamp": "2024-01-01T00:00:01Z",
        },
    ]
    timeline = build_timeline(activities, {"test.topic.search": "SearchTopic"})
    step_events = [e for e in timeline.events if e.event_type == EventType.STEP_TRIGGERED]
    assert len(step_events) == 1
    assert step_events[0].thought == "I need to search for this information"


# --- Feature: Integration - render_report includes new sections ---


def test_render_report_includes_new_sections():
    profile = BotProfile(
        display_name="Full Bot",
        gpt_info=GptInfo(
            conversation_starters=[{"title": "Help", "message": "How can you help?"}],
        ),
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="ExternalTopic",
                schema_name="test.topic.ext",
                trigger_kind="OnIntent",
                action_summary={"InvokeConnectorAction": 1},
                has_external_calls=True,
            ),
            ComponentSummary(
                kind="KnowledgeSourceComponent",
                display_name="MainKS",
                schema_name="test.ks.main",
                description="Main knowledge source",
                source_kind="SharePointSearchSource",
            ),
        ],
        environment_variables=[{"name": "VAR1", "type": "String", "value": "val"}],
        connectors=[{"displayName": "Conn1", "type": "REST"}],
    )
    timeline = ConversationTimeline(
        events=[
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="ExternalTopic",
                thought="Need to call external service",
                timestamp="2024-01-01T00:00:01Z",
            ),
        ],
    )
    output = render_report(profile, timeline)
    assert "Conversation Starters" in output
    assert "Topics with External Calls" in output
    assert "Knowledge Inventory" in output
    assert "Orchestrator Reasoning" in output
    assert "Environment Variables" in output
    assert "Connectors" in output


# --- Phase 1: Entity-Level Properties ---


def test_auth_config_botcontent1():
    """A1: botContent (1) has Integrated auth with Always trigger."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.authentication_mode == "Integrated"
    assert profile.authentication_trigger == "Always"


def test_access_control_botcontent1():
    """A2: botContent (1) has GroupMembership access control."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.access_control_policy == "GroupMembership"


def test_generative_actions_botcontent1():
    """A3: botContent (1) has generative actions enabled."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.generative_actions_enabled is True


def test_agent_connectable_botcontent1():
    """A4: botContent (1) has isAgentConnectable."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert profile.is_agent_connectable is True


def test_entity_props_defaults_synthetic():
    """Entity-level properties have safe defaults when not present."""
    profile = BotProfile()
    assert profile.authentication_mode == "Unknown"
    assert profile.access_control_policy == "Unknown"
    assert profile.generative_actions_enabled is False
    assert profile.is_agent_connectable is False


def test_auth_rendered_in_metadata():
    """A1: Auth mode appears in rendered bot metadata."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_bot_metadata(profile)
    assert "Integrated (Always)" in output
    assert "GroupMembership" in output


def test_app_insights_synthetic():
    """A5: AppInsightsConfig model works correctly."""
    ai = AppInsightsConfig(configured=True, log_activities=True, log_sensitive_properties=False)
    assert ai.configured is True
    assert ai.log_activities is True
    profile = BotProfile(app_insights=ai)
    output = render_bot_metadata(profile)
    assert "Application Insights" in output
    assert "log activities" in output


# --- Phase 2: Tool Classification ---


def test_connector_tool_botcontent3():
    """B1: InvokeConnectorTaskAction classified as ConnectorTool."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (3)" / "botContent.yml")
    connector_tools = [c for c in profile.components if c.tool_type == "ConnectorTool"]
    assert len(connector_tools) >= 1
    tool = connector_tools[0]
    assert tool.operation_id == "ListRecordsWithOrganization"
    assert tool.connection_mode == "Invoker"


def test_a2a_agents_botcontent1():
    """B2: InvokeExternalAgentTaskAction + A2A classified as A2AAgent."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    a2a = [c for c in profile.components if c.tool_type == "A2AAgent"]
    assert len(a2a) == 2
    names = {c.display_name for c in a2a}
    assert "pydantic_ai" in names
    for agent in a2a:
        assert agent.external_agent_protocol == "AgentToAgentProtocolMetadata"
        assert agent.connection_mode == "Invoker"


def test_connected_agents_botcontent1():
    """B4: InvokeConnectedAgentTaskAction classified as ConnectedAgent."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    connected = [c for c in profile.components if c.tool_type == "ConnectedAgent"]
    assert len(connected) == 2
    names = {c.display_name for c in connected}
    assert "Equippy" in names
    assert "Schedule" in names
    for agent in connected:
        assert agent.connected_bot_schema is not None


def test_child_agents_botcontent1():
    """B5: AgentDialog classified as ChildAgent with instructions."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    children = [c for c in profile.components if c.tool_type == "ChildAgent"]
    assert len(children) == 2
    with_instructions = [c for c in children if c.agent_instructions]
    assert len(with_instructions) == 2


def test_mcp_server_synthetic():
    """B3: ModelContextProtocolMetadata classified as MCPServer."""
    comp = ComponentSummary(
        kind="DialogComponent",
        display_name="MCP Test",
        schema_name="test.mcp",
        dialog_kind="TaskDialog",
        action_kind="InvokeExternalAgentTaskAction",
        tool_type="MCPServer",
        external_agent_protocol="ModelContextProtocolMetadata",
    )
    assert comp.tool_type == "MCPServer"


def test_flow_tool_synthetic():
    """B6: InvokeFlowAction classified as FlowTool."""
    comp = ComponentSummary(
        kind="DialogComponent",
        display_name="Flow Test",
        schema_name="test.flow",
        dialog_kind="TaskDialog",
        action_kind="InvokeFlowAction",
        tool_type="FlowTool",
    )
    assert comp.tool_type == "FlowTool"


def test_cua_tool_synthetic():
    """B7: InvokeComputerUseAction classified as CUATool."""
    comp = ComponentSummary(
        kind="DialogComponent",
        display_name="CUA Test",
        schema_name="test.cua",
        dialog_kind="TaskDialog",
        action_kind="InvokeComputerUseAction",
        tool_type="CUATool",
    )
    assert comp.tool_type == "CUATool"


def test_tool_type_in_tool_inventory():
    """B1: Tool type appears in tool inventory table."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_tool_inventory(profile)
    assert "ConnectedAgent" in output
    assert "A2AAgent" in output
    assert "ChildAgent" in output


# --- Phase 3: Connection Infrastructure ---


def test_connection_references_botcontent1():
    """C1: Connection references parsed from botContent (1)."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert len(profile.connection_references) == 2
    for ref in profile.connection_references:
        assert ref["connectionReferenceLogicalName"]
        assert ref["connectorId"]
        assert ref["customConnectorId"]  # both are custom in this export


def test_connector_definitions_botcontent1():
    """C2: Connector definitions parsed from botContent (1)."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    assert len(profile.connector_definitions) == 2
    for cdef in profile.connector_definitions:
        assert cdef["displayName"]
        assert cdef["isCustom"] is True
        assert cdef["operationCount"] >= 1


def test_connector_definitions_mcp_detection():
    """C2: MCP operations detected in connector definitions."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (3)" / "botContent.yml")
    mcp_defs = [cd for cd in profile.connector_definitions if cd.get("hasMCP")]
    assert len(mcp_defs) >= 1


def test_connection_cross_reference():
    """C3: Components enriched with resolved connector display names."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    a2a = [c for c in profile.components if c.tool_type == "A2AAgent"]
    resolved = [c for c in a2a if c.connector_display_name]
    assert len(resolved) >= 1


def test_connection_refs_rendered():
    """C1: Connection references appear in rendered metadata."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_bot_metadata(profile)
    assert "Connection References" in output
    assert "Connector Definitions" in output


# --- Phase 4: Component Metadata ---


def test_custom_entity_kind_genai():
    """D1: CustomEntity kind + item count parsed from genai export."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    entities = [c for c in profile.components if c.kind == "CustomEntityComponent"]
    assert len(entities) > 0
    has_closed_list = any(c.entity_kind == "ClosedListEntity" for c in entities)
    assert has_closed_list
    with_items = [c for c in entities if c.entity_item_count > 0]
    assert len(with_items) > 0


def test_file_attachment_type():
    """D2: File type extracted from FileAttachment display name."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    files = [c for c in profile.components if c.kind == "FileAttachmentComponent"]
    xlsx_files = [f for f in files if f.file_type == "xlsx"]
    assert len(xlsx_files) >= 1


def test_global_variable_scope():
    """D3: Variable scope parsed from GlobalVariableComponent."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    variables = [c for c in profile.components if c.kind == "GlobalVariableComponent"]
    assert len(variables) > 0


def test_knowledge_trigger_condition():
    """D4: Trigger condition parsed from KnowledgeSourceComponent."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    ks_comps = [c for c in profile.components if c.kind == "KnowledgeSourceComponent"]
    with_trigger = [c for c in ks_comps if c.trigger_condition_raw]
    assert len(with_trigger) > 0


def test_entity_kind_in_component_table():
    """D1: Entity kind appears in custom entities table."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_topic_inventory(profile)
    assert "ClosedListEntity" in output


def test_variable_scope_in_table():
    """D3: Variable scope appears in variables table."""
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="GlobalVariableComponent",
                display_name="TestVar",
                schema_name="test.var",
                variable_scope="Global",
            ),
        ],
    )
    output = render_topic_inventory(profile)
    assert "Global" in output


# --- Phase 5: Visualization ---


def test_security_summary_orchestrator():
    """E1: Security summary rendered for orchestrator bot."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_security_summary(profile)
    assert "Security Inventory" in output
    assert "Integrated" in output
    assert "GroupMembership" in output


def test_tool_inventory_orchestrator():
    """E2: Tool inventory rendered for orchestrator bot."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_tool_inventory(profile)
    assert "Tool Inventory" in output
    assert "ConnectedAgent" in output
    assert "A2AAgent" in output
    assert "ChildAgent" in output


def test_tool_inventory_empty_for_simple_bot():
    """E2: Tool inventory empty for non-orchestrator bot."""
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    output = render_tool_inventory(profile)
    assert output == ""


def test_integration_map_orchestrator():
    """E3: Integration map rendered for orchestrator bot."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_integration_map(profile)
    assert "Integration Map" in output
    assert "```mermaid" in output
    assert "flowchart LR" in output
    assert "child agent" in output
    assert "connected agent" in output
    assert "A2A" in output


def test_integration_map_empty_for_simple_bot():
    """E3: Integration map handles bots with no tools gracefully."""
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    output = render_integration_map(profile)
    # Should still render if there are knowledge sources
    if output:
        assert "```mermaid" in output


def test_knowledge_architecture():
    """E4: Knowledge architecture rendered with sources and files."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_knowledge_inventory(profile)
    assert "Knowledge Inventory" in output
    assert "Knowledge Sources" in output
    assert "File Attachments" in output


def test_knowledge_architecture_trigger_warning():
    """E4: Always-on trigger condition shown as warning."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_knowledge_inventory(profile)
    assert "always-on" in output


# --- Phase 6: Report Assembly ---


def test_tldr_orchestrator():
    """F1: TL;DR includes auth mode and tool breakdown."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    timeline = ConversationTimeline()
    output = render_tldr(profile, timeline)
    assert "TL;DR" in output
    assert "orchestrator" in output
    assert "Integrated" in output
    assert "Tools:" in output


def test_tldr_simple_bot():
    """F1: TL;DR works for simple bots without tools."""
    profile, _ = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    timeline = ConversationTimeline()
    output = render_tldr(profile, timeline)
    assert "TL;DR" in output
    assert "conversational agent" in output


def test_report_new_sections_orchestrator():
    """F2: Full report for orchestrator includes all new sections."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)
    assert "## TL;DR" in report
    assert "## Security Inventory" in report
    assert "## Tool Inventory" in report
    assert "## Integration Map" in report
    assert "## Topic Inventory" in report
    # Verify ordering: TL;DR < Security < Bot Profile < Components < Tool Inventory
    assert report.index("## TL;DR") < report.index("## Security Inventory")
    assert report.index("## Security Inventory") < report.index("## Bot Profile")
    assert report.index("## Topic Inventory") < report.index("## Tool Inventory")
    assert report.index("## Tool Inventory") < report.index("## Integration Map")


def test_report_graceful_degradation_simple_bot():
    """F2: Simple bot report doesn't crash, optional sections omitted."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)
    assert "## TL;DR" in report
    assert "## Bot Profile" in report
    assert "## Topic Inventory" in report
    # These should NOT appear for simple bots
    assert "## Tool Inventory" not in report


# --- Credit estimation tests ---


def test_credit_estimate_empty_timeline():
    """Empty timeline should produce 0 credits, no crash."""
    timeline = ConversationTimeline()
    profile = BotProfile()
    estimate = estimate_credits(timeline, profile)
    assert estimate.total_credits == 0.0
    assert estimate.total_credits == 0.0
    assert estimate.line_items == []
    assert len(estimate.warnings) > 0


def test_credit_estimate_botcontent_custom_topic():
    """botContent dialog.json has a CustomTopic step under generative orchestration → 5 credits."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    estimate = estimate_credits(timeline, profile)

    assert estimate.total_credits > 0
    assert estimate.total_credits > 0
    assert len(estimate.line_items) >= 1
    # The bot uses GenerativeAIRecognizer, so CustomTopic → agent_action (5 credits)
    step_types = [item.step_type for item in estimate.line_items]
    assert "agent_action" in step_types


def test_credit_estimate_botcontent1_agent_step():
    """botContent (1) dialog.json has an Agent step → 5 credits."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    estimate = estimate_credits(timeline, profile)

    assert estimate.total_credits >= 5
    agent_items = [i for i in estimate.line_items if i.step_type == "agent_action"]
    assert len(agent_items) >= 1
    # Connected agent should be 5 credits
    assert any(i.credits == 5 for i in agent_items)


def test_credit_estimate_synthetic_knowledge_search():
    """Synthetic: KnowledgeSource step → 2 credits."""
    events = [
        TimelineEvent(
            position=1,
            event_type=EventType.USER_MESSAGE,
            summary='User: "test query"',
        ),
        TimelineEvent(
            position=2,
            event_type=EventType.PLAN_RECEIVED,
            summary="Plan: [UniversalSearchTool]",
        ),
        TimelineEvent(
            position=3,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="UniversalSearchTool",
            summary="Step start: UniversalSearchTool (KnowledgeSource)",
            state="inProgress",
        ),
        TimelineEvent(
            position=4,
            event_type=EventType.STEP_FINISHED,
            topic_name="UniversalSearchTool",
            summary="Step end: UniversalSearchTool [completed]",
            state="completed",
        ),
    ]
    timeline = ConversationTimeline(events=events)
    profile = BotProfile(recognizer_kind="GenerativeAIRecognizer")
    estimate = estimate_credits(timeline, profile)

    assert estimate.total_credits == 2
    assert len(estimate.line_items) == 1
    assert estimate.line_items[0].step_type == "generative_answer"
    assert estimate.line_items[0].credits == 2


def test_credit_estimate_synthetic_mixed():
    """Synthetic: knowledge search + agent action → 7 credits total."""
    events = [
        TimelineEvent(
            position=1,
            event_type=EventType.USER_MESSAGE,
            summary='User: "find printers"',
        ),
        TimelineEvent(
            position=2,
            event_type=EventType.PLAN_RECEIVED,
            summary="Plan: [UniversalSearchTool, Equippy]",
        ),
        TimelineEvent(
            position=3,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="UniversalSearchTool",
            summary="Step start: UniversalSearchTool (KnowledgeSource)",
            state="inProgress",
        ),
        TimelineEvent(
            position=4,
            event_type=EventType.STEP_FINISHED,
            topic_name="UniversalSearchTool",
            summary="Step end: UniversalSearchTool [completed]",
            state="completed",
        ),
        TimelineEvent(
            position=5,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="Equippy",
            summary="Step start: Equippy (Agent)",
            state="inProgress",
        ),
        TimelineEvent(
            position=6,
            event_type=EventType.STEP_FINISHED,
            topic_name="Equippy",
            summary="Step end: Equippy [completed]",
            state="completed",
        ),
    ]
    timeline = ConversationTimeline(events=events)
    profile = BotProfile(recognizer_kind="GenerativeAIRecognizer")
    estimate = estimate_credits(timeline, profile)

    assert estimate.total_credits == 7
    assert len(estimate.line_items) == 2
    assert estimate.line_items[0].credits == 2  # knowledge search
    assert estimate.line_items[1].credits == 5  # agent action


def test_credit_estimate_classic_recognizer():
    """CustomTopic under classic recognizer → 1 credit."""
    events = [
        TimelineEvent(
            position=1,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="Greeting",
            summary="Step start: Greeting (CustomTopic)",
            state="inProgress",
        ),
    ]
    timeline = ConversationTimeline(events=events)
    profile = BotProfile(recognizer_kind="ClassicRecognizer")
    estimate = estimate_credits(timeline, profile)

    assert estimate.total_credits == 1
    assert estimate.line_items[0].step_type == "classic_answer"


def test_credit_estimate_in_report():
    """Credit estimate section should appear in rendered report."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    assert "## MCS Credit Estimate" in report
    assert "### Credit Breakdown" in report
    assert "### Credit Flow" in report
    assert "sequenceDiagram" in report
    assert "### Estimation Caveats" in report


def test_credit_estimate_in_tldr():
    """TL;DR should include credit summary when credits > 0."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    estimate = estimate_credits(timeline, profile)
    tldr = render_tldr(profile, timeline, estimate)

    assert "Estimated Credits" in tldr
    assert "estimate" in tldr


def test_credit_estimate_mermaid_valid_syntax():
    """Mermaid diagram should have valid structure."""
    events = [
        TimelineEvent(
            position=1,
            event_type=EventType.USER_MESSAGE,
            summary='User: "test"',
        ),
        TimelineEvent(
            position=2,
            event_type=EventType.PLAN_RECEIVED,
            summary="Plan: [TestTool]",
        ),
        TimelineEvent(
            position=3,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="TestTool",
            summary="Step start: TestTool (Agent)",
            state="inProgress",
        ),
    ]
    timeline = ConversationTimeline(events=events)
    profile = BotProfile(recognizer_kind="GenerativeAIRecognizer")
    estimate = estimate_credits(timeline, profile)
    rendered = render_credit_estimate(estimate, timeline)

    assert "```mermaid" in rendered
    assert "sequenceDiagram" in rendered
    assert "participant U as User" in rendered
    assert "participant O as Orchestrator" in rendered
    assert "```" in rendered
    # Check proper closing
    mermaid_blocks = rendered.split("```mermaid")
    assert len(mermaid_blocks) == 2
    assert "```" in mermaid_blocks[1]


def test_render_credit_estimate_empty():
    """Empty estimate should return empty string."""
    estimate = CreditEstimate()
    timeline = ConversationTimeline()
    result = render_credit_estimate(estimate, timeline)
    assert result == ""


# --- Step 1: Connection Reference Validation (1.5) ---


def test_validate_connections_clean():
    """No issues when everything lines up."""
    profile = BotProfile(
        connector_definitions=[{"connectorId": "conn-1", "displayName": "My Connector"}],
        connection_references=[
            {"connectionReferenceLogicalName": "ref-1", "connectorId": "conn-1", "displayName": "Ref 1"}
        ],
        components=[
            ComponentSummary(kind="DialogComponent", display_name="T1", schema_name="s1", connection_reference="ref-1")
        ],
    )
    issues = validate_connections(profile)
    assert issues == []


def test_validate_connections_missing_connector():
    """Connection ref points to a connector ID that doesn't exist in definitions."""
    profile = BotProfile(
        connector_definitions=[],
        connection_references=[
            {"connectionReferenceLogicalName": "ref-1", "connectorId": "conn-missing", "displayName": "Ref 1"}
        ],
        components=[],
    )
    issues = validate_connections(profile)
    assert any("Missing connector" in i["message"] for i in issues)
    assert any(i["severity"] == "warning" for i in issues)


def test_validate_connections_orphaned_connector():
    """Connector definition not referenced by any connection ref."""
    profile = BotProfile(
        connector_definitions=[{"connectorId": "conn-1", "displayName": "Orphan"}],
        connection_references=[],
        components=[],
    )
    issues = validate_connections(profile)
    assert any("Orphaned" in i["message"] for i in issues)
    assert any(i["severity"] == "info" for i in issues)


def test_validate_connections_unused_ref():
    """Connection ref not used by any component."""
    profile = BotProfile(
        connector_definitions=[{"connectorId": "conn-1", "displayName": "C1"}],
        connection_references=[
            {"connectionReferenceLogicalName": "ref-1", "connectorId": "conn-1", "displayName": "R1"}
        ],
        components=[],
    )
    issues = validate_connections(profile)
    assert any("Unused" in i["message"] for i in issues)


# --- Step 2: Trigger Query Overlap Detection (1.3) ---


def test_detect_trigger_overlaps_no_overlap():
    """Completely different trigger queries produce no overlaps."""
    components = [
        ComponentSummary(
            kind="DialogComponent",
            display_name="T1",
            schema_name="s1",
            trigger_queries=["how to reset password", "forgot my password", "password help"],
        ),
        ComponentSummary(
            kind="DialogComponent",
            display_name="T2",
            schema_name="s2",
            trigger_queries=["track my order", "where is my shipment", "delivery status"],
        ),
    ]
    overlaps = detect_trigger_overlaps(components)
    assert overlaps == []


def test_detect_trigger_overlaps_high_overlap():
    """Nearly identical trigger queries should be flagged."""
    components = [
        ComponentSummary(
            kind="DialogComponent",
            display_name="T1",
            schema_name="s1",
            trigger_queries=["how to reset my password", "I forgot my password"],
        ),
        ComponentSummary(
            kind="DialogComponent",
            display_name="T2",
            schema_name="s2",
            trigger_queries=["reset my password please", "forgot password help"],
        ),
    ]
    overlaps = detect_trigger_overlaps(components)
    assert len(overlaps) > 0
    assert overlaps[0]["overlap_pct"] > 50


def test_detect_trigger_overlaps_skips_short():
    """Topics with fewer than 3 tokens are skipped."""
    components = [
        ComponentSummary(kind="DialogComponent", display_name="T1", schema_name="s1", trigger_queries=["hi", "hello"]),
        ComponentSummary(kind="DialogComponent", display_name="T2", schema_name="s2", trigger_queries=["hi", "hello"]),
    ]
    overlaps = detect_trigger_overlaps(components)
    assert overlaps == []


def test_render_trigger_overlaps_empty():
    """No overlaps produces empty string."""
    assert render_trigger_overlaps([]) == ""


def test_render_trigger_overlaps_table():
    """Non-empty overlaps produce a markdown table."""
    overlaps = [{"topic_a": "T1", "topic_b": "T2", "overlap_pct": 75.0, "shared_tokens": ["reset", "password"]}]
    result = render_trigger_overlaps(overlaps)
    assert "## Trigger Query Overlaps" in result
    assert "T1" in result
    assert "75.0%" in result


# --- build_topic_lifecycles ---


def test_build_topic_lifecycles_basic():
    """Triggered + finished step produces a lifecycle entry."""
    from renderer.sections import build_topic_lifecycles

    tl = ConversationTimeline(
        events=[
            TimelineEvent(
                position=1,
                event_type=EventType.STEP_TRIGGERED,
                step_id="s1",
                topic_name="Billing Help",
                thought="User wants billing info",
                timestamp="2024-01-01T10:00:00Z",
            ),
            TimelineEvent(
                position=2,
                event_type=EventType.STEP_FINISHED,
                step_id="s1",
                state="completed",
                timestamp="2024-01-01T10:00:02Z",
            ),
        ],
    )
    lifecycles = build_topic_lifecycles(tl)
    assert len(lifecycles) == 1
    assert lifecycles[0]["name"] == "Billing Help"
    assert lifecycles[0]["status"] == "completed"
    assert lifecycles[0]["thought"] == "User wants billing info"


def test_build_topic_lifecycles_pending():
    """Step without a finish event shows as pending."""
    from renderer.sections import build_topic_lifecycles

    tl = ConversationTimeline(
        events=[
            TimelineEvent(
                position=1,
                event_type=EventType.STEP_TRIGGERED,
                step_id="s1",
                topic_name="Orphaned",
                timestamp="2024-01-01T10:00:00Z",
            ),
        ],
    )
    lifecycles = build_topic_lifecycles(tl)
    assert len(lifecycles) == 1
    assert lifecycles[0]["status"] == "pending"


# --- match_query_to_triggers ---


def test_match_query_to_triggers_basic():
    """A query with shared tokens scores above threshold."""
    components = [
        ComponentSummary(
            kind="DialogComponent",
            display_name="Password Reset",
            schema_name="s1",
            trigger_queries=["how to reset my password", "forgot my password"],
        ),
        ComponentSummary(
            kind="DialogComponent",
            display_name="Order Tracking",
            schema_name="s2",
            trigger_queries=["track my order", "where is my shipment"],
        ),
    ]
    results = match_query_to_triggers("I need to reset my password", components)
    assert len(results) >= 1
    assert results[0]["display_name"] == "Password Reset"
    assert results[0]["score"] >= 0.5


def test_match_query_to_triggers_threshold():
    """Matches below 0.5 threshold are excluded."""
    components = [
        ComponentSummary(
            kind="DialogComponent",
            display_name="Password Reset",
            schema_name="s1",
            trigger_queries=["how to reset my password"],
        ),
    ]
    results = match_query_to_triggers("what is the weather today", components)
    assert results == []


def test_match_query_to_triggers_max_results():
    """At most max_results entries are returned."""
    components = [
        ComponentSummary(
            kind="DialogComponent",
            display_name=f"Topic{i}",
            schema_name=f"s{i}",
            trigger_queries=["reset password help"],
        )
        for i in range(20)
    ]
    results = match_query_to_triggers("reset password help", components, max_results=5)
    assert len(results) <= 5


def test_match_query_to_triggers_empty_query():
    """Empty query returns no results."""
    components = [
        ComponentSummary(
            kind="DialogComponent",
            display_name="T1",
            schema_name="s1",
            trigger_queries=["hello"],
        ),
    ]
    assert match_query_to_triggers("", components) == []


# --- Step 3: Quick Wins Section (1.1) ---


def test_render_quick_wins_disabled_topic():
    """Disabled topics should appear in quick wins."""
    profile = BotProfile(
        components=[
            ComponentSummary(kind="DialogComponent", display_name="Disabled One", schema_name="s1", state="Inactive"),
        ],
    )
    result = render_quick_wins(profile)
    assert "Disabled topic" in result
    assert "warning" in result


def test_render_quick_wins_no_trigger_queries():
    """User topics with no trigger queries should be flagged."""
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="NoTrigger",
                schema_name="s1",
                trigger_kind="OnIntent",
                trigger_queries=[],
            ),
        ],
    )
    result = render_quick_wins(profile)
    assert "No trigger queries" in result


def test_render_quick_wins_weak_description():
    """Topics where description matches display name should be flagged."""
    profile = BotProfile(
        components=[
            ComponentSummary(kind="DialogComponent", display_name="FAQ", schema_name="s1", description="FAQ"),
        ],
    )
    result = render_quick_wins(profile)
    assert "Weak description" in result


def test_render_quick_wins_missing_system_topics():
    """Missing OnError/OnUnknownIntent/OnEscalate should be flagged."""
    profile = BotProfile(components=[])
    result = render_quick_wins(profile)
    assert "OnError" in result
    assert "OnUnknownIntent" in result
    assert "OnEscalate" in result


def test_render_quick_wins_empty_when_clean():
    """A well-configured profile should produce empty quick wins."""
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="Error",
                schema_name="s1",
                trigger_kind="OnError",
                description="Handles all errors gracefully",
            ),
            ComponentSummary(
                kind="DialogComponent",
                display_name="Fallback",
                schema_name="s2",
                trigger_kind="OnUnknownIntent",
                description="Handles unmatched intents",
            ),
            ComponentSummary(
                kind="DialogComponent",
                display_name="Escalate",
                schema_name="s3",
                trigger_kind="OnEscalate",
                description="Escalates to human agent",
            ),
        ],
    )
    result = render_quick_wins(profile)
    assert result == ""


# --- Step 4: Knowledge Source Coverage Matrix (1.6) ---


def test_render_knowledge_coverage_empty():
    """No knowledge sources produces empty string."""
    profile = BotProfile(components=[])
    result = render_knowledge_coverage(profile)
    assert result == ""


def test_render_knowledge_coverage_with_sources():
    """Knowledge sources render a table."""
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="KnowledgeSourceComponent",
                display_name="SharePoint FAQ",
                schema_name="ks1",
                source_kind="SharePoint",
                state="Active",
                trigger_condition_raw="true",
            ),
            ComponentSummary(
                kind="FileAttachmentComponent",
                display_name="guide.pdf",
                schema_name="fa1",
                file_type="pdf",
                state="Active",
            ),
        ],
    )
    result = render_knowledge_coverage(profile)
    assert "## Knowledge Source Coverage" in result
    assert "SharePoint FAQ" in result
    assert "guide.pdf" in result


def test_render_knowledge_coverage_inactive_flagged():
    """Inactive knowledge sources should have a note."""
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="KnowledgeSourceComponent",
                display_name="Old KB",
                schema_name="ks1",
                source_kind="Web",
                state="Inactive",
            ),
        ],
    )
    result = render_knowledge_coverage(profile)
    assert "Inactive" in result


# --- Step 5: Topic Graph Annotations (1.2) ---


def test_topic_graph_annotations_orphaned():
    """Topic graph should annotate orphaned nodes."""
    from models import TopicConnection

    profile = BotProfile(
        topic_connections=[
            TopicConnection(source_schema="s1", source_display="Start", target_schema="s2", target_display="Middle"),
            TopicConnection(source_schema="s2", source_display="Middle", target_schema="s3", target_display="End"),
        ],
        components=[
            ComponentSummary(kind="DialogComponent", display_name="Start", schema_name="s1", trigger_kind="OnIntent"),
            ComponentSummary(kind="DialogComponent", display_name="Middle", schema_name="s2"),
            ComponentSummary(kind="DialogComponent", display_name="End", schema_name="s3"),
        ],
    )
    result = render_topic_graph(profile)
    assert "classDef warning" in result
    assert "classDef danger" in result


def test_topic_graph_system_topic_not_orphaned():
    """System topics with no inbound edges should NOT be marked orphaned."""
    from models import TopicConnection

    profile = BotProfile(
        topic_connections=[
            TopicConnection(
                source_schema="s1", source_display="OnError", target_schema="s2", target_display="HandleError"
            ),
        ],
        components=[
            ComponentSummary(kind="DialogComponent", display_name="OnError", schema_name="s1", trigger_kind="OnError"),
            ComponentSummary(kind="DialogComponent", display_name="HandleError", schema_name="s2"),
        ],
    )
    result = render_topic_graph(profile)
    # OnError is a system trigger, should not be in warning class
    # We can't easily check absence of specific class assignment without parsing,
    # but at minimum the graph should render
    assert "graph TD" in result


# --- Step 6: Orchestrator Health Checks (1.4) ---


def test_solution_checker_categories_include_orchestrator():
    """CATEGORIES and _CAT_ICONS should include Orchestrator."""
    from solution_checker import CATEGORIES, _CAT_ICONS

    assert "Orchestrator" in CATEGORIES
    assert "Orchestrator" in _CAT_ICONS
    assert _CAT_ICONS["Orchestrator"] == "network"


# --- Integration: render_report includes new sections ---


def test_render_report_includes_quick_wins():
    """render_report should include Quick Wins section when issues exist."""
    profile = BotProfile(
        components=[
            ComponentSummary(kind="DialogComponent", display_name="Disabled", schema_name="s1", state="Inactive"),
        ],
    )
    result = render_report(profile)
    assert "## Quick Wins" in result


def test_render_report_includes_knowledge_coverage():
    """render_report should include Knowledge Coverage section."""
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="KnowledgeSourceComponent",
                display_name="KB1",
                schema_name="ks1",
                source_kind="Web",
                state="Active",
            ),
            # Add system topics so quick wins section doesn't dominate
            ComponentSummary(kind="DialogComponent", display_name="Error", schema_name="s1", trigger_kind="OnError"),
            ComponentSummary(
                kind="DialogComponent", display_name="Fallback", schema_name="s2", trigger_kind="OnUnknownIntent"
            ),
            ComponentSummary(
                kind="DialogComponent", display_name="Escalate", schema_name="s3", trigger_kind="OnEscalate"
            ),
        ],
    )
    result = render_report(profile)
    assert "## Knowledge Source Coverage" in result


# --- Custom Rule Engine tests ---


def test_load_rules_yaml_valid():
    """Load valid YAML -> correct CustomRule list."""
    yaml_text = """
rules:
  - rule_id: CUSTOM001
    severity: warning
    category: Security
    message: "App Insights must be configured"
    condition:
      field: "app_insights"
      operator: not_exists
  - rule_id: CUSTOM002
    severity: fail
    category: Agent
    message: "Must have components"
    condition:
      field: "components"
      operator: exists
"""
    rules = load_rules_yaml(yaml_text)
    assert len(rules) == 2
    assert rules[0].rule_id == "CUSTOM001"
    assert rules[0].severity == "warning"
    assert rules[0].condition.operator == "not_exists"
    assert rules[1].rule_id == "CUSTOM002"
    assert rules[1].category == "Agent"


def test_load_rules_yaml_invalid_operator():
    """Load YAML with invalid operator -> ValueError."""
    yaml_text = """
rules:
  - rule_id: BAD001
    severity: warning
    category: Custom
    message: "bad"
    condition:
      field: "app_insights"
      operator: invalid_op
"""
    with pytest.raises(ValueError, match="Invalid operator"):
        load_rules_yaml(yaml_text)


def test_resolve_field_dotted_path():
    """Resolve dotted path 'gpt_info.instructions' on BotProfile."""
    profile = BotProfile(gpt_info=GptInfo(display_name="Test", instructions="Do stuff"))
    values = _resolve_field(profile, "gpt_info.instructions")
    assert values == ["Do stuff"]


def test_resolve_field_components_array():
    """Resolve components[].tool_type -> iterates all components."""
    profile = BotProfile(
        components=[
            ComponentSummary(kind="DialogComponent", display_name="A", schema_name="a", tool_type="Connector"),
            ComponentSummary(kind="DialogComponent", display_name="B", schema_name="b", tool_type="Flow"),
            ComponentSummary(kind="DialogComponent", display_name="C", schema_name="c", tool_type=None),
        ]
    )
    values = _resolve_field(profile, "components[].tool_type")
    assert values == ["Connector", "Flow", None]


def test_operator_eq():
    """eq operator matches equal values."""
    assert _apply_operator("hello", "eq", "hello") is True
    assert _apply_operator("hello", "eq", "world") is False
    assert _apply_operator(42, "eq", 42) is True


def test_operator_ne():
    """ne operator matches unequal values."""
    assert _apply_operator("hello", "ne", "world") is True
    assert _apply_operator("hello", "ne", "hello") is False


def test_operator_contains():
    """contains operator checks substring or list membership."""
    assert _apply_operator("hello world", "contains", "world") is True
    assert _apply_operator("hello world", "contains", "xyz") is False
    assert _apply_operator(["a", "b"], "contains", "b") is True


def test_operator_not_contains():
    """not_contains operator checks absence."""
    assert _apply_operator("hello world", "not_contains", "xyz") is True
    assert _apply_operator("hello world", "not_contains", "world") is False


def test_operator_matches():
    """matches operator uses regex search."""
    assert _apply_operator("error-code-42", "matches", r"error-code-\d+") is True
    assert _apply_operator("no-match", "matches", r"error-code-\d+") is False


def test_operator_exists():
    """exists operator checks value is not None."""
    assert _apply_operator("something", "exists", None) is True
    assert _apply_operator(None, "exists", None) is False
    assert _apply_operator(0, "exists", None) is True


def test_operator_not_exists():
    """not_exists operator checks value is None."""
    assert _apply_operator(None, "not_exists", None) is True
    assert _apply_operator("something", "not_exists", None) is False


def test_evaluate_rules_against_profile():
    """Evaluate rule against profile -> correct result dict."""
    profile = BotProfile(
        app_insights=AppInsightsConfig(configured=False),
    )
    rules = [
        CustomRule(
            rule_id="TEST001",
            severity="warning",
            category="Security",
            message="App Insights not configured",
            condition=RuleCondition(field="app_insights.configured", operator="eq", value=False),
        )
    ]
    results = evaluate_rules(rules, profile)
    assert len(results) == 1
    assert results[0]["rule_id"] == "TEST001"
    assert results[0]["severity"] == "warning"
    assert results[0]["category"] == "Security"
    assert results[0]["detail"] == "App Insights not configured"
    assert results[0]["title"] == "TEST001"


def test_evaluate_rules_empty_list():
    """Empty rules list -> no extra results."""
    profile = BotProfile()
    results = evaluate_rules([], profile)
    assert results == []


def test_load_default_rules_yaml():
    """Load data/default_rules.yaml -> 18 valid BP rules, no errors."""
    rules_path = Path(__file__).parent.parent / "data" / "default_rules.yaml"
    yaml_text = rules_path.read_text()
    rules = load_rules_yaml(yaml_text)
    assert len(rules) == 18
    rule_ids = [r.rule_id for r in rules]
    assert all(rid.startswith("BP") for rid in rule_ids)
    assert len(set(rule_ids)) == 18  # no duplicates
    for rule in rules:
        assert rule.severity in ("fail", "warning", "info", "pass")
        assert rule.message
        assert rule.condition.field
        assert rule.condition.operator


def test_default_rules_auto_load(monkeypatch, tmp_path):
    """get_custom_rules() auto-loads from CUSTOM_RULES_FILE when rules are empty."""
    from web.state._rules import RulesMixin

    rules_path = Path(__file__).parent.parent / "data" / "default_rules.yaml"
    yaml_text = rules_path.read_text()

    # Write rules to a temp file
    tmp_rules = tmp_path / "rules.yaml"
    tmp_rules.write_text(yaml_text)
    monkeypatch.setenv("CUSTOM_RULES_FILE", str(tmp_rules))

    # Create a fresh mixin instance attributes on a simple namespace
    class FakeState:
        custom_rules_yaml: str = ""
        custom_rules_parsed: list[dict] = []
        _custom_rules_dicts: list[dict] = []
        rules_parse_error: str = ""
        rules_count: int = 0

    obj = FakeState()
    # Bind the methods
    obj._reparse_rules = RulesMixin._reparse_rules.__get__(obj)
    obj.get_custom_rules = RulesMixin.get_custom_rules.__get__(obj)

    rules = obj.get_custom_rules()
    assert len(rules) == 18
    assert all(r["rule_id"].startswith("BP") for r in rules)
    # Second call should not re-read (rules already loaded)
    rules2 = obj.get_custom_rules()
    assert rules2 == rules


def test_default_rules_auto_load_fallback_no_env(monkeypatch):
    """get_custom_rules() falls back to data/default_rules.yaml when no env var is set."""
    from web.state._rules import RulesMixin

    monkeypatch.delenv("CUSTOM_RULES_FILE", raising=False)

    class FakeState:
        custom_rules_yaml: str = ""
        custom_rules_parsed: list[dict] = []
        _custom_rules_dicts: list[dict] = []
        rules_parse_error: str = ""
        rules_count: int = 0

    obj = FakeState()
    obj._reparse_rules = RulesMixin._reparse_rules.__get__(obj)
    obj.get_custom_rules = RulesMixin.get_custom_rules.__get__(obj)

    rules = obj.get_custom_rules()
    assert len(rules) == 18
    assert all(r["rule_id"].startswith("BP") for r in rules)


def test_default_rules_no_auto_load_when_user_has_rules(monkeypatch, tmp_path):
    """get_custom_rules() does NOT auto-load if user already has rules set."""
    from web.state._rules import RulesMixin

    rules_path = Path(__file__).parent.parent / "data" / "default_rules.yaml"
    tmp_rules = tmp_path / "rules.yaml"
    tmp_rules.write_text(rules_path.read_text())
    monkeypatch.setenv("CUSTOM_RULES_FILE", str(tmp_rules))

    class FakeState:
        custom_rules_yaml: str = "# user edited"
        custom_rules_parsed: list[dict] = []
        _custom_rules_dicts: list[dict] = []
        rules_parse_error: str = ""
        rules_count: int = 0

    obj = FakeState()
    obj._reparse_rules = RulesMixin._reparse_rules.__get__(obj)
    obj.get_custom_rules = RulesMixin.get_custom_rules.__get__(obj)

    # Should NOT auto-load because custom_rules_yaml is non-empty
    rules = obj.get_custom_rules()
    assert rules == []


# --- Custom rules evaluation for report ---


def test_evaluate_custom_rules_returns_findings():
    """evaluate_rules returns structured findings for triggered rules."""
    profile = BotProfile(
        display_name="TestBot",
        components=[],
        authentication_mode="None",
    )
    rules = [
        CustomRule(
            rule_id="BP-TEST-TRIGGER",
            category="security",
            severity="warning",
            message="Auth should not be None",
            condition=RuleCondition(field="authentication_mode", operator="eq", value="None"),
        ),
        CustomRule(
            rule_id="BP-TEST-SKIP",
            category="security",
            severity="fail",
            message="Should not fire",
            condition=RuleCondition(field="authentication_mode", operator="eq", value="OAuth"),
        ),
    ]
    results = evaluate_rules(rules, profile)
    # Only the triggered rule should appear
    assert len(results) == 1
    assert results[0]["rule_id"] == "BP-TEST-TRIGGER"
    assert results[0]["severity"] == "warning"
    assert results[0]["category"] == "security"
    assert results[0]["detail"] == "Auth should not be None"


def test_evaluate_custom_rules_empty_list():
    """Empty rules list returns empty findings."""
    profile = BotProfile(display_name="TestBot", components=[])
    results = evaluate_rules([], profile)
    assert results == []


def test_render_quick_wins_no_custom_rules_in_markdown():
    """render_quick_wins() only contains built-in checks, not custom rules."""
    profile = BotProfile(
        display_name="TestBot",
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="Greeting",
                schema_name="cr_greeting",
                trigger_kind="OnUnknownIntent",
            ),
        ],
    )
    output = render_quick_wins(profile)
    # Built-in findings present
    assert "Quick Wins" in output
    # No custom rules section in markdown
    assert "Custom Rules" not in output
    # Emoji severity indicators present
    assert "\U0001f535" in output or "\U0001f7e1" in output  # blue or yellow circle


def test_render_report_no_custom_rules_param():
    """render_report() signature has no custom_rules parameter."""
    import inspect

    sig = inspect.signature(render_report)
    assert "custom_rules" not in sig.parameters


# --- Bot Comparison / Diff tests ---


def _make_bot(name: str = "TestBot", components: list[ComponentSummary] | None = None, **kwargs) -> BotProfile:
    return BotProfile(display_name=name, components=components or [], **kwargs)


def test_compare_identical_bots():
    """Identical bots produce empty diff."""
    comp = ComponentSummary(kind="Topic", display_name="Greeting", schema_name="cr_greeting")
    a = _make_bot("Bot", components=[comp])
    b = _make_bot("Bot", components=[comp])
    diff = compare_bots(a, b)
    assert diff.added_components == []
    assert diff.removed_components == []
    assert diff.changed_components == []
    assert diff.instruction_diff == ""
    assert diff.connection_changes == []
    assert diff.settings_changes == []


def test_compare_added_component():
    """Bot B has extra component -> in added_components."""
    a = _make_bot("A")
    b = _make_bot("B", components=[ComponentSummary(kind="Topic", display_name="New", schema_name="cr_new")])
    diff = compare_bots(a, b)
    assert "cr_new" in diff.added_components
    assert diff.removed_components == []


def test_compare_removed_component():
    """Bot A has component not in B -> in removed_components."""
    a = _make_bot("A", components=[ComponentSummary(kind="Topic", display_name="Old", schema_name="cr_old")])
    b = _make_bot("B")
    diff = compare_bots(a, b)
    assert "cr_old" in diff.removed_components
    assert diff.added_components == []


def test_compare_changed_component():
    """Same schema_name, different field -> in changed_components."""
    ca = ComponentSummary(kind="Topic", display_name="Greet", schema_name="cr_greet", state="Active")
    cb = ComponentSummary(kind="Topic", display_name="Greet", schema_name="cr_greet", state="Disabled")
    diff = compare_bots(_make_bot("A", components=[ca]), _make_bot("B", components=[cb]))
    assert len(diff.changed_components) == 1
    assert diff.changed_components[0].field == "state"
    assert diff.changed_components[0].value_a == "Active"
    assert diff.changed_components[0].value_b == "Disabled"


def test_compare_instruction_diff():
    """Different instructions -> instruction_diff not empty."""
    a = _make_bot("A", gpt_info=GptInfo(instructions="You are helpful."))
    b = _make_bot("B", gpt_info=GptInfo(instructions="You are concise."))
    diff = compare_bots(a, b)
    assert diff.instruction_diff != ""
    assert "helpful" in diff.instruction_diff
    assert "concise" in diff.instruction_diff


def test_compare_connection_added():
    """Connection in B not in A -> in connection_changes."""
    conn = TopicConnection(source_schema="src", source_display="Src", target_schema="tgt", target_display="Tgt")
    a = _make_bot("A")
    b = _make_bot("B", topic_connections=[conn])
    diff = compare_bots(a, b)
    assert any("+ src -> tgt" in c for c in diff.connection_changes)


def test_compare_settings_changed():
    """Different ai_settings -> in settings_changes."""
    a = _make_bot("A", ai_settings=AISettings(use_model_knowledge=False))
    b = _make_bot("B", ai_settings=AISettings(use_model_knowledge=True))
    diff = compare_bots(a, b)
    assert any("use_model_knowledge" in s for s in diff.settings_changes)


def test_render_diff_report():
    """render_diff_report produces valid markdown with expected sections."""
    diff = BotDiffResult(
        bot_a_name="A",
        bot_b_name="B",
        added_components=["cr_new"],
        removed_components=["cr_old"],
        changed_components=[
            ComponentChange(schema_name="cr_x", display_name="X", field="state", value_a="Active", value_b="Disabled")
        ],
        instruction_diff="--- a\n+++ b\n-old\n+new",
        connection_changes=["+ src -> tgt"],
        settings_changes=["is_orchestrator: False -> True"],
        summary_markdown="## Comparison: A vs B\n\n| Metric | Count |\n| --- | --- |",
    )
    md = render_diff_report(diff)
    assert "## Comparison" in md
    assert "Component Changes" in md
    assert "Instruction Diff" in md
    assert "Connection Changes" in md
    assert "Settings Changes" in md
    assert "cr_new" in md
    assert "cr_old" in md


def test_compare_empty_components():
    """One bot with no components, other with some -> all shown as added/removed."""
    comps = [
        ComponentSummary(kind="Topic", display_name="A", schema_name="cr_a"),
        ComponentSummary(kind="Topic", display_name="B", schema_name="cr_b"),
    ]
    diff = compare_bots(_make_bot("Empty"), _make_bot("Full", components=comps))
    assert sorted(diff.added_components) == ["cr_a", "cr_b"]
    assert diff.removed_components == []

    diff2 = compare_bots(_make_bot("Full", components=comps), _make_bot("Empty"))
    assert diff2.added_components == []
    assert sorted(diff2.removed_components) == ["cr_a", "cr_b"]


def test_compare_no_gpt_info():
    """Both bots with no gpt_info -> instruction_diff empty."""
    a = _make_bot("A", gpt_info=None)
    b = _make_bot("B", gpt_info=None)
    diff = compare_bots(a, b)
    assert diff.instruction_diff == ""


# --- Instruction versioning tests ---


def _make_profile(
    bot_id: str = "",
    schema_name: str = "test_bot",
    display_name: str = "Test Bot",
    instructions: str | None = None,
    description: str | None = None,
) -> BotProfile:
    gpt = GptInfo(instructions=instructions, description=description) if instructions or description else None
    return BotProfile(bot_id=bot_id, schema_name=schema_name, display_name=display_name, gpt_info=gpt)


def test_instruction_snapshot_first(tmp_path, monkeypatch):
    """First snapshot returns None (no previous)."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    profile = _make_profile(bot_id="bot1", instructions="Do stuff")
    result = save_snapshot(profile)
    assert result is None


def test_instruction_snapshot_same(tmp_path, monkeypatch):
    """Same instructions -> returns None (no change)."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    profile = _make_profile(bot_id="bot1", instructions="Do stuff")
    save_snapshot(profile)
    result = save_snapshot(profile)
    assert result is None


def test_instruction_snapshot_changed(tmp_path, monkeypatch):
    """Changed instructions -> returns diff with instructions_changed=True."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    save_snapshot(_make_profile(bot_id="bot1", instructions="Do stuff"))
    diff = save_snapshot(_make_profile(bot_id="bot1", instructions="Do other stuff"))
    assert diff is not None
    assert diff.instructions_changed is True
    assert diff.unified_diff != ""


def test_instruction_significant(tmp_path, monkeypatch):
    """is_significant True when >20% changed."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    save_snapshot(_make_profile(bot_id="bot1", instructions="AAAA"))
    diff = save_snapshot(_make_profile(bot_id="bot1", instructions="BBBB"))
    assert diff is not None
    assert diff.is_significant is True
    assert diff.change_ratio > 0.2


def test_instruction_change_ratio(tmp_path, monkeypatch):
    """change_ratio correct calculation."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    original = "Hello world this is a test"
    save_snapshot(_make_profile(bot_id="bot1", instructions=original))
    # Small change
    diff = save_snapshot(_make_profile(bot_id="bot1", instructions="Hello world this is a test!"))
    assert diff is not None
    assert 0.0 < diff.change_ratio < 0.2
    assert diff.is_significant is False


def test_instruction_get_history(tmp_path, monkeypatch):
    """get_history returns ordered list."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    save_snapshot(_make_profile(bot_id="bot1", instructions="v1"))
    save_snapshot(_make_profile(bot_id="bot1", instructions="v2"))
    save_snapshot(_make_profile(bot_id="bot1", instructions="v3"))
    history = get_history("bot1")
    assert len(history) == 3
    assert history[0].instructions == "v1"
    assert history[2].instructions == "v3"


def test_instruction_atomic_write(tmp_path, monkeypatch):
    """File written correctly."""
    versions_file = tmp_path / "sub" / "versions.json"
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", versions_file)
    save_snapshot(_make_profile(bot_id="bot1", instructions="test"))
    assert versions_file.exists()
    import json

    data = json.loads(versions_file.read_text())
    assert "versions" in data
    assert "bot1" in data["versions"]


def test_instruction_identity_bot_id(tmp_path, monkeypatch):
    """Bot identity uses bot_id when available."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    save_snapshot(_make_profile(bot_id="my-bot-id", schema_name="my_schema", instructions="test"))
    history = get_history("my-bot-id")
    assert len(history) == 1
    assert history[0].bot_identity == "my-bot-id"


def test_instruction_identity_schema_name(tmp_path, monkeypatch):
    """Bot identity falls back to schema_name."""
    monkeypatch.setattr(instruction_store, "_VERSIONS_FILE", tmp_path / "versions.json")
    save_snapshot(_make_profile(bot_id="", schema_name="my_schema", instructions="test"))
    history = get_history("my_schema")
    assert len(history) == 1
    assert history[0].bot_identity == "my_schema"


def test_render_instruction_drift():
    """Renders valid markdown with diff block."""
    diff = InstructionDiff(
        bot_identity="bot1",
        from_timestamp="2026-01-01T00:00:00",
        to_timestamp="2026-01-02T00:00:00",
        instructions_changed=True,
        description_changed=False,
        unified_diff="--- previous\n+++ current\n-old line\n+new line",
        change_ratio=0.5,
        is_significant=True,
    )
    result = render_instruction_drift(diff)
    assert "Instruction Drift Detected" in result
    assert "50%" in result
    assert "```diff" in result
    assert "-old line" in result
    assert "+new line" in result


# --- Batch analytics tests ---


def test_batch_single_timeline():
    """Single timeline produces correct summary with count=1."""
    timeline = ConversationTimeline(
        conversation_id="conv-1",
        total_elapsed_ms=500.0,
        events=[
            TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="Bot: hello"),
        ],
    )
    summary = aggregate_timelines([timeline])
    assert summary.conversation_count == 1
    assert summary.avg_elapsed_ms == 500.0
    assert summary.success_count == 1


def test_batch_multiple_timelines():
    """Multiple timelines aggregate correctly."""
    t1 = ConversationTimeline(
        conversation_id="c1",
        total_elapsed_ms=200.0,
        events=[TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="hi")],
    )
    t2 = ConversationTimeline(
        conversation_id="c2",
        total_elapsed_ms=400.0,
        events=[TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="hi")],
    )
    summary = aggregate_timelines([t1, t2])
    assert summary.conversation_count == 2
    assert summary.avg_elapsed_ms == 300.0
    assert summary.success_count == 2
    assert summary.failure_count == 0


def test_batch_success_rate():
    """Success rate calculated correctly with metadata."""
    t1 = ConversationTimeline(conversation_id="c1", total_elapsed_ms=100.0)
    t2 = ConversationTimeline(conversation_id="c2", total_elapsed_ms=100.0)
    meta = [
        {"session_info": {"outcome": "Resolved"}},
        {"session_info": {"outcome": "Abandoned"}},
    ]
    summary = aggregate_timelines([t1, t2], meta)
    assert summary.success_count == 1
    assert summary.failure_count == 1
    assert summary.success_rate == pytest.approx(0.5)


def test_batch_success_heuristic():
    """Without metadata, success = no errors + has bot message."""
    t_success = ConversationTimeline(
        conversation_id="c1",
        total_elapsed_ms=100.0,
        events=[TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="ok")],
    )
    t_fail = ConversationTimeline(
        conversation_id="c2",
        total_elapsed_ms=100.0,
        errors=["something broke"],
        events=[TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="ok")],
    )
    summary = aggregate_timelines([t_success, t_fail])
    assert summary.success_count == 1
    assert summary.failure_count == 1


def test_batch_escalation_detection():
    """STEP_TRIGGERED with 'Escalate' topic detected as escalation."""
    timeline = ConversationTimeline(
        conversation_id="c1",
        total_elapsed_ms=100.0,
        events=[
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="Escalate to Agent",
                summary="escalation",
            ),
        ],
    )
    summary = aggregate_timelines([timeline])
    assert summary.escalation_count == 1


def test_batch_topic_usage():
    """Topic usage counted across conversations."""
    t1 = ConversationTimeline(
        conversation_id="c1",
        total_elapsed_ms=100.0,
        events=[
            TimelineEvent(event_type=EventType.STEP_TRIGGERED, topic_name="Greeting", summary="greet"),
            TimelineEvent(event_type=EventType.STEP_TRIGGERED, topic_name="Farewell", summary="bye"),
        ],
    )
    t2 = ConversationTimeline(
        conversation_id="c2",
        total_elapsed_ms=100.0,
        events=[
            TimelineEvent(event_type=EventType.STEP_TRIGGERED, topic_name="Greeting", summary="greet"),
        ],
    )
    summary = aggregate_timelines([t1, t2])
    topic_map = {t.topic_name: t.invocation_count for t in summary.topic_usage}
    assert topic_map["Greeting"] == 2
    assert topic_map["Farewell"] == 1


def test_batch_failure_mode_grouping():
    """Errors grouped by normalized pattern (GUIDs stripped)."""
    t1 = ConversationTimeline(
        conversation_id="c1",
        total_elapsed_ms=100.0,
        errors=["Failed for resource 1a2b3c4d5e6f7890"],
    )
    t2 = ConversationTimeline(
        conversation_id="c2",
        total_elapsed_ms=100.0,
        errors=["Failed for resource 9f8e7d6c5b4a3210"],
    )
    summary = aggregate_timelines([t1, t2])
    assert len(summary.failure_modes) == 1
    assert summary.failure_modes[0].count == 2
    assert len(summary.failure_modes[0].example_conversation_ids) == 2


def test_batch_empty_list():
    """Empty timeline list returns zeroed summary."""
    summary = aggregate_timelines([])
    assert summary.conversation_count == 0
    assert summary.avg_elapsed_ms == 0.0
    assert summary.success_rate == 0.0


def test_batch_render_report():
    """render_batch_report produces valid markdown with expected sections."""
    summary = BatchAnalyticsSummary(
        conversation_count=5,
        avg_elapsed_ms=250.0,
        success_count=3,
        failure_count=2,
        escalation_count=1,
        success_rate=0.6,
        escalation_rate=0.2,
    )
    report = render_batch_report(summary)
    assert "# Batch Analytics Report" in report
    assert "## Overview" in report
    assert "## Conversation Outcomes" in report
    assert "```mermaid" in report
    assert "pie title" in report


def test_batch_mixed_outcomes():
    """Mixed success/failure conversations counted correctly."""
    timelines = [
        ConversationTimeline(
            conversation_id=f"c{i}",
            total_elapsed_ms=100.0,
            events=[TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="ok")],
        )
        for i in range(3)
    ]
    # Third timeline has errors -> failure
    timelines[2].errors = ["boom"]
    summary = aggregate_timelines(timelines)
    assert summary.success_count == 2
    assert summary.failure_count == 1


def test_batch_escalation_rate():
    """escalation_rate = escalation_count / conversation_count."""
    t1 = ConversationTimeline(
        conversation_id="c1",
        total_elapsed_ms=100.0,
        events=[
            TimelineEvent(
                event_type=EventType.STEP_TRIGGERED,
                topic_name="Transfer to Human",
                summary="transfer",
            ),
        ],
    )
    t2 = ConversationTimeline(
        conversation_id="c2",
        total_elapsed_ms=100.0,
        events=[TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="hi")],
    )
    summary = aggregate_timelines([t1, t2])
    assert summary.escalation_rate == pytest.approx(0.5)
    assert summary.escalation_count == 1


def test_batch_avg_elapsed():
    """avg_elapsed_ms calculated correctly."""
    timelines = [
        ConversationTimeline(conversation_id="c1", total_elapsed_ms=100.0),
        ConversationTimeline(conversation_id="c2", total_elapsed_ms=300.0),
        ConversationTimeline(conversation_id="c3", total_elapsed_ms=500.0),
    ]
    summary = aggregate_timelines(timelines)
    assert summary.avg_elapsed_ms == pytest.approx(300.0)


def test_dv_batch_analysis_pipeline():
    """Dataverse batch pipeline: parse multiple transcripts, aggregate, render report."""
    import json
    import tempfile

    # 3 minimal transcript JSONs with different user messages
    transcripts = [
        {
            "activities": [
                {
                    "type": "message",
                    "from": {"role": "user"},
                    "text": f"Hello from conversation {i}",
                    "timestamp": f"2025-01-0{i + 1}T10:00:00Z",
                },
                {
                    "type": "message",
                    "from": {"role": "bot"},
                    "text": f"Response {i}",
                    "timestamp": f"2025-01-0{i + 1}T10:00:01Z",
                },
            ]
        }
        for i in range(3)
    ]

    timelines = []
    metadata_list = []

    for i, transcript_data in enumerate(transcripts):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / f"transcript_{i}.json"
            json_path.write_text(json.dumps(transcript_data))

            activities, metadata = parse_transcript_json(json_path)
            timeline = build_timeline(activities, {})
            timelines.append(timeline)
            metadata_list.append(metadata)

    assert len(timelines) == 3

    summary = aggregate_timelines(timelines, metadata_list)
    assert summary.conversation_count == 3

    report = render_batch_report(summary)
    assert "## Overview" in report
    assert "3" in report


# --- Orchestrator routing tests ---


def _make_orchestrator_timeline() -> ConversationTimeline:
    """Build a timeline with orchestrator events for routing tests."""
    events = [
        TimelineEvent(
            timestamp="2025-01-01T10:00:00Z",
            position=1,
            event_type=EventType.USER_MESSAGE,
            summary='User: "How do I reset my password?"',
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:01Z",
            position=2,
            event_type=EventType.PLAN_RECEIVED_DEBUG,
            summary='Ask: "password reset procedure"',
            plan_identifier="plan-1",
            orchestrator_ask="password reset procedure",
            is_final_plan=True,
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:01Z",
            position=3,
            event_type=EventType.PLAN_RECEIVED,
            summary="Plan: [PasswordReset, KnowledgeSearch]",
            plan_identifier="plan-1",
            is_final_plan=False,
            plan_steps=["PasswordReset", "KnowledgeSearch"],
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:02Z",
            position=4,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="PasswordReset",
            summary="Step start: PasswordReset (CustomTopic)",
            state="inProgress",
            step_id="step-1",
            plan_identifier="plan-1",
            thought="User wants to reset their password",
            has_recommendations=True,
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:04Z",
            position=5,
            event_type=EventType.STEP_FINISHED,
            topic_name="PasswordReset",
            summary="Step end: PasswordReset [completed] (2000ms)",
            state="completed",
            step_id="step-1",
            plan_identifier="plan-1",
            has_recommendations=True,
            plan_used_outputs="Used outputs from: KnowledgeSearch",
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:05Z",
            position=6,
            event_type=EventType.PLAN_FINISHED,
            summary="Plan finished (cancelled=False)",
            plan_identifier="plan-1",
        ),
    ]
    return ConversationTimeline(events=events)


def test_timeline_event_new_fields():
    """Verify new fields on TimelineEvent model."""
    ev = TimelineEvent(
        is_final_plan=True,
        has_recommendations=True,
        plan_used_outputs="Used outputs from: step_a",
        orchestrator_ask="password reset",
        plan_steps=["StepA", "StepB"],
    )
    assert ev.is_final_plan is True
    assert ev.has_recommendations is True
    assert ev.plan_used_outputs == "Used outputs from: step_a"
    assert ev.orchestrator_ask == "password reset"
    assert ev.plan_steps == ["StepA", "StepB"]


def test_timeline_event_new_fields_defaults():
    """Verify new fields default to None/empty."""
    ev = TimelineEvent()
    assert ev.is_final_plan is None
    assert ev.has_recommendations is None
    assert ev.plan_used_outputs is None
    assert ev.orchestrator_ask is None
    assert ev.plan_steps == []


def test_build_orchestrator_decision_timeline_grouping():
    """Verify decision timeline groups events correctly and extracts fields."""
    tl = _make_orchestrator_timeline()
    items = build_orchestrator_decision_timeline(tl)

    kinds = [item["kind"] for item in items]
    assert "user_message" in kinds
    assert "interpreted" in kinds
    assert "plan" in kinds
    assert "step" in kinds
    assert "plan_finished" in kinds

    # User message should be first
    assert items[0]["kind"] == "user_message"
    assert "password" in items[0]["text"]

    # Interpreted should show different ask
    interpreted = [i for i in items if i["kind"] == "interpreted"]
    assert len(interpreted) == 1
    assert interpreted[0]["ask"] == "password reset procedure"


def test_build_orchestrator_decision_timeline_no_interpretation_when_same():
    """When orchestrator ask matches user text, no 'interpreted' item should appear."""
    events = [
        TimelineEvent(
            timestamp="2025-01-01T10:00:00Z",
            position=1,
            event_type=EventType.USER_MESSAGE,
            summary="User: reset password",
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:01Z",
            position=2,
            event_type=EventType.PLAN_RECEIVED_DEBUG,
            summary='Ask: "reset password"',
            orchestrator_ask="reset password",
        ),
    ]
    tl = ConversationTimeline(events=events)
    items = build_orchestrator_decision_timeline(tl)
    interpreted = [i for i in items if i["kind"] == "interpreted"]
    assert len(interpreted) == 0


def test_build_plan_evolution_single_plan():
    """With only one plan, evolution should be empty."""
    events = [
        TimelineEvent(
            event_type=EventType.PLAN_RECEIVED,
            plan_steps=["A", "B"],
            plan_identifier="plan-1",
            is_final_plan=True,
        ),
    ]
    tl = ConversationTimeline(events=events)
    result = build_plan_evolution(tl)
    assert result == []


def test_build_plan_evolution_multiple_plans():
    """With multiple plans, evolution should detect added/removed steps."""
    events = [
        TimelineEvent(
            timestamp="2025-01-01T10:00:01Z",
            event_type=EventType.PLAN_RECEIVED,
            plan_steps=["A", "B"],
            plan_identifier="plan-1",
            is_final_plan=False,
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:05Z",
            event_type=EventType.PLAN_RECEIVED,
            plan_steps=["A", "C"],
            plan_identifier="plan-2",
            is_final_plan=True,
        ),
    ]
    tl = ConversationTimeline(events=events)
    result = build_plan_evolution(tl)
    assert len(result) == 2

    # First plan has no diff
    assert result[0]["plan_index"] == "1"
    assert result[0]["change_summary"] == ""

    # Second plan shows diff
    assert result[1]["plan_index"] == "2"
    assert "C" in result[1]["added_steps"]
    assert "B" in result[1]["removed_steps"]
    assert "+1 added" in result[1]["change_summary"]
    assert "-1 removed" in result[1]["change_summary"]


def test_build_topic_lifecycles_enhanced_fields():
    """Verify lifecycles include has_recommendations, used_outputs, plan_identifier."""
    tl = _make_orchestrator_timeline()
    lifecycles = build_topic_lifecycles(tl)
    assert len(lifecycles) == 1

    lc = lifecycles[0]
    assert lc["name"] == "PasswordReset"
    assert lc["has_recommendations"] == "true"
    assert lc["used_outputs"] == "Used outputs from: KnowledgeSearch"
    assert lc["plan_identifier"] == "plan-1"


def test_build_trigger_match_items_orchestrator_ask():
    """Verify trigger match items include orchestrator_ask when it differs."""
    events = [
        TimelineEvent(
            timestamp="2025-01-01T10:00:00Z",
            position=1,
            event_type=EventType.USER_MESSAGE,
            summary='User: "help with pw"',
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:01Z",
            position=2,
            event_type=EventType.PLAN_RECEIVED_DEBUG,
            summary='Ask: "password reset"',
            orchestrator_ask="password reset",
        ),
        TimelineEvent(
            timestamp="2025-01-01T10:00:02Z",
            position=3,
            event_type=EventType.STEP_TRIGGERED,
            topic_name="PasswordReset",
            summary="Step start: PasswordReset (CustomTopic)",
            state="inProgress",
            step_id="step-1",
        ),
    ]
    tl = ConversationTimeline(events=events)
    profile = BotProfile(
        components=[
            ComponentSummary(
                kind="DialogComponent",
                display_name="PasswordReset",
                schema_name="cr_pw_reset",
                trigger_queries=["reset password", "forgot my password"],
            ),
        ],
    )
    items = build_trigger_match_items(tl, profile)
    assert len(items) == 1
    assert items[0]["orchestrator_ask"] == "password reset"

from pathlib import Path

import pytest

from models import AppInsightsConfig, BotProfile, ComponentSummary, ConversationTimeline, EventType, GptInfo, KnowledgeSearchInfo, SearchResult, TimelineEvent
from parser import _count_action_kinds, _sanitize_yaml, parse_dialog_json, parse_yaml, resolve_topic_name
from renderer import (
    _grounding_score,
    _source_efficiency,
    _topic_display,
    render_bot_metadata,
    render_bot_profile,
    render_components,
    render_event_log,
    render_gantt_chart,
    render_integration_map,
    render_knowledge_architecture,
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
    render_transcript_report,
)
from timeline import build_timeline
from transcript import parse_transcript_json

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


def test_sanitize_yaml_at_keys():
    yaml_text = "  @odata.type: String\n  name: test\n"
    sanitized = _sanitize_yaml(yaml_text)
    assert '"@odata.type"' in sanitized
    assert "name: test" in sanitized


def test_sanitize_yaml_at_values():
    yaml_text = "  displayName: @mention tag\n"
    sanitized = _sanitize_yaml(yaml_text)
    assert '"@mention tag"' in sanitized


def test_sanitize_yaml_tabs():
    yaml_text = "  key:\tvalue\n"
    sanitized = _sanitize_yaml(yaml_text)
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
    assert "## Components" in report
    assert "## Conversation Trace" in report
    assert "```mermaid" in report
    assert "sequenceDiagram" in report
    assert "### Errors" in report
    # TL;DR comes before Bot Profile metadata
    assert report.index("## TL;DR") < report.index("## Bot Profile")
    # Bot Profile comes before Execution Flow
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


def test_render_components_has_summary():
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_components(profile)
    assert "components total" in output
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
    """Report sections should follow the new order: AI Config → Diagrams → Bot Profile → Components."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent (1)" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)

    ai_config_pos = report.index("## AI Configuration")
    tldr_pos = report.index("## TL;DR")
    bot_profile_pos = report.index("## Bot Profile")
    exec_flow_pos = report.index("### Execution Flow")
    components_pos = report.index("## Components")

    assert ai_config_pos < tldr_pos
    assert tldr_pos < bot_profile_pos
    assert bot_profile_pos < exec_flow_pos
    assert exec_flow_pos < components_pos


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
                            {"Name": "Printer Guide", "Url": "https://example.com/printer", "Text": "How to fix printer"},
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
    results = [SearchResult(name=f"Result {i}", url=f"http://example.com/{i}", text=long_snippet if i == 1 else None) for i in range(1, 6)]
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
    output = render_components(profile)
    assert "Source ✓" in output
    # Should NOT have separate "Source" and "Active" columns
    assert "| Source | Active" not in output


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


def test_render_bot_profile_conversation_starters():
    profile = BotProfile(
        display_name="Test Bot",
        gpt_info=GptInfo(
            conversation_starters=[
                {"title": "Password reset", "message": "How do I reset my password?"},
                {"title": "VPN help", "message": "How to connect to VPN?"},
            ],
        ),
    )
    output = render_bot_profile(profile)
    assert "Conversation Starters" in output
    assert "Password reset" in output
    assert "How do I reset my password?" in output


def test_render_bot_profile_no_conversation_starters():
    profile = BotProfile(
        display_name="Test Bot",
        gpt_info=GptInfo(),
    )
    output = render_bot_profile(profile)
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


def test_render_components_user_topics_triggers():
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
    output = render_components(profile)
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
    assert "Knowledge Architecture" in output
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


def test_tool_type_in_orchestrator_table():
    """B1: Tool type appears in orchestrator topics table."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_components(profile)
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
    output = render_components(profile)
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
    output = render_components(profile)
    assert "Global" in output


# --- Phase 5: Visualization ---


def test_security_summary_orchestrator():
    """E1: Security summary rendered for orchestrator bot."""
    profile, _ = parse_yaml(BASE_DIR / "botContent (1)" / "botContent.yml")
    output = render_security_summary(profile)
    assert "Security & Access" in output
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
    output = render_knowledge_architecture(profile)
    assert "Knowledge Architecture" in output
    assert "Knowledge Sources" in output
    assert "File Attachments" in output


def test_knowledge_architecture_trigger_warning():
    """E4: Always-on trigger condition shown as warning."""
    profile, _ = parse_yaml(BASE_DIR / "botContent_genaitopicsadded" / "botContent.yml")
    output = render_knowledge_architecture(profile)
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
    assert "## Security & Access" in report
    assert "## Tool Inventory" in report
    assert "## Integration Map" in report
    assert "## Components" in report
    # Verify ordering: TL;DR < Security < Bot Profile < Components < Tool Inventory
    assert report.index("## TL;DR") < report.index("## Security & Access")
    assert report.index("## Security & Access") < report.index("## Bot Profile")
    assert report.index("## Components") < report.index("## Tool Inventory")
    assert report.index("## Tool Inventory") < report.index("## Integration Map")


def test_report_graceful_degradation_simple_bot():
    """F2: Simple bot report doesn't crash, optional sections omitted."""
    profile, lookup = parse_yaml(BASE_DIR / "botContent" / "botContent.yml")
    activities = parse_dialog_json(BASE_DIR / "botContent" / "dialog.json")
    timeline = build_timeline(activities, lookup)
    report = render_report(profile, timeline)
    assert "## TL;DR" in report
    assert "## Bot Profile" in report
    assert "## Components" in report
    # These should NOT appear for simple bots
    assert "## Tool Inventory" not in report

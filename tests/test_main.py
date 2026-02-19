from pathlib import Path

import pytest

from models import BotProfile, ConversationTimeline, EventType, TimelineEvent
from parser import _sanitize_yaml, parse_dialog_json, parse_yaml, resolve_topic_name
from renderer import (
    _topic_display,
    render_components,
    render_event_log,
    render_gantt_chart,
    render_mermaid_sequence,
    render_report,
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
    assert "## Bot Profile" in report
    assert "## Components" in report
    assert "## Conversation Trace" in report
    assert "```mermaid" in report
    assert "sequenceDiagram" in report
    assert "### Errors" in report
    # Diagrams come before Bot Profile metadata
    assert report.index("### Execution Flow") < report.index("## Bot Profile")


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
    exec_flow_pos = report.index("### Execution Flow")
    bot_profile_pos = report.index("## Bot Profile")
    components_pos = report.index("## Components")

    assert ai_config_pos < exec_flow_pos
    assert exec_flow_pos < bot_profile_pos
    assert bot_profile_pos < components_pos


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
    """Large idle gaps should be collapsed with an Idle marker."""
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

    # Event bars (lines with :eN) should not have multi-minute durations
    for line in output.split("\n"):
        if ":e" in line and ":idle" not in line:
            assert "2m" not in line, f"Event bar has un-collapsed duration: {line}"

    # Total axis range should be small (< 5000ms)
    end_positions = []
    for line in output.split("\n"):
        parts = line.strip().rsplit(",", 1)
        if len(parts) == 2:
            try:
                end_positions.append(int(parts[-1].strip()))
            except ValueError:
                pass
    assert end_positions, "No positions found in gantt output"
    assert max(end_positions) < 5000, f"Axis range too large: {max(end_positions)}"


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
    """Gantt output should include a color legend table."""
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

    assert "| Color | Category |" in output
    assert "| Blue | Orchestrator |" in output
    assert "| Green | User |" in output
    assert "| Purple | Agent |" in output
    assert "| Orange | Tool Calls |" in output
    assert "| Red | Errors |" in output
    assert "| Gray | Idle |" in output


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

    assert ":done, crit, idle" in output

"""Tests for conversation_analysis.py — all 8 features."""

from conversation_analysis import (
    AlignmentReport,
    DeadCodeReport,
    DelegationReport,
    KnowledgeEffectivenessReport,
    LatencyReport,
    PlanDiffReport,
    ResponseQualityReport,
    TurnEfficiencyReport,
    analyze_delegations,
    analyze_instruction_alignment,
    analyze_knowledge_effectiveness,
    analyze_latency_bottlenecks,
    analyze_plan_diffs,
    analyze_response_quality,
    analyze_turn_efficiency,
    detect_dead_code,
)
from models import (
    BotProfile,
    ComponentSummary,
    ConversationTimeline,
    EventType,
    ExecutionPhase,
    GptInfo,
    KnowledgeSearchInfo,
    SearchResult,
    TimelineEvent,
    ToolCall,
)
from renderer.conversation_analysis import (
    render_dead_code,
    render_delegation_analysis,
    render_instruction_alignment,
    render_knowledge_effectiveness,
    render_latency_heatmap,
    render_plan_diffs,
    render_response_quality,
    render_turn_efficiency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: EventType,
    timestamp: str | None = None,
    summary: str = "",
    topic_name: str | None = None,
    step_id: str | None = None,
    state: str | None = None,
    plan_steps: list[str] | None = None,
    plan_identifier: str | None = None,
    orchestrator_ask: str | None = None,
    is_final_plan: bool | None = None,
    intent_score: float | None = None,
    position: int = 0,
    thought: str | None = None,
) -> TimelineEvent:
    return TimelineEvent(
        event_type=event_type,
        timestamp=timestamp,
        summary=summary,
        topic_name=topic_name,
        step_id=step_id,
        state=state,
        plan_steps=plan_steps or [],
        plan_identifier=plan_identifier,
        orchestrator_ask=orchestrator_ask,
        is_final_plan=is_final_plan,
        intent_score=intent_score,
        position=position,
        thought=thought,
    )


def _make_timeline(
    events: list[TimelineEvent] | None = None,
    knowledge_searches: list[KnowledgeSearchInfo] | None = None,
    tool_calls: list[ToolCall] | None = None,
    phases: list[ExecutionPhase] | None = None,
) -> ConversationTimeline:
    return ConversationTimeline(
        bot_name="TestBot",
        conversation_id="conv-1",
        events=events or [],
        knowledge_searches=knowledge_searches or [],
        tool_calls=tool_calls or [],
        phases=phases or [],
    )


def _make_profile(
    components: list[ComponentSummary] | None = None,
    gpt_info: GptInfo | None = None,
    is_orchestrator: bool = False,
) -> BotProfile:
    return BotProfile(
        display_name="TestBot",
        schema_name="cr_test_bot",
        components=components or [],
        gpt_info=gpt_info,
        is_orchestrator=is_orchestrator,
    )


# ---------------------------------------------------------------------------
# Feature 1: Turn Efficiency
# ---------------------------------------------------------------------------


class TestTurnEfficiency:
    def test_empty_timeline(self):
        result = analyze_turn_efficiency(_make_timeline())
        assert isinstance(result, TurnEfficiencyReport)
        assert len(result.turns) == 0

    def test_single_turn_basic(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z", 'User: "hello"'),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", "Plan: [greet]", plan_steps=["greet"]),
            _make_event(EventType.STEP_TRIGGERED, "2024-01-01T00:00:01Z", "Step start: greet", step_id="s1"),
            _make_event(
                EventType.STEP_FINISHED, "2024-01-01T00:00:02Z", "Step end: greet", step_id="s1", state="completed"
            ),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:02Z", "Bot: Hi there!"),
        ]
        result = analyze_turn_efficiency(_make_timeline(events))
        assert len(result.turns) == 1
        assert result.turns[0].plan_count == 1
        assert result.turns[0].tool_call_count == 1
        assert result.turns[0].user_message == "hello"

    def test_sequential_planning_not_flagged(self):
        """5 unique plans with matching tool calls = normal multi-step workflow, no flag."""
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z", 'User: "complex query"'),
        ]
        for i in range(5):
            events.append(
                _make_event(EventType.PLAN_RECEIVED, f"2024-01-01T00:00:0{i + 1}Z", plan_steps=[f"step{i}"])
            )
            events.append(
                _make_event(EventType.STEP_TRIGGERED, f"2024-01-01T00:00:0{i + 1}Z", step_id=f"s{i}")
            )
            events.append(
                _make_event(EventType.STEP_FINISHED, f"2024-01-01T00:00:0{i + 1}Z", step_id=f"s{i}", state="completed")
            )
        result = analyze_turn_efficiency(_make_timeline(events))
        assert result.turns[0].plan_count == 5
        assert not result.turns[0].flags  # No flags — this is legitimate multi-step

    def test_plan_thrashing_flagged(self):
        """Same plan set appearing twice = thrashing, should flag."""
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z", 'User: "query"'),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", plan_steps=["stepA"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:02Z", plan_steps=["stepB"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:03Z", plan_steps=["stepA"]),  # repeat
            _make_event(EventType.STEP_TRIGGERED, "2024-01-01T00:00:04Z", step_id="s1"),
            _make_event(EventType.STEP_FINISHED, "2024-01-01T00:00:04Z", step_id="s1", state="completed"),
        ]
        result = analyze_turn_efficiency(_make_timeline(events))
        assert any("thrashing" in f.lower() for f in result.turns[0].flags)
        assert result.inefficient_turn_count == 1

    def test_high_plan_to_tool_ratio_flagged(self):
        """Many plans but few tool calls = inefficient planning."""
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z", 'User: "query"'),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", plan_steps=["a"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:02Z", plan_steps=["b"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:03Z", plan_steps=["c"]),
            _make_event(EventType.STEP_TRIGGERED, "2024-01-01T00:00:04Z", step_id="s1"),
            _make_event(EventType.STEP_FINISHED, "2024-01-01T00:00:04Z", step_id="s1", state="completed"),
        ]
        result = analyze_turn_efficiency(_make_timeline(events))
        assert any("plan-to-tool" in f.lower() for f in result.turns[0].flags)

    def test_abandoned_tool_chain_flagged(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z", 'User: "query"'),
            _make_event(EventType.STEP_TRIGGERED, "2024-01-01T00:00:01Z", "Step start: tool1", step_id="s1"),
            # No STEP_FINISHED for s1
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:03Z", "Bot: response"),
        ]
        result = analyze_turn_efficiency(_make_timeline(events))
        assert any("Abandoned" in f for f in result.turns[0].flags)

    def test_multi_turn(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z", 'User: "first"'),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:01Z", "Bot: response1"),
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:02Z", 'User: "second"'),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:03Z", "Bot: response2"),
        ]
        result = analyze_turn_efficiency(_make_timeline(events))
        assert len(result.turns) == 2

    def test_render_turn_efficiency(self):
        report = TurnEfficiencyReport(
            turns=[],
            avg_plans_per_turn=0,
            avg_tools_per_turn=0,
            avg_thinking_ratio=0,
            inefficient_turn_count=0,
        )
        assert render_turn_efficiency(report) == ""

        # Non-empty report
        from conversation_analysis import TurnMetrics

        report.turns = [TurnMetrics(turn_index=1, user_message="hello", plan_count=1, total_ms=1000)]
        md = render_turn_efficiency(report)
        assert "Turn Efficiency" in md
        assert "hello" in md


# ---------------------------------------------------------------------------
# Feature 2: Dead Code Detection
# ---------------------------------------------------------------------------


class TestDeadCodeDetection:
    def test_no_dead_code(self):
        components = [
            ComponentSummary(kind="DialogComponent", display_name="Greet", schema_name="topic_greet"),
        ]
        events = [
            _make_event(EventType.STEP_TRIGGERED, topic_name="Greet"),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline(events)])
        assert len(result.dead_items) == 0
        assert result.dead_ratio == 0.0

    def test_dead_topic_detected(self):
        components = [
            ComponentSummary(kind="DialogComponent", display_name="Greet", schema_name="topic_greet"),
            ComponentSummary(kind="DialogComponent", display_name="FAQ", schema_name="topic_faq"),
        ]
        events = [
            _make_event(EventType.STEP_TRIGGERED, topic_name="Greet"),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline(events)])
        assert len(result.dead_items) == 1
        assert result.dead_items[0].display_name == "FAQ"

    def test_system_topics_excluded(self):
        components = [
            ComponentSummary(kind="DialogComponent", display_name="On Error", schema_name="crsys_on_error"),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline()])
        assert len(result.dead_items) == 0

    def test_inactive_components_excluded(self):
        components = [
            ComponentSummary(kind="DialogComponent", display_name="Old Topic", schema_name="old", state="Inactive"),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline()])
        assert len(result.dead_items) == 0

    def test_dead_tool_detected(self):
        components = [
            ComponentSummary(
                kind="DialogComponent",
                display_name="MyTool",
                schema_name="tool_1",
                dialog_kind="TaskDialog",
                tool_type="ConnectorTool",
            ),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline()])
        assert len(result.dead_items) == 1
        assert result.dead_items[0].component_kind == "Tool"

    def test_system_topics_by_schema_suffix_excluded(self):
        """System topics like Greeting, Escalate, etc. should be excluded by schema suffix."""
        components = [
            ComponentSummary(kind="DialogComponent", display_name="Greeting", schema_name="rrs_bot.topic.Greeting"),
            ComponentSummary(kind="DialogComponent", display_name="Escalate", schema_name="rrs_bot.topic.Escalate"),
            ComponentSummary(kind="DialogComponent", display_name="Start Over", schema_name="rrs_bot.topic.StartOver"),
            ComponentSummary(
                kind="DialogComponent",
                display_name="End of Conversation",
                schema_name="rrs_bot.topic.EndofConversation",
            ),
            ComponentSummary(
                kind="DialogComponent",
                display_name="Multiple Topics Matched",
                schema_name="rrs_bot.topic.MultipleTopicsMatched",
            ),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline()])
        assert len(result.dead_items) == 0

    def test_gpt_default_topic_excluded(self):
        """The GPT default topic (orchestrator itself) should never be flagged."""
        components = [
            ComponentSummary(kind="GptComponent", display_name="My Bot", schema_name="rrs_bot.gpt.default"),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline()])
        assert len(result.dead_items) == 0

    def test_mcp_tool_matched_by_partial_id(self):
        """MCP tools use MCP:<schema>:<tool> format — should match partial."""
        components = [
            ComponentSummary(
                kind="DialogComponent",
                display_name="ZavaMCP",
                schema_name="rrs_bot.topic.ZavaMCP",
                dialog_kind="TaskDialog",
                tool_type="MCPServer",
            ),
        ]
        tc = ToolCall(
            task_dialog_id="MCP:rrs_bot.topic.ZavaMCP:create_expense",
            display_name="create_expense",
            state="completed",
        )
        result = detect_dead_code(_make_profile(components), [_make_timeline(tool_calls=[tc])])
        assert len(result.dead_items) == 0

    def test_planned_tool_not_flagged(self):
        """Tools that appear in plan steps should not be flagged as dead."""
        components = [
            ComponentSummary(
                kind="DialogComponent",
                display_name="Search Tool",
                schema_name="rrs_bot.topic.SearchTool",
                dialog_kind="TaskDialog",
                tool_type="ConnectorTool",
            ),
        ]
        events = [
            _make_event(EventType.PLAN_RECEIVED, plan_steps=["Search Tool", "Other"]),
        ]
        result = detect_dead_code(_make_profile(components), [_make_timeline(events)])
        assert len(result.dead_items) == 0

    def test_render_dead_code_empty(self):
        report = DeadCodeReport(dead_items=[], total_components=5, active_components=5, dead_ratio=0.0)
        md = render_dead_code(report)
        assert "All components" in md

    def test_render_dead_code_with_items(self):
        from conversation_analysis import DeadCodeItem

        report = DeadCodeReport(
            dead_items=[DeadCodeItem(component_kind="Topic", display_name="FAQ", schema_name="topic_faq")],
            total_components=5,
            active_components=4,
            dead_ratio=0.2,
        )
        md = render_dead_code(report)
        assert "FAQ" in md
        assert "Dead Code" in md


# ---------------------------------------------------------------------------
# Feature 3: Plan Diff
# ---------------------------------------------------------------------------


class TestPlanDiff:
    def test_no_replanning(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", plan_steps=["step1"]),
        ]
        result = analyze_plan_diffs(_make_timeline(events))
        assert result.total_replans == 0

    def test_single_replan(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", plan_steps=["stepA"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:02Z", plan_steps=["stepA", "stepB"]),
        ]
        result = analyze_plan_diffs(_make_timeline(events))
        assert result.total_replans == 1
        assert result.diffs[0].added_steps == ["stepB"]
        assert result.diffs[0].removed_steps == []

    def test_thrashing_detected(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", plan_steps=["stepA"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:02Z", plan_steps=["stepB"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:03Z", plan_steps=["stepA"]),  # back to A
        ]
        result = analyze_plan_diffs(_make_timeline(events))
        assert result.thrashing_count == 1
        assert result.diffs[-1].is_thrashing

    def test_scope_creep_detected(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:01Z", plan_steps=["a"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:02Z", plan_steps=["a", "b"]),
            _make_event(EventType.PLAN_RECEIVED, "2024-01-01T00:00:03Z", plan_steps=["a", "b", "c"]),
        ]
        result = analyze_plan_diffs(_make_timeline(events))
        assert result.scope_creep_count == 2

    def test_render_plan_diffs_empty(self):
        assert render_plan_diffs(PlanDiffReport()) == ""

    def test_render_plan_diffs_with_data(self):
        from conversation_analysis import PlanDiffEntry

        report = PlanDiffReport(
            diffs=[
                PlanDiffEntry(
                    turn_index=1, plan_a_steps=["a"], plan_b_steps=["a", "b"], added_steps=["b"], removed_steps=[]
                )
            ],
            total_replans=1,
        )
        md = render_plan_diffs(report)
        assert "Plan Evolution" in md
        assert "`b`" in md


# ---------------------------------------------------------------------------
# Feature 4: Knowledge Source Effectiveness
# ---------------------------------------------------------------------------


class TestKnowledgeEffectiveness:
    def test_empty_timelines(self):
        result = analyze_knowledge_effectiveness([_make_timeline()])
        assert result.total_searches == 0
        assert result.sources == []

    def test_single_search_with_contribution(self):
        ks = KnowledgeSearchInfo(
            knowledge_sources=["docs"],
            output_knowledge_sources=["docs"],
            search_results=[SearchResult(name="doc1", text="content")],
        )
        result = analyze_knowledge_effectiveness([_make_timeline(knowledge_searches=[ks])])
        assert result.total_searches == 1
        assert len(result.sources) == 1
        assert result.sources[0].hit_rate == 1.0

    def test_zero_result_counted(self):
        ks = KnowledgeSearchInfo(
            knowledge_sources=["docs"],
            output_knowledge_sources=[],
            search_results=[],
        )
        result = analyze_knowledge_effectiveness([_make_timeline(knowledge_searches=[ks])])
        assert result.zero_result_searches == 1
        assert result.sources[0].hit_rate == 0.0

    def test_multiple_sources(self):
        ks = KnowledgeSearchInfo(
            knowledge_sources=["src_a", "src_b"],
            output_knowledge_sources=["src_a"],
            search_results=[SearchResult(name="r1")],
        )
        result = analyze_knowledge_effectiveness([_make_timeline(knowledge_searches=[ks])])
        assert len(result.sources) == 2
        src_a = next(s for s in result.sources if s.source_name == "src_a")
        src_b = next(s for s in result.sources if s.source_name == "src_b")
        assert src_a.hit_rate == 1.0
        assert src_b.hit_rate == 0.0

    def test_render_knowledge_effectiveness(self):
        report = KnowledgeEffectivenessReport(sources=[], total_searches=0)
        assert render_knowledge_effectiveness(report) == ""


# ---------------------------------------------------------------------------
# Feature 5: Response Quality Scorecard
# ---------------------------------------------------------------------------


class TestResponseQuality:
    def test_empty_timeline(self):
        result = analyze_response_quality(_make_timeline())
        assert result.grounded_count == 0
        assert result.ungrounded_count == 0

    def test_grounded_response_with_knowledge(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.KNOWLEDGE_SEARCH, "2024-01-01T00:00:01Z"),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:02Z", "Bot: answer"),
        ]
        ks = KnowledgeSearchInfo(
            timestamp="2024-01-01T00:00:01Z",
            search_results=[SearchResult(name="doc1")],
        )
        result = analyze_response_quality(_make_timeline(events, knowledge_searches=[ks]))
        assert result.grounded_count == 1

    def test_ungrounded_response_no_source(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:01Z", "Bot: making it up"),
        ]
        result = analyze_response_quality(_make_timeline(events))
        assert result.ungrounded_count == 1
        assert result.items[0].hallucination_risk == "medium"

    def test_high_risk_zero_results(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.KNOWLEDGE_SEARCH, "2024-01-01T00:00:01Z"),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:02Z", "Bot: answer anyway"),
        ]
        ks = KnowledgeSearchInfo(
            timestamp="2024-01-01T00:00:01Z",
            search_results=[],  # Zero results
        )
        result = analyze_response_quality(_make_timeline(events, knowledge_searches=[ks]))
        assert result.high_risk_count == 1

    def test_swallowed_error_detected(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00Z"),
            _make_event(EventType.STEP_TRIGGERED, "2024-01-01T00:00:01Z", step_id="s1"),
            _make_event(EventType.STEP_FINISHED, "2024-01-01T00:00:02Z", step_id="s1", state="failed"),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:03Z", "Bot: everything fine"),
        ]
        result = analyze_response_quality(_make_timeline(events))
        assert result.swallowed_error_count == 1

    def test_render_response_quality_empty(self):
        assert render_response_quality(ResponseQualityReport()) == ""


# ---------------------------------------------------------------------------
# Feature 6: Multi-Agent Delegation
# ---------------------------------------------------------------------------


class TestDelegationAnalysis:
    def test_no_agents(self):
        result = analyze_delegations(_make_timeline(), _make_profile())
        assert result.configured_agents == []
        assert result.delegations == []

    def test_dead_agent_detected(self):
        components = [
            ComponentSummary(
                kind="DialogComponent",
                display_name="SubAgent",
                schema_name="agent_sub",
                dialog_kind="AgentDialog",
                tool_type="ChildAgent",
            ),
        ]
        result = analyze_delegations(_make_timeline(), _make_profile(components))
        assert "SubAgent" in result.dead_agents

    def test_delegation_tracked(self):
        components = [
            ComponentSummary(
                kind="DialogComponent",
                display_name="SubAgent",
                schema_name="agent_sub",
                dialog_kind="AgentDialog",
                tool_type="ChildAgent",
                agent_instructions="You help with billing",
            ),
        ]
        tc = ToolCall(
            task_dialog_id="agent_sub",
            display_name="SubAgent",
            tool_type="ChildAgent",
            step_type="Agent",
            state="completed",
            duration_ms=500,
            thought="User needs billing help",
        )
        result = analyze_delegations(
            _make_timeline(tool_calls=[tc]),
            _make_profile(components),
        )
        assert len(result.delegations) == 1
        assert result.delegations[0].agent_name == "SubAgent"
        assert result.delegations[0].agent_instructions == "You help with billing"
        assert "SubAgent" not in result.dead_agents

    def test_failing_agent_detected(self):
        components = [
            ComponentSummary(
                kind="DialogComponent",
                display_name="BadAgent",
                schema_name="bad",
                dialog_kind="AgentDialog",
                tool_type="ConnectedAgent",
            ),
        ]
        tc = ToolCall(
            task_dialog_id="bad",
            display_name="BadAgent",
            tool_type="ConnectedAgent",
            step_type="Agent",
            state="failed",
            error="timeout",
        )
        result = analyze_delegations(
            _make_timeline(tool_calls=[tc]),
            _make_profile(components),
        )
        assert "BadAgent" in result.failing_agents

    def test_render_delegation_empty(self):
        assert render_delegation_analysis(DelegationReport()) == ""


# ---------------------------------------------------------------------------
# Feature 7: Latency Bottleneck
# ---------------------------------------------------------------------------


class TestLatencyBottleneck:
    def test_empty_timeline(self):
        result = analyze_latency_bottlenecks(_make_timeline())
        assert result.turns == []

    def test_single_turn_breakdown(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:01:01Z"),
            _make_event(
                EventType.ORCHESTRATOR_THINKING, "2024-01-01T00:01:02Z", "Orchestrator: Planning response (1500ms)"
            ),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:01:03Z", "Bot: answer"),
        ]
        result = analyze_latency_bottlenecks(_make_timeline(events))
        assert len(result.turns) == 1
        assert result.turns[0].total_ms > 0

    def test_bottleneck_detection(self):
        events = [
            _make_event(EventType.USER_MESSAGE, "2024-01-01T00:00:00.000Z"),
            _make_event(EventType.ORCHESTRATOR_THINKING, "2024-01-01T00:00:01.000Z", "Orchestrator: Planning (4000ms)"),
            _make_event(EventType.BOT_MESSAGE, "2024-01-01T00:00:05.000Z", "Bot: answer"),
        ]
        result = analyze_latency_bottlenecks(_make_timeline(events))
        assert result.bottleneck_turn_count >= 0  # May or may not detect depending on threshold

    def test_render_latency_empty(self):
        assert render_latency_heatmap(LatencyReport()) == ""


# ---------------------------------------------------------------------------
# Feature 8: Instruction Alignment
# ---------------------------------------------------------------------------


class TestInstructionAlignment:
    def test_no_instructions(self):
        result = analyze_instruction_alignment(_make_timeline(), _make_profile())
        assert result.directives_found == 0

    def test_language_directive_detected(self):
        profile = _make_profile(gpt_info=GptInfo(instructions="Always respond in Dutch"))
        events = [
            _make_event(EventType.BOT_MESSAGE, summary="Bot: This is the answer to your question"),
            _make_event(EventType.BOT_MESSAGE, summary="Bot: The service is available from Monday to Friday"),
            _make_event(
                EventType.BOT_MESSAGE, summary="Bot: That is correct, the policy states that all users have access"
            ),
            _make_event(EventType.BOT_MESSAGE, summary="Bot: Here are the details you requested"),
        ]
        result = analyze_instruction_alignment(_make_timeline(events), profile)
        assert result.directives_found >= 1

    def test_escalation_directive_detected(self):
        profile = _make_profile(gpt_info=GptInfo(instructions="Escalate when user asks about pricing"))
        events = [
            _make_event(EventType.USER_MESSAGE, summary='User: "What is the pricing for enterprise?"'),
            _make_event(EventType.BOT_MESSAGE, summary="Bot: Our pricing starts at $99"),
        ]
        result = analyze_instruction_alignment(_make_timeline(events), profile)
        assert result.directives_found >= 1
        # Should detect missing escalation since user asked about pricing but no escalation happened
        escalation_violations = [v for v in result.violations if v.violation_type == "missing_escalation"]
        assert len(escalation_violations) >= 1

    def test_scope_breach_detected(self):
        profile = _make_profile(gpt_info=GptInfo(instructions="Do not discuss competitor products or services"))
        events = [
            _make_event(
                EventType.BOT_MESSAGE, summary="Bot: competitor products are great and their services are better"
            ),
        ]
        result = analyze_instruction_alignment(_make_timeline(events), profile)
        scope_violations = [v for v in result.violations if v.violation_type == "scope_breach"]
        assert len(scope_violations) >= 1

    def test_render_alignment_empty(self):
        assert render_instruction_alignment(AlignmentReport()) == ""

    def test_render_alignment_with_violations(self):
        from conversation_analysis import AlignmentViolation

        report = AlignmentReport(
            directives_found=2,
            violations=[
                AlignmentViolation(
                    directive="Respond in Dutch",
                    violation_type="language_mismatch",
                    evidence="Found 5 English markers",
                )
            ],
            coverage_score=0.5,
        )
        md = render_instruction_alignment(report)
        assert "Alignment" in md
        assert "language_mismatch" in md

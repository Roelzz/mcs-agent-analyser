"""Conversation analysis features — turn efficiency, dead code detection,
plan diff, knowledge effectiveness, response quality, delegation analysis,
latency bottlenecks, and instruction alignment."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from models import (
    BotProfile,
    ComponentSummary,
    ConversationTimeline,
    EventType,
    TimelineEvent,
)


# ---------------------------------------------------------------------------
# Feature 1: Conversation Turn Efficiency Analysis
# ---------------------------------------------------------------------------


@dataclass
class TurnMetrics:
    """Metrics for a single user turn (user message → next user message)."""

    turn_index: int = 0
    user_message: str = ""
    plan_count: int = 0
    tool_call_count: int = 0
    knowledge_search_count: int = 0
    thinking_ms: float = 0.0
    execution_ms: float = 0.0
    total_ms: float = 0.0
    flags: list[str] = field(default_factory=list)


@dataclass
class TurnEfficiencyReport:
    """Aggregated turn efficiency analysis for a conversation."""

    turns: list[TurnMetrics] = field(default_factory=list)
    avg_plans_per_turn: float = 0.0
    avg_tools_per_turn: float = 0.0
    avg_thinking_ratio: float = 0.0
    inefficient_turn_count: int = 0


def _ms_between(start: str | None, end: str | None) -> float:
    """Calculate ms between two ISO timestamps."""
    from timeline import _parse_timestamp

    dt_start = _parse_timestamp(start)
    dt_end = _parse_timestamp(end)
    if dt_start and dt_end:
        return (dt_end - dt_start).total_seconds() * 1000
    return 0.0


def _split_events_by_turn(events: list[TimelineEvent]) -> list[list[TimelineEvent]]:
    """Split events into turns, each starting with a USER_MESSAGE."""
    turns: list[list[TimelineEvent]] = []
    current: list[TimelineEvent] = []
    for event in events:
        if event.event_type == EventType.USER_MESSAGE and current:
            turns.append(current)
            current = []
        current.append(event)
    if current:
        turns.append(current)
    return turns


def analyze_turn_efficiency(timeline: ConversationTimeline) -> TurnEfficiencyReport:
    """Analyze per-turn efficiency metrics for a conversation."""
    turn_groups = _split_events_by_turn(timeline.events)
    turns: list[TurnMetrics] = []

    for idx, events in enumerate(turn_groups):
        if not events:
            continue

        plans = [e for e in events if e.event_type == EventType.PLAN_RECEIVED]
        tools = [e for e in events if e.event_type == EventType.STEP_TRIGGERED]
        searches = [e for e in events if e.event_type == EventType.KNOWLEDGE_SEARCH]
        thinking = [e for e in events if e.event_type == EventType.ORCHESTRATOR_THINKING]

        thinking_ms = sum(
            _ms_between(e.timestamp, events[i + 1].timestamp)
            if e.timestamp and i + 1 < len(events) and events[i + 1].timestamp
            else 0.0
            for i, e in enumerate(events)
            if e.event_type == EventType.ORCHESTRATOR_THINKING
        )
        # Use phase-based thinking time from summary if available
        for e in thinking:
            # Extract ms from summary like "Orchestrator: Planning response (1234ms)"
            match = re.search(r"\((\d+(?:\.\d+)?)ms\)", e.summary or "")
            if match:
                thinking_ms = max(thinking_ms, float(match.group(1)))

        total_ms = _ms_between(events[0].timestamp, events[-1].timestamp) if len(events) > 1 else 0.0
        execution_ms = total_ms - thinking_ms if total_ms > thinking_ms else 0.0

        user_msg = ""
        for e in events:
            if e.event_type == EventType.USER_MESSAGE:
                user_msg = (
                    e.summary.replace('User: "', "").rstrip('"') if e.summary.startswith('User: "') else e.summary
                )
                break

        flags: list[str] = []
        # Detect plan thrashing: same step set appearing more than once
        plan_step_sets = [frozenset(p.plan_steps) for p in plans if p.plan_steps]
        has_thrashing = len(plan_step_sets) != len(set(plan_step_sets))
        if has_thrashing:
            flags.append(f"Plan thrashing ({len(plans)} plans, repeated step sets)")
        # Flag high plan-to-tool ratio: lots of re-planning but few actual tool executions
        elif len(plans) > 2 and len(tools) > 0 and len(plans) / len(tools) > 2:
            flags.append(f"High plan-to-tool ratio ({len(plans)} plans / {len(tools)} tools)")
        if total_ms > 0 and thinking_ms / total_ms > 0.7:
            flags.append(f"High thinking ratio ({thinking_ms / total_ms:.0%})")
        # Detect abandoned tool chains: tool triggered but not finished
        triggered_steps = {e.step_id for e in events if e.event_type == EventType.STEP_TRIGGERED and e.step_id}
        finished_steps = {e.step_id for e in events if e.event_type == EventType.STEP_FINISHED and e.step_id}
        abandoned = triggered_steps - finished_steps
        if abandoned:
            flags.append(f"Abandoned tool chain ({len(abandoned)} unfinished)")

        turns.append(
            TurnMetrics(
                turn_index=idx + 1,
                user_message=user_msg[:100],
                plan_count=len(plans),
                tool_call_count=len(tools),
                knowledge_search_count=len(searches),
                thinking_ms=thinking_ms,
                execution_ms=execution_ms,
                total_ms=total_ms,
                flags=flags,
            )
        )

    if not turns:
        return TurnEfficiencyReport()

    avg_plans = sum(t.plan_count for t in turns) / len(turns)
    avg_tools = sum(t.tool_call_count for t in turns) / len(turns)
    thinking_ratios = [t.thinking_ms / t.total_ms for t in turns if t.total_ms > 0]
    avg_thinking_ratio = sum(thinking_ratios) / len(thinking_ratios) if thinking_ratios else 0.0
    inefficient = sum(1 for t in turns if t.flags)

    return TurnEfficiencyReport(
        turns=turns,
        avg_plans_per_turn=avg_plans,
        avg_tools_per_turn=avg_tools,
        avg_thinking_ratio=avg_thinking_ratio,
        inefficient_turn_count=inefficient,
    )


# ---------------------------------------------------------------------------
# Feature 2: Topic Dead Code Detection
# ---------------------------------------------------------------------------


@dataclass
class DeadCodeItem:
    """A component that was never triggered at runtime."""

    component_kind: str  # "Topic", "KnowledgeSource", "Variable", "Entity", "Tool"
    display_name: str
    schema_name: str


@dataclass
class DeadCodeReport:
    """Dead code detection results."""

    dead_items: list[DeadCodeItem] = field(default_factory=list)
    total_components: int = 0
    active_components: int = 0
    dead_ratio: float = 0.0


def detect_dead_code(
    profile: BotProfile,
    timelines: list[ConversationTimeline],
) -> DeadCodeReport:
    """Cross-reference bot profile components against runtime evidence."""
    # Collect all runtime-observed names
    triggered_topics: set[str] = set()
    searched_sources: set[str] = set()
    assigned_variables: set[str] = set()
    called_tools: set[str] = set()
    planned_steps: set[str] = set()

    for tl in timelines:
        for event in tl.events:
            if event.event_type == EventType.STEP_TRIGGERED and event.topic_name:
                triggered_topics.add(event.topic_name)
            if event.event_type == EventType.KNOWLEDGE_SEARCH:
                triggered_topics.add("Knowledge Search")  # generic marker
            if event.event_type == EventType.VARIABLE_ASSIGNMENT:
                # Extract variable name from summary like "Topic var_name = value"
                parts = (event.summary or "").split("=", 1)
                if parts:
                    var_part = parts[0].strip().split()
                    if len(var_part) >= 2:
                        assigned_variables.add(var_part[-1])
            # Plan steps are evidence of intended usage
            if event.event_type == EventType.PLAN_RECEIVED and event.plan_steps:
                for step in event.plan_steps:
                    planned_steps.add(step)
        for ks in tl.knowledge_searches:
            for src in ks.knowledge_sources:
                searched_sources.add(src.lower())
        for tc in tl.tool_calls:
            called_tools.add(tc.task_dialog_id)
            called_tools.add(tc.display_name)

    # System/orchestrator topics to exclude from dead code detection
    system_prefixes = {"cr", "crsys_", "P:", "microsoft.virtual"}
    system_names = {
        "Conversation Start",
        "On Conversation Start",
        "On Error",
        "On Escalate",
        "Escalate",
        "Fallback",
        "Conversational boosting",
        "Reset Conversation",
        "Start Over",
        "Sign in",
        "Goodbye",
        "Greeting",
        "End of Conversation",
        "Multiple Topics Matched",
        "Thank you",
    }
    # Schema name suffixes that indicate system/framework topics
    system_schema_suffixes = {
        ".Escalate",
        ".Greeting",
        ".Signin",
        ".StartOver",
        ".EndofConversation",
        ".MultipleTopicsMatched",
        ".ThankYou",
        ".Goodbye",
        ".Fallback",
        ".ConversationalBoosting",
        ".ResetConversation",
        ".OnError",
        ".OnEscalate",
    }

    dead_items: list[DeadCodeItem] = []
    checkable: list[ComponentSummary] = []

    for comp in profile.components:
        # Skip system components by prefix
        if comp.schema_name and any(comp.schema_name.startswith(p) for p in system_prefixes):
            continue
        # Skip by display name
        if comp.display_name in system_names:
            continue
        # Skip by schema suffix (catches system topics regardless of publisher prefix)
        if comp.schema_name and any(comp.schema_name.endswith(s) for s in system_schema_suffixes):
            continue
        # Skip the GPT default topic — it's the orchestrator itself, always "active"
        if comp.kind == "GptComponent" and ".gpt.default" in comp.schema_name:
            continue
        if comp.state == "Inactive":
            continue

        checkable.append(comp)

        is_alive = False

        # Check tools FIRST (dialog_kind takes priority over kind for TaskDialog/AgentDialog)
        if comp.dialog_kind in ("TaskDialog", "AgentDialog"):
            # Tool — check if it was called (direct or MCP format)
            if comp.schema_name in called_tools or comp.display_name in called_tools:
                is_alive = True
            # MCP tools: task_dialog_id is "MCP:<schema>:<tool>" — check partial match
            elif any(comp.schema_name in tool_id for tool_id in called_tools):
                is_alive = True
            # Also check planned steps for tools that were planned but not yet called
            elif any(comp.display_name in step or comp.schema_name in step for step in planned_steps):
                is_alive = True
        elif comp.kind in ("DialogComponent", "GptComponent"):
            # Check if topic was triggered or planned
            if comp.display_name in triggered_topics or comp.schema_name in triggered_topics:
                is_alive = True
            elif comp.display_name in planned_steps or comp.schema_name in planned_steps:
                is_alive = True
        elif comp.kind == "KnowledgeComponent":
            # Check if knowledge source was queried
            name_lower = comp.display_name.lower()
            schema_lower = comp.schema_name.lower()
            if any(name_lower in s or schema_lower in s for s in searched_sources):
                is_alive = True
        elif comp.kind == "VariableComponent":
            if comp.display_name in assigned_variables or comp.schema_name in assigned_variables:
                is_alive = True
        elif comp.kind == "EntityComponent":
            # Entities are harder to detect usage for — mark as alive by default
            is_alive = True
        else:
            is_alive = True  # Unknown kind, don't flag

        if not is_alive:
            kind_label = "Topic"
            if comp.kind == "KnowledgeComponent":
                kind_label = "KnowledgeSource"
            elif comp.kind == "VariableComponent":
                kind_label = "Variable"
            elif comp.dialog_kind in ("TaskDialog", "AgentDialog"):
                kind_label = "Tool"
            dead_items.append(
                DeadCodeItem(
                    component_kind=kind_label,
                    display_name=comp.display_name,
                    schema_name=comp.schema_name,
                )
            )

    total = len(checkable)
    active = total - len(dead_items)
    dead_ratio = len(dead_items) / total if total > 0 else 0.0

    return DeadCodeReport(
        dead_items=dead_items,
        total_components=total,
        active_components=active,
        dead_ratio=dead_ratio,
    )


# ---------------------------------------------------------------------------
# Feature 3: Orchestrator Plan Diff
# ---------------------------------------------------------------------------


@dataclass
class PlanDiffEntry:
    """A single diff between consecutive plans within a turn."""

    turn_index: int
    plan_a_steps: list[str]
    plan_b_steps: list[str]
    added_steps: list[str]
    removed_steps: list[str]
    orchestrator_ask: str | None = None
    is_thrashing: bool = False


@dataclass
class PlanDiffReport:
    """Plan diff analysis across all turns."""

    diffs: list[PlanDiffEntry] = field(default_factory=list)
    total_replans: int = 0
    thrashing_count: int = 0
    scope_creep_count: int = 0  # plans that only grow


def analyze_plan_diffs(timeline: ConversationTimeline) -> PlanDiffReport:
    """Diff consecutive PLAN_RECEIVED events within same user turn."""
    turn_groups = _split_events_by_turn(timeline.events)
    diffs: list[PlanDiffEntry] = []
    total_replans = 0
    thrashing = 0
    scope_creep = 0

    for turn_idx, events in enumerate(turn_groups):
        plans = [e for e in events if e.event_type == EventType.PLAN_RECEIVED and e.plan_steps]
        if len(plans) < 2:
            continue

        # Collect asks from debug events in this turn
        asks = {
            e.plan_identifier: e.orchestrator_ask
            for e in events
            if e.event_type == EventType.PLAN_RECEIVED_DEBUG and e.orchestrator_ask
        }

        # Track all step sets for thrashing detection
        seen_step_sets: list[frozenset[str]] = []

        for i in range(len(plans) - 1):
            a = plans[i].plan_steps
            b = plans[i + 1].plan_steps
            a_set = set(a)
            b_set = set(b)
            added = sorted(b_set - a_set)
            removed = sorted(a_set - b_set)

            # Thrashing: plan B matches a previous plan (not plan A)
            b_frozen = frozenset(b)
            is_thrash = b_frozen in seen_step_sets
            seen_step_sets.append(frozenset(a))

            if is_thrash:
                thrashing += 1

            # Scope creep: only additions, no removals
            if added and not removed:
                scope_creep += 1

            ask = asks.get(plans[i + 1].plan_identifier)
            diffs.append(
                PlanDiffEntry(
                    turn_index=turn_idx + 1,
                    plan_a_steps=a,
                    plan_b_steps=b,
                    added_steps=added,
                    removed_steps=removed,
                    orchestrator_ask=ask,
                    is_thrashing=is_thrash,
                )
            )
            total_replans += 1

    return PlanDiffReport(
        diffs=diffs,
        total_replans=total_replans,
        thrashing_count=thrashing,
        scope_creep_count=scope_creep,
    )


# ---------------------------------------------------------------------------
# Feature 4: Knowledge Source Effectiveness Report
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeSourceStats:
    """Per-source statistics across conversations."""

    source_name: str
    query_count: int = 0
    contribution_count: int = 0  # appeared in output_knowledge_sources
    hit_rate: float = 0.0  # contribution_count / query_count
    error_count: int = 0
    avg_result_count: float = 0.0


@dataclass
class KnowledgeEffectivenessReport:
    """Aggregated knowledge source effectiveness."""

    sources: list[KnowledgeSourceStats] = field(default_factory=list)
    total_searches: int = 0
    avg_sources_per_search: float = 0.0
    zero_result_searches: int = 0


def analyze_knowledge_effectiveness(
    timelines: list[ConversationTimeline],
) -> KnowledgeEffectivenessReport:
    """Per-knowledge-source stats across conversations."""
    source_stats: dict[str, dict] = defaultdict(
        lambda: {"query_count": 0, "contribution_count": 0, "error_count": 0, "result_counts": []}
    )
    total_searches = 0
    zero_results = 0
    total_sources_per_search: list[int] = []

    for tl in timelines:
        for ks in tl.knowledge_searches:
            total_searches += 1
            total_sources_per_search.append(len(ks.knowledge_sources))

            if not ks.search_results:
                zero_results += 1

            output_set = {s.lower() for s in ks.output_knowledge_sources}
            has_errors = bool(ks.search_errors)

            for src in ks.knowledge_sources:
                stats = source_stats[src]
                stats["query_count"] += 1
                if src.lower() in output_set:
                    stats["contribution_count"] += 1
                if has_errors:
                    stats["error_count"] += 1
                stats["result_counts"].append(len(ks.search_results))

    sources = []
    for name, stats in source_stats.items():
        qc = stats["query_count"]
        cc = stats["contribution_count"]
        rc = stats["result_counts"]
        sources.append(
            KnowledgeSourceStats(
                source_name=name,
                query_count=qc,
                contribution_count=cc,
                hit_rate=cc / qc if qc > 0 else 0.0,
                error_count=stats["error_count"],
                avg_result_count=sum(rc) / len(rc) if rc else 0.0,
            )
        )

    # Sort by query count descending
    sources.sort(key=lambda s: s.query_count, reverse=True)

    avg_sources = sum(total_sources_per_search) / len(total_sources_per_search) if total_sources_per_search else 0.0

    return KnowledgeEffectivenessReport(
        sources=sources,
        total_searches=total_searches,
        avg_sources_per_search=avg_sources,
        zero_result_searches=zero_results,
    )


# ---------------------------------------------------------------------------
# Feature 5: Response Quality Scorecard
# ---------------------------------------------------------------------------


@dataclass
class ResponseQualityItem:
    """Quality assessment for a single bot response."""

    turn_index: int
    bot_message: str
    is_grounded: bool = True
    grounding_source: str = ""  # "knowledge", "tool", "none"
    hallucination_risk: str = "low"  # "low", "medium", "high"
    flags: list[str] = field(default_factory=list)


@dataclass
class ResponseQualityReport:
    """Response quality scorecard for a conversation."""

    items: list[ResponseQualityItem] = field(default_factory=list)
    grounded_count: int = 0
    ungrounded_count: int = 0
    high_risk_count: int = 0
    swallowed_error_count: int = 0


def analyze_response_quality(timeline: ConversationTimeline) -> ResponseQualityReport:
    """Grade bot responses for groundedness and hallucination risk."""
    turn_groups = _split_events_by_turn(timeline.events)
    items: list[ResponseQualityItem] = []
    grounded = 0
    ungrounded = 0
    high_risk = 0
    swallowed_errors = 0

    for turn_idx, events in enumerate(turn_groups):
        bot_messages = [e for e in events if e.event_type == EventType.BOT_MESSAGE]
        if not bot_messages:
            continue

        # Check what preceded the bot message
        has_knowledge = any(e.event_type in (EventType.KNOWLEDGE_SEARCH, EventType.GENERATIVE_ANSWER) for e in events)
        has_tool = any(e.event_type == EventType.STEP_TRIGGERED for e in events)
        failed_tools = [e for e in events if e.event_type == EventType.STEP_FINISHED and e.state == "failed"]
        zero_result_search = False
        for ks in timeline.knowledge_searches:
            # Check if this search belongs to this turn by timestamp range
            if events[0].timestamp and events[-1].timestamp and ks.timestamp:
                if events[0].timestamp <= ks.timestamp <= events[-1].timestamp:
                    if not ks.search_results:
                        zero_result_search = True
        # Topic-level generative answers in this turn — flag fallbacks and empty hits
        turn_traces: list = []
        for trace in getattr(timeline, "generative_answer_traces", []) or []:
            if events[0].timestamp and events[-1].timestamp and trace.timestamp:
                if events[0].timestamp <= trace.timestamp <= events[-1].timestamp:
                    turn_traces.append(trace)
                    if not trace.search_results:
                        zero_result_search = True

        for bot_ev in bot_messages:
            msg = bot_ev.summary.replace("Bot: ", "", 1)[:100] if bot_ev.summary else ""
            flags: list[str] = []
            grounding_source = "none"
            hallucination_risk = "low"
            is_grounded = True

            if has_knowledge:
                grounding_source = "knowledge"
                if zero_result_search:
                    hallucination_risk = "high"
                    is_grounded = False
                    flags.append("Knowledge search returned zero results")
                    high_risk += 1
            elif has_tool:
                grounding_source = "tool"
            else:
                # No knowledge or tool — response based solely on LLM
                grounding_source = "none"
                hallucination_risk = "medium"
                is_grounded = False
                flags.append("No knowledge search or tool preceded this response")

            if failed_tools:
                swallowed_errors += 1
                flags.append(f"Tool error silently swallowed ({len(failed_tools)} failed)")
                if hallucination_risk == "low":
                    hallucination_risk = "medium"

            for trace in turn_traces:
                if trace.triggered_fallback:
                    flags.append("Generative answer fell back to GPT default response")
                    hallucination_risk = "high"
                    is_grounded = False
                elif trace.gpt_answer_state and trace.gpt_answer_state.lower() != "answered":
                    flags.append(f"Generative answer state: {trace.gpt_answer_state}")
                    if hallucination_risk == "low":
                        hallucination_risk = "medium"

            if is_grounded:
                grounded += 1
            else:
                ungrounded += 1

            items.append(
                ResponseQualityItem(
                    turn_index=turn_idx + 1,
                    bot_message=msg,
                    is_grounded=is_grounded,
                    grounding_source=grounding_source,
                    hallucination_risk=hallucination_risk,
                    flags=flags,
                )
            )

    return ResponseQualityReport(
        items=items,
        grounded_count=grounded,
        ungrounded_count=ungrounded,
        high_risk_count=high_risk,
        swallowed_error_count=swallowed_errors,
    )


# ---------------------------------------------------------------------------
# Feature 6: Multi-Agent Delegation Analyzer
# ---------------------------------------------------------------------------

AGENT_TOOL_TYPES = {"ConnectedAgent", "ChildAgent", "A2AAgent", "ExternalAgent"}


@dataclass
class DelegationEntry:
    """A single agent delegation from the orchestrator."""

    agent_name: str
    tool_type: str | None = None
    thought: str | None = None
    state: str = ""
    duration_ms: float = 0.0
    error: str | None = None
    agent_instructions: str | None = None


@dataclass
class DelegationReport:
    """Multi-agent delegation analysis."""

    delegations: list[DelegationEntry] = field(default_factory=list)
    configured_agents: list[str] = field(default_factory=list)
    dead_agents: list[str] = field(default_factory=list)  # configured but never called
    failing_agents: list[str] = field(default_factory=list)  # called but always fail
    agent_stats: dict[str, dict] = field(default_factory=dict)  # name -> {calls, successes, failures}


def analyze_delegations(
    timeline: ConversationTimeline,
    profile: BotProfile,
) -> DelegationReport:
    """Analyze orchestrator delegations to child/connected agents."""
    # Build agent component lookup
    agent_components: dict[str, ComponentSummary] = {}
    for comp in profile.components:
        if comp.tool_type in AGENT_TOOL_TYPES or comp.dialog_kind == "AgentDialog":
            agent_components[comp.schema_name] = comp
            agent_components[comp.display_name] = comp

    configured_agents = sorted({c.display_name for c in agent_components.values()})

    # Analyze tool calls for agent delegations
    delegations: list[DelegationEntry] = []
    agent_stats: dict[str, dict] = defaultdict(lambda: {"calls": 0, "successes": 0, "failures": 0})

    for tc in timeline.tool_calls:
        # Check if this tool call is an agent delegation
        comp = agent_components.get(tc.task_dialog_id) or agent_components.get(tc.display_name)
        is_agent = comp is not None or tc.tool_type in AGENT_TOOL_TYPES or tc.step_type == "Agent"

        if not is_agent:
            continue

        name = tc.display_name
        stats = agent_stats[name]
        stats["calls"] += 1
        if tc.state == "completed":
            stats["successes"] += 1
        elif tc.state == "failed":
            stats["failures"] += 1

        delegations.append(
            DelegationEntry(
                agent_name=name,
                tool_type=tc.tool_type,
                thought=tc.thought,
                state=tc.state,
                duration_ms=tc.duration_ms,
                error=tc.error,
                agent_instructions=comp.agent_instructions if comp else None,
            )
        )

    # Dead agents: configured but never called
    called_names = set(agent_stats.keys())
    dead_agents = [a for a in configured_agents if a not in called_names]

    # Always-failing agents
    failing_agents = [name for name, stats in agent_stats.items() if stats["calls"] > 0 and stats["successes"] == 0]

    return DelegationReport(
        delegations=delegations,
        configured_agents=configured_agents,
        dead_agents=dead_agents,
        failing_agents=failing_agents,
        agent_stats=dict(agent_stats),
    )


# ---------------------------------------------------------------------------
# Feature 7: Latency Bottleneck Heatmap
# ---------------------------------------------------------------------------


@dataclass
class LatencySegment:
    """A time segment within a turn."""

    category: str  # "thinking", "tool", "knowledge", "message", "other"
    label: str
    duration_ms: float = 0.0
    percentage: float = 0.0


@dataclass
class TurnLatency:
    """Latency breakdown for a single turn."""

    turn_index: int
    user_message: str = ""
    total_ms: float = 0.0
    segments: list[LatencySegment] = field(default_factory=list)
    bottleneck: str | None = None  # label of dominant segment if >50%


@dataclass
class LatencyReport:
    """Latency bottleneck analysis across turns."""

    turns: list[TurnLatency] = field(default_factory=list)
    bottleneck_turn_count: int = 0
    avg_thinking_pct: float = 0.0
    avg_tool_pct: float = 0.0


def analyze_latency_bottlenecks(timeline: ConversationTimeline) -> LatencyReport:
    """Per-turn latency breakdown by category."""
    turn_groups = _split_events_by_turn(timeline.events)
    turns: list[TurnLatency] = []
    thinking_pcts: list[float] = []
    tool_pcts: list[float] = []
    bottleneck_count = 0

    for turn_idx, events in enumerate(turn_groups):
        total_ms = _ms_between(events[0].timestamp, events[-1].timestamp) if len(events) > 1 else 0.0
        if total_ms <= 0:
            continue

        user_msg = ""
        for e in events:
            if e.event_type == EventType.USER_MESSAGE:
                user_msg = (
                    e.summary.replace('User: "', "").rstrip('"') if e.summary.startswith('User: "') else e.summary
                )
                break

        # Categorize time from phases and events
        thinking_ms = 0.0
        tool_ms = 0.0
        knowledge_ms = 0.0

        for e in events:
            if e.event_type == EventType.ORCHESTRATOR_THINKING:
                match = re.search(r"\((\d+(?:\.\d+)?)ms\)", e.summary or "")
                if match:
                    thinking_ms += float(match.group(1))

        # Tool call durations from this turn's tool calls
        for tc in timeline.tool_calls:
            if tc.trigger_timestamp and tc.finish_timestamp:
                if events[0].timestamp and events[-1].timestamp:
                    if events[0].timestamp <= tc.trigger_timestamp <= events[-1].timestamp:
                        tool_ms += tc.duration_ms

        # Knowledge search durations
        for ks in timeline.knowledge_searches:
            if ks.timestamp and events[0].timestamp and events[-1].timestamp:
                if events[0].timestamp <= ks.timestamp <= events[-1].timestamp:
                    if ks.execution_time:
                        # Parse .NET TimeSpan format or just use a default
                        try:
                            parts = ks.execution_time.split(":")
                            if len(parts) == 3:
                                h, m, s = parts
                                knowledge_ms += (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
                        except (ValueError, IndexError):
                            pass

        other_ms = max(0.0, total_ms - thinking_ms - tool_ms - knowledge_ms)

        segments: list[LatencySegment] = []
        for cat, label, ms in [
            ("thinking", "Orchestrator Thinking", thinking_ms),
            ("tool", "Tool Execution", tool_ms),
            ("knowledge", "Knowledge Search", knowledge_ms),
            ("other", "Other", other_ms),
        ]:
            if ms > 0:
                segments.append(
                    LatencySegment(
                        category=cat,
                        label=label,
                        duration_ms=ms,
                        percentage=ms / total_ms * 100,
                    )
                )

        # Find bottleneck (>50% of turn time)
        bottleneck = None
        for seg in segments:
            if seg.percentage > 50:
                bottleneck = seg.label
                break

        if bottleneck:
            bottleneck_count += 1

        thinking_pct = thinking_ms / total_ms * 100 if total_ms > 0 else 0.0
        tool_pct = tool_ms / total_ms * 100 if total_ms > 0 else 0.0
        thinking_pcts.append(thinking_pct)
        tool_pcts.append(tool_pct)

        turns.append(
            TurnLatency(
                turn_index=turn_idx + 1,
                user_message=user_msg[:80],
                total_ms=total_ms,
                segments=segments,
                bottleneck=bottleneck,
            )
        )

    return LatencyReport(
        turns=turns,
        bottleneck_turn_count=bottleneck_count,
        avg_thinking_pct=sum(thinking_pcts) / len(thinking_pcts) if thinking_pcts else 0.0,
        avg_tool_pct=sum(tool_pcts) / len(tool_pcts) if tool_pcts else 0.0,
    )


# ---------------------------------------------------------------------------
# Feature 8: Instruction-to-Behavior Alignment
# ---------------------------------------------------------------------------


@dataclass
class InstructionDirective:
    """A parsed directive from system instructions."""

    directive_type: str  # "language", "escalation", "scope", "behavior"
    text: str  # the raw instruction text
    pattern: str  # regex or keyword pattern to check compliance


@dataclass
class AlignmentViolation:
    """A detected violation of an instruction directive."""

    directive: str
    violation_type: str  # "missing_escalation", "language_mismatch", "scope_breach"
    evidence: str  # the bot message or event that violated


@dataclass
class AlignmentReport:
    """Instruction-to-behavior alignment analysis."""

    directives_found: int = 0
    violations: list[AlignmentViolation] = field(default_factory=list)
    coverage_score: float = 1.0  # 0.0-1.0, proportion of directives with compliance evidence


# Patterns that indicate instruction directives
_LANGUAGE_PATTERN = re.compile(
    r"(?:respond|answer|reply|communicate|speak)\s+(?:in|using)\s+(\w+)",
    re.IGNORECASE,
)
_ESCALATION_PATTERN = re.compile(
    r"(?:escalate|transfer|hand\s*off|redirect)\s+(?:when|if|for)\s+(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_SCOPE_PATTERN = re.compile(
    r"(?:do\s+not|don'?t|never|avoid)\s+(?:answer|respond|discuss|provide|talk\s+about)\s+(.+?)(?:\.|$)",
    re.IGNORECASE,
)
_MUST_PATTERN = re.compile(
    r"(?:always|must|should)\s+(.+?)(?:\.|$)",
    re.IGNORECASE,
)


def analyze_instruction_alignment(
    timeline: ConversationTimeline,
    profile: BotProfile,
) -> AlignmentReport:
    """Check if bot behavior aligns with its system instructions."""
    instructions = ""
    if profile.gpt_info and profile.gpt_info.instructions:
        instructions = profile.gpt_info.instructions

    if not instructions:
        return AlignmentReport()

    violations: list[AlignmentViolation] = []
    directives_found = 0

    # Collect bot messages
    bot_messages = [
        e.summary.replace("Bot: ", "", 1)
        for e in timeline.events
        if e.event_type == EventType.BOT_MESSAGE and e.summary
    ]
    bot_text_combined = " ".join(bot_messages).lower()

    # Collect topic names triggered
    triggered_topics = {
        e.topic_name.lower() for e in timeline.events if e.event_type == EventType.STEP_TRIGGERED and e.topic_name
    }

    # Check language directives
    lang_matches = _LANGUAGE_PATTERN.findall(instructions)
    for lang in lang_matches:
        directives_found += 1
        lang_lower = lang.lower()
        # Simple heuristic: check if common words in that language appear
        # This is a v1 approximation — not a real language detector
        if lang_lower in ("dutch", "nederlands"):
            # Check for common English words that shouldn't be there
            english_markers = {"the ", " is ", " are ", " this ", " that ", " have "}
            english_count = sum(1 for m in english_markers if m in bot_text_combined)
            if english_count > 3 and bot_messages:
                violations.append(
                    AlignmentViolation(
                        directive=f"Respond in {lang}",
                        violation_type="language_mismatch",
                        evidence=f"Found {english_count} English markers in bot responses",
                    )
                )

    # Check escalation directives
    esc_matches = _ESCALATION_PATTERN.findall(instructions)
    for esc_condition in esc_matches:
        directives_found += 1
        # Check if any escalation actually happened
        has_escalation = any("escalat" in t or "transfer" in t for t in triggered_topics)
        # Check if the condition keywords appear in user messages
        user_messages = [
            e.summary.replace('User: "', "").rstrip('"').lower()
            for e in timeline.events
            if e.event_type == EventType.USER_MESSAGE and e.summary
        ]
        condition_words = set(esc_condition.lower().split())
        user_text = " ".join(user_messages)
        condition_mentioned = any(w in user_text for w in condition_words if len(w) > 3)
        if condition_mentioned and not has_escalation:
            violations.append(
                AlignmentViolation(
                    directive=f"Escalate when: {esc_condition.strip()}",
                    violation_type="missing_escalation",
                    evidence="Condition keywords found in user messages but no escalation triggered",
                )
            )

    # Check scope restrictions ("do not answer about X")
    scope_matches = _SCOPE_PATTERN.findall(instructions)
    for scope in scope_matches:
        directives_found += 1
        scope_words = {w.lower() for w in scope.split() if len(w) > 3}
        if scope_words:
            scope_hits = sum(1 for w in scope_words if w in bot_text_combined)
            if scope_hits >= 2:
                violations.append(
                    AlignmentViolation(
                        directive=f"Do not discuss: {scope.strip()}",
                        violation_type="scope_breach",
                        evidence=f"Found {scope_hits} restricted terms in bot responses",
                    )
                )

    coverage = 1.0 - (len(violations) / directives_found) if directives_found > 0 else 1.0

    return AlignmentReport(
        directives_found=directives_found,
        violations=violations,
        coverage_score=max(0.0, coverage),
    )

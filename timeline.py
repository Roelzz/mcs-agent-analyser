import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from models import (
    BotProfile,
    ConversationTimeline,
    CreditEstimate,
    CreditLineItem,
    CustomSearchStep,
    EventType,
    ExecutionPhase,
    KnowledgeSearchInfo,
    SearchResult,
    TimelineEvent,
)


@dataclass
class _TimelineState:
    """Mutable accumulator for build_timeline processing."""

    events: list[TimelineEvent] = field(default_factory=list)
    phases: list[ExecutionPhase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    knowledge_searches: list[KnowledgeSearchInfo] = field(default_factory=list)
    custom_search_steps: list[CustomSearchStep] = field(default_factory=list)
    pending_ks_query: dict | None = None
    pending_ks_info: KnowledgeSearchInfo | None = None
    pending_ks_thought: str | None = None
    pending_ks_execution_time: str | None = None
    pending_ks_results: list[SearchResult] = field(default_factory=list)
    pending_ks_errors: list[str] = field(default_factory=list)
    bot_name: str = ""
    conversation_id: str = ""
    user_query: str = ""
    latest_user_text: str | None = None
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    step_triggers: dict[str, str] = field(default_factory=dict)
    tool_display_names: dict[str, str] = field(default_factory=dict)
    pending_custom_searches: dict[str, CustomSearchStep] = field(default_factory=dict)


def _parse_timestamp(ts: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts:
        return None
    try:
        # Handle .NET-style timestamps with 7 fractional digits
        ts = ts.rstrip("Z").rstrip("+00:00")
        if "+" in ts and ts.count("+") > 0:
            # Has timezone offset like +00:00
            parts = ts.rsplit("+", 1)
            ts_part = parts[0]
        else:
            ts_part = ts

        # Truncate fractional seconds to 6 digits (Python max)
        if "." in ts_part:
            main, frac = ts_part.split(".", 1)
            frac = frac[:6]
            ts_part = f"{main}.{frac}"

        return datetime.fromisoformat(ts_part).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _epoch_to_iso(epoch_ms: int | float | None) -> str | None:
    """Convert epoch milliseconds to ISO string."""
    if epoch_ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _get_timestamp(activity: dict) -> str | None:
    """Get best available timestamp from activity."""
    ts = activity.get("timestamp")
    if ts:
        return ts
    channel_data = activity.get("channelData", {}) or {}
    received_at = channel_data.get("webchat:internal:received-at")
    if received_at:
        return _epoch_to_iso(received_at)
    return None


def _extract_adaptive_card_text(attachments: list) -> str:
    """Extract readable text from Adaptive Card attachments."""
    texts: list[str] = []

    def _extract_from_elements(elements: list) -> None:
        for el in elements:
            if len(texts) >= 2:
                return
            if el.get("type") == "TextBlock" and el.get("text"):
                texts.append(el["text"])
            # Recurse into containers and column sets
            for child_key in ("items", "columns", "body"):
                children = el.get(child_key, []) or []
                if children:
                    _extract_from_elements(children)

    for att in attachments:
        if len(texts) >= 2:
            break
        content = att.get("content", {}) or {}
        body = content.get("body", []) or []
        _extract_from_elements(body)

    if texts:
        combined = " | ".join(texts)
        return combined[:150] + "..." if len(combined) > 150 else combined
    return "[Adaptive Card]"


def _ms_between(start: str | None, end: str | None) -> float:
    """Calculate milliseconds between two ISO timestamps."""
    dt_start = _parse_timestamp(start)
    dt_end = _parse_timestamp(end)
    if dt_start and dt_end:
        return (dt_end - dt_start).total_seconds() * 1000
    return 0.0


def _finalize_knowledge_search(state: _TimelineState) -> None:
    """Flush pending knowledge search state into a KnowledgeSearchInfo and append it."""
    if state.pending_ks_info:
        if state.pending_ks_execution_time is not None:
            state.pending_ks_info.execution_time = state.pending_ks_execution_time
            state.pending_ks_info.search_results = state.pending_ks_results
            state.pending_ks_info.search_errors = state.pending_ks_errors
        state.knowledge_searches.append(state.pending_ks_info)
        state.pending_ks_info = None
        state.pending_ks_execution_time = None
        state.pending_ks_results = []
        state.pending_ks_errors = []


def _build_phase(
    topic: str,
    value: dict,
    trigger_ts: str | None,
    end_ts: str | None,
    duration_ms: float,
    state_str: str,
) -> ExecutionPhase:
    """Construct an ExecutionPhase from step trigger/finish data."""
    return ExecutionPhase(
        label=topic,
        phase_type=value.get("type", "") if "type" in value else "",
        start=trigger_ts,
        end=end_ts,
        duration_ms=duration_ms,
        state=state_str,
    )


def _process_trace_event(
    activity: dict,
    state: _TimelineState,
    schema_lookup: dict[str, str],
    timestamp: str | None,
    position: int,
) -> None:
    """Process a single event or trace activity, updating state in place."""
    act_type = activity.get("type", "")
    value_type = activity.get("valueType", "") or activity.get("name", "")
    value = activity.get("value", {}) or {}

    if act_type == "event":
        if value_type == "DynamicPlanReceived":
            steps = value.get("steps", [])
            step_names = []
            for s in steps:
                from parser import resolve_topic_name

                step_names.append(resolve_topic_name(s, schema_lookup))
            tools_summary = ", ".join(step_names) if step_names else "unknown"
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.PLAN_RECEIVED,
                    summary=f"Plan: [{tools_summary}]",
                    plan_identifier=value.get("planIdentifier"),
                )
            )
            for td in value.get("toolDefinitions", []):
                schema = td.get("schemaName", "")
                display = td.get("displayName", "")
                if schema and display:
                    state.tool_display_names[schema] = display

        elif value_type == "DynamicPlanReceivedDebug":
            ask = value.get("ask", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.PLAN_RECEIVED_DEBUG,
                    summary=f'Ask: "{ask}"',
                    plan_identifier=value.get("planIdentifier"),
                )
            )

        elif value_type == "DynamicPlanStepTriggered":
            task_dialog_id = value.get("taskDialogId", "")
            from parser import resolve_topic_name

            topic = resolve_topic_name(task_dialog_id, schema_lookup)
            step_type = value.get("type", "")
            step_id = value.get("stepId", "")

            if step_id and timestamp:
                state.step_triggers[step_id] = timestamp

            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.STEP_TRIGGERED,
                    topic_name=topic,
                    summary=f"Step start: {topic} ({step_type})",
                    state="inProgress",
                    step_id=step_id,
                    plan_identifier=value.get("planIdentifier"),
                    thought=value.get("thought"),
                )
            )

            if task_dialog_id == "P:UniversalSearchTool":
                state.pending_ks_thought = value.get("thought")

            if value.get("type") == "CustomTopic" and "search" in task_dialog_id.lower():
                state.pending_custom_searches[task_dialog_id] = CustomSearchStep(
                    task_dialog_id=task_dialog_id,
                    display_name=state.tool_display_names.get(task_dialog_id, task_dialog_id.split(".")[-1]),
                    thought=value.get("thought"),
                    status="inProgress",
                )

        elif value_type == "DynamicPlanStepFinished":
            task_dialog_id = value.get("taskDialogId", "")
            if task_dialog_id == "P:UniversalSearchTool":
                observation = value.get("observation") or {}
                sr = observation.get("search_result") or {}
                raw_results = sr.get("search_results") or []
                step_results = [
                    SearchResult(
                        name=r.get("Name"),
                        url=r.get("Url"),
                        text=r.get("Text"),
                        file_type=r.get("FileType"),
                        result_type=r.get("Type"),
                    )
                    for r in raw_results[:10]
                ]
                step_errors = list(sr.get("search_errors") or [])
                if state.pending_ks_info:
                    state.pending_ks_info.execution_time = value.get("executionTime")
                    state.pending_ks_info.search_results = step_results
                    state.pending_ks_info.search_errors = step_errors
                    state.knowledge_searches.append(state.pending_ks_info)
                    state.pending_ks_info = None
                    state.pending_ks_execution_time = None
                    state.pending_ks_results = []
                    state.pending_ks_errors = []
                else:
                    state.pending_ks_execution_time = value.get("executionTime")
                    state.pending_ks_results = step_results
                    state.pending_ks_errors = step_errors

            if task_dialog_id in state.pending_custom_searches:
                step = state.pending_custom_searches.pop(task_dialog_id)
                step.status = value.get("state", "unknown")
                err = value.get("error")
                if err:
                    step.error = err.get("message") if isinstance(err, dict) else str(err)
                step.execution_time = value.get("executionTime")
                state.custom_search_steps.append(step)

            from parser import resolve_topic_name

            topic = resolve_topic_name(task_dialog_id, schema_lookup)
            step_state = value.get("state", "")
            step_id = value.get("stepId", "")
            error = value.get("error")

            duration_ms = 0.0
            trigger_ts = state.step_triggers.get(step_id)
            if trigger_ts and timestamp:
                duration_ms = _ms_between(trigger_ts, timestamp)

            error_msg = None
            if error and isinstance(error, dict):
                error_msg = error.get("message", str(error))
                state.errors.append(f"{topic}: {error_msg}")
            elif step_state == "failed":
                error_msg = "Step failed"
                state.errors.append(f"{topic}: failed")

            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.STEP_FINISHED,
                    topic_name=topic,
                    summary=f"Step end: {topic} [{step_state}]"
                    + (f" ({duration_ms:.0f}ms)" if duration_ms > 0 else ""),
                    state=step_state,
                    error=error_msg,
                    step_id=step_id,
                    plan_identifier=value.get("planIdentifier"),
                )
            )

            state.phases.append(_build_phase(topic, value, trigger_ts, timestamp, duration_ms, step_state))

        elif value_type == "DynamicPlanFinished":
            was_cancelled = value.get("wasCancelled", False)
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.PLAN_FINISHED,
                    summary=f"Plan finished (cancelled={was_cancelled})",
                    plan_identifier=value.get("planId"),
                )
            )

        elif value_type == "DialogTracingInfo":
            ACTION_TYPE_MAP = {
                "HttpRequestAction": EventType.ACTION_HTTP_REQUEST,
                "InvokeFlowAction": EventType.ACTION_HTTP_REQUEST,
                "BeginDialog": EventType.ACTION_BEGIN_DIALOG,
                "SendActivity": EventType.ACTION_SEND_ACTIVITY,
                "ConditionGroup": EventType.ACTION_TRIGGER_EVAL,
                "ConditionItem": EventType.ACTION_TRIGGER_EVAL,
            }

            SUMMARY_TEMPLATES = {
                EventType.ACTION_HTTP_REQUEST: "HTTP call in {topic}",
                EventType.ACTION_QA: "QA in {topic}",
                EventType.ACTION_TRIGGER_EVAL: "Evaluate: {topic}",
                EventType.ACTION_BEGIN_DIALOG: "Call to {topic}",
                EventType.ACTION_SEND_ACTIVITY: "Send response in {topic}",
            }

            actions = value.get("actions", [])
            for action in actions:
                topic_id = action.get("topicId", "")
                action_type = action.get("actionType", "")
                exception = action.get("exception", "")
                from parser import resolve_topic_name

                topic = resolve_topic_name(topic_id, schema_lookup)

                if exception:
                    state.errors.append(f"{topic}.{action_type}: {exception}")

                event_type = ACTION_TYPE_MAP.get(action_type, EventType.DIALOG_TRACING)
                template = SUMMARY_TEMPLATES.get(event_type)
                if template:
                    summary = template.format(topic=topic)
                else:
                    summary = f"{action_type} in {topic}"

                state.events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=event_type,
                        topic_name=topic,
                        summary=summary,
                    )
                )

        elif value_type == "DynamicPlanStepBindUpdate" and value.get("taskDialogId") == "P:UniversalSearchTool":
            state.pending_ks_query = {
                "search_query": value.get("arguments", {}).get("search_query"),
                "search_keywords": value.get("arguments", {}).get("search_keywords"),
            }

        elif value_type == "UniversalSearchToolTraceData":
            sources = value.get("knowledgeSources", [])
            source_names = [s.split(".")[-1] if "." in s else s for s in sources]
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.KNOWLEDGE_SEARCH,
                    summary=f"Knowledge search: [{', '.join(source_names[:3])}]"
                    + (f" (+{len(source_names) - 3})" if len(source_names) > 3 else ""),
                )
            )

            def _clean_source(s: str) -> str:
                """Clean a raw knowledge source identifier to a display name."""
                if ".file." in s:
                    filename_with_id = s.split(".file.", 1)[1]
                    return re.sub(r"_[A-Za-z0-9]{3,}$", "", filename_with_id)
                base = re.sub(r"_[A-Za-z0-9]{3,}$", "", s)
                return base.split(".")[-1]

            cleaned = [_clean_source(s) for s in sources]
            deduped = list(dict.fromkeys(cleaned))
            output_sources = value.get("outputKnowledgeSources", [])
            output_cleaned = [_clean_source(s) for s in output_sources]
            output_deduped = list(dict.fromkeys(output_cleaned))
            state.pending_ks_info = KnowledgeSearchInfo(
                position=position,
                timestamp=timestamp,
                knowledge_sources=deduped,
                thought=state.pending_ks_thought,
                output_knowledge_sources=output_deduped,
                triggering_user_message=state.latest_user_text,
                **(state.pending_ks_query or {}),
            )
            state.pending_ks_query = None
            state.pending_ks_thought = None
            # If DynamicPlanStepFinished already arrived (inverted order), commit now
            if state.pending_ks_execution_time is not None:
                state.pending_ks_info.execution_time = state.pending_ks_execution_time
                state.pending_ks_info.search_results = state.pending_ks_results
                state.pending_ks_info.search_errors = state.pending_ks_errors
                state.knowledge_searches.append(state.pending_ks_info)
                state.pending_ks_info = None
                state.pending_ks_execution_time = None
                state.pending_ks_results = []
                state.pending_ks_errors = []

        elif value_type == "ErrorCode":
            error_code = value.get("ErrorCode", "Unknown")
            state.errors.append(f"ErrorCode: {error_code}")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.ERROR,
                    summary=f"Error: {error_code}",
                    error=error_code,
                )
            )

    elif act_type == "trace":
        if value_type == "VariableAssignment":
            var_id = value.get("id", "")
            new_value = str(value.get("newValue", ""))[:80]
            scope = value.get("type", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.VARIABLE_ASSIGNMENT,
                    summary=f"{scope.title()} {var_id} = {new_value}",
                )
            )

        elif value_type == "DialogRedirect":
            target_id = value.get("targetDialogId", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.DIALOG_REDIRECT,
                    summary=f"Redirect → {target_id[:40]}",
                )
            )

        elif value.get("ErrorCode"):
            error_code = value["ErrorCode"]
            state.errors.append(f"ErrorCode: {error_code}")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.ERROR,
                    summary=f"Error: {error_code}",
                    error=error_code,
                )
            )


def build_timeline(activities: list[dict], schema_lookup: dict[str, str]) -> ConversationTimeline:
    """Build a ConversationTimeline from sorted activities and schema name lookup."""
    state = _TimelineState()

    for activity in activities:
        act_type = activity.get("type", "")
        from_info = activity.get("from", {}) or {}
        role = from_info.get("role", "")
        timestamp = _get_timestamp(activity)
        channel_data = activity.get("channelData", {}) or {}
        position = channel_data.get("webchat:internal:position", 0)

        # Track bot name and conversation id
        if not state.bot_name and from_info.get("name"):
            if role == "bot":
                state.bot_name = from_info["name"]
        conv = activity.get("conversation", {}) or {}
        if not state.conversation_id and conv.get("id"):
            state.conversation_id = conv["id"]

        # Track time range
        if timestamp:
            if not state.first_timestamp:
                state.first_timestamp = timestamp
            state.last_timestamp = timestamp

        # Skip typing indicators and streaming
        if act_type == "typing":
            continue

        # User message
        if act_type == "message" and role == "user":
            text = activity.get("text", "")
            if text:
                state.latest_user_text = text
            if not state.user_query and text:
                state.user_query = text
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.USER_MESSAGE,
                    summary=f'User: "{text}"' if text else "User message",
                )
            )
            continue

        # Bot message
        if act_type == "message" and role == "bot":
            text = activity.get("text", "")
            # Check for attachments (adaptive cards)
            attachments = activity.get("attachments", []) or []
            if not text and attachments:
                text = _extract_adaptive_card_text(attachments)
            clean_text = text.replace("\n", " ").replace("\r", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.BOT_MESSAGE,
                    summary=f"Bot: {clean_text}" if clean_text else "Bot message",
                )
            )
            continue

        # Delegate event and trace activity types to helper
        if act_type in ("event", "trace"):
            _process_trace_event(activity, state, schema_lookup, timestamp, position)

    _finalize_knowledge_search(state)

    total_elapsed = _ms_between(state.first_timestamp, state.last_timestamp)

    return ConversationTimeline(
        bot_name=state.bot_name,
        conversation_id=state.conversation_id,
        user_query=state.user_query,
        events=state.events,
        phases=state.phases,
        errors=state.errors,
        total_elapsed_ms=total_elapsed,
        knowledge_searches=state.knowledge_searches,
        custom_search_steps=state.custom_search_steps,
    )


# --- Credit rate constants ---

CREDIT_CLASSIC_ANSWER = 1
CREDIT_GENERATIVE_ANSWER = 2
CREDIT_AGENT_ACTION = 5
CREDIT_TENANT_GRAPH = 10
CREDIT_FLOW_ACTIONS_PER_100 = 13

# Tool types that are agent actions (5 credits each)
AGENT_ACTION_TOOL_TYPES = {
    "ConnectorTool",
    "ConnectedAgent",
    "ChildAgent",
    "A2AAgent",
    "MCPServer",
    "ExternalAgent",
    "CUATool",
    "FlowTool",
}


def _build_tool_type_lookup(profile: BotProfile) -> dict[str, str]:
    """Build taskDialogId -> tool_type lookup from profile components."""
    lookup: dict[str, str] = {}
    for comp in profile.components:
        if comp.tool_type and comp.schema_name:
            lookup[comp.schema_name] = comp.tool_type
    return lookup


def estimate_credits(timeline: ConversationTimeline, profile: BotProfile) -> CreditEstimate:
    """Estimate MCS credit consumption from timeline events.

    Walks events in order, classifying each billable step:
    - KnowledgeSource / P:UniversalSearchTool → 2 credits (generative answer)
    - Agent/tool steps (ConnectedAgent, ChildAgent, etc.) → 5 credits (agent action)
    - CustomTopic under generative orchestration → 5 credits (agent action / topic transition)
    - CustomTopic under classic recognizer → 1 credit (classic answer)
    - HTTP/connector calls not inside already-counted steps → 5 credits (agent action)
    """
    line_items: list[CreditLineItem] = []
    warnings: list[str] = []
    tool_type_lookup = _build_tool_type_lookup(profile)
    is_generative = profile.recognizer_kind == "GenerativeAIRecognizer"

    # Track which positions have been billed via STEP_TRIGGERED to avoid double-counting
    billed_step_positions: set[int] = set()
    # Track active step context (position range where HTTP calls are already covered)
    active_step_topics: set[str] = set()

    for event in timeline.events:
        if event.event_type == EventType.STEP_TRIGGERED:
            summary = event.summary or ""
            topic = event.topic_name or ""
            position = event.position

            # Extract step type from summary: "Step start: TopicName (StepType)"
            step_type_raw = ""
            if "(" in summary and summary.endswith(")"):
                step_type_raw = summary.rsplit("(", 1)[-1].rstrip(")")

            # Check taskDialogId pattern via topic name matching against tool_type_lookup
            resolved_tool_type = None
            for schema, tt in tool_type_lookup.items():
                if topic in schema or schema.endswith(f".{topic}") or topic == schema:
                    resolved_tool_type = tt
                    break

            # Classify the step
            if "P:UniversalSearchTool" in summary or "KnowledgeSource" in step_type_raw:
                line_items.append(
                    CreditLineItem(
                        step_name=f"Knowledge Search: {topic}",
                        step_type="generative_answer",
                        credits=CREDIT_GENERATIVE_ANSWER,
                        detail=f"KnowledgeSource via {topic}",
                        position=position,
                    )
                )
            elif step_type_raw == "Agent" or resolved_tool_type in AGENT_ACTION_TOOL_TYPES:
                tool_label = resolved_tool_type or "Agent"
                line_items.append(
                    CreditLineItem(
                        step_name=topic,
                        step_type="agent_action",
                        credits=CREDIT_AGENT_ACTION,
                        detail=f"{tool_label} tool",
                        position=position,
                    )
                )
            elif step_type_raw == "CustomTopic":
                if is_generative:
                    line_items.append(
                        CreditLineItem(
                            step_name=topic,
                            step_type="agent_action",
                            credits=CREDIT_AGENT_ACTION,
                            detail="Topic transition (generative orchestration)",
                            position=position,
                        )
                    )
                else:
                    line_items.append(
                        CreditLineItem(
                            step_name=topic,
                            step_type="classic_answer",
                            credits=CREDIT_CLASSIC_ANSWER,
                            detail="Classic topic execution",
                            position=position,
                        )
                    )
            else:
                # Unknown step type — still count as agent action if under generative orchestration
                if is_generative:
                    line_items.append(
                        CreditLineItem(
                            step_name=topic or "Unknown step",
                            step_type="agent_action",
                            credits=CREDIT_AGENT_ACTION,
                            detail=f"Orchestrator step ({step_type_raw or 'unknown'})",
                            position=position,
                        )
                    )

            billed_step_positions.add(position)
            active_step_topics.add(topic)

        elif event.event_type == EventType.STEP_FINISHED:
            topic = event.topic_name or ""
            active_step_topics.discard(topic)

        elif event.event_type == EventType.ACTION_HTTP_REQUEST:
            # Only bill if not already inside a counted step
            if event.position not in billed_step_positions and not active_step_topics:
                topic = event.topic_name or "HTTP call"
                line_items.append(
                    CreditLineItem(
                        step_name=f"HTTP: {topic}",
                        step_type="agent_action",
                        credits=CREDIT_AGENT_ACTION,
                        detail="Connector/HTTP action",
                        position=event.position,
                    )
                )

        elif event.event_type == EventType.ACTION_BEGIN_DIALOG:
            # Topic transition outside of an active step — agent action under generative orchestration
            if is_generative and not active_step_topics and event.position not in billed_step_positions:
                topic = event.topic_name or "Dialog"
                line_items.append(
                    CreditLineItem(
                        step_name=f"Topic transition: {topic}",
                        step_type="agent_action",
                        credits=CREDIT_AGENT_ACTION,
                        detail="BeginDialog (generative orchestration)",
                        position=event.position,
                    )
                )

    # Add standard warnings
    warnings.append("Cannot detect tenant graph grounding (10 credits) — not in transcript data")
    warnings.append("Cannot detect AI tool tier (basic/standard/premium) — no token counts in transcript")
    warnings.append("Cannot distinguish reasoning model surcharge — no model identifier in trace")
    if is_generative:
        warnings.append("CustomTopic steps counted as agent actions (5 credits) under generative orchestration")

    total_credits = sum(item.credits for item in line_items)

    return CreditEstimate(
        line_items=line_items,
        total_credits=total_credits,
        warnings=warnings,
    )

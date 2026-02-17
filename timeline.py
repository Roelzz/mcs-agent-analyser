from datetime import datetime, timezone

from models import ConversationTimeline, EventType, ExecutionPhase, TimelineEvent


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


def build_timeline(activities: list[dict], schema_lookup: dict[str, str]) -> ConversationTimeline:
    """Build a ConversationTimeline from sorted activities and schema name lookup."""
    events: list[TimelineEvent] = []
    phases: list[ExecutionPhase] = []
    errors: list[str] = []
    bot_name = ""
    conversation_id = ""
    user_query = ""
    first_timestamp: str | None = None
    last_timestamp: str | None = None

    # Track step triggers for duration calculation
    step_triggers: dict[str, str] = {}  # step_id -> trigger timestamp

    for activity in activities:
        act_type = activity.get("type", "")
        value_type = activity.get("valueType", "") or activity.get("name", "")
        from_info = activity.get("from", {}) or {}
        role = from_info.get("role", "")
        timestamp = _get_timestamp(activity)
        channel_data = activity.get("channelData", {}) or {}
        position = channel_data.get("webchat:internal:position", 0)

        # Track bot name and conversation id
        if not bot_name and from_info.get("name"):
            if role == "bot":
                bot_name = from_info["name"]
        conv = activity.get("conversation", {}) or {}
        if not conversation_id and conv.get("id"):
            conversation_id = conv["id"]

        # Track time range
        if timestamp:
            if not first_timestamp:
                first_timestamp = timestamp
            last_timestamp = timestamp

        # Skip typing indicators and streaming
        if act_type == "typing":
            continue

        # User message
        if act_type == "message" and role == "user":
            text = activity.get("text", "")
            if not user_query and text:
                user_query = text
            events.append(
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
            summary = clean_text[:120] + "..." if len(clean_text) > 120 else clean_text
            events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.BOT_MESSAGE,
                    summary=f"Bot: {summary}" if summary else "Bot message",
                )
            )
            continue

        # Event types
        if act_type == "event":
            value = activity.get("value", {}) or {}

            if value_type == "DynamicPlanReceived":
                steps = value.get("steps", [])
                step_names = []
                for s in steps:
                    from parser import resolve_topic_name

                    step_names.append(resolve_topic_name(s, schema_lookup))
                tools_summary = ", ".join(step_names) if step_names else "unknown"
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.PLAN_RECEIVED,
                        summary=f"Plan: [{tools_summary}]",
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

            elif value_type == "DynamicPlanReceivedDebug":
                ask = value.get("ask", "")
                events.append(
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
                    step_triggers[step_id] = timestamp

                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.STEP_TRIGGERED,
                        topic_name=topic,
                        summary=f"Step start: {topic} ({step_type})",
                        state="inProgress",
                        step_id=step_id,
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

            elif value_type == "DynamicPlanStepFinished":
                task_dialog_id = value.get("taskDialogId", "")
                from parser import resolve_topic_name

                topic = resolve_topic_name(task_dialog_id, schema_lookup)
                state = value.get("state", "")
                step_id = value.get("stepId", "")
                error = value.get("error")

                # Calculate duration from trigger timestamp
                duration_ms = 0.0
                trigger_ts = step_triggers.get(step_id)
                if trigger_ts and timestamp:
                    duration_ms = _ms_between(trigger_ts, timestamp)

                error_msg = None
                if error and isinstance(error, dict):
                    error_msg = error.get("message", str(error))
                    errors.append(f"{topic}: {error_msg}")
                elif state == "failed":
                    error_msg = "Step failed"
                    errors.append(f"{topic}: failed")

                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.STEP_FINISHED,
                        topic_name=topic,
                        summary=f"Step end: {topic} [{state}]" + (f" ({duration_ms:.0f}ms)" if duration_ms > 0 else ""),
                        state=state,
                        error=error_msg,
                        step_id=step_id,
                        plan_identifier=value.get("planIdentifier"),
                    )
                )

                phases.append(
                    ExecutionPhase(
                        label=topic,
                        phase_type=value.get("type", "") if "type" in value else "",
                        start=trigger_ts,
                        end=timestamp,
                        duration_ms=duration_ms,
                        state=state,
                    )
                )

            elif value_type == "DynamicPlanFinished":
                was_cancelled = value.get("wasCancelled", False)
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.PLAN_FINISHED,
                        summary=f"Plan finished (cancelled={was_cancelled})",
                        plan_identifier=value.get("planId"),
                    )
                )

            elif value_type == "DialogTracingInfo":
                actions = value.get("actions", [])
                for action in actions:
                    topic_id = action.get("topicId", "")
                    action_type = action.get("actionType", "")
                    exception = action.get("exception", "")
                    from parser import resolve_topic_name

                    topic = resolve_topic_name(topic_id, schema_lookup)

                    if exception:
                        errors.append(f"{topic}.{action_type}: {exception}")

                action_types = [a.get("actionType", "") for a in actions]
                topics_involved = set()
                for a in actions:
                    tid = a.get("topicId", "")
                    if tid:
                        from parser import resolve_topic_name

                        topics_involved.add(resolve_topic_name(tid, schema_lookup))

                summary = f"Actions: {', '.join(action_types[:4])}"
                if len(action_types) > 4:
                    summary += f" (+{len(action_types) - 4} more)"
                if topics_involved:
                    summary += f" in {', '.join(sorted(topics_involved))}"

                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.DIALOG_TRACING,
                        summary=summary,
                    )
                )

            elif value_type == "UniversalSearchToolTraceData":
                sources = value.get("knowledgeSources", [])
                source_names = [s.split(".")[-1] if "." in s else s for s in sources]
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.KNOWLEDGE_SEARCH,
                        summary=f"Knowledge search: [{', '.join(source_names[:3])}]"
                        + (f" (+{len(source_names) - 3})" if len(source_names) > 3 else ""),
                    )
                )

            elif value_type == "ErrorCode":
                error_code = value.get("ErrorCode", "Unknown")
                errors.append(f"ErrorCode: {error_code}")
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.ERROR,
                        summary=f"Error: {error_code}",
                        error=error_code,
                    )
                )

        # Trace type
        if act_type == "trace":
            value = activity.get("value", {}) or {}

            if value_type == "VariableAssignment":
                var_id = value.get("id", "")
                new_value = str(value.get("newValue", ""))[:80]
                scope = value.get("type", "")
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.VARIABLE_ASSIGNMENT,
                        summary=f"{scope.title()} {var_id} = {new_value}",
                    )
                )

            elif value_type == "DialogRedirect":
                target_id = value.get("targetDialogId", "")
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.DIALOG_REDIRECT,
                        summary=f"Redirect → {target_id[:40]}",
                    )
                )

            elif value.get("ErrorCode"):
                error_code = value["ErrorCode"]
                errors.append(f"ErrorCode: {error_code}")
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=EventType.ERROR,
                        summary=f"Error: {error_code}",
                        error=error_code,
                    )
                )

    total_elapsed = _ms_between(first_timestamp, last_timestamp)

    return ConversationTimeline(
        bot_name=bot_name,
        conversation_id=conversation_id,
        user_query=user_query,
        events=events,
        phases=phases,
        errors=errors,
        total_elapsed_ms=total_elapsed,
    )

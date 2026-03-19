from models import (
    ConversationTimeline,
    EventType,
    TimelineEvent,
)

from ._helpers import (
    ACTOR_NAMES,
    IDLE_THRESHOLD_MS,
    _format_duration,
    _is_genuine_idle,
    _make_participant_id,
    _parse_timestamp_to_epoch_ms,
    _pct,
    _sanitize_mermaid,
    _topic_display,
)


def render_timeline(timeline: ConversationTimeline, *, skip_diagrams: bool = False) -> str:
    """Render conversation trace section as Markdown."""
    if not timeline.events:
        return "## Conversation Trace\n\nNo dialog events recorded.\n"

    lines = [
        "## Conversation Trace\n",
        "| Property | Value |",
        "| --- | --- |",
        f"| Bot Name | {timeline.bot_name} |",
        f"| Conversation ID | `{timeline.conversation_id}` |",
        f"| User Query | {timeline.user_query or 'N/A'} |",
        f"| Total Elapsed | {_format_duration(timeline.total_elapsed_ms)} |",
        "",
    ]

    if not skip_diagrams:
        # Mermaid sequence diagram
        if timeline.phases or any(
            e.event_type in (EventType.STEP_TRIGGERED, EventType.USER_MESSAGE) for e in timeline.events
        ):
            lines.append(render_mermaid_sequence(timeline))

        # Gantt chart
        gantt = render_gantt_chart(timeline)
        if gantt:
            lines.append(gantt)

    # Phase breakdown
    if timeline.phases:
        lines.append(render_phase_breakdown(timeline))

    # Event log
    lines.append(render_event_log(timeline))

    # Errors
    if timeline.errors:
        lines.append(render_errors(timeline))

    return "\n".join(lines)


def render_mermaid_sequence(timeline: ConversationTimeline) -> str:
    """Generate Mermaid sequence diagram."""
    lines = ["### Execution Flow\n", "```mermaid", "sequenceDiagram"]

    # Track which step IDs are KnowledgeSource type (first pass)
    ks_step_ids: set[str] = set()
    ks_topics: set[str] = set()
    has_ks = False
    for event in timeline.events:
        if event.event_type == EventType.KNOWLEDGE_SEARCH:
            has_ks = True
        if event.event_type == EventType.STEP_TRIGGERED and "KnowledgeSource" in event.summary:
            if event.step_id:
                ks_step_ids.add(event.step_id)
            if event.topic_name:
                ks_topics.add(event.topic_name)
            has_ks = True

    # Collect unique participants from phases and events
    participants: dict[str, str] = {}  # id -> display name
    participants["User"] = ACTOR_NAMES["User"]
    participants["AI"] = ACTOR_NAMES["AI"]

    for phase in timeline.phases:
        if phase.label in ks_topics:
            continue  # KnowledgeSource phases use KS participant
        pid = _make_participant_id(phase.label)
        if pid not in participants:
            participants[pid] = _topic_display(phase.label)

    if has_ks:
        participants["KS"] = ACTOR_NAMES["KS"]

    # Conditional participants for new action event types
    if any(e.event_type == EventType.ACTION_HTTP_REQUEST for e in timeline.events):
        participants["Conn"] = ACTOR_NAMES["Conn"]
    if any(e.event_type == EventType.ACTION_QA for e in timeline.events):
        participants["QA"] = ACTOR_NAMES["QA"]
    if any(e.event_type == EventType.ACTION_TRIGGER_EVAL for e in timeline.events):
        participants["Eval"] = ACTOR_NAMES["Eval"]

    # Pre-scan events for topic participants not yet registered
    for event in timeline.events:
        if event.event_type == EventType.STEP_TRIGGERED:
            topic = event.topic_name or "Unknown"
            if topic in ks_topics or "KnowledgeSource" in event.summary:
                continue
            pid = _make_participant_id(topic)
            if pid not in participants:
                participants[pid] = _topic_display(topic)
        elif event.event_type == EventType.ACTION_BEGIN_DIALOG:
            topic = event.topic_name or "Unknown"
            pid = _make_participant_id(topic)
            if pid not in participants:
                participants[pid] = _topic_display(topic)

    # Declare participants
    for pid, display in participants.items():
        if pid == display:
            lines.append(f"    participant {pid}")
        else:
            lines.append(f"    participant {pid} as {display}")

    # Build sequence from events
    for event in timeline.events:
        if event.event_type == EventType.USER_MESSAGE:
            msg = _sanitize_mermaid(event.summary.replace("User: ", ""))
            lines.append(f"    User->>AI: {msg}")

        elif event.event_type == EventType.PLAN_RECEIVED:
            msg = _sanitize_mermaid(event.summary)
            lines.append(f"    Note over AI: {msg}")

        elif event.event_type == EventType.STEP_TRIGGERED:
            topic = event.topic_name or "Unknown"
            pid = _make_participant_id(topic)
            if pid not in participants:
                participants[pid] = _topic_display(topic)
                # We can't add participant mid-diagram in all renderers, but it works in most
            if "KnowledgeSource" in event.summary:
                pid = "KS"
            lines.append(f"    AI->>{pid}: Execute {_sanitize_mermaid(topic)}")

        elif event.event_type == EventType.KNOWLEDGE_SEARCH:
            lines.append(f"    Note over KS: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.STEP_FINISHED:
            topic = event.topic_name or "Unknown"
            pid = _make_participant_id(topic)
            if event.step_id in ks_step_ids:
                pid = "KS"
            # Find matching phase for duration
            for phase in timeline.phases:
                if phase.label == topic and phase.duration_ms > 0:
                    pct = _pct(phase.duration_ms, timeline.total_elapsed_ms)
                    dur = _format_duration(phase.duration_ms)
                    state_icon = "OK" if phase.state == "completed" else "FAIL"
                    lines.append(f"    Note over {pid}: {state_icon} {dur} ({pct.replace('%', 'pct')})")
                    break
            state_arrow = "-->>" if event.state == "failed" else "->>"
            lines.append(f"    {pid}{state_arrow}AI: {event.state or 'done'}")

        elif event.event_type == EventType.BOT_MESSAGE:
            msg = _sanitize_mermaid(event.summary.replace("Bot: ", ""))
            lines.append(f"    AI->>User: {msg}")

        elif event.event_type == EventType.ACTION_HTTP_REQUEST:
            lines.append(f"    AI->>Conn: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.ACTION_QA:
            lines.append(f"    AI->>QA: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.ACTION_TRIGGER_EVAL:
            lines.append(f"    Note over Eval: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.ACTION_BEGIN_DIALOG:
            topic = event.topic_name or "Unknown"
            pid = _make_participant_id(topic)
            if pid not in participants:
                participants[pid] = _topic_display(topic)
            lines.append(f"    AI->>{pid}: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.ACTION_SEND_ACTIVITY:
            pass  # BOT_MESSAGE already covers responses

        elif event.event_type == EventType.VARIABLE_ASSIGNMENT:
            lines.append(f"    Note right of AI: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.DIALOG_REDIRECT:
            lines.append(f"    AI->>AI: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.PLAN_FINISHED:
            lines.append(f"    Note over AI: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.DIALOG_TRACING:
            lines.append(f"    Note over AI: {_sanitize_mermaid(event.summary)}")

        elif event.event_type == EventType.ERROR:
            lines.append(f"    Note over AI: [!] {_sanitize_mermaid(event.summary)}")

    # Deduplicate consecutive identical sequence lines
    deduped: list[str] = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    lines = deduped

    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def render_phase_breakdown(timeline: ConversationTimeline) -> str:
    """Render phase breakdown table."""
    lines = [
        "### Phase Breakdown\n",
        "| Phase | Type | Duration | % of Total | Status |",
        "| --- | --- | --- | --- | --- |",
    ]

    for phase in timeline.phases:
        dur = _format_duration(phase.duration_ms)
        pct = _pct(phase.duration_ms, timeline.total_elapsed_ms)
        status = "✓" if phase.state == "completed" else "✗ " + phase.state
        lines.append(f"| {phase.label} | {phase.phase_type} | {dur} | {pct} | {status} |")

    lines.append("")
    return "\n".join(lines)


def render_event_log(timeline: ConversationTimeline) -> str:
    """Render chronological event log."""
    lines = [
        "### Event Log\n",
        "| # | Position | Type | Summary |",
        "| --- | --- | --- | --- |",
    ]

    for i, event in enumerate(timeline.events, 1):
        etype = event.event_type.value
        summary = event.summary.replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {i} | {event.position} | {etype} | {summary} |")

    lines.append("")
    return "\n".join(lines)


def render_errors(timeline: ConversationTimeline) -> str:
    """Render errors section."""
    lines = [
        "### Errors\n",
    ]
    for error in timeline.errors:
        lines.append(f"- {error}")
    lines.append("")
    return "\n".join(lines)



def _gantt_label(event: TimelineEvent) -> str:
    """Short label for a Gantt task."""
    if event.event_type == EventType.USER_MESSAGE:
        return "User message"
    if event.event_type == EventType.BOT_MESSAGE:
        return "Agent response"
    if event.event_type == EventType.PLAN_RECEIVED:
        return "Plan received"
    if event.event_type == EventType.PLAN_FINISHED:
        return "Plan finished"
    if event.event_type == EventType.STEP_TRIGGERED:
        return f"Step: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.STEP_FINISHED:
        return f"Done: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.KNOWLEDGE_SEARCH:
        return "Knowledge search"
    if event.event_type == EventType.ERROR:
        return f"Error: {event.summary[:40]}"
    if event.event_type == EventType.ACTION_HTTP_REQUEST:
        return f"HTTP: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.ACTION_QA:
        return f"QA: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.ACTION_TRIGGER_EVAL:
        return f"Eval: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.ACTION_BEGIN_DIALOG:
        return f"Begin: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.ACTION_SEND_ACTIVITY:
        return f"Send: {event.topic_name or 'unknown'}"
    if event.event_type == EventType.DIALOG_TRACING:
        return "Dialog trace"
    return event.summary[:40] or "Event"


def _gantt_section(event: TimelineEvent) -> str:
    """Determine Gantt section for an event."""
    if event.event_type == EventType.USER_MESSAGE:
        return ACTOR_NAMES["User"]
    if event.event_type == EventType.BOT_MESSAGE:
        return ACTOR_NAMES["Bot"]
    if event.event_type in (EventType.PLAN_RECEIVED, EventType.PLAN_RECEIVED_DEBUG, EventType.PLAN_FINISHED):
        return ACTOR_NAMES["AI"]
    if event.event_type == EventType.KNOWLEDGE_SEARCH:
        return ACTOR_NAMES["KS"]
    if event.event_type == EventType.ERROR:
        return ACTOR_NAMES["Err"]
    if event.event_type == EventType.ACTION_HTTP_REQUEST:
        return ACTOR_NAMES["Conn"]
    if event.event_type == EventType.ACTION_QA:
        return ACTOR_NAMES["QA"]
    if event.event_type == EventType.ACTION_TRIGGER_EVAL:
        return ACTOR_NAMES["Eval"]
    if event.event_type == EventType.ACTION_BEGIN_DIALOG:
        return f"Topic - {event.topic_name}" if event.topic_name else ACTOR_NAMES["Sys"]
    if event.event_type == EventType.ACTION_SEND_ACTIVITY:
        return ACTOR_NAMES["Bot"]
    if event.topic_name:
        return f"Topic - {event.topic_name}"
    return ACTOR_NAMES["Sys"]


_GANTT_TAG_MAP: dict[EventType, str] = {
    EventType.USER_MESSAGE: "active, ",
    EventType.BOT_MESSAGE: "done, ",
    EventType.ACTION_SEND_ACTIVITY: "done, ",
    EventType.ACTION_HTTP_REQUEST: "active, crit, ",
    EventType.ACTION_QA: "active, crit, ",
    EventType.ACTION_TRIGGER_EVAL: "active, crit, ",
    EventType.KNOWLEDGE_SEARCH: "active, crit, ",
    EventType.ERROR: "crit, ",
}


def _gantt_tag(event: TimelineEvent) -> str:
    if event.state == "failed" or event.event_type == EventType.ERROR:
        return "crit, "
    return _GANTT_TAG_MAP.get(event.event_type, "")



def render_gantt_chart(timeline: ConversationTimeline) -> str:
    """Render Mermaid Gantt chart of execution timeline."""
    if not timeline.events:
        return ""

    # Build list of (epoch_ms, event) pairs, filtering out events without timestamps
    timed: list[tuple[int, TimelineEvent]] = []
    for event in timeline.events:
        ms = _parse_timestamp_to_epoch_ms(event.timestamp or "")
        if ms is not None:
            timed.append((ms, event))

    if not timed:
        return ""

    timed.sort(key=lambda x: x[0])

    # Deduplicate: skip consecutive events with same label and timestamp
    deduped: list[tuple[int, TimelineEvent]] = []
    prev_key = ("", 0)
    for epoch_ms, event in timed:
        key = (_gantt_label(event), epoch_ms)
        if key != prev_key:
            deduped.append((epoch_ms, event))
            prev_key = key
    timed = deduped

    if not timed:
        return ""

    # Normalize to elapsed time so axis starts at 00:00
    epoch_offset = timed[0][0]

    lines = [
        "### Execution Gantt\n",
        "*Color coding: 🔵 Orchestrator · 🟢 User · 🟣 Agent · 🟠 Tool Calls · 🔴 Errors · ⚫ Idle*\n",
        "```mermaid",
        "%%{init: {'theme':'base','themeVariables':{"
        "'taskBkgColor':'#4a90d9','taskBorderColor':'#357abd','taskTextColor':'#fff',"
        "'activeTaskBkgColor':'#2ecc71','activeTaskBorderColor':'#27ae60',"
        "'doneTaskBkgColor':'#9b59b6','doneTaskBorderColor':'#8e44ad',"
        "'critBkgColor':'#e74c3c','critBorderColor':'#c0392b',"
        "'activeCritBkgColor':'#f39c12','activeCritBorderColor':'#e67e22',"
        "'doneCritBkgColor':'#2a2a2a','doneCritBorderColor':'#555555'}}}%%",
        "gantt",
        "    dateFormat x",
        "    axisFormat %M:%S",
        f"    title {_sanitize_mermaid(timeline.bot_name)} - Execution Timeline",
    ]

    current_section = ""
    min_duration = 50  # ms minimum display width

    # Detect genuine idle gaps (user thinking, HITL waits — not orchestrator processing)
    idle_gaps: list[tuple[int, int]] = []  # (index, original_gap_ms)
    for i in range(1, len(timed)):
        gap = timed[i][0] - timed[i - 1][0]
        if gap > IDLE_THRESHOLD_MS and _is_genuine_idle(timed[i - 1][1], timed[i][1]):
            idle_gaps.append((i, gap))
    idle_gap_set = {idx for idx, _ in idle_gaps}
    precedes_idle = {idx - 1 for idx, _ in idle_gaps}

    for i, (epoch_ms, event) in enumerate(timed):
        start_rel = epoch_ms - epoch_offset  # actual elapsed time, no adjustment

        # Cap events that precede an idle gap to min_duration
        if i in precedes_idle:
            end_rel = start_rel + min_duration
        elif i + 1 < len(timed):
            next_start = timed[i + 1][0] - epoch_offset
            end_rel = max(next_start, start_rel + min_duration)
        else:
            end_rel = start_rel + min_duration

        duration_ms = end_rel - start_rel
        duration_str = _format_duration(duration_ms)

        # Insert idle marker before events that follow a gap
        if i in idle_gap_set:
            for gap_idx, gap_ms in idle_gaps:
                if gap_idx == i:
                    prev_start = timed[i - 1][0] - epoch_offset
                    idle_start = prev_start + min_duration
                    idle_end = start_rel  # actual gap duration
                    idle_label = f"Idle {_format_duration(gap_ms)}"
                    if current_section != "Idle":
                        lines.append("    section Idle")
                        current_section = "Idle"
                    lines.append(f"    {idle_label} :crit, done, idle{i}, {idle_start}, {idle_end}")
                    break

        section = _sanitize_mermaid(_gantt_section(event))
        if section != current_section:
            lines.append(f"    section {section}")
            current_section = section

        label = _sanitize_mermaid(_gantt_label(event))
        label_with_duration = f"{label} ({duration_str})"
        tag = _gantt_tag(event)
        lines.append(f"    {label_with_duration} :{tag}e{i}, {start_rel}, {end_rel}")

    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def render_orchestrator_reasoning(timeline: ConversationTimeline) -> str:
    """Render orchestrator reasoning chain from STEP_TRIGGERED thoughts."""
    rows: list[tuple[int, str, str]] = []
    step_num = 0
    for event in timeline.events:
        if event.event_type == EventType.STEP_TRIGGERED:
            step_num += 1
            if event.thought:
                topic = event.topic_name or "Unknown"
                reasoning = event.thought.replace("|", "\\|").replace("\n", " ")
                rows.append((step_num, topic, reasoning))
    if not rows:
        return ""
    lines = [
        "### Orchestrator Reasoning\n",
        "| Step | Topic | Reasoning |",
        "| --- | --- | --- |",
    ]
    for num, topic, reasoning in rows:
        lines.append(f"| {num} | {topic} | {reasoning} |")
    lines.append("")
    return "\n".join(lines)

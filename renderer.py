from datetime import datetime, timezone

from models import BotProfile, ConversationTimeline, EventType, TimelineEvent


def _format_duration(ms: float) -> str:
    """Format milliseconds to human-readable duration."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds % 60
    return f"{minutes}m {remaining:.1f}s"


def _pct(part: float, total: float) -> str:
    """Calculate percentage string."""
    if total <= 0:
        return "—"
    return f"{(part / total) * 100:.1f}%"


def _sanitize_mermaid(text: str) -> str:
    """Sanitize text for Mermaid diagram labels."""
    # Remove or escape characters that break Mermaid syntax
    text = text.replace('"', "'")
    text = text.replace("\n", " ")
    text = text.replace("\r", "")
    text = text.replace("#", "")
    text = text.replace(";", ",")
    text = text.replace(":", " -")
    return text[:80]


def _make_participant_id(name: str) -> str:
    """Create a valid Mermaid participant ID from a name."""
    # Remove spaces and special chars
    clean = "".join(c for c in name if c.isalnum() or c == "_")
    return clean or "Unknown"


def render_bot_profile(profile: BotProfile) -> str:
    """Render H1 heading and AI Configuration section as Markdown."""
    lines = [f"# {profile.display_name}\n"]

    # AI Configuration section (if GPT component exists)
    if profile.gpt_info:
        gpt = profile.gpt_info
        lines.append("## AI Configuration\n")
        lines.append("| Property | Value |")
        lines.append("| --- | --- |")
        if gpt.model_hint:
            lines.append(f"| Model | {gpt.model_hint} |")
        if gpt.knowledge_sources_kind:
            lines.append(f"| Knowledge Sources | {gpt.knowledge_sources_kind} |")
        lines.append(f"| Web Browsing | {gpt.web_browsing} |")
        lines.append(f"| Code Interpreter | {gpt.code_interpreter} |")
        lines.append("")
        if gpt.description:
            lines.append(f"**Description:** {gpt.description}\n")
        if gpt.instructions:
            char_count = len(gpt.instructions)
            lines.append(f"**System Instructions** ({char_count} chars):\n")
            lines.append(f"```\n{gpt.instructions}\n```")
            lines.append("")

    return "\n".join(lines)


def render_bot_metadata(profile: BotProfile) -> str:
    """Render Bot Profile metadata table as Markdown."""
    lines = [
        "## Bot Profile\n",
        "| Property | Value |",
        "| --- | --- |",
        f"| Schema Name | `{profile.schema_name}` |",
        f"| Bot ID | `{profile.bot_id}` |",
        f"| Channels | {', '.join(profile.channels) if profile.channels else 'None configured'} |",
        f"| Recognizer | {profile.recognizer_kind} |",
        f"| Orchestrator | {'Yes' if profile.is_orchestrator else 'No'} |",
        f"| Use Model Knowledge | {profile.ai_settings.use_model_knowledge} |",
        f"| File Analysis | {profile.ai_settings.file_analysis} |",
        f"| Semantic Search | {profile.ai_settings.semantic_search} |",
        f"| Content Moderation | {profile.ai_settings.content_moderation} |",
        "",
    ]
    return "\n".join(lines)


def render_components(profile: BotProfile) -> str:
    """Render components section grouped by kind."""
    # Group by kind
    by_kind: dict[str, list] = {}
    for comp in profile.components:
        by_kind.setdefault(comp.kind, []).append(comp)

    total = len(profile.components)
    active = sum(1 for c in profile.components if c.state == "Active")
    inactive = total - active

    lines = [
        "## Components\n",
        f"**{total}** components total — **{active}** active, **{inactive}** inactive\n",
        "| Kind | Count | Active | Inactive |",
        "| --- | --- | --- | --- |",
    ]
    for kind, comps in sorted(by_kind.items()):
        kind_active = sum(1 for c in comps if c.state == "Active")
        kind_inactive = len(comps) - kind_active
        lines.append(f"| {kind} | {len(comps)} | {kind_active} | {kind_inactive} |")
    lines.append("")

    # Detail tables per kind
    for kind, comps in sorted(by_kind.items()):
        lines.append(f"### {kind} ({len(comps)})\n")
        lines.append("| Name | Schema | State | Trigger | Dialog Kind |")
        lines.append("| --- | --- | --- | --- | --- |")
        for comp in comps:
            trigger = comp.trigger_kind or "—"
            dialog = comp.dialog_kind or "—"
            lines.append(f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {trigger} | {dialog} |")
        lines.append("")

    return "\n".join(lines)


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
    participants["User"] = "User"
    participants["AI"] = "AI Recognizer"

    for phase in timeline.phases:
        if phase.label in ks_topics:
            continue  # KnowledgeSource phases use KS participant
        pid = _make_participant_id(phase.label)
        if pid not in participants:
            participants[pid] = phase.label

    if has_ks:
        participants["KS"] = "Knowledge Search"

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
                participants[pid] = topic
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
                    state_icon = "✓" if phase.state == "completed" else "✗"
                    lines.append(f"    Note over {pid}: {state_icon} {dur} ({pct})")
                    break
            state_arrow = "-->>" if event.state == "failed" else "->>"
            lines.append(f"    {pid}{state_arrow}AI: {event.state or 'done'}")

        elif event.event_type == EventType.BOT_MESSAGE:
            msg = _sanitize_mermaid(event.summary.replace("Bot: ", ""))
            lines.append(f"    AI->>User: {msg}")

        elif event.event_type == EventType.ERROR:
            lines.append(f"    Note over AI: ⚠ {_sanitize_mermaid(event.summary)}")

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
        summary = summary[:100] + "..." if len(summary) > 100 else summary
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


def render_topic_graph(profile: BotProfile) -> str:
    """Render Mermaid flowchart of topic-to-topic connections via BeginDialog."""
    if not profile.topic_connections:
        return ""

    # Collect unique nodes and edges (dedup by src_id, tgt_id pair only)
    nodes: dict[str, str] = {}  # id -> display
    edges: list[tuple[str, str, str | None]] = []
    seen_edges: dict[tuple[str, str], int] = {}  # (src, tgt) -> count

    for conn in profile.topic_connections:
        src_id = _make_participant_id(conn.source_display)
        tgt_id = _make_participant_id(conn.target_display)
        nodes[src_id] = conn.source_display
        nodes[tgt_id] = conn.target_display

        edge_key = (src_id, tgt_id)
        if edge_key not in seen_edges:
            seen_edges[edge_key] = 1
            edges.append((src_id, tgt_id, conn.condition))
        else:
            # Multiple conditions between same pair — drop condition label
            seen_edges[edge_key] += 1
            for i, (s, t, _c) in enumerate(edges):
                if s == src_id and t == tgt_id:
                    edges[i] = (s, t, None)
                    break

    # Size cap: if diagram would exceed ~40KB, keep top 80 most-connected nodes
    max_size = 40_000
    max_nodes = 80
    truncated = False

    if len(nodes) > max_nodes:
        # Count connections per node
        connection_count: dict[str, int] = {nid: 0 for nid in nodes}
        for src, tgt, _ in edges:
            connection_count[src] = connection_count.get(src, 0) + 1
            connection_count[tgt] = connection_count.get(tgt, 0) + 1

        # Keep top N most-connected
        top_nodes = sorted(connection_count, key=lambda n: connection_count[n], reverse=True)[:max_nodes]
        keep = set(top_nodes)
        nodes = {nid: display for nid, display in nodes.items() if nid in keep}
        edges = [(s, t, c) for s, t, c in edges if s in keep and t in keep]
        truncated = True

    lines = ["## Topic Connection Graph\n", "```mermaid", "graph TD"]

    if truncated:
        lines.append(f"    %% Diagram truncated to {max_nodes} most-connected nodes")

    for nid, display in sorted(nodes.items()):
        label = _sanitize_mermaid(display)
        lines.append(f"    {nid}[{label}]")

    for src, tgt, condition in edges:
        if condition:
            cond_label = _sanitize_mermaid(condition)
            lines.append(f"    {src} -->|{cond_label}| {tgt}")
        else:
            lines.append(f"    {src} --> {tgt}")

    lines.append("```")
    lines.append("")

    result = "\n".join(lines)

    # Final safety check
    if len(result.encode("utf-8")) > max_size:
        # Further trim edges to fit
        lines_trimmed = lines[:3]  # header + mermaid + graph TD
        lines_trimmed.append("    %% Diagram truncated to fit size limit")
        for nid, display in sorted(nodes.items()):
            label = _sanitize_mermaid(display)
            lines_trimmed.append(f"    {nid}[{label}]")
        budget = max_size - len("\n".join(lines_trimmed).encode("utf-8")) - 50
        for src, tgt, condition in edges:
            if condition:
                cond_label = _sanitize_mermaid(condition)
                edge_line = f"    {src} -->|{cond_label}| {tgt}"
            else:
                edge_line = f"    {src} --> {tgt}"
            budget -= len(edge_line.encode("utf-8")) + 1
            if budget < 0:
                break
            lines_trimmed.append(edge_line)
        lines_trimmed.append("```")
        lines_trimmed.append("")
        result = "\n".join(lines_trimmed)

    return result


def _parse_timestamp_to_epoch_ms(ts: str) -> int | None:
    """Parse ISO timestamp to epoch milliseconds."""
    if not ts:
        return None
    try:
        # Handle various ISO formats
        cleaned = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, OSError):
        return None


def _gantt_label(event: TimelineEvent) -> str:
    """Short label for a Gantt task."""
    if event.event_type == EventType.USER_MESSAGE:
        return "User message"
    if event.event_type == EventType.BOT_MESSAGE:
        return "Bot response"
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
    if event.event_type == EventType.DIALOG_TRACING:
        return "Dialog trace"
    return event.summary[:40] or "Event"


def _gantt_section(event: TimelineEvent) -> str:
    """Determine Gantt section for an event."""
    if event.event_type == EventType.USER_MESSAGE:
        return "User"
    if event.event_type == EventType.BOT_MESSAGE:
        return "Bot"
    if event.event_type in (EventType.PLAN_RECEIVED, EventType.PLAN_RECEIVED_DEBUG, EventType.PLAN_FINISHED):
        return "Orchestrator"
    if event.event_type == EventType.KNOWLEDGE_SEARCH:
        return "Knowledge"
    if event.event_type == EventType.ERROR:
        return "Errors"
    if event.topic_name:
        return event.topic_name
    return "System"


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

    lines = [
        "### Execution Gantt\n",
        "```mermaid",
        "gantt",
        "    dateFormat x",
        "    axisFormat %M:%S",
        f"    title {_sanitize_mermaid(timeline.bot_name)} — Execution Timeline",
    ]

    current_section = ""
    min_duration = 50  # ms minimum display width

    for i, (epoch_ms, event) in enumerate(timed):
        # Determine end time: next event's timestamp or +min_duration
        if i + 1 < len(timed):
            end_ms = timed[i + 1][0]
            if end_ms - epoch_ms < min_duration:
                end_ms = epoch_ms + min_duration
        else:
            end_ms = epoch_ms + min_duration

        duration_ms = end_ms - epoch_ms
        duration_str = _format_duration(duration_ms)

        section = _gantt_section(event)
        if section != current_section:
            lines.append(f"    section {section}")
            current_section = section

        label = _sanitize_mermaid(_gantt_label(event))
        label_with_duration = f"{label} ({duration_str})"
        crit = "crit, " if event.state == "failed" or event.event_type == EventType.ERROR else ""
        lines.append(f"    {label_with_duration} :{crit}e{i}, {epoch_ms}, {end_ms}")

    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def render_transcript_report(
    title: str,
    timeline: ConversationTimeline,
    metadata: dict,
) -> str:
    """Render Markdown report for a transcript (no bot profile data)."""
    sections = [f"# {title}\n"]

    # Session summary table from metadata
    session = metadata.get("session_info")
    if session:
        sections.append("## Session Summary\n")
        lines = ["| Property | Value |", "| --- | --- |"]
        if session.get("startTimeUtc"):
            lines.append(f"| Start Time | {session['startTimeUtc']} |")
        if session.get("endTimeUtc"):
            lines.append(f"| End Time | {session['endTimeUtc']} |")
        if session.get("type"):
            lines.append(f"| Session Type | {session['type']} |")
        if session.get("outcome"):
            lines.append(f"| Outcome | {session['outcome']} |")
        if session.get("outcomeReason"):
            lines.append(f"| Outcome Reason | {session['outcomeReason']} |")
        if session.get("turnCount") is not None:
            lines.append(f"| Turn Count | {session['turnCount']} |")
        if session.get("impliedSuccess") is not None:
            lines.append(f"| Implied Success | {session['impliedSuccess']} |")
        lines.append("")
        sections.append("\n".join(lines))

    # Conversation trace (reuses existing render_timeline which includes
    # sequence diagram, gantt, phase breakdown, event log, errors)
    sections.append(render_timeline(timeline))

    return "\n".join(sections)


def render_report(profile: BotProfile, timeline: ConversationTimeline) -> str:
    """Render complete Markdown report."""
    sections = [render_bot_profile(profile)]

    # Execution diagrams promoted to top
    if timeline.events:
        has_steps = timeline.phases or any(
            e.event_type in (EventType.STEP_TRIGGERED, EventType.USER_MESSAGE) for e in timeline.events
        )
        if has_steps:
            sections.append(render_mermaid_sequence(timeline))
        gantt = render_gantt_chart(timeline)
        if gantt:
            sections.append(gantt)

    sections.append(render_bot_metadata(profile))
    sections.append(render_components(profile))

    topic_graph = render_topic_graph(profile)
    if topic_graph:
        sections.append(topic_graph)

    sections.append(render_timeline(timeline, skip_diagrams=True))

    return "\n".join(sections)

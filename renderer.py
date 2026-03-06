from datetime import datetime, timezone

from models import BotProfile, ComponentSummary, ConversationTimeline, EventType, KnowledgeSearchInfo, TimelineEvent

IDLE_THRESHOLD_MS = 5000  # gaps > 5s are shown as idle markers

ACTOR_NAMES: dict[str, str] = {
    "User": "User",
    "AI": "Orchestrator",
    "Bot": "Agent",
    "KS": "Knowledge Search",
    "Conn": "Connectors",
    "QA": "QA Engine",
    "Eval": "Evaluator",
    "Err": "Errors",
    "Sys": "System",
}


def _parse_execution_time_ms(raw: str | None) -> float | None:
    """Parse .NET TimeSpan 'HH:MM:SS.fffffff' to milliseconds."""
    if not raw:
        return None
    import re
    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", raw)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return (h * 3600 + mi * 60 + s) * 1000


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
    # Replace unicode symbols with ASCII-safe equivalents
    text = text.replace("→", "to")
    text = text.replace("—", "-")
    text = text.replace("✓", "OK")
    text = text.replace("✗", "FAIL")
    text = text.replace("⚠", "WARN")
    # Remove characters that are Mermaid syntax tokens
    text = text.replace('"', "")
    text = text.replace("'", "")
    text = text.replace("%", "pct")
    text = text.replace("\n", " ")
    text = text.replace("\r", "")
    text = text.replace("#", "")
    text = text.replace(";", ",")
    text = text.replace(":", " -")
    text = text.replace("[", "")
    text = text.replace("]", "")
    text = text.replace("(", "")
    text = text.replace(")", "")
    text = text.replace("{", "")
    text = text.replace("}", "")
    text = text.replace("|", "")
    text = text.replace("<", "")
    text = text.replace(">", "")
    return text[:80]


def _make_participant_id(name: str) -> str:
    """Create a valid Mermaid participant ID from a name."""
    # Remove spaces and special chars
    clean = "".join(c for c in name if c.isalnum() or c == "_")
    return clean or "Unknown"


def _topic_display(name: str) -> str:
    """Prefix topic names with 'Topic - ' to distinguish them from system actors."""
    pid = _make_participant_id(name)
    if pid in ACTOR_NAMES:
        return ACTOR_NAMES[pid]
    return f"Topic - {name}"


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
        if gpt.conversation_starters:
            lines.append("### Conversation Starters\n")
            lines.append("| Title | Example Query |")
            lines.append("| --- | --- |")
            for starter in gpt.conversation_starters:
                title = starter.get("title", "—")
                message = starter.get("message", "—")
                lines.append(f"| {title} | {message} |")
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

    if profile.environment_variables:
        lines.append("### Environment Variables\n")
        lines.append("| Name | Type | Value |")
        lines.append("| --- | --- | --- |")
        for var in profile.environment_variables:
            name = var.get("name", var.get("displayName", "—"))
            var_type = var.get("type", "—")
            value = str(var.get("value", var.get("defaultValue", "—")))
            value = value.replace("|", "\\|").replace("\n", " ").replace("\r", "")
            lines.append(f"| {name} | {var_type} | {value} |")
        lines.append("")

    if profile.connectors:
        lines.append("### Connectors\n")
        lines.append("| Name | Type | Description |")
        lines.append("| --- | --- | --- |")
        for conn in profile.connectors:
            name = conn.get("displayName", conn.get("name", "—"))
            conn_type = conn.get("type", conn.get("kind", "—"))
            desc = conn.get("description", "—") or "—"
            desc = desc.replace("|", "\\|").replace("\n", " ").replace("\r", "")
            lines.append(f"| {name} | {conn_type} | {desc} |")
        lines.append("")

    return "\n".join(lines)


_SYSTEM_TRIGGERS: set[str] = {
    "OnSystemRedirect",
    "OnError",
    "OnEscalate",
    "OnSignIn",
    "OnUnknownIntent",
    "OnConversationStart",
    "OnSelectIntent",
    "OnInactivity",
}

_AUTOMATION_TRIGGERS: set[str] = {
    "OnRedirect",
    "OnActivity",
}

_CATEGORY_ORDER: list[str] = [
    "user_topics",
    "orchestrator_topics",
    "system_topics",
    "automation_topics",
    "knowledge",
    "skills",
    "custom_entities",
    "variables",
    "settings",
]

_CATEGORY_DISPLAY: dict[str, str] = {
    "user_topics": "User Topics",
    "orchestrator_topics": "Orchestrator Topics",
    "system_topics": "System Topics",
    "automation_topics": "Automation Topics",
    "knowledge": "Knowledge",
    "skills": "Skills & Connectors",
    "custom_entities": "Custom Entities",
    "variables": "Variables",
    "settings": "Settings",
}

_CATEGORY_COLUMNS: dict[str, list[str]] = {
    "user_topics": ["Name", "Schema", "State", "Triggers", "Description"],
    "orchestrator_topics": ["Name", "Schema", "State", "Dialog Kind", "Action Kind"],
    "system_topics": ["Name", "Schema", "State", "Trigger"],
    "automation_topics": ["Name", "Schema", "State", "Trigger"],
    "knowledge": ["Name", "Status", "Description"],
    "skills": ["Name", "Schema", "State", "Description"],
    "custom_entities": ["Name", "Schema", "State"],
    "variables": ["Name", "Schema", "State"],
    "settings": ["Name", "Schema", "State"],
}


def _classify_component(comp: ComponentSummary) -> str | None:
    """Classify a component into a category key, or None to exclude."""
    if comp.kind == "GptComponent":
        return None
    if comp.kind == "DialogComponent":
        if comp.dialog_kind in ("TaskDialog", "AgentDialog"):
            return "orchestrator_topics"
        trigger = comp.trigger_kind or ""
        if trigger in _SYSTEM_TRIGGERS:
            return "system_topics"
        if trigger in _AUTOMATION_TRIGGERS:
            return "automation_topics"
        return "user_topics"
    if comp.kind in ("FileAttachmentComponent", "KnowledgeSourceComponent"):
        return "knowledge"
    if comp.kind == "SkillComponent":
        return "skills"
    if comp.kind == "CustomEntityComponent":
        return "custom_entities"
    if comp.kind == "GlobalVariableComponent":
        return "variables"
    if comp.kind == "BotSettingsComponent":
        return "settings"
    return "settings"


def _render_component_row(comp: ComponentSummary, category: str) -> str:
    """Render a single component row matching the category's columns."""
    def _cell(text: str | None) -> str:
        return (text or "—").replace("|", "\\|").replace("\n", " ").replace("\r", "")

    if category == "user_topics":
        trigger_str = ", ".join(comp.trigger_queries) if comp.trigger_queries else "—"
        trigger_str = _cell(trigger_str)
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {trigger_str} | {_cell(comp.description)} |"
    if category == "orchestrator_topics":
        dialog = comp.dialog_kind or "—"
        action = comp.action_kind or "—"
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {dialog} | {action} |"
    if category in ("system_topics", "automation_topics"):
        trigger = comp.trigger_kind or "—"
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {trigger} |"
    if category == "knowledge":
        kind_type = "File" if comp.kind == "FileAttachmentComponent" else "Source"
        state_icon = "✓" if comp.state == "Active" else "✗"
        status = f"{kind_type} {state_icon}"
        return f"| {comp.display_name} | {status} | {_cell(comp.description)} |"
    if category == "skills":
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {_cell(comp.description)} |"
    # custom_entities, variables, settings
    return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} |"


def render_components(profile: BotProfile) -> str:
    """Render components section with smart categorization."""
    # Classify into categories (exclude GptComponent)
    by_category: dict[str, list[ComponentSummary]] = {}
    for comp in profile.components:
        cat = _classify_component(comp)
        if cat is not None:
            by_category.setdefault(cat, []).append(comp)

    total = sum(len(comps) for comps in by_category.values())
    active = sum(1 for comps in by_category.values() for c in comps if c.state == "Active")
    inactive = total - active

    lines = [
        "## Components\n",
        f"**{total}** components total — **{active}** active, **{inactive}** inactive\n",
        "| Kind | Count | Active | Inactive |",
        "| --- | --- | --- | --- |",
    ]
    for cat in _CATEGORY_ORDER:
        comps = by_category.get(cat)
        if not comps:
            continue
        display = _CATEGORY_DISPLAY[cat]
        cat_active = sum(1 for c in comps if c.state == "Active")
        cat_inactive = len(comps) - cat_active
        lines.append(f"| {display} | {len(comps)} | {cat_active} | {cat_inactive} |")
    lines.append("")

    # Detail tables per category
    for cat in _CATEGORY_ORDER:
        comps = by_category.get(cat)
        if not comps:
            continue
        display = _CATEGORY_DISPLAY[cat]
        columns = _CATEGORY_COLUMNS[cat]
        lines.append(f"### {display} ({len(comps)})\n")
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for comp in comps:
            lines.append(_render_component_row(comp, cat))
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

    lines = ["## Topic Connection Graph\n", "```mermaid", '%%{init: {"useMaxWidth": false}}%%', "graph TD"]

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

    # Detect idle gaps (no adjustments — events use actual elapsed time)
    idle_gaps: list[tuple[int, int]] = []  # (index, original_gap_ms)
    for i in range(1, len(timed)):
        gap = timed[i][0] - timed[i - 1][0]
        if gap > IDLE_THRESHOLD_MS:
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


def _grounding_score(ks: "KnowledgeSearchInfo") -> tuple[str, str]:
    count = len(ks.search_results)
    if count == 0:
        return "⚠️", "No Grounding"
    raw = f"{ks.search_query or ''} {ks.search_keywords or ''}".lower()
    stop = {"the", "a", "an", "is", "in", "of", "to", "for", "and", "or", "what", "how", ""}
    terms = {w for w in raw.split() if w not in stop and len(w) > 2}
    if terms:
        hits = sum(
            1 for r in ks.search_results[:5]
            if any(t in (r.name or "").lower() or t in (r.text or "").lower()[:200] for t in terms)
        )
        relevance = hits / min(count, 5)
    else:
        relevance = 0.5
    if count >= 7 and relevance >= 0.4:
        return "🟢", "Strong"
    elif count >= 3 or relevance >= 0.4:
        return "🟡", "Moderate"
    else:
        return "🟠", "Weak"


def _source_efficiency(ks: "KnowledgeSearchInfo") -> str | None:
    queried = set(ks.knowledge_sources)
    used = set(ks.output_knowledge_sources)
    if not queried or not used:
        return None
    contributing = queried & used
    silent = queried - used
    pct = int(len(contributing) / len(queried) * 100)

    if pct >= 80:
        badge = "🟢"
    elif pct >= 50:
        badge = "🟡"
    else:
        badge = "🔴"

    line = f"{badge} **Source efficiency:** {len(contributing)}/{len(queried)} sources returned results ({pct}%)"
    if silent:
        silent_names = ", ".join(f"`{s}`" for s in sorted(silent))
        line += f"\n⚫ **Silent sources** (no results): {silent_names}"
    return line


def _clean_user_message(msg: str) -> str:
    """Clean a user message for display as a group header."""
    return msg.replace("\n", " ").replace("\r", "").strip()


def _compact_sources(src_list: list[str]) -> str:
    """Show all sources for table display."""
    if not src_list:
        return "—"
    return ", ".join(src_list)


def _render_ks_table(searches: list[tuple[int, "KnowledgeSearchInfo"]]) -> list[str]:
    """Render a numbered search table for a group of KnowledgeSearchInfo items."""
    lines = [
        "| # | Search Query | Keywords | Sources | Duration | Grounding |",
        "| :-- | :-- | :-- | :-- | --: | :-- |",
    ]
    for idx, ks in searches:
        query = (ks.search_query or "—").replace("|", "\\|").replace("\n", " ").replace("\r", "")
        keywords = (ks.search_keywords or "—").replace("|", "\\|").replace("\n", " ").replace("\r", "")
        sources = _compact_sources(ks.knowledge_sources)
        dur_ms = _parse_execution_time_ms(ks.execution_time)
        dur = _format_duration(dur_ms) if dur_ms is not None else (ks.execution_time or "—")
        badge, label = _grounding_score(ks)
        lines.append(f"| {idx} | {query} | {keywords} | {sources} | {dur} | {badge} {label} |")
    lines.append("")
    return lines


def _render_ks_details(searches: list[tuple[int, "KnowledgeSearchInfo"]]) -> list[str]:
    """Render thought and grounding details for a group of searches."""
    lines: list[str] = []
    for idx, ks in searches:
        if ks.thought:
            lines.append(f"**#{idx} Why searched:** *{ks.thought}*\n")

    for idx, ks in searches:
        has_detail = ks.search_results or ks.search_errors or ks.output_knowledge_sources
        if not has_detail:
            continue
        lines.append(f"\n#### Search #{idx} — Grounding Details\n")

        if ks.output_knowledge_sources:
            out_src = ", ".join(ks.output_knowledge_sources)
            lines.append(f"**Sources used for grounding:** {out_src}\n")
        eff = _source_efficiency(ks)
        if eff:
            lines.append(f"{eff}\n")

        for err in ks.search_errors:
            lines.append(f"> ⚠ Search error: `{err}`\n")

        result_count = len(ks.search_results)
        if result_count == 0:
            lines.append("> ⚠ **No results returned** — response may not be grounded.\n")
        else:
            lines.append(f"**{result_count} result{'s' if result_count != 1 else ''} retrieved:**\n")
            for j, r in enumerate(ks.search_results, 1):
                title = r.name or r.url or f"Result {j}"
                title = title.replace("|", "\\|").replace("\n", " ")
                snippet = (r.text or "").replace("\n", " ").replace("|", "\\|")
                snippet_len = len(r.text or "")
                if snippet_len >= 200:
                    ke_icon = "🟢"
                elif snippet_len >= 50:
                    ke_icon = "🟡"
                else:
                    ke_icon = "🔴"
                if r.url:
                    lines.append(f"{ke_icon} {j}. [{title}]({r.url})" + (f" — {snippet}" if snippet else "") + "\n")
                else:
                    lines.append(f"{ke_icon} {j}. **{title}**" + (f" — {snippet}" if snippet else "") + "\n")
        lines.append("")
    return lines


def render_knowledge_search_section(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> str:
    """Render Knowledge Search section as Markdown, grouped by triggering user message."""
    searches = timeline.knowledge_searches
    custom = getattr(timeline, "custom_search_steps", [])
    gk = (
        "✓ On"
        if (profile and profile.ai_settings and profile.ai_settings.use_model_knowledge)
        else "✗ Off"
    )
    total = len(searches)

    lines: list[str] = ["## Knowledge Search\n"]

    if not searches and not custom:
        lines.append(f"**0 searches** | General Knowledge: {gk}\n")
        lines.append("No knowledge searches recorded.\n")
        return "\n".join(lines)

    # Group searches by triggering_user_message (preserve order)
    from collections import OrderedDict
    groups: OrderedDict[str | None, list[tuple[int, "KnowledgeSearchInfo"]]] = OrderedDict()
    for i, ks in enumerate(searches, 1):
        key = ks.triggering_user_message
        groups.setdefault(key, []).append((i, ks))

    user_turns = sum(1 for k in groups if k is not None)
    total_turns = len(groups)

    if total_turns <= 1:
        lines.append(f"**{total} search{'es' if total != 1 else ''}** | General Knowledge: {gk}\n")
    else:
        lines.append(f"**{total} search{'es' if total != 1 else ''} across {total_turns} user turn{'s' if total_turns != 1 else ''}** | General Knowledge: {gk}\n")

    # Render each group
    for msg_key, group_searches in groups.items():
        if total_turns > 1:
            lines.append("---\n")
        if msg_key is not None:
            header = _clean_user_message(msg_key)
            lines.append(f'### 💬 "{header}"\n')
        elif total_turns > 1:
            lines.append("### 🔧 System-initiated\n")

        lines.extend(_render_ks_table(group_searches))
        lines.extend(_render_ks_details(group_searches))

    if custom:
        lines.append("\n### Custom Search Topics\n")
        for cs in custom:
            status_icon = "✓" if cs.status == "completed" else ("✗" if cs.status == "failed" else "⏳")
            lines.append(f"**{status_icon} {cs.display_name}** ({cs.status})")
            if cs.thought:
                lines.append(f"> {cs.thought}")
            if cs.error:
                lines.append(f"> ⚠ Error: `{cs.error}`")
            dur_ms = _parse_execution_time_ms(cs.execution_time)
            dur = _format_duration(dur_ms) if dur_ms is not None else (cs.execution_time or "—")
            lines.append(f"Duration: {dur}\n")

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


def render_topic_details(profile: BotProfile, timeline: ConversationTimeline | None = None) -> str:
    """Render topic deep dive: external calls and coverage analysis."""
    lines: list[str] = []

    # Section 1: Topics with external calls
    external_topics = [
        c for c in profile.components
        if c.kind == "DialogComponent" and c.has_external_calls
    ]
    if external_topics:
        lines.append("### Topics with External Calls\n")
        lines.append("| Topic | Connector | Flow | AI Builder | HTTP | Total Actions |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for comp in external_topics:
            connector = comp.action_summary.get("InvokeConnectorAction", 0)
            flow = comp.action_summary.get("InvokeFlowAction", 0)
            ai_builder = comp.action_summary.get("InvokeAIBuilderModelAction", 0)
            http = comp.action_summary.get("HttpRequestAction", 0)
            total = sum(comp.action_summary.values())
            lines.append(f"| {comp.display_name} | {connector} | {flow} | {ai_builder} | {http} | {total} |")
        lines.append("")

    # Section 2: Topic coverage (only if timeline provided)
    if timeline:
        dialog_comps = [
            c for c in profile.components
            if c.kind == "DialogComponent" and c.trigger_kind not in (
                _SYSTEM_TRIGGERS | _AUTOMATION_TRIGGERS | {None}
            ) and c.dialog_kind not in ("TaskDialog", "AgentDialog")
        ]
        if dialog_comps:
            triggered_names = {
                event.topic_name
                for event in timeline.events
                if event.event_type == EventType.STEP_TRIGGERED and event.topic_name
            }
            triggered_count = sum(1 for c in dialog_comps if c.display_name in triggered_names)
            total_count = len(dialog_comps)
            untriggered = [c for c in dialog_comps if c.display_name not in triggered_names]

            lines.append("### Topic Coverage\n")
            lines.append(f"**{triggered_count} of {total_count} user topics triggered** in this conversation.")
            if untriggered:
                lines.append(" Not triggered in this session:\n")
                lines.append("| Topic | State | Has External Calls |")
                lines.append("| --- | --- | --- |")
                for comp in untriggered:
                    ext = "Yes" if comp.has_external_calls else "No"
                    lines.append(f"| {comp.display_name} | {comp.state} | {ext} |")
            lines.append("")

    return "\n".join(lines)


def render_knowledge_source_details(profile: BotProfile) -> str:
    """Render expanded knowledge source details with descriptions and source config."""
    ks_comps = [
        c for c in profile.components
        if c.kind == "KnowledgeSourceComponent" and (c.description or c.source_kind)
    ]
    if not ks_comps:
        return ""
    lines = ["### Knowledge Source Details\n"]
    for comp in ks_comps:
        lines.append(f"#### {comp.display_name}\n")
        source_parts = []
        if comp.source_kind:
            source_parts.append(comp.source_kind)
        if comp.source_site:
            source_parts.append(comp.source_site)
        if source_parts:
            lines.append(f"**Source:** {' · '.join(source_parts)}\n")
        if comp.description:
            lines.append(f"{comp.description}\n")
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

    sections.append(render_knowledge_search_section(timeline))

    reasoning = render_orchestrator_reasoning(timeline)
    if reasoning:
        sections.append(reasoning)

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

    topic_details = render_topic_details(profile, timeline)
    if topic_details:
        sections.append(topic_details)

    sections.append(render_knowledge_search_section(timeline, profile=profile))

    ks_details = render_knowledge_source_details(profile)
    if ks_details:
        sections.append(ks_details)

    reasoning = render_orchestrator_reasoning(timeline)
    if reasoning:
        sections.append(reasoning)

    topic_graph = render_topic_graph(profile)
    if topic_graph:
        sections.append(topic_graph)

    sections.append(render_timeline(timeline, skip_diagrams=True))

    return "\n".join(sections)

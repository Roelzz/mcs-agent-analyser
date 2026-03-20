from models import (
    BotProfile,
    ComponentSummary,
    ConversationTimeline,
    EventType,
)

from ._helpers import (
    _make_participant_id,
    _sanitize_mermaid,
)

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

_EXT_KINDS = {"InvokeConnectorAction", "InvokeFlowAction", "InvokeAIBuilderModelAction", "HttpRequestAction"}

_CATEGORY_ORDER: list[str] = [
    "user_topics",
    "system_topics",
    "automation_topics",
    "orchestrator_topics",
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
    "orchestrator_topics": ["Name", "State", "Tool Type", "Connector", "Mode"],
    "system_topics": ["Name", "Schema", "State", "Trigger"],
    "automation_topics": ["Name", "Schema", "State", "Trigger"],
    "knowledge": ["Name", "Status", "Description"],
    "skills": ["Name", "Schema", "State", "Description"],
    "custom_entities": ["Name", "Schema", "State", "Entity Kind"],
    "variables": ["Name", "Schema", "State", "Scope"],
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
        return (
            f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {trigger_str} | {_cell(comp.description)} |"
        )
    if category == "orchestrator_topics":
        tool = comp.tool_type or comp.action_kind or "—"
        connector = comp.connector_display_name or "—"
        mode = comp.connection_mode or "—"
        return f"| {comp.display_name} | {comp.state} | {tool} | {connector} | {mode} |"
    if category in ("system_topics", "automation_topics"):
        trigger = comp.trigger_kind or "—"
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {trigger} |"
    if category == "knowledge":
        kind_type = "File" if comp.kind == "FileAttachmentComponent" else "Source"
        state_icon = "✓" if comp.state == "Active" else "✗"
        status = f"{kind_type} {state_icon}"
        extra = ""
        if comp.file_type:
            extra = f" ({comp.file_type})"
        if comp.trigger_condition_raw and comp.trigger_condition_raw.lower() == "false":
            extra = " ⚠ always-on"
        return f"| {comp.display_name}{extra} | {status} | {_cell(comp.description)} |"
    if category == "skills":
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {_cell(comp.description)} |"
    if category == "custom_entities":
        entity_info = comp.entity_kind or "—"
        if comp.entity_item_count:
            entity_info += f" ({comp.entity_item_count} items)"
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {entity_info} |"
    if category == "variables":
        scope = comp.variable_scope or "—"
        return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} | {scope} |"
    # settings
    return f"| {comp.display_name} | `{comp.schema_name}` | {comp.state} |"


def render_bot_profile(profile: BotProfile) -> str:
    """Render H1 heading only."""
    return f"# {profile.display_name}\n"


def render_ai_config(profile: BotProfile) -> str:
    """Render AI Configuration section as Markdown."""
    if not profile.gpt_info:
        return ""

    gpt = profile.gpt_info
    lines = [
        "## AI Configuration\n",
        "| Property | Value |",
        "| --- | --- |",
    ]
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
    auth_display = profile.authentication_mode
    if profile.authentication_trigger != "Unknown":
        auth_display += f" ({profile.authentication_trigger})"

    lines = [
        "## Bot Profile\n",
        "| Property | Value |",
        "| --- | --- |",
        f"| Schema Name | `{profile.schema_name}` |",
        f"| Bot ID | `{profile.bot_id}` |",
        f"| Channels | {', '.join(profile.channels) if profile.channels else 'None configured'} |",
        f"| Recognizer | {profile.recognizer_kind} |",
        f"| Orchestrator | {'Yes' if profile.is_orchestrator else 'No'} |",
        f"| Authentication | {auth_display} |",
        f"| Access Control | {profile.access_control_policy} |",
        f"| Generative Actions | {'Enabled' if profile.generative_actions_enabled else 'Disabled'} |",
        f"| Agent Connectable | {'Yes' if profile.is_agent_connectable else 'No'} |",
    ]
    if profile.is_lightweight_bot:
        lines.append("| Lightweight Bot | Yes |")
    if profile.app_insights:
        ai = profile.app_insights
        flags = []
        if ai.log_activities:
            flags.append("log activities")
        if ai.log_sensitive_properties:
            flags.append("log sensitive")
        detail = f"Configured ({', '.join(flags)})" if flags else "Configured"
        lines.append(f"| Application Insights | {detail} |")
    lines.extend(
        [
            f"| Use Model Knowledge | {profile.ai_settings.use_model_knowledge} |",
            f"| File Analysis | {profile.ai_settings.file_analysis} |",
            f"| Semantic Search | {profile.ai_settings.semantic_search} |",
            f"| Content Moderation | {profile.ai_settings.content_moderation} |",
            "",
        ]
    )

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

    if profile.connection_references:
        lines.append("### Connection References\n")
        lines.append("| Name | Connector | Custom |")
        lines.append("| --- | --- | --- |")
        for ref in profile.connection_references:
            name = ref.get("displayName", ref.get("connectionReferenceLogicalName", "—"))
            connector = ref.get("connectorId", "—")
            # Extract short connector name from path
            if "/" in connector:
                connector = connector.rsplit("/", 1)[-1]
            custom = "Yes" if ref.get("customConnectorId") else "No"
            lines.append(f"| {name} | {connector} | {custom} |")
        lines.append("")

    if profile.connector_definitions:
        lines.append("### Connector Definitions\n")
        lines.append("| Name | Type | Custom | Operations | MCP |")
        lines.append("| --- | --- | --- | --- | --- |")
        for cdef in profile.connector_definitions:
            name = cdef.get("displayName", "—")
            ctype = cdef.get("connectorType", "—")
            custom = "Yes" if cdef.get("isCustom") else "No"
            ops = cdef.get("operationCount", 0)
            mcp = "Yes" if cdef.get("hasMCP") else "No"
            lines.append(f"| {name} | {ctype} | {custom} | {ops} | {mcp} |")
        lines.append("")

    return "\n".join(lines)


def render_topic_inventory(profile: BotProfile) -> str:
    """Render topic inventory: user, system, automation topics + supporting config."""
    # Classify into categories (exclude GptComponent, orchestrator_topics, knowledge)
    by_category: dict[str, list[ComponentSummary]] = {}
    for comp in profile.components:
        cat = _classify_component(comp)
        if cat is not None and cat in _CATEGORY_ORDER:
            by_category.setdefault(cat, []).append(comp)

    total = sum(len(comps) for comps in by_category.values())
    active = sum(1 for comps in by_category.values() for c in comps if c.state == "Active")
    inactive = total - active

    lines = [
        "## Topic Inventory\n",
        f"**{total}** topics & config — **{active}** active, **{inactive}** inactive\n",
    ]
    if total == 0:
        lines.append(
            "> **Note:** No components found in Dataverse. "
            "The bot may use embedded configuration or a different component model.\n"
        )
        return "\n".join(lines)

    lines.extend(
        [
            "| Kind | Count | Active | Inactive |",
            "| --- | --- | --- | --- |",
        ]
    )
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


def render_topic_details(profile: BotProfile, timeline: ConversationTimeline | None = None) -> str:
    """Render topic deep dive: external calls and coverage analysis."""
    lines: list[str] = []

    # Section 1: Topics with external calls (per-action detail)
    external_topics = [c for c in profile.components if c.kind == "DialogComponent" and c.has_external_calls]
    if external_topics:
        lines.append("### Topics with External Calls\n")
        # Check if any topic has action_details
        has_details = any(c.action_details for c in external_topics)
        if has_details:
            lines.append("| Topic | Action Kind | Connector | Operation |")
            lines.append("| --- | --- | --- | --- |")
            # Collect all rows, then deduplicate
            raw_rows: list[tuple[str, str, str, str]] = []
            for comp in external_topics:
                if comp.action_details:
                    for detail in comp.action_details:
                        kind = detail.get("kind", "—")
                        connector = detail.get("connector_display_name") or detail.get("connection_reference") or "—"
                        operation = detail.get("operation_id") or "—"
                        raw_rows.append((comp.display_name, kind, connector, operation))
                else:
                    total = sum(v for k, v in comp.action_summary.items() if k in _EXT_KINDS)
                    raw_rows.append((comp.display_name, "(summary)", "—", f"{total} calls"))
            # Deduplicate: count identical rows
            from collections import Counter
            row_counts = Counter(raw_rows)
            for (topic, kind, connector, operation), count in row_counts.items():
                op_display = f"{operation} (×{count})" if count > 1 else operation
                lines.append(f"| {topic} | {kind} | {connector} | {op_display} |")
        else:
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
            c
            for c in profile.components
            if c.kind == "DialogComponent"
            and c.trigger_kind not in (_SYSTEM_TRIGGERS | _AUTOMATION_TRIGGERS | {None})
            and c.dialog_kind not in ("TaskDialog", "AgentDialog")
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
        c for c in profile.components if c.kind == "KnowledgeSourceComponent" and (c.description or c.source_kind)
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


def render_knowledge_inventory(profile: BotProfile) -> str:
    """Render knowledge architecture view combining sources and files."""
    ks_comps = [c for c in profile.components if c.kind == "KnowledgeSourceComponent"]
    file_comps = [c for c in profile.components if c.kind == "FileAttachmentComponent"]

    if not ks_comps and not file_comps:
        return ""

    lines = ["## Knowledge Inventory\n"]

    if ks_comps:
        lines.append(f"### Knowledge Sources ({len(ks_comps)})\n")
        lines.append("| Name | Type | Site | Trigger | Status |")
        lines.append("| --- | --- | --- | --- | --- |")
        for comp in ks_comps:
            source_type = comp.source_kind or "—"
            site = comp.source_site or "—"
            trigger = comp.trigger_condition_raw or "auto"
            if trigger.lower() == "false":
                trigger = "⚠ always-on"
            state_icon = "✓" if comp.state == "Active" else "✗"
            lines.append(f"| {comp.display_name} | {source_type} | {site} | {trigger} | {state_icon} |")
        lines.append("")

    if file_comps:
        lines.append(f"### File Attachments ({len(file_comps)})\n")
        lines.append("| File | Type | Status |")
        lines.append("| --- | --- | --- |")
        for comp in file_comps:
            ftype = comp.file_type or "—"
            state_icon = "✓" if comp.state == "Active" else "✗"
            lines.append(f"| {comp.display_name} | {ftype} | {state_icon} |")
        lines.append("")

    total = len(ks_comps) + len(file_comps)
    active = sum(1 for c in ks_comps + file_comps if c.state == "Active")
    lines.append(f"**Summary:** {total} knowledge entries, {active} active\n")

    return "\n".join(lines)


_SEVERITY_ICON: dict[str, str] = {
    "fail": "\U0001f534",      # red circle
    "warning": "\U0001f7e1",   # yellow circle
    "info": "\U0001f535",      # blue circle
    "pass": "\U0001f7e2",      # green circle
}


def render_quick_wins(profile: BotProfile) -> str:
    """Surface actionable issues the user would miss reading raw config."""
    from parser import validate_connections

    findings: list[str] = []
    n = 0

    def _fmt(severity: str, text: str) -> str:
        nonlocal n
        n += 1
        icon = _SEVERITY_ICON.get(severity, "\u26aa")
        return f"{n}. {icon} **{severity}** — {text}"

    # 1. Disabled topics
    for comp in profile.components:
        if comp.kind == "DialogComponent" and comp.state != "Active":
            findings.append(
                _fmt("warning", f'Disabled topic: "{comp.display_name}" — '
                     "Topic is inactive. Enable or remove to reduce clutter.")
            )

    # 2. No trigger queries (user topics only)
    for comp in profile.components:
        if (
            comp.kind == "DialogComponent"
            and not comp.trigger_queries
            and comp.trigger_kind
            and comp.trigger_kind not in _SYSTEM_TRIGGERS
            and comp.trigger_kind not in _AUTOMATION_TRIGGERS
        ):
            findings.append(
                _fmt("warning", f'No trigger queries: "{comp.display_name}" — '
                     "User topic has no trigger phrases. It may never be matched by the recognizer.")
            )

    # 3. Weak descriptions
    for comp in profile.components:
        if comp.kind == "DialogComponent":
            desc = comp.description
            if desc is None or len(desc) < 10 or desc.strip() == comp.display_name.strip():
                if desc is None:
                    reason_detail = "missing"
                elif len(desc) < 10:
                    reason_detail = f'too short: "{desc}"'
                else:
                    reason_detail = "matches display name"
                findings.append(
                    _fmt("info", f'Weak description: "{comp.display_name}" — {reason_detail}')
                )

    # 4. Missing system topics
    trigger_kinds = {c.trigger_kind for c in profile.components if c.trigger_kind}
    for trigger in ("OnError", "OnUnknownIntent", "OnEscalate"):
        if trigger not in trigger_kinds:
            findings.append(
                _fmt("warning", f"Missing system topic: {trigger} — No handler for this lifecycle event.")
            )

    # 5. Unused global variables (heuristic)
    global_vars = [c for c in profile.components if c.kind == "GlobalVariableComponent"]
    other_schemas = set()
    for c in profile.components:
        if c.kind != "GlobalVariableComponent":
            if c.description:
                other_schemas.add(c.description)
            if c.schema_name:
                other_schemas.add(c.schema_name)
    all_text = " ".join(other_schemas)
    for gv in global_vars:
        if gv.schema_name and gv.schema_name not in all_text:
            findings.append(
                _fmt("info", f'Possibly unused variable: "{gv.display_name}" — '
                     "Schema name not found in other component references (heuristic).")
            )

    # 6. Connection reference issues
    conn_issues = validate_connections(profile)
    for issue in conn_issues:
        icon = _SEVERITY_ICON.get(issue["severity"], "\u26aa")
        n += 1
        findings.append(f"{n}. {icon} **{issue['severity']}** — {issue['message']}")

    if not findings:
        return ""

    lines = ["## Quick Wins\n"]
    lines.extend(findings)
    lines.append("")
    return "\n".join(lines)


def render_trigger_overlaps(overlaps: list[dict]) -> str:
    """Render trigger query overlap warnings as markdown table."""
    if not overlaps:
        return ""

    lines = [
        "### Trigger Query Overlaps\n",
        "Topics with >50% token overlap in trigger phrases may cause disambiguation issues.\n",
        "| Topic A | Topic B | Overlap | Shared Tokens |",
        "|---------|---------|---------|---------------|",
    ]
    for o in overlaps:
        shared = ", ".join(o["shared_tokens"][:8])
        if len(o["shared_tokens"]) > 8:
            shared += f" (+{len(o['shared_tokens']) - 8} more)"
        lines.append(f"| {o['topic_a']} | {o['topic_b']} | {o['overlap_pct']}% | {shared} |")
    lines.append("")
    return "\n".join(lines)


def render_knowledge_coverage(profile: BotProfile) -> str:
    """Render knowledge source status and coverage overview."""
    ks_comps = [c for c in profile.components if c.kind in ("KnowledgeSourceComponent", "FileAttachmentComponent")]
    if not ks_comps:
        return ""

    lines = [
        "## Knowledge Source Coverage\n",
        "| Name | Type | State | Trigger Condition | Notes |",
        "|------|------|-------|-------------------|-------|",
    ]

    for comp in ks_comps:
        name = comp.display_name or comp.schema_name
        source_type = comp.source_kind or comp.file_type or comp.kind.replace("Component", "")
        state = comp.state
        trigger = comp.trigger_condition_raw or "—"

        notes_parts: list[str] = []
        if state != "Active":
            notes_parts.append("Inactive")
        if trigger in ("false", "False"):
            notes_parts.append("Trigger disabled")
        elif trigger in ("—", "None"):
            notes_parts.append("Always-on")
        notes = "; ".join(notes_parts) if notes_parts else "—"

        lines.append(f"| {name} | {source_type} | {state} | {trigger} | {notes} |")

    lines.append("")
    return "\n".join(lines)


def render_security_summary(profile: BotProfile) -> str:
    """Render security and access configuration summary."""
    tools = [c for c in profile.components if c.tool_type]
    if not tools and profile.authentication_mode == "Unknown" and profile.access_control_policy == "Unknown":
        return ""

    auth_display = profile.authentication_mode
    if profile.authentication_trigger != "Unknown":
        auth_display += f" ({profile.authentication_trigger})"

    maker_count = sum(1 for t in tools if t.connection_mode == "Maker")
    invoker_count = sum(1 for t in tools if t.connection_mode == "Invoker")

    lines = [
        "## Security Inventory\n",
        f"**Auth:** {auth_display} | **Access:** {profile.access_control_policy} | **Agent Connectable:** {'Yes' if profile.is_agent_connectable else 'No'}\n",
        "| Property | Value |",
        "| --- | --- |",
        f"| Authentication | {auth_display} |",
        f"| Access Control | {profile.access_control_policy} |",
        f"| Agent Connectable | {'Yes' if profile.is_agent_connectable else 'No'} |",
    ]
    if tools:
        lines.append(f"| Connection Modes | {maker_count} Maker, {invoker_count} Invoker |")
    lines.append("")
    return "\n".join(lines)


def render_tool_inventory(profile: BotProfile) -> str:
    """Render tool inventory for orchestrator bots."""
    tools = [c for c in profile.components if c.tool_type]
    if not tools:
        return ""

    connector_tools = sum(1 for t in tools if t.tool_type == "ConnectorTool")
    agent_tools = sum(1 for t in tools if t.tool_type in ("ChildAgent", "ConnectedAgent", "A2AAgent"))
    mcp_servers = sum(1 for t in tools if t.tool_type == "MCPServer")

    lines = [
        "## Tool Inventory\n",
        f"**{len(tools)} tools** | {connector_tools} connector | {agent_tools} agent | {mcp_servers} MCP\n",
        "| Tool | Type | Connector | Mode | State | Description |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for t in tools:
        desc = (t.description or t.model_description or "—").replace("|", "\\|").replace("\n", " ").replace("\r", "")
        connector = t.connector_display_name or "—"
        mode = t.connection_mode or "—"
        lines.append(f"| {t.display_name} | {t.tool_type} | {connector} | {mode} | {t.state} | {desc} |")
    lines.append("")
    return "\n".join(lines)


def render_integration_map(profile: BotProfile) -> str:
    """Render Mermaid integration map showing agent connections."""
    tools = [c for c in profile.components if c.tool_type]
    ks_comps = [c for c in profile.components if c.kind in ("KnowledgeSourceComponent", "FileAttachmentComponent")]
    mcp_connectors = [cd for cd in profile.connector_definitions if cd.get("hasMCP")]

    if not tools and not ks_comps and not mcp_connectors:
        return ""

    lines = ["## Integration Map\n", "```mermaid", "flowchart LR"]
    agent_id = "Agent"
    lines.append(f'    {agent_id}["{_sanitize_mermaid(profile.display_name)}"]')

    node_idx = 0

    # Group connector tools by connector name
    connector_groups: dict[str, list[ComponentSummary]] = {}
    for t in tools:
        if t.tool_type == "ConnectorTool":
            key = t.connector_display_name or t.display_name
            connector_groups.setdefault(key, []).append(t)
        elif t.tool_type == "ChildAgent":
            node_id = f"child{node_idx}"
            node_idx += 1
            lines.append(f'    {node_id}["{_sanitize_mermaid(t.display_name)}"]')
            lines.append(f"    {agent_id} -->|child agent| {node_id}")
        elif t.tool_type == "ConnectedAgent":
            node_id = f"conn{node_idx}"
            node_idx += 1
            lines.append(f'    {node_id}["{_sanitize_mermaid(t.display_name)}"]')
            lines.append(f"    {agent_id} -->|connected agent| {node_id}")
        elif t.tool_type == "A2AAgent":
            node_id = f"a2a{node_idx}"
            node_idx += 1
            lines.append(f'    {node_id}["{_sanitize_mermaid(t.display_name)}"]')
            lines.append(f"    {agent_id} -->|A2A| {node_id}")
        elif t.tool_type == "MCPServer":
            node_id = f"mcp{node_idx}"
            node_idx += 1
            lines.append(f'    {node_id}["{_sanitize_mermaid(t.display_name)}"]')
            lines.append(f"    {agent_id} -->|MCP| {node_id}")
        elif t.tool_type == "FlowTool":
            node_id = f"flow{node_idx}"
            node_idx += 1
            lines.append(f'    {node_id}["{_sanitize_mermaid(t.display_name)}"]')
            lines.append(f"    {agent_id} -->|flow| {node_id}")

    for group_name, group_tools in connector_groups.items():
        node_id = f"ctr{node_idx}"
        node_idx += 1
        label = f"{_sanitize_mermaid(group_name)} ({len(group_tools)} ops)"
        lines.append(f'    {node_id}["{label}"]')
        lines.append(f"    {agent_id} -->|connector| {node_id}")

    # MCP from connector definitions (not component-level)
    for mcp_cd in mcp_connectors:
        node_id = f"mcpcd{node_idx}"
        node_idx += 1
        lines.append(f'    {node_id}["{_sanitize_mermaid(mcp_cd.get("displayName", "MCP"))} MCP"]')
        lines.append(f"    {agent_id} -.->|MCP connector| {node_id}")

    # Knowledge sources
    if ks_comps:
        ks_id = f"ks{node_idx}"
        node_idx += 1
        lines.append(f'    {ks_id}[("Knowledge ({len(ks_comps)} sources)")]')
        lines.append(f"    {agent_id} -->|search| {ks_id}")

    lines.extend(["```", ""])
    return "\n".join(lines)


def detect_topic_graph_anomalies(profile: BotProfile) -> dict[str, int]:
    """Detect orphaned topics, dead ends, and cycles in the topic graph.

    Returns dict with keys: orphaned, dead_ends, cycles (counts).
    """
    if not profile.topic_connections:
        return {"orphaned": 0, "dead_ends": 0, "cycles": 0}

    nodes: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    for conn in profile.topic_connections:
        src_id = _make_participant_id(conn.source_display)
        tgt_id = _make_participant_id(conn.target_display)
        nodes[src_id] = conn.source_display
        nodes[tgt_id] = conn.target_display
        edge_key = (src_id, tgt_id)
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            edges.append(edge_key)

    schema_to_component: dict[str, ComponentSummary] = {}
    display_to_schema: dict[str, str] = {}
    for comp in profile.components:
        if comp.schema_name:
            schema_to_component[comp.schema_name] = comp
        if comp.display_name:
            display_to_schema[comp.display_name] = comp.schema_name

    inbound: dict[str, set[str]] = {nid: set() for nid in nodes}
    outbound: dict[str, set[str]] = {nid: set() for nid in nodes}
    for src, tgt in edges:
        outbound.setdefault(src, set()).add(tgt)
        inbound.setdefault(tgt, set()).add(src)

    orphaned = 0
    for nid, display in nodes.items():
        if inbound.get(nid):
            continue
        schema = display_to_schema.get(display, "")
        comp = schema_to_component.get(schema)
        if comp and comp.trigger_kind and comp.trigger_kind in (_SYSTEM_TRIGGERS | _AUTOMATION_TRIGGERS):
            continue
        orphaned += 1

    dead_ends = 0
    for nid, display in nodes.items():
        if outbound.get(nid):
            continue
        schema = display_to_schema.get(display, "")
        comp = schema_to_component.get(schema)
        if comp and comp.action_summary:
            has_terminal = any(
                k in comp.action_summary for k in ("EndConversation", "TransferToAgent", "EscalateToAgent")
            )
            if has_terminal:
                continue
        dead_ends += 1

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in nodes}
    cycle_nodes: set[str] = set()
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for src, tgt in edges:
        adj[src].append(tgt)

    def _dfs(node: str) -> None:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            if color.get(neighbor) == GRAY:
                cycle_nodes.add(node)
                cycle_nodes.add(neighbor)
            elif color.get(neighbor) == WHITE:
                _dfs(neighbor)
        color[node] = BLACK

    for nid in nodes:
        if color.get(nid) == WHITE:
            _dfs(nid)

    return {"orphaned": orphaned, "dead_ends": dead_ends, "cycles": len(cycle_nodes)}


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

    # Build schema_to_component lookup for annotation checks
    schema_to_component: dict[str, ComponentSummary] = {}
    display_to_schema: dict[str, str] = {}
    for comp in profile.components:
        if comp.schema_name:
            schema_to_component[comp.schema_name] = comp
        if comp.display_name:
            display_to_schema[comp.display_name] = comp.schema_name

    # Build inbound/outbound maps from edges
    inbound: dict[str, set[str]] = {nid: set() for nid in nodes}
    outbound: dict[str, set[str]] = {nid: set() for nid in nodes}
    for src, tgt, _ in edges:
        outbound.setdefault(src, set()).add(tgt)
        inbound.setdefault(tgt, set()).add(src)

    # Detect orphaned topics (no inbound edges, excluding system/automation entry points)
    orphaned_nodes: set[str] = set()
    for nid, display in nodes.items():
        if inbound.get(nid):
            continue
        schema = display_to_schema.get(display, "")
        comp = schema_to_component.get(schema)
        if comp and comp.trigger_kind and comp.trigger_kind in (_SYSTEM_TRIGGERS | _AUTOMATION_TRIGGERS):
            continue
        orphaned_nodes.add(nid)

    # Detect dead ends (no outbound edges and no EndConversation/TransferToAgent)
    dead_end_nodes: set[str] = set()
    for nid, display in nodes.items():
        if outbound.get(nid):
            continue
        schema = display_to_schema.get(display, "")
        comp = schema_to_component.get(schema)
        if comp and comp.action_summary:
            has_terminal = any(
                k in comp.action_summary for k in ("EndConversation", "TransferToAgent", "EscalateToAgent")
            )
            if has_terminal:
                continue
        dead_end_nodes.add(nid)

    # Detect cycles via DFS
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in nodes}
    cycle_nodes: set[str] = set()
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for src, tgt, _ in edges:
        adj[src].append(tgt)

    def _dfs(node: str) -> None:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            if color.get(neighbor) == GRAY:
                cycle_nodes.add(node)
                cycle_nodes.add(neighbor)
            elif color.get(neighbor) == WHITE:
                _dfs(neighbor)
        color[node] = BLACK

    for nid in nodes:
        if color.get(nid) == WHITE:
            _dfs(nid)

    lines = ["## Topic Connection Graph\n"]

    # Anomaly summary before diagram
    anomalies = detect_topic_graph_anomalies(profile)
    anomaly_parts = []
    if anomalies["orphaned"]:
        anomaly_parts.append(f"{anomalies['orphaned']} orphaned")
    if anomalies["dead_ends"]:
        anomaly_parts.append(f"{anomalies['dead_ends']} dead ends")
    if anomalies["cycles"]:
        anomaly_parts.append(f"{anomalies['cycles']} cycles")
    if anomaly_parts:
        lines.append(f"> **Anomalies:** {', '.join(anomaly_parts)}\n")

    lines.extend(["```mermaid", '%%{init: {"useMaxWidth": false}}%%', "graph TD"])
    lines.append("    classDef warning fill:#fef3cd,stroke:#856404,color:#856404")
    lines.append("    classDef danger fill:#f8d7da,stroke:#842029,color:#842029")

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

    for nid in orphaned_nodes | dead_end_nodes:
        if nid in nodes:
            lines.append(f"    class {nid} warning")
    for nid in cycle_nodes:
        if nid in nodes:
            lines.append(f"    class {nid} danger")

    lines.append("```")

    # Legend
    has_annotations = orphaned_nodes or dead_end_nodes or cycle_nodes
    if has_annotations:
        lines.append("")
        legend_parts: list[str] = []
        if orphaned_nodes:
            legend_parts.append(
                f"**Yellow:** orphaned topics ({len(orphaned_nodes)}) or dead ends ({len(dead_end_nodes)})"
            )
        elif dead_end_nodes:
            legend_parts.append(f"**Yellow:** dead-end topics ({len(dead_end_nodes)})")
        if cycle_nodes:
            legend_parts.append(f"**Red:** cycle detected ({len(cycle_nodes)} nodes)")
        lines.append("*Legend: " + " · ".join(legend_parts) + "*")

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

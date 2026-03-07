import json
import re
from pathlib import Path

import yaml

from models import AISettings, AppInsightsConfig, BotProfile, ComponentSummary, GptInfo, TopicConnection


def _sanitize_yaml(text: str) -> str:
    """Fix YAML that contains characters PyYAML can't handle."""
    # Replace tabs with spaces (YAML spec disallows tabs for indentation, but they appear in values too)
    text = text.replace("\t", "    ")
    # Quote bare keys starting with @ (e.g. `@odata.type: String` -> `"@odata.type": String`)
    text = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', text, flags=re.MULTILINE)
    # Quote bare values starting with @ (e.g. `displayName: @mention tag` -> `displayName: "@mention tag"`)
    text = re.sub(r"(:\s+)(@[^\n]+)$", lambda m: m.group(1) + '"' + m.group(2) + '"', text, flags=re.MULTILINE)
    return text


_EXTERNAL_ACTION_KINDS = {"InvokeConnectorAction", "InvokeFlowAction", "InvokeAIBuilderModelAction", "HttpRequestAction"}


def _count_action_kinds(actions: list) -> dict[str, int]:
    """Recursively walk action trees and count action kinds."""
    counts: dict[str, int] = {}
    if not actions:
        return counts
    for action in actions:
        if not isinstance(action, dict):
            continue
        kind = action.get("kind", "")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
        # Recurse into nested action lists
        for key in ("actions", "elseActions"):
            nested = action.get(key)
            if isinstance(nested, list):
                for k, v in _count_action_kinds(nested).items():
                    counts[k] = counts.get(k, 0) + v
        # Recurse into conditions
        for cond in action.get("conditions", []) or []:
            if isinstance(cond, dict):
                for key in ("actions", "elseActions"):
                    nested = cond.get(key)
                    if isinstance(nested, list):
                        for k, v in _count_action_kinds(nested).items():
                            counts[k] = counts.get(k, 0) + v
    return counts


def _extract_gpt_info(comp: dict) -> GptInfo:
    """Extract GPT configuration from a GptComponent."""
    metadata = comp.get("metadata", {}) or {}
    ai_settings = metadata.get("aISettings", {}) or {}
    model = ai_settings.get("model", {}) or {}
    capabilities = metadata.get("gptCapabilities", {}) or {}
    ks = metadata.get("knowledgeSources", {}) or {}

    return GptInfo(
        display_name=metadata.get("displayName", "") or comp.get("displayName", ""),
        description=comp.get("description"),
        instructions=metadata.get("instructions"),
        model_hint=model.get("modelNameHint"),
        knowledge_sources_kind=ks.get("kind"),
        web_browsing=capabilities.get("webBrowsing", False),
        code_interpreter=capabilities.get("codeInterpreter", False),
        conversation_starters=metadata.get("conversationStarters", []) or [],
    )


def _extract_begin_dialogs(
    actions: list,
    source_schema: str,
    source_display: str,
    schema_to_display: dict[str, str],
    condition: str | None = None,
) -> list[TopicConnection]:
    """Recursively walk dialog actions and extract BeginDialog connections."""
    connections: list[TopicConnection] = []
    if not actions:
        return connections

    for action in actions:
        if not isinstance(action, dict):
            continue
        kind = action.get("kind", "")

        if kind == "BeginDialog":
            target_schema = action.get("dialog", "")
            if target_schema:
                target_display = schema_to_display.get(target_schema, "")
                if not target_display:
                    parts = target_schema.split(".")
                    target_display = parts[-1] if len(parts) >= 2 else target_schema
                connections.append(
                    TopicConnection(
                        source_schema=source_schema,
                        source_display=source_display,
                        target_schema=target_schema,
                        target_display=target_display,
                        condition=condition,
                    )
                )

        elif kind == "ConditionGroup":
            for cond in action.get("conditions", []) or []:
                if not isinstance(cond, dict):
                    continue
                cond_expr = cond.get("condition")
                connections.extend(
                    _extract_begin_dialogs(
                        cond.get("actions", []) or [],
                        source_schema,
                        source_display,
                        schema_to_display,
                        condition=cond_expr,
                    )
                )
            connections.extend(
                _extract_begin_dialogs(
                    action.get("elseActions", []) or [],
                    source_schema,
                    source_display,
                    schema_to_display,
                    condition="else",
                )
            )

        # Recurse into any nested actions/elseActions on other action kinds
        if kind != "ConditionGroup":
            for key in ("actions", "elseActions"):
                nested = action.get(key)
                if isinstance(nested, list):
                    connections.extend(
                        _extract_begin_dialogs(
                            nested,
                            source_schema,
                            source_display,
                            schema_to_display,
                            condition=condition,
                        )
                    )

    return connections


def parse_yaml(path: Path) -> tuple[BotProfile, dict[str, str]]:
    """Parse botContent.yml and return (BotProfile, schema_to_display_name lookup)."""
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(_sanitize_yaml(raw))

    entity = data.get("entity", {})
    config = entity.get("configuration", {})

    # Channels
    channels_raw = config.get("channels", []) or []
    channels = [ch.get("channelId", "") for ch in channels_raw if isinstance(ch, dict)]

    # AI settings
    ai_raw = config.get("aISettings", {}) or {}
    ai_settings = AISettings(
        use_model_knowledge=ai_raw.get("useModelKnowledge", False),
        file_analysis=ai_raw.get("isFileAnalysisEnabled", False),
        semantic_search=ai_raw.get("isSemanticSearchEnabled", False),
        content_moderation=ai_raw.get("contentModeration", "Unknown"),
        opt_in_latest_models=ai_raw.get("optInUseLatestModels", False),
    )

    # Recognizer
    recognizer = config.get("recognizer", {}) or {}
    recognizer_kind = recognizer.get("kind", "Unknown")

    # Components + lookup table
    components: list[ComponentSummary] = []
    schema_to_display: dict[str, str] = {}
    is_orchestrator = False

    for comp in data.get("components", []) or []:
        kind = comp.get("kind", "Unknown")
        display_name = comp.get("displayName", "")
        schema_name = comp.get("schemaName", "")
        state = comp.get("state", "Active")
        description = comp.get("description")

        # Extract dialog metadata
        dialog = comp.get("dialog", {}) or {}
        dialog_kind = dialog.get("kind")
        trigger_kind = None
        action_kind = None

        begin_dialog = dialog.get("beginDialog", {}) or {}
        if begin_dialog:
            trigger_kind = begin_dialog.get("kind")

        # Tool classification for TaskDialog/AgentDialog
        tool_type = None
        connection_reference = None
        operation_id = None
        connection_mode = None
        external_agent_protocol = None
        connected_bot_schema = None
        agent_instructions = None

        if dialog_kind in ("TaskDialog", "AgentDialog"):
            is_orchestrator = True
            action = dialog.get("action", {}) or {}
            action_kind = action.get("kind")
            connection_reference = action.get("connectionReference")
            operation_id = action.get("operationId")
            conn_props = action.get("connectionProperties", {}) or {}
            connection_mode = conn_props.get("mode")

            if dialog_kind == "AgentDialog":
                tool_type = "ChildAgent"
                settings = dialog.get("settings", {}) or {}
                agent_instructions = settings.get("instructions")
            elif action_kind == "InvokeConnectorTaskAction":
                tool_type = "ConnectorTool"
            elif action_kind == "InvokeExternalAgentTaskAction":
                op_details = action.get("operationDetails", {}) or {}
                protocol_kind = op_details.get("kind")
                external_agent_protocol = protocol_kind
                operation_id = operation_id or op_details.get("operationId")
                if protocol_kind == "AgentToAgentProtocolMetadata":
                    tool_type = "A2AAgent"
                elif protocol_kind == "ModelContextProtocolMetadata":
                    tool_type = "MCPServer"
                else:
                    tool_type = "ExternalAgent"
            elif action_kind == "InvokeConnectedAgentTaskAction":
                tool_type = "ConnectedAgent"
                connected_bot_schema = action.get("botSchemaName")
            elif action_kind == "InvokeFlowAction":
                tool_type = "FlowTool"
            elif action_kind == "InvokeComputerUseAction":
                tool_type = "CUATool"
            elif dialog_kind == "PromptDialog":
                tool_type = "AIPrompt"

        # GptComponent fallback for display name
        if kind == "GptComponent" and not display_name:
            metadata = comp.get("metadata", {}) or {}
            display_name = metadata.get("displayName", schema_name)

        # DialogComponent: extract trigger queries, model description, action summary
        model_description = None
        trigger_queries: list[str] = []
        action_summary: dict[str, int] = {}
        has_external_calls = False
        if kind == "DialogComponent":
            model_description = dialog.get("modelDescription")
            trigger_queries = begin_dialog.get("intent", {}).get("triggerQueries", []) or []
            dialog_actions = begin_dialog.get("actions", []) or []
            action_summary = _count_action_kinds(dialog_actions)
            has_external_calls = bool(set(action_summary) & _EXTERNAL_ACTION_KINDS)

        # KnowledgeSourceComponent: extract source config + trigger condition
        source_kind = None
        source_site = None
        trigger_condition_raw = None
        if kind == "KnowledgeSourceComponent":
            ks_config = comp.get("configuration", {}) or {}
            source = ks_config.get("source", {}) or {}
            source_kind = source.get("kind")
            source_site = source.get("siteName") or source.get("siteUrl")
            tc = source.get("triggerCondition")
            trigger_condition_raw = str(tc) if tc is not None else None

        # CustomEntityComponent: entity kind + item count
        entity_kind = None
        entity_item_count = 0
        if kind == "CustomEntityComponent":
            entity_data = comp.get("entity", {}) or {}
            entity_kind = entity_data.get("kind")
            entity_item_count = len(entity_data.get("items", []) or [])

        # FileAttachmentComponent: file type from extension
        file_type = None
        if kind == "FileAttachmentComponent" and display_name:
            parts = display_name.rsplit(".", 1)
            if len(parts) == 2:
                file_type = parts[1].lower()

        # GlobalVariableComponent: variable scope
        variable_scope = None
        if kind == "GlobalVariableComponent":
            variable_data = comp.get("variable", {}) or {}
            variable_scope = variable_data.get("scope")

        components.append(
            ComponentSummary(
                kind=kind,
                display_name=display_name,
                schema_name=schema_name,
                state=state,
                trigger_kind=trigger_kind,
                dialog_kind=dialog_kind,
                action_kind=action_kind,
                description=description,
                model_description=model_description,
                trigger_queries=trigger_queries,
                action_summary=action_summary,
                has_external_calls=has_external_calls,
                source_kind=source_kind,
                source_site=source_site,
                tool_type=tool_type,
                connection_reference=connection_reference,
                operation_id=operation_id,
                connection_mode=connection_mode,
                external_agent_protocol=external_agent_protocol,
                connected_bot_schema=connected_bot_schema,
                agent_instructions=agent_instructions,
                entity_kind=entity_kind,
                entity_item_count=entity_item_count,
                file_type=file_type,
                variable_scope=variable_scope,
                trigger_condition_raw=trigger_condition_raw,
            )
        )

        if schema_name and display_name:
            schema_to_display[schema_name] = display_name

    # Display name: prefer GptComponent displayName, fallback to entity displayName, then schemaName
    bot_display_name = entity.get("displayName", "")
    if not bot_display_name:
        gpt_comps = [c for c in components if c.kind == "GptComponent"]
        if gpt_comps:
            bot_display_name = gpt_comps[0].display_name
    if not bot_display_name:
        bot_display_name = entity.get("schemaName", "Unknown Bot")

    # Second pass: extract GPT info and topic connections
    gpt_info: GptInfo | None = None
    topic_connections: list[TopicConnection] = []

    for comp in data.get("components", []) or []:
        kind = comp.get("kind", "")

        if kind == "GptComponent" and gpt_info is None:
            gpt_info = _extract_gpt_info(comp)

        if kind == "DialogComponent":
            comp_schema = comp.get("schemaName", "")
            comp_display = schema_to_display.get(comp_schema, comp.get("displayName", comp_schema))
            dialog = comp.get("dialog", {}) or {}
            begin_dialog = dialog.get("beginDialog", {}) or {}
            dialog_actions = begin_dialog.get("actions", []) or []
            topic_connections.extend(
                _extract_begin_dialogs(dialog_actions, comp_schema, comp_display, schema_to_display)
            )

    # Extract environment variables and connectors from config
    env_vars = config.get("environmentVariables", []) or []
    connectors_raw = config.get("connectors", []) or []

    # Entity-level properties (Phase 1)
    auth_mode = entity.get("authenticationMode", "Unknown")
    auth_trigger = entity.get("authenticationTrigger", "Unknown")
    access_control = entity.get("accessControlPolicy", "Unknown")
    settings = config.get("settings", {}) or {}
    gen_actions = settings.get("GenerativeActionsEnabled", False)
    is_agent_connectable = config.get("isAgentConnectable", False)
    is_lightweight_bot = config.get("isLightweightBot", False)

    # Application Insights (Phase 1 A5)
    app_insights_raw = config.get("applicationInsights", {}) or {}
    app_insights = None
    if app_insights_raw:
        app_insights = AppInsightsConfig(
            configured=True,
            log_activities=app_insights_raw.get("logActivities", False),
            log_sensitive_properties=app_insights_raw.get("logSensitiveProperties", False),
        )

    # Connection infrastructure (Phase 3)
    connection_refs_raw = data.get("connectionReferences", []) or []
    connection_references = []
    for ref in connection_refs_raw:
        if not isinstance(ref, dict):
            continue
        connection_references.append({
            "connectionReferenceLogicalName": ref.get("connectionReferenceLogicalName", ""),
            "connectorId": ref.get("connectorId", ""),
            "customConnectorId": ref.get("customConnectorId"),
            "displayName": ref.get("displayName", ""),
            "connectionId": ref.get("connectionId", ""),
        })

    connector_defs_raw = data.get("connectorDefinitions", []) or []
    connector_definitions = []
    for cdef in connector_defs_raw:
        if not isinstance(cdef, dict):
            continue
        operations = cdef.get("operations", []) or []
        display_name = cdef.get("displayName", "") or ""
        has_mcp = (
            "mcp" in display_name.lower()
            or any(
                (op.get("operationId", "") or "").startswith(("InvokeMCP", "mcp_"))
                for op in operations
                if isinstance(op, dict)
            )
        )
        connector_definitions.append({
            "connectorId": cdef.get("connectorId", ""),
            "displayName": cdef.get("displayName", ""),
            "isCustom": cdef.get("isCustom", False),
            "connectorType": cdef.get("connectorType", ""),
            "operationCount": len(operations),
            "hasMCP": has_mcp,
        })

    # Cross-reference: build connection_ref → connector display name lookup
    connector_id_to_name: dict[str, str] = {}
    for cdef in connector_definitions:
        cid = cdef.get("connectorId", "")
        if cid:
            connector_id_to_name[cid] = cdef.get("displayName", "")

    ref_logical_to_connector: dict[str, str] = {}
    for ref in connection_references:
        logical = ref.get("connectionReferenceLogicalName", "")
        cid = ref.get("connectorId", "")
        if logical and cid and cid in connector_id_to_name:
            ref_logical_to_connector[logical] = connector_id_to_name[cid]

    # Enrich components with resolved connector names
    for comp_summary in components:
        if comp_summary.connection_reference and comp_summary.connection_reference in ref_logical_to_connector:
            comp_summary.connector_display_name = ref_logical_to_connector[comp_summary.connection_reference]

    profile = BotProfile(
        schema_name=entity.get("schemaName", ""),
        bot_id=entity.get("cdsBotId", ""),
        display_name=bot_display_name,
        channels=channels,
        ai_settings=ai_settings,
        recognizer_kind=recognizer_kind,
        components=components,
        environment_variables=env_vars,
        connectors=connectors_raw,
        is_orchestrator=is_orchestrator,
        gpt_info=gpt_info,
        topic_connections=topic_connections,
        authentication_mode=auth_mode,
        authentication_trigger=auth_trigger,
        access_control_policy=access_control,
        generative_actions_enabled=gen_actions,
        is_agent_connectable=is_agent_connectable,
        is_lightweight_bot=is_lightweight_bot,
        app_insights=app_insights,
        connection_references=connection_references,
        connector_definitions=connector_definitions,
    )

    return profile, schema_to_display


def parse_dialog_json(path: Path) -> list[dict]:
    """Parse dialog.json and return activities sorted by position."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    activities = data.get("activities", [])

    def get_position(activity: dict) -> int:
        channel_data = activity.get("channelData", {}) or {}
        return channel_data.get("webchat:internal:position", 0)

    activities.sort(key=get_position)
    return activities


def resolve_topic_name(schema_name: str, lookup: dict[str, str]) -> str:
    """Resolve a schema name like 'copilots_header_21961.topic.GenAIAnsGeneration' to a display name."""
    if schema_name in lookup:
        return lookup[schema_name]

    # Fallback: extract last segment after the last dot
    parts = schema_name.split(".")
    if len(parts) >= 2:
        return parts[-1]
    return schema_name

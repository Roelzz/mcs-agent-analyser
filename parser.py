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


_EXTERNAL_ACTION_KINDS = {
    "InvokeConnectorAction",
    "InvokeFlowAction",
    "InvokeAIBuilderModelAction",
    "HttpRequestAction",
}


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
    return _parse_bot_dict(data)


def parse_bot_data(data: dict) -> tuple[BotProfile, dict[str, str]]:
    """Public entry point for pre-built dicts (e.g. from Dataverse)."""
    return _parse_bot_dict(data)


def _parse_bot_dict(data: dict) -> tuple[BotProfile, dict[str, str]]:
    """Core parsing logic shared by file-based and Dataverse-based flows."""
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
        connection_references.append(
            {
                "connectionReferenceLogicalName": ref.get("connectionReferenceLogicalName", ""),
                "connectorId": ref.get("connectorId", ""),
                "customConnectorId": ref.get("customConnectorId"),
                "displayName": ref.get("displayName", ""),
                "connectionId": ref.get("connectionId", ""),
            }
        )

    connector_defs_raw = data.get("connectorDefinitions", []) or []
    connector_definitions = []
    for cdef in connector_defs_raw:
        if not isinstance(cdef, dict):
            continue
        operations = cdef.get("operations", []) or []
        display_name = cdef.get("displayName", "") or ""
        has_mcp = "mcp" in display_name.lower() or any(
            (op.get("operationId", "") or "").startswith(("InvokeMCP", "mcp_"))
            for op in operations
            if isinstance(op, dict)
        )
        connector_definitions.append(
            {
                "connectorId": cdef.get("connectorId", ""),
                "displayName": cdef.get("displayName", ""),
                "isCustom": cdef.get("isCustom", False),
                "connectorType": cdef.get("connectorType", ""),
                "operationCount": len(operations),
                "hasMCP": has_mcp,
            }
        )

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


def validate_connections(profile: BotProfile) -> list[dict]:
    """Cross-reference connection_references against connector_definitions and component usage."""
    issues: list[dict] = []

    # Build sets
    connector_ids = {cd.get("connectorId", "") for cd in profile.connector_definitions if cd.get("connectorId")}
    ref_logical_names: list[str] = []
    ref_connector_map: dict[str, str] = {}
    for ref in profile.connection_references:
        logical = ref.get("connectionReferenceLogicalName", "")
        cid = ref.get("connectorId", "")
        if logical:
            ref_logical_names.append(logical)
            ref_connector_map[logical] = cid

    # Connection refs actually used by components
    used_refs = {c.connection_reference for c in profile.components if c.connection_reference}

    # Flag: missing connectors — connection ref points to unknown connector ID
    for logical, cid in ref_connector_map.items():
        if cid and cid not in connector_ids:
            issues.append({
                "severity": "warning",
                "message": f"Missing connector definition for connection reference '{logical}'",
                "detail": f"Connection reference '{logical}' points to connector ID '{cid}' which has no matching connector definition.",
            })

    # Flag: duplicate references — same logical name appears twice
    seen: set[str] = set()
    for name in ref_logical_names:
        if name in seen:
            issues.append({
                "severity": "warning",
                "message": f"Duplicate connection reference: '{name}'",
                "detail": f"The logical name '{name}' appears more than once in connection references.",
            })
        seen.add(name)

    # Flag: orphaned connectors — connector definition not referenced by any connection ref
    referenced_connector_ids = set(ref_connector_map.values())
    for cd in profile.connector_definitions:
        cid = cd.get("connectorId", "")
        if cid and cid not in referenced_connector_ids:
            display = cd.get("displayName", cid)
            issues.append({
                "severity": "info",
                "message": f"Orphaned connector definition: '{display}'",
                "detail": f"Connector '{display}' (ID: {cid}) is defined but not referenced by any connection reference.",
            })

    # Flag: unused refs — connection ref not used by any component
    ref_set = set(ref_logical_names)
    for logical in ref_set - used_refs:
        issues.append({
            "severity": "info",
            "message": f"Unused connection reference: '{logical}'",
            "detail": f"Connection reference '{logical}' is defined but not used by any component.",
        })

    return issues


def detect_trigger_overlaps(components: list[ComponentSummary]) -> list[dict]:
    """Compare trigger queries across topics using normalized token overlap."""
    # Filter DialogComponents with non-empty trigger_queries
    topic_tokens: list[tuple[str, set[str]]] = []
    for comp in components:
        if comp.kind != "DialogComponent" or not comp.trigger_queries:
            continue
        tokens = set(" ".join(comp.trigger_queries).lower().split())
        if len(tokens) < 3:
            continue
        topic_tokens.append((comp.display_name, tokens))

    overlaps: list[dict] = []
    for i, (name_a, tokens_a) in enumerate(topic_tokens):
        for j in range(i + 1, len(topic_tokens)):
            name_b, tokens_b = topic_tokens[j]
            shared = tokens_a & tokens_b
            min_len = min(len(tokens_a), len(tokens_b))
            if min_len == 0:
                continue
            overlap_pct = len(shared) / min_len
            if overlap_pct > 0.5:
                overlaps.append({
                    "topic_a": name_a,
                    "topic_b": name_b,
                    "overlap_pct": round(overlap_pct * 100, 1),
                    "shared_tokens": sorted(shared),
                })

    overlaps.sort(key=lambda x: x["overlap_pct"], reverse=True)
    return overlaps


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


def build_bot_dict(bot_record: dict, component_records: list[dict]) -> dict:
    """Reconstruct a botContent.yml-equivalent dict from Dataverse bot + botcomponents records.

    Maps Dataverse lowercase column names to the camelCase keys expected by _parse_bot_dict.
    """
    from loguru import logger

    # Parse the bot's configuration JSON
    config_raw = bot_record.get("configuration", "") or ""
    config: dict = {}
    if config_raw:
        try:
            config = json.loads(config_raw) if isinstance(config_raw, str) else config_raw
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse bot configuration JSON: {e}")

    logger.debug(f"Bot config keys: {list(config.keys()) if config else '(empty)'}")

    # Build entity block
    entity = {
        "schemaName": bot_record.get("schemaname", ""),
        "cdsBotId": bot_record.get("botid", ""),
        "displayName": bot_record.get("name", ""),
        "description": bot_record.get("description", ""),
        "authenticationMode": config.get("authenticationMode", "Unknown"),
        "authenticationTrigger": config.get("authenticationTrigger", "Unknown"),
        "accessControlPolicy": config.get("accessControlPolicy", "Unknown"),
        "configuration": config,
    }

    # Parse each component
    logger.info(f"Processing {len(component_records)} raw component records from Dataverse")
    components: list[dict] = []
    skipped_empty = 0
    skipped_parse = 0
    for comp_record in component_records:
        content_raw = comp_record.get("content", "") or ""
        if not content_raw:
            if skipped_empty == 0:
                logger.debug(f"First empty-content record keys: {list(comp_record.keys())}")
            skipped_empty += 1
            continue

        comp_data: dict | None = None

        # Try YAML first, fall back to JSON
        try:
            comp_data = yaml.safe_load(_sanitize_yaml(content_raw))
        except Exception:
            pass

        if not isinstance(comp_data, dict):
            try:
                comp_data = json.loads(content_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        if not isinstance(comp_data, dict):
            skipped_parse += 1
            logger.warning(
                f"Skipping component {comp_record.get('name', '?')} — content is neither valid YAML nor JSON"
            )
            continue

        # Map Dataverse componenttype int to kind string
        comp_type = comp_record.get("componenttype")
        kind = _component_type_to_kind(comp_type, comp_data)

        logger.debug(
            "Component '{}': componenttype={}, content_kind={}, computed_kind={}",
            comp_record.get("name", "?"),
            comp_type,
            comp_data.get("kind"),
            kind,
        )

        # Merge schema-level fields from the record into the parsed content
        # If componenttype mapped to a known kind, force it (don't let inner YAML shadow)
        if comp_type is not None and comp_type in _COMPONENT_TYPE_MAP:
            # Dataverse content is flat — restructure to match botContent.yml wrapper format
            # that _parse_bot_dict expects (kind + dialog/metadata sub-keys)
            inner_kind = comp_data.get("kind", "")
            if kind == "DialogComponent" and inner_kind != "DialogComponent":
                # Content IS the dialog — wrap it: {kind: DialogComponent, dialog: <content>}
                wrapped = {
                    "kind": kind,
                    "dialog": comp_data,
                    "schemaName": comp_record.get("schemaname", ""),
                    "displayName": comp_record.get("name", ""),
                }
                comp_data = wrapped
            elif kind == "GptComponent" and inner_kind != "GptComponent":
                # Content IS the metadata — wrap it: {kind: GptComponent, metadata: <content>}
                wrapped = {
                    "kind": kind,
                    "metadata": comp_data,
                    "schemaName": comp_record.get("schemaname", ""),
                    "displayName": comp_record.get("name", ""),
                }
                comp_data = wrapped
            else:
                comp_data["kind"] = kind
        else:
            comp_data.setdefault("kind", kind)
        comp_data.setdefault("schemaName", comp_record.get("schemaname", ""))
        comp_data.setdefault("displayName", comp_record.get("name", ""))

        components.append(comp_data)

    logger.info(f"Components: {len(components)} valid, {skipped_empty} empty content, {skipped_parse} parse failures")

    # Extract connectionReferences and connectorDefinitions from config
    connection_references = config.get("connectionReferences", []) or []
    connector_definitions = config.get("connectorDefinitions", []) or []

    return {
        "entity": entity,
        "components": components,
        "connectionReferences": connection_references,
        "connectorDefinitions": connector_definitions,
    }


# Mapping from Dataverse botcomponent.componenttype (int) to kind strings
# Values discovered via diagnostic logging against live Dataverse instances
_COMPONENT_TYPE_MAP: dict[int, str] = {
    0: "DialogComponent",
    1: "GptComponent",
    2: "KnowledgeSourceComponent",
    3: "CustomEntityComponent",
    4: "FileAttachmentComponent",
    5: "GlobalVariableComponent",
    6: "SkillComponent",
    7: "BotSettingsComponent",
    9: "DialogComponent",  # Dataverse uses 9 for all dialog types
    15: "GptComponent",  # Dataverse uses 15 for GPT/AI components
}


def _component_type_to_kind(comp_type: int | None, comp_data: dict) -> str:
    """Resolve component kind from Dataverse componenttype int or content hints."""
    if comp_type is not None and comp_type in _COMPONENT_TYPE_MAP:
        return _COMPONENT_TYPE_MAP[comp_type]
    # Fallback: check if the content already has a kind field
    return comp_data.get("kind", "Unknown")

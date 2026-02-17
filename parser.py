import json
import re
from pathlib import Path

import yaml

from models import AISettings, BotProfile, ComponentSummary, GptInfo, TopicConnection


def _sanitize_yaml(text: str) -> str:
    """Fix YAML that contains characters PyYAML can't handle."""
    # Replace tabs with spaces (YAML spec disallows tabs for indentation, but they appear in values too)
    text = text.replace("\t", "    ")
    # Quote bare keys starting with @ (e.g. `@odata.type: String` -> `"@odata.type": String`)
    text = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', text, flags=re.MULTILINE)
    # Quote bare values starting with @ (e.g. `displayName: @mention tag` -> `displayName: "@mention tag"`)
    text = re.sub(r"(:\s+)(@[^\n]+)$", lambda m: m.group(1) + '"' + m.group(2) + '"', text, flags=re.MULTILINE)
    return text


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

        # Check for orchestrator patterns
        if dialog_kind in ("TaskDialog", "AgentDialog"):
            is_orchestrator = True
            action = dialog.get("action", {}) or {}
            action_kind = action.get("kind")

        # GptComponent fallback for display name
        if kind == "GptComponent" and not display_name:
            metadata = comp.get("metadata", {}) or {}
            display_name = metadata.get("displayName", schema_name)

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

    profile = BotProfile(
        schema_name=entity.get("schemaName", ""),
        bot_id=entity.get("cdsBotId", ""),
        display_name=bot_display_name,
        channels=channels,
        ai_settings=ai_settings,
        recognizer_kind=recognizer_kind,
        components=components,
        is_orchestrator=is_orchestrator,
        gpt_info=gpt_info,
        topic_connections=topic_connections,
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

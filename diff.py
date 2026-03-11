"""Bot comparison / diff engine."""

import difflib

from models import BotDiffResult, BotProfile, ComponentChange

_COMPARE_FIELDS = ("state", "trigger_queries", "description", "action_summary", "tool_type")


def compare_bots(a: BotProfile, b: BotProfile) -> BotDiffResult:
    """Compare two BotProfiles and return a structured diff."""
    result = BotDiffResult(
        bot_a_name=a.display_name or a.schema_name or "Bot A",
        bot_b_name=b.display_name or b.schema_name or "Bot B",
    )

    # --- Components ---
    a_map = {c.schema_name: c for c in a.components}
    b_map = {c.schema_name: c for c in b.components}

    a_keys = set(a_map.keys())
    b_keys = set(b_map.keys())

    result.added_components = sorted(b_keys - a_keys)
    result.removed_components = sorted(a_keys - b_keys)

    for schema in sorted(a_keys & b_keys):
        ca, cb = a_map[schema], b_map[schema]
        for field in _COMPARE_FIELDS:
            va = getattr(ca, field)
            vb = getattr(cb, field)
            if va != vb:
                result.changed_components.append(
                    ComponentChange(
                        schema_name=schema,
                        display_name=ca.display_name,
                        field=field,
                        value_a=str(va),
                        value_b=str(vb),
                    )
                )

    # --- Instructions ---
    instr_a = (a.gpt_info.instructions or "") if a.gpt_info else ""
    instr_b = (b.gpt_info.instructions or "") if b.gpt_info else ""
    if instr_a != instr_b:
        diff_lines = difflib.unified_diff(
            instr_a.splitlines(keepends=True),
            instr_b.splitlines(keepends=True),
            fromfile=result.bot_a_name,
            tofile=result.bot_b_name,
        )
        result.instruction_diff = "".join(diff_lines)

    # --- Connections ---
    a_conns = {(tc.source_schema, tc.target_schema) for tc in a.topic_connections}
    b_conns = {(tc.source_schema, tc.target_schema) for tc in b.topic_connections}

    for pair in sorted(b_conns - a_conns):
        result.connection_changes.append(f"+ {pair[0]} -> {pair[1]}")
    for pair in sorted(a_conns - b_conns):
        result.connection_changes.append(f"- {pair[0]} -> {pair[1]}")

    # --- Settings ---
    _compare_setting(
        result, "ai_settings.use_model_knowledge", a.ai_settings.use_model_knowledge, b.ai_settings.use_model_knowledge
    )
    _compare_setting(result, "ai_settings.file_analysis", a.ai_settings.file_analysis, b.ai_settings.file_analysis)
    _compare_setting(
        result, "ai_settings.semantic_search", a.ai_settings.semantic_search, b.ai_settings.semantic_search
    )
    _compare_setting(
        result, "ai_settings.content_moderation", a.ai_settings.content_moderation, b.ai_settings.content_moderation
    )
    _compare_setting(
        result,
        "ai_settings.opt_in_latest_models",
        a.ai_settings.opt_in_latest_models,
        b.ai_settings.opt_in_latest_models,
    )
    _compare_setting(result, "authentication_mode", a.authentication_mode, b.authentication_mode)
    _compare_setting(result, "access_control_policy", a.access_control_policy, b.access_control_policy)
    _compare_setting(result, "recognizer_kind", a.recognizer_kind, b.recognizer_kind)
    _compare_setting(result, "is_orchestrator", a.is_orchestrator, b.is_orchestrator)
    _compare_setting(result, "generative_actions_enabled", a.generative_actions_enabled, b.generative_actions_enabled)

    # --- Summary ---
    result.summary_markdown = _build_summary(result)

    return result


def _compare_setting(result: BotDiffResult, name: str, va: object, vb: object) -> None:
    if va != vb:
        result.settings_changes.append(f"{name}: {va} -> {vb}")


def _build_summary(diff: BotDiffResult) -> str:
    lines = [
        f"## Comparison: {diff.bot_a_name} vs {diff.bot_b_name}",
        "",
        "| Metric | Count |",
        "| --- | --- |",
        f"| Added components | {len(diff.added_components)} |",
        f"| Removed components | {len(diff.removed_components)} |",
        f"| Changed components | {len(diff.changed_components)} |",
        f"| Connection changes | {len(diff.connection_changes)} |",
        f"| Settings changes | {len(diff.settings_changes)} |",
        f"| Instruction diff | {'Yes' if diff.instruction_diff else 'No'} |",
    ]
    return "\n".join(lines)


def render_diff_report(diff: BotDiffResult) -> str:
    """Render a BotDiffResult as a full markdown report."""
    sections: list[str] = []

    # Summary table
    sections.append(diff.summary_markdown)

    # Component changes
    if diff.added_components or diff.removed_components or diff.changed_components:
        sections.append("\n## Component Changes\n")
        for name in diff.added_components:
            sections.append(f"- `+` **{name}** (added in {diff.bot_b_name})")
        for name in diff.removed_components:
            sections.append(f"- `-` **{name}** (removed from {diff.bot_b_name})")
        if diff.changed_components:
            sections.append("\n| Component | Field | Bot A | Bot B |")
            sections.append("| --- | --- | --- | --- |")
            for ch in diff.changed_components:
                sections.append(f"| {ch.display_name} | {ch.field} | {ch.value_a} | {ch.value_b} |")

    # Instruction diff
    if diff.instruction_diff:
        sections.append("\n## Instruction Diff\n")
        sections.append("```diff")
        sections.append(diff.instruction_diff)
        sections.append("```")

    # Connection changes
    if diff.connection_changes:
        sections.append("\n## Connection Changes\n")
        for change in diff.connection_changes:
            sections.append(f"- `{change}`")

    # Settings changes
    if diff.settings_changes:
        sections.append("\n## Settings Changes\n")
        for change in diff.settings_changes:
            sections.append(f"- {change}")

    return "\n".join(sections)

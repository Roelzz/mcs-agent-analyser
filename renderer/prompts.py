"""Static prompt assets harvested from botContent.yml.

Renders three blocks:
- Inline `SearchAndSummarizeContent.additionalInstructions` prompts (full text).
- A table of `aIModelDefinitions` (AI Builder prompt stubs) with call-site counts.
- One detail block per AI Builder model listing every call-site.

The AI Builder *prompt template body* lives in Dataverse, not the YAML export,
so the section caps itself with a portal-pointer note.
"""

from collections import Counter

from models import BotProfile

from ._helpers import _sanitize_table_cell


_DATAVERSE_NOTE = (
    "> AI Builder prompt bodies are stored in Dataverse, not in this YAML export."
    " Inspect them in the Copilot Studio portal under **AI Builder → Prompts**"
    " using the IDs above."
)


def render_prompts_section(profile: BotProfile) -> str:
    """Render the `## Prompts (static)` section. Returns "" when neither inline
    prompts nor AI Builder models are present."""
    if not profile.inline_prompts and not profile.ai_builder_models:
        return ""

    lines: list[str] = ["## Prompts (static)\n"]
    lines.append(
        "Prompt assets the bot author authored inside `botContent.yml`. Distinct from the"
        " main agent system prompt (see **AI Configuration**).\n"
    )

    if profile.inline_prompts:
        lines.append("### Inline prompts (SearchAndSummarizeContent)\n")
        lines.append(
            f"**{len(profile.inline_prompts)} prompt"
            f"{'s' if len(profile.inline_prompts) != 1 else ''}** found inside topic dialog actions.\n"
        )
        for p in profile.inline_prompts:
            lines.append(f"#### {p.host_topic_display} → {p.kind}\n")
            meta_bits = []
            if p.user_input:
                meta_bits.append(f"`userInput={p.user_input}`")
            if p.output_variable:
                meta_bits.append(f"`output={p.output_variable}`")
            if p.response_capture_type:
                meta_bits.append(f"`responseCaptureType={p.response_capture_type}`")
            if p.knowledge_sources_mode:
                meta_bits.append(f"`knowledgeSources={p.knowledge_sources_mode}`")
            if p.auto_send is not None:
                meta_bits.append(f"`autoSend={p.auto_send}`")
            if meta_bits:
                lines.append(" · ".join(meta_bits))
                lines.append("")
            lines.append(f"_{len(p.text)} chars._\n")
            lines.append("```")
            lines.append(p.text)
            lines.append("```\n")

    if profile.ai_builder_models:
        lines.append("### AI Builder prompt models\n")
        call_counts: Counter[str] = Counter(cs.model_id for cs in profile.ai_builder_call_sites)
        lines.append("| Name | Model ID | Input fields | Output fields | # call-sites |")
        lines.append("| --- | --- | --- | --- | ---: |")
        for m in profile.ai_builder_models:
            input_fields = ", ".join(_describe_type(m.input_type)) or "—"
            output_fields = ", ".join(_describe_type(m.output_type)) or "—"
            lines.append(
                f"| {_sanitize_table_cell(m.name)}"
                f" | `{m.id}`"
                f" | {_sanitize_table_cell(input_fields)}"
                f" | {_sanitize_table_cell(output_fields)}"
                f" | {call_counts.get(m.id, 0)} |"
            )
        lines.append("")

        if profile.ai_builder_call_sites:
            lines.append("#### Call-sites\n")
            sites_by_model: dict[str, list] = {}
            for cs in profile.ai_builder_call_sites:
                sites_by_model.setdefault(cs.model_id, []).append(cs)
            id_to_name = {m.id: m.name for m in profile.ai_builder_models}
            for model_id, sites in sites_by_model.items():
                name = id_to_name.get(model_id) or model_id
                lines.append(f"**{name}** (`{model_id}`)\n")
                for cs in sites:
                    bindings = []
                    for k, v in cs.input_bindings.items():
                        bindings.append(f"`{k}={v}`")
                    arrow = ", ".join(bindings) or "—"
                    outs = ", ".join(f"`{k}→{v}`" for k, v in cs.output_bindings.items()) or "—"
                    lines.append(f"- {cs.host_topic_display}: {arrow} → {outs}")
                lines.append("")

        lines.append(_DATAVERSE_NOTE)
        lines.append("")

    return "\n".join(lines)


def _describe_type(schema: dict) -> list[str]:
    """Render a JSON-schema-ish type dict from `aIModelDefinitions.input/outputType`
    as a flat list of field names. Falls back to top-level keys when the shape
    is unexpected."""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        return list(props.keys())
    schema_block = schema.get("schema")
    if isinstance(schema_block, dict):
        inner_props = schema_block.get("properties")
        if isinstance(inner_props, dict) and inner_props:
            return list(inner_props.keys())
    return [k for k in schema.keys() if k not in {"type", "kind"}]

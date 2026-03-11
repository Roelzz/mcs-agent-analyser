"""AGT001–AGT006: Bot configuration.json settings checks."""

from __future__ import annotations

import re
from pathlib import Path

from ._helpers import _fail, _info, _load_yaml, _pass, _read_xml, _warn


def _check_agent_config(work_dir: Path, schema: str) -> list[dict]:  # noqa: C901
    results: list[dict] = []
    config_path = work_dir / "bots" / schema / "configuration.json"

    if not config_path.exists():
        results.append(
            _warn(
                "AGT001",
                "Agent",
                "Bot configuration.json not found",
                f"No configuration.json found at bots/{schema}/configuration.json. Agent settings checks are skipped.",
            )
        )
        return results

    try:
        import json

        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        results.append(
            _fail(
                "AGT001",
                "Agent",
                "configuration.json could not be parsed",
                f"Failed to parse bots/{schema}/configuration.json: {exc}",
            )
        )
        return results

    # AGT001 — Agent has a description (pulled from gpt.default/botcomponent.xml)
    gpt_xml_path = work_dir / "botcomponents" / f"{schema}.gpt.default" / "botcomponent.xml"
    if gpt_xml_path.exists():
        fields = _read_xml(gpt_xml_path, "description")
        desc = fields.get("description", "").strip()
        if desc:
            results.append(
                _pass(
                    "AGT001",
                    "Agent",
                    "Agent description is present",
                    f'Description: "{desc}"',
                )
            )
        else:
            results.append(
                _warn(
                    "AGT001",
                    "Agent",
                    "Agent has no description",
                    "A description for the agent helps administrators understand its purpose. "
                    "Add one in Copilot Studio under Settings → General → Description.",
                )
            )
    else:
        results.append(
            _warn(
                "AGT001",
                "Agent",
                "GPT component (gpt.default) not found — description check skipped",
                f"Could not find botcomponents/{schema}.gpt.default/botcomponent.xml.",
            )
        )

    # AGT002 — Content moderation level
    ai_settings = config.get("aISettings", {}) or {}
    moderation = (ai_settings.get("contentModeration") or "").strip()
    if moderation.lower() in ("none", "off", "disabled", ""):
        results.append(
            _fail(
                "AGT002",
                "Agent",
                f"Content moderation is disabled ('{moderation or 'not set'}')",
                "Content moderation is turned off. This allows harmful, offensive, or inappropriate "
                "content to pass through the agent without filtering. Set to 'Medium' or 'High' in "
                "Copilot Studio under Settings → AI Capabilities → Content Moderation.",
            )
        )
    elif moderation.lower() == "low":
        results.append(
            _warn(
                "AGT002",
                "Agent",
                "Content moderation is set to Low",
                "Content moderation is set to 'Low', which provides minimal protection against "
                "harmful outputs. Consider raising to 'Medium' or 'High' for enterprise or "
                "public-facing agents.",
            )
        )
    elif moderation:
        results.append(
            _pass(
                "AGT002",
                "Agent",
                f"Content moderation is active ('{moderation}')",
                "Content moderation is enabled, providing a safety layer over agent responses.",
            )
        )

    # AGT003 — useModelKnowledge risk
    use_model_knowledge = bool(ai_settings.get("useModelKnowledge", False))
    # Check if grounding rules appear in instructions
    gpt_data_path = work_dir / "botcomponents" / f"{schema}.gpt.default" / "data"
    gpt_data = _load_yaml(gpt_data_path)
    instructions = gpt_data.get("instructions") or ""
    has_grounding = bool(
        re.search(
            r"\bground(ed|ing)?\b|\bexclusively from\b|\bonly (from|based on)\b|\bsearch result\b",
            instructions,
            re.I,
        )
    )

    if use_model_knowledge and not has_grounding:
        results.append(
            _warn(
                "AGT003",
                "Agent",
                "Model knowledge is enabled without grounding rules",
                "useModelKnowledge is true, meaning the agent can draw on broad LLM training data "
                "beyond provided knowledge sources. Without explicit grounding rules in the system "
                "instructions, the agent may hallucinate or answer questions outside its intended "
                "scope. Add grounding directives (e.g., 'Answer exclusively from provided search "
                "results') to constrain responses.",
            )
        )
    elif use_model_knowledge and has_grounding:
        results.append(
            _pass(
                "AGT003",
                "Agent",
                "Model knowledge enabled with grounding rules in place",
                "useModelKnowledge is true and the system instructions contain grounding directives "
                "that constrain the model to provided data sources.",
            )
        )
    else:
        results.append(
            _pass(
                "AGT003",
                "Agent",
                "Model knowledge is disabled (scoped knowledge sources only)",
                "useModelKnowledge is false. The agent will only use explicitly provided knowledge "
                "sources, reducing hallucination risk.",
            )
        )

    # AGT004 — Recognizer type (Generative AI is modern best practice)
    recognizer = config.get("recognizer", {}) or {}
    recognizer_kind = recognizer.get("$kind", "")
    if "GenerativeAI" in recognizer_kind or "Generative" in recognizer_kind:
        results.append(
            _pass(
                "AGT004",
                "Agent",
                "Generative AI recognizer in use",
                f"The agent uses the '{recognizer_kind}' recognizer, which is the modern "
                "recommended approach for Copilot Studio agents leveraging LLM-based intent "
                "recognition.",
            )
        )
    elif recognizer_kind:
        results.append(
            _warn(
                "AGT004",
                "Agent",
                f"Classic recognizer in use ('{recognizer_kind}')",
                f"The agent uses '{recognizer_kind}' instead of the Generative AI Recognizer. "
                "The classic recognizer relies on fixed trigger phrases and NLU training data, "
                "which is less flexible than the generative approach. Consider migrating to the "
                "Generative AI Recognizer for improved natural language understanding.",
            )
        )

    # AGT005 — publishOnImport
    publish_on_import = config.get("publishOnImport", None)
    if publish_on_import is True:
        results.append(
            _info(
                "AGT005",
                "Agent",
                "Agent will be auto-published on import (publishOnImport: true)",
                "The agent is configured to publish automatically when the solution is imported. "
                "This is convenient for deployments but means the agent becomes live immediately "
                "without a manual review step. Verify this is the intended behaviour for your "
                "target environment.",
            )
        )
    elif publish_on_import is False:
        results.append(
            _info(
                "AGT005",
                "Agent",
                "Agent requires manual publish after import (publishOnImport: false)",
                "The agent will not be published automatically on solution import. An administrator "
                "must manually publish the agent in the target environment before it becomes active.",
            )
        )

    # AGT006 — isAgentConnectable (exposes agent as a plugin/connector)
    is_connectable = config.get("isAgentConnectable", False)
    if is_connectable:
        results.append(
            _warn(
                "AGT006",
                "Agent",
                "Agent is connectable (isAgentConnectable: true)",
                "isAgentConnectable is set to true, meaning this agent can be invoked as a "
                "skill or plugin by other agents and systems. Ensure this is intentional and "
                "that the agent's scope, instructions, and access controls are appropriate "
                "for external invocation.",
            )
        )
    else:
        results.append(
            _pass(
                "AGT006",
                "Agent",
                "Agent is not exposed as a connectable plugin",
                "isAgentConnectable is false, limiting the agent's invocation to direct user "
                "sessions within its configured channels.",
            )
        )

    return results

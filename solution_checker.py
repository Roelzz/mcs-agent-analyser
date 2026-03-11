"""Solution Checker — static analysis for Power Platform Copilot Studio solution exports.

Mirrors the intent of the Power Platform Solution Checker (pac solution check) but
focuses on Copilot Studio agent-specific rules that the generic checker does not cover.

Rules are grouped into five categories:

  - Solution   : solution.xml metadata health
  - Agent      : bot configuration.json settings
  - Topics     : topic coverage and quality
  - Knowledge  : knowledge sources and capabilities
  - Security   : security and injection risks

Returns a structured result dict suitable for storing in Reflex state.
"""

from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

import defusedxml.ElementTree as ET

from utils import safe_extractall

try:
    import yaml as _yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False


# ── Category labels ────────────────────────────────────────────────────────────

CATEGORIES: list[str] = ["Solution", "Agent", "Topics", "Knowledge", "Security", "Orchestrator"]

_CAT_ICONS: dict[str, str] = {
    "Solution": "file-text",
    "Agent": "bot",
    "Topics": "list",
    "Knowledge": "database",
    "Security": "shield-alert",
    "Orchestrator": "network",
}

# System topics that every production agent should have
_REQUIRED_SYSTEM_TOPICS: dict[str, tuple[str, str]] = {
    # trigger → (display label, severity if absent)
    "OnError": ("On Error", "fail"),
    "OnUnknownIntent": ("Fallback (Unknown Intent)", "warning"),
    "OnConversationStart": ("Conversation Start", "warning"),
    "OnEscalate": ("Escalate", "warning"),
    "OnSignIn": ("Sign-In", "warning"),
}

# Patterns that look like hardcoded secrets / credentials
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|apikey|api[_-]?secret)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(client[_-]?secret|clientsecret)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(bearer\s+[A-Za-z0-9\-._~+/]+=*)"),
    re.compile(r"(?i)(access[_-]?token)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(connection[_-]?string)\s*[=:]\s*.{10,}"),
    # Typical Azure SAS / storage keys length
    re.compile(r"[A-Za-z0-9+/]{64,}={0,2}"),
]

# Prompt injection patterns (same set as validator.py rule 11)
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore (all |previous |above |prior |system |original )?instructions", re.I),
    re.compile(r"disregard (all |previous |above |prior )?instructions", re.I),
    re.compile(r"override (all |previous |above |prior )?instructions", re.I),
    re.compile(r"forget (all |your |previous )?instructions", re.I),
    re.compile(r"new (role|persona|objective):", re.I),
    re.compile(r"you are now (a |an )?(?!legal|financial|hr|support)", re.I),
    re.compile(r"pretend (you are|to be)", re.I),
    re.compile(r"act as (?!a |an |the )", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"DAN mode", re.I),
]


# ── Internal helpers ───────────────────────────────────────────────────────────


def _read_xml(path: Path, *tags: str) -> dict[str, str]:
    """Return {tag: text} from an XML file; empty string on any parse failure."""
    try:
        root = ET.parse(path).getroot()
        return {tag: root.findtext(tag) or "" for tag in tags}
    except Exception:
        return {tag: "" for tag in tags}


def _load_yaml(path: Path) -> dict:
    """Load a YAML file (Power Platform 'data'); return {} on any failure."""
    if not _YAML_AVAILABLE or not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        # Fix common PP YAML quirks
        raw = raw.replace("\t", "    ")
        raw = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', raw, flags=re.MULTILINE)
        raw = re.sub(
            r"(:\s+)(@[^\n]+)$",
            lambda m: m.group(1) + '"' + m.group(2) + '"',
            raw,
            flags=re.MULTILINE,
        )
        result = _yaml.safe_load(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _pass(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "pass", "detail": detail}


def _warn(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "warning", "detail": detail}


def _fail(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "fail", "detail": detail}


def _info(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "info", "detail": detail}


# ── Rule implementations ───────────────────────────────────────────────────────


def _check_solution_xml(work_dir: Path) -> list[dict]:
    results: list[dict] = []
    sol_path = work_dir / "solution.xml"

    if not sol_path.exists():
        results.append(
            _fail(
                "SOL001",
                "Solution",
                "solution.xml is missing",
                "The ZIP does not contain a solution.xml at the root level. This is required for "
                "all Power Platform solution imports.",
            )
        )
        # No point running further solution checks
        return results

    try:
        root = ET.parse(sol_path).getroot()
    except Exception as exc:
        results.append(
            _fail(
                "SOL001",
                "Solution",
                "solution.xml could not be parsed",
                f"The solution.xml could not be parsed as XML: {exc}. The file may be corrupt.",
            )
        )
        return results

    results.append(
        _pass(
            "SOL001",
            "Solution",
            "solution.xml is present and valid",
            "solution.xml exists and is well-formed XML.",
        )
    )

    # SOL002 — Publisher prefix not "new" (default publisher)
    manifest = root.find("SolutionManifest")
    if manifest is not None:
        prefix = (manifest.findtext("Publisher/CustomizationPrefix") or "").strip().lower()
        if prefix in ("new", "default", ""):
            results.append(
                _warn(
                    "SOL002",
                    "Solution",
                    f"Default publisher prefix detected ('{prefix or 'empty'}')",
                    "The solution uses the default publisher prefix. This is acceptable for development "
                    "but for production solutions you should create a dedicated publisher with a unique "
                    "prefix (e.g., your organisation abbreviation). Clashing prefixes cause import "
                    "conflicts when multiple solutions share the default publisher.",
                )
            )
        else:
            results.append(
                _pass(
                    "SOL002",
                    "Solution",
                    f"Custom publisher prefix in use ('{prefix}')",
                    f"The solution uses the publisher prefix '{prefix}', which is not the default. "
                    "This reduces the risk of naming conflicts with other solutions.",
                )
            )

    # SOL003 — Version is still 1.0.0.0
    version = (manifest.findtext("Version") if manifest is not None else None) or ""
    if version == "1.0.0.0":
        results.append(
            _warn(
                "SOL003",
                "Solution",
                "Solution version is the default (1.0.0.0)",
                "The solution version has not been incremented from the initial default. Before "
                "promoting to a Test or Production environment, update the version to reflect the "
                "release state (e.g., 1.1.0.0 or 2.0.0.0).",
            )
        )
    elif version:
        results.append(
            _pass(
                "SOL003",
                "Solution",
                f"Solution version is set ({version})",
                f"The solution carries version {version}, indicating it has been versioned for promotion.",
            )
        )

    # SOL004 — Solution description
    if manifest is not None:
        desc_node = manifest.find("Descriptions/Description")
        desc = (desc_node.get("description") or "").strip() if desc_node is not None else ""
        if not desc:
            results.append(
                _warn(
                    "SOL004",
                    "Solution",
                    "Solution has no description",
                    "Adding a description to the solution helps administrators understand its purpose "
                    "without opening each component. Edit this in your Power Platform environment under "
                    "Solutions → Properties.",
                )
            )
        else:
            results.append(
                _pass(
                    "SOL004",
                    "Solution",
                    "Solution description is present",
                    f'Solution description: "{desc}"',
                )
            )

    # SOL005 — Managed vs unmanaged
    managed = (manifest.findtext("Managed") if manifest is not None else None) or "0"
    if managed == "1":
        results.append(
            _info(
                "SOL005",
                "Solution",
                "Solution is managed",
                "This is a managed solution. Components cannot be edited directly in the target "
                "environment. This is the expected state for production deployments.",
            )
        )
    else:
        results.append(
            _info(
                "SOL005",
                "Solution",
                "Solution is unmanaged",
                "This is an unmanaged solution, which allows components to be edited after import. "
                "Consider exporting as managed for production environments to prevent accidental changes.",
            )
        )

    return results


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


def _check_topics(work_dir: Path, schema: str) -> list[dict]:
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    if not botcomponents_dir.exists():
        results.append(
            _warn(
                "TOP000",
                "Topics",
                "No botcomponents/ directory found",
                "The solution does not contain a botcomponents/ directory. Topic checks are skipped.",
            )
        )
        return results

    # Collect all topic components for this bot schema
    topics: list[dict] = []  # list of {folder, display_name, trigger_kind, state, has_actions}
    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        if folder.startswith("mspva_"):
            continue
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue

        xml_path = comp_dir / "botcomponent.xml"
        if not xml_path.exists():
            continue
        fields = _read_xml(xml_path, "name", "statecode")
        name = fields.get("name") or folder
        state = "active" if fields.get("statecode", "0") == "0" else "inactive"

        data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
        begin = data.get("beginDialog") or {}
        trigger_kind = begin.get("kind") or ""
        has_actions = bool(begin.get("actions"))
        topics.append(
            {
                "folder": folder,
                "display_name": name,
                "trigger_kind": trigger_kind,
                "state": state,
                "has_actions": has_actions,
            }
        )

    # TOP001–TOP005 — Required system topics
    found_triggers = {t["trigger_kind"] for t in topics}
    for trigger, (label, severity) in _REQUIRED_SYSTEM_TOPICS.items():
        if trigger in found_triggers:
            results.append(
                _pass(
                    "TOP001" if trigger == "OnError" else "TOP002",
                    "Topics",
                    f"'{label}' system topic is present",
                    f"The '{label}' topic (trigger: {trigger}) is included in the solution.",
                )
            )
        else:
            entry = _fail if severity == "fail" else _warn
            results.append(
                entry(
                    "TOP001" if trigger == "OnError" else "TOP002",
                    "Topics",
                    f"'{label}' system topic is missing",
                    f"No topic with a '{trigger}' trigger was found. This system topic is important "
                    f"for handling the corresponding lifecycle event. Consider adding it in Copilot "
                    f"Studio to ensure robust conversational flow.",
                )
            )

    # TOP003 — Inactive topics
    inactive = [t for t in topics if t["state"] == "inactive"]
    if inactive:
        names = ", ".join(t["display_name"] for t in inactive[:5])
        suffix = f" and {len(inactive) - 5} more" if len(inactive) > 5 else ""
        results.append(
            _warn(
                "TOP003",
                "Topics",
                f"{len(inactive)} inactive topic(s) detected",
                f"The following topic(s) are inactive and will not be triggered: {names}{suffix}. "
                "Inactive topics clutter the solution and may cause confusion during maintenance. "
                "Consider removing unused topics before promoting to production.",
            )
        )
    else:
        results.append(
            _pass(
                "TOP003",
                "Topics",
                "No inactive topics detected",
                "All topics in the solution are active.",
            )
        )

    # TOP004 — Empty topics (no actions in beginDialog)
    empty = [t for t in topics if not t["has_actions"] and t["trigger_kind"]]
    if empty:
        names = ", ".join(t["display_name"] for t in empty[:5])
        suffix = f" and {len(empty) - 5} more" if len(empty) > 5 else ""
        results.append(
            _warn(
                "TOP004",
                "Topics",
                f"{len(empty)} topic(s) have empty dialog (no actions)",
                f"The following topic(s) define a trigger but have no actions: {names}{suffix}. "
                "Empty topics will be triggered but do nothing, resulting in silent failures or "
                "confusing user experiences. Add at least one action (e.g., a message or redirect) "
                "or disable the topic.",
            )
        )
    else:
        results.append(
            _pass(
                "TOP004",
                "Topics",
                "All topics have dialog actions defined",
                "No topics were found with triggers but empty dialog action lists.",
            )
        )

    # TOP005 — Large topic count
    user_topics = [
        t
        for t in topics
        if t["trigger_kind"]
        and t["trigger_kind"]
        not in (
            "OnError",
            "OnUnknownIntent",
            "OnConversationStart",
            "OnEscalate",
            "OnSignIn",
            "OnRedirect",
            "OnActivity",
            "OnInactivity",
            "OnSystemRedirect",
            "OnSelectIntent",
        )
    ]
    user_count = len(user_topics)
    if user_count > 100:
        results.append(
            _warn(
                "TOP005",
                "Topics",
                f"Very large number of user topics ({user_count})",
                f"The solution contains {user_count} user-triggered topics. Agents with more than "
                "100 user topics can be difficult to maintain and may experience slower topic "
                "disambiguation at runtime. Consider consolidating related topics or off-loading "
                "logic to Power Automate flows.",
            )
        )
    elif user_count > 50:
        results.append(
            _warn(
                "TOP005",
                "Topics",
                f"High number of user topics ({user_count})",
                f"The solution contains {user_count} user-triggered topics. This is manageable but "
                "consider grouping topics into logical sections and using redirect chains to keep "
                "the topic list navigable.",
            )
        )
    else:
        results.append(
            _pass(
                "TOP005",
                "Topics",
                f"Topic count is within a manageable range ({user_count} user topics)",
                f"The solution contains {user_count} user-triggered topics, which is within the "
                "recommended range for maintainability.",
            )
        )

    return results


def _check_knowledge(work_dir: Path, schema: str, config: dict) -> list[dict]:
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    # KNO001 — Has at least one knowledge source
    knowledge_dirs: list[Path] = []
    if botcomponents_dir.exists():
        for comp_dir in botcomponents_dir.iterdir():
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            parts = folder.split(".", 2)
            if len(parts) >= 2 and parts[0] == schema and parts[1] in ("file", "knowledge", "entity"):
                knowledge_dirs.append(comp_dir)

    if knowledge_dirs:
        results.append(
            _pass(
                "KNO001",
                "Knowledge",
                f"{len(knowledge_dirs)} knowledge source(s) / entity component(s) present",
                f"The solution includes {len(knowledge_dirs)} file/knowledge/entity component(s), "
                "providing grounding data for the agent.",
            )
        )
    else:
        results.append(
            _info(
                "KNO001",
                "Knowledge",
                "No knowledge sources found",
                "No file or knowledge source components were found. If this agent is expected to "
                "answer domain-specific questions, add knowledge sources in Copilot Studio under "
                "Knowledge → Add Knowledge.",
            )
        )

    # KNO002 — Oversized file attachments (> 20 MB)
    MAX_FILE_BYTES = 20 * 1024 * 1024
    large_files: list[tuple[str, int]] = []
    if botcomponents_dir.exists():
        for fdir in knowledge_dirs:
            filedata_dir = fdir / "filedata"
            if filedata_dir.exists():
                for f in filedata_dir.iterdir():
                    if f.is_file():
                        size = f.stat().st_size
                        if size > MAX_FILE_BYTES:
                            large_files.append((f.name, size))

    if large_files:
        details = "; ".join(f"{name} ({sz // 1024 // 1024} MB)" for name, sz in large_files[:5])
        results.append(
            _warn(
                "KNO002",
                "Knowledge",
                f"{len(large_files)} oversized knowledge file(s) detected",
                f"The following knowledge files exceed 20 MB: {details}. Very large files increase "
                "ZIP extraction time, solution import time, and may hit platform size limits. "
                "Consider chunking large documents or hosting them externally and referencing via "
                "SharePoint or URL knowledge sources.",
            )
        )
    else:
        results.append(
            _pass(
                "KNO002",
                "Knowledge",
                "No oversized knowledge files detected",
                "All knowledge source files are within the 20 MB recommended size limit.",
            )
        )

    # KNO003 — Semantic search enabled
    ai_settings = config.get("aISettings", {}) or {}
    semantic_search = bool(ai_settings.get("isSemanticSearchEnabled", False))
    if semantic_search:
        results.append(
            _pass(
                "KNO003",
                "Knowledge",
                "Semantic search is enabled",
                "isSemanticSearchEnabled is true. The agent will use vector-based semantic search "
                "over knowledge sources, improving recall for natural language queries compared to "
                "keyword matching.",
            )
        )
    else:
        results.append(
            _warn(
                "KNO003",
                "Knowledge",
                "Semantic search is disabled",
                "isSemanticSearchEnabled is false. The agent falls back to keyword-based search "
                "over knowledge sources, which may miss relevant documents when user phrasing "
                "differs from document text. Enable semantic search in Copilot Studio Settings → "
                "AI Capabilities for better knowledge retrieval.",
            )
        )

    # KNO004 — Web browsing enabled
    web_browsing = False
    settings = config.get("settings", {}) or {}
    for _key, sv in settings.items():
        if isinstance(sv, dict):
            caps = (sv.get("content") or {}).get("capabilities") or {}
            if caps.get("webBrowsing"):
                web_browsing = True
                break

    if web_browsing:
        results.append(
            _warn(
                "KNO004",
                "Knowledge",
                "Web browsing capability is enabled",
                "The agent has web browsing enabled, allowing it to retrieve information from the "
                "public internet in real time. This can lead to responses based on unverified "
                "sources. Ensure your system instructions explicitly scope what the agent may "
                "or may not retrieve via browsing, or disable web browsing if not required.",
            )
        )
    else:
        results.append(
            _pass(
                "KNO004",
                "Knowledge",
                "Web browsing is not enabled",
                "Web browsing is disabled. The agent relies solely on provided knowledge sources "
                "and model knowledge (if enabled), keeping responses grounded in controlled data.",
            )
        )

    return results


def _check_security(work_dir: Path, schema: str) -> list[dict]:  # noqa: C901
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    # SEC001 — Prompt injection patterns in topic data files
    injection_hits: list[tuple[str, str]] = []  # (topic_name, matched_pattern)
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            if folder.startswith("mspva_"):
                continue
            parts = folder.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            data_path = comp_dir / "data"
            if not data_path.exists():
                continue
            try:
                text = data_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in _INJECTION_PATTERNS:
                m = pat.search(text)
                if m:
                    xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
                    name = xml_fields.get("name") or folder
                    injection_hits.append((name, m.group(0)[:60]))
                    break  # one hit per component is enough

    if injection_hits:
        details = "; ".join(f"'{n}' (matched: \"{s}\")" for n, s in injection_hits[:3])
        suffix = f" and {len(injection_hits) - 3} more" if len(injection_hits) > 3 else ""
        results.append(
            _fail(
                "SEC001",
                "Security",
                f"Prompt injection patterns detected in {len(injection_hits)} topic(s)",
                f"Potential prompt injection or instruction-override language found in: {details}{suffix}. "
                "System instructions and topic content must not contain language that could override "
                "the agent's safety constraints. Review and sanitise the affected topics before "
                "deploying to production.",
            )
        )
    else:
        results.append(
            _pass(
                "SEC001",
                "Security",
                "No prompt injection patterns detected in topic content",
                "None of the topic data files contain common prompt injection or instruction-override patterns.",
            )
        )

    # SEC002 — Hardcoded secrets / credentials in topic data
    secret_hits: list[tuple[str, str]] = []
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            if folder.startswith("mspva_"):
                continue
            parts = folder.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            data_path = comp_dir / "data"
            if not data_path.exists():
                continue
            try:
                text = data_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in _SECRET_PATTERNS:
                m = pat.search(text)
                if m:
                    xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
                    name = xml_fields.get("name") or folder
                    # Only flag high-confidence patterns (skip long base64 if it's in known-safe contexts)
                    matched = m.group(0)
                    # Skip base64 blobs that appear inside filedata (legitimate binary encoding)
                    if len(matched) > 100 and "filedata" in str(comp_dir):
                        continue
                    secret_hits.append((name, matched[:40]))
                    break

    if secret_hits:
        names = ", ".join(f"'{n}'" for n, _ in secret_hits[:3])
        suffix = f" and {len(secret_hits) - 3} more" if len(secret_hits) > 3 else ""
        results.append(
            _warn(
                "SEC002",
                "Security",
                f"Possible hardcoded credential patterns in {len(secret_hits)} component(s)",
                f"Patterns resembling hardcoded secrets were found in: {names}{suffix}. "
                "Credentials must not be embedded in topic data or bot configuration. "
                "Use Power Platform Environment Variables or Azure Key Vault references instead. "
                "Review the flagged components and remove or replace any embedded secrets.",
            )
        )
    else:
        results.append(
            _pass(
                "SEC002",
                "Security",
                "No hardcoded credential patterns detected",
                "No patterns resembling hardcoded API keys, passwords, or tokens were found in "
                "the botcomponent data files.",
            )
        )

    # SEC003 — File analysis enabled (can process uploaded files from users)
    config_path = work_dir / "bots" / schema / "configuration.json"
    file_analysis_enabled = False
    if config_path.exists():
        try:
            import json

            config = json.loads(config_path.read_text(encoding="utf-8"))
            ai_settings = config.get("aISettings", {}) or {}
            file_analysis_enabled = bool(ai_settings.get("isFileAnalysisEnabled", False))
        except Exception:
            pass

    if file_analysis_enabled:
        results.append(
            _warn(
                "SEC003",
                "Security",
                "File analysis (user file uploads) is enabled",
                "isFileAnalysisEnabled is true, allowing end users to upload files directly to "
                "the agent for analysis. This expands the attack surface: users could upload "
                "malicious documents or attempt prompt injection through file content. Ensure "
                "this capability is required for the agent's use case, and that uploaded content "
                "is processed safely.",
            )
        )
    else:
        results.append(
            _pass(
                "SEC003",
                "Security",
                "File upload analysis is disabled",
                "isFileAnalysisEnabled is false. End users cannot upload files to this agent.",
            )
        )

    return results


def _check_orchestrator(work_dir: Path, schema: str) -> list[dict]:
    """ORCH001-ORCH005: Orchestrator-specific health checks."""
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    if not botcomponents_dir.exists():
        return results

    # Collect TaskDialog / AgentDialog components
    agent_topics: list[dict] = []  # {folder, display_name, dialog_kind, connection_ref, model_desc}
    all_topics: list[dict] = []

    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        if folder.startswith("mspva_"):
            continue
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue

        data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
        dialog_kind = data.get("kind", "")
        xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
        display_name = xml_fields.get("name") or folder

        topic_info = {
            "folder": folder,
            "display_name": display_name,
            "dialog_kind": dialog_kind,
        }
        all_topics.append(topic_info)

        if dialog_kind in ("TaskDialog", "AgentDialog"):
            action = data.get("action", {}) or {}
            conn_ref = action.get("connectionReference", "")
            settings = data.get("settings", {}) or {}
            model_desc = (data.get("modelDescription") or "").strip().lower()

            topic_info["connection_reference"] = conn_ref
            topic_info["model_description"] = model_desc
            topic_info["instructions"] = (settings.get("instructions") or "").strip()
            agent_topics.append(topic_info)

    if not agent_topics:
        return results

    # ORCH001: Child agents have connection references
    missing_conn = [t for t in agent_topics if not t.get("connection_reference")]
    if missing_conn:
        names = ", ".join(t["display_name"] for t in missing_conn[:5])
        suffix = f" and {len(missing_conn) - 5} more" if len(missing_conn) > 5 else ""
        results.append(
            _warn(
                "ORCH001",
                "Orchestrator",
                f"{len(missing_conn)} agent tool(s) missing connection references",
                f"The following TaskDialog/AgentDialog components have no connectionReference: "
                f"{names}{suffix}. Without a connection reference, the orchestrator cannot invoke "
                "the agent at runtime.",
            )
        )
    else:
        results.append(
            _pass(
                "ORCH001",
                "Orchestrator",
                "All agent tools have connection references",
                "Every TaskDialog/AgentDialog component has a connectionReference configured.",
            )
        )

    # ORCH002: Fallback handler exists (OnUnknownIntent)
    has_fallback = False
    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue
        data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
        begin = data.get("beginDialog") or {}
        if begin.get("kind") == "OnUnknownIntent":
            has_fallback = True
            break

    if has_fallback:
        results.append(
            _pass(
                "ORCH002",
                "Orchestrator",
                "Fallback handler (OnUnknownIntent) is present",
                "The orchestrator has a topic with OnUnknownIntent trigger to handle unmatched user input.",
            )
        )
    else:
        results.append(
            _warn(
                "ORCH002",
                "Orchestrator",
                "No fallback handler (OnUnknownIntent) found",
                "The orchestrator has no topic with OnUnknownIntent trigger. Without a fallback, "
                "unmatched user input will produce no response. Add a fallback topic.",
            )
        )

    # ORCH003: No single agent >70% of routed topics
    ref_counts: dict[str, int] = {}
    for t in agent_topics:
        ref = t.get("connection_reference", "") or "unset"
        ref_counts[ref] = ref_counts.get(ref, 0) + 1

    total_agent = len(agent_topics)
    if total_agent > 1:
        for ref, count in ref_counts.items():
            ratio = count / total_agent
            if ratio > 0.7:
                results.append(
                    _warn(
                        "ORCH003",
                        "Orchestrator",
                        f"Single agent handles {ratio:.0%} of routed topics",
                        f"Connection reference '{ref}' handles {count}/{total_agent} agent topics. "
                        "If one agent dominates, the orchestrator adds latency without meaningful "
                        "routing. Consider simplifying or rebalancing.",
                    )
                )
                break
        else:
            results.append(
                _pass(
                    "ORCH003",
                    "Orchestrator",
                    "Agent workload is distributed across connections",
                    f"{len(ref_counts)} distinct connection references handle {total_agent} agent topics.",
                )
            )

    # ORCH004: Distinct agent descriptions
    seen_descs: dict[str, list[str]] = {}
    for t in agent_topics:
        md = t.get("model_description", "")
        if md:
            seen_descs.setdefault(md, []).append(t["display_name"])
    duplicates = {desc: names for desc, names in seen_descs.items() if len(names) > 1}
    if duplicates:
        dup_detail = "; ".join(
            f"'{names[0]}' and '{names[1]}'" + (f" (+{len(names)-2} more)" if len(names) > 2 else "")
            for names in duplicates.values()
        )
        results.append(
            _warn(
                "ORCH004",
                "Orchestrator",
                f"{len(duplicates)} set(s) of agents share identical descriptions",
                f"Agents with duplicate modelDescription: {dup_detail}. "
                "The orchestrator uses descriptions to route — duplicates cause ambiguous routing.",
            )
        )
    else:
        results.append(
            _pass(
                "ORCH004",
                "Orchestrator",
                "All agent descriptions are distinct",
                "Each agent tool has a unique modelDescription, enabling clear routing decisions.",
            )
        )

    # ORCH005: External agent ratio (mostly-router check)
    if total_agent > 0 and len(all_topics) > 0:
        agent_ratio = total_agent / max(len(all_topics), 1)
        if agent_ratio > 0.8:
            results.append(
                _info(
                    "ORCH005",
                    "Orchestrator",
                    f"High agent-to-topic ratio ({agent_ratio:.0%})",
                    f"{total_agent} of {len(all_topics)} topics are agent tools. "
                    "This orchestrator is primarily a router with minimal native logic.",
                )
            )
        else:
            results.append(
                _pass(
                    "ORCH005",
                    "Orchestrator",
                    f"Balanced topic mix ({total_agent} agent tools / {len(all_topics)} total topics)",
                    "The orchestrator has a mix of native topics and delegated agent tools.",
                )
            )

    return results


# ── Main entry point ───────────────────────────────────────────────────────────


def check_solution_zip(zip_bytes: bytes) -> dict:
    """Run all solution checks against a Power Platform solution ZIP.

    Args:
        zip_bytes: Raw bytes of the solution ZIP file.

    Returns:
        A dict with keys:
          - ``results``: list of check result dicts (rule_id, category, title, severity, detail)
          - ``agent_name``: detected agent display name
          - ``solution_name``: detected solution unique name
          - ``pass_count``, ``warn_count``, ``fail_count``, ``info_count``: summary counts
          - ``error``: non-empty string if the ZIP could not be parsed at all
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        return {
            "results": [],
            "agent_name": "",
            "solution_name": "",
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "info_count": 0,
            "error": f"Invalid ZIP file: {exc}",
        }

    # Ensure it looks like a solution ZIP
    has_solution = any(n == "bots" or n.startswith("bots/") for n in names)
    if not has_solution:
        return {
            "results": [],
            "agent_name": "",
            "solution_name": "",
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "info_count": 0,
            "error": (
                "Uploaded file does not appear to be a Power Platform solution ZIP "
                "(no bots/ directory found). Solution check requires a solution export."
            ),
        }

    results: list[dict] = []
    agent_name = ""
    solution_name = ""
    bot_config: dict = {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, work_dir)

        # Detect bot schema
        bots_dir = work_dir / "bots"
        bot_folders = [d for d in bots_dir.iterdir() if d.is_dir()] if bots_dir.exists() else []
        schema = bot_folders[0].name if bot_folders else ""

        # Detect agent / solution names for the summary header
        if schema:
            gpt_xml = work_dir / "botcomponents" / f"{schema}.gpt.default" / "botcomponent.xml"
            if gpt_xml.exists():
                agent_name = _read_xml(gpt_xml, "name").get("name", schema)
            else:
                agent_name = schema

            config_path = work_dir / "bots" / schema / "configuration.json"
            if config_path.exists():
                try:
                    import json

                    bot_config = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        sol_xml = work_dir / "solution.xml"
        if sol_xml.exists():
            try:
                root = ET.parse(sol_xml).getroot()
                manifest = root.find("SolutionManifest")
                if manifest is not None:
                    solution_name = manifest.findtext("UniqueName") or ""
            except Exception:
                pass

        # ── Run all check groups ────────────────────────────────────────
        results.extend(_check_solution_xml(work_dir))
        if schema:
            results.extend(_check_agent_config(work_dir, schema))
            results.extend(_check_topics(work_dir, schema))
            results.extend(_check_knowledge(work_dir, schema, bot_config))
            results.extend(_check_security(work_dir, schema))
            # Orchestrator checks (only if agent has TaskDialog/AgentDialog)
            botcomponents_dir = work_dir / "botcomponents"
            is_orchestrator = False
            if botcomponents_dir.exists():
                for comp_dir in botcomponents_dir.iterdir():
                    if not comp_dir.is_dir():
                        continue
                    folder = comp_dir.name
                    parts = folder.split(".", 2)
                    if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
                        continue
                    data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
                    if data.get("kind") in ("TaskDialog", "AgentDialog"):
                        is_orchestrator = True
                        break
            if is_orchestrator:
                results.extend(_check_orchestrator(work_dir, schema))
        else:
            results.append(
                _fail(
                    "AGT000",
                    "Agent",
                    "No bot schema detected",
                    "Could not detect a bot schema name from the bots/ directory. "
                    "Agent, topic, knowledge, and security checks are skipped.",
                )
            )

    pass_count = sum(1 for r in results if r["severity"] == "pass")
    warn_count = sum(1 for r in results if r["severity"] == "warning")
    fail_count = sum(1 for r in results if r["severity"] == "fail")
    info_count = sum(1 for r in results if r["severity"] == "info")

    return {
        "results": results,
        "agent_name": agent_name,
        "solution_name": solution_name,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "info_count": info_count,
        "error": "",
    }

"""Validator — validate agent system instructions against model-specific best practices.

Supports models from GPT-4.1 and higher as used in Power Platform Copilot Studio.
Returns structured validation results suitable for storage in Reflex state.
"""

from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

from utils import safe_extractall

try:
    import yaml as _yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False

BEST_PRACTICES_DIR = Path(__file__).parent / "best_practices"

# ── Model catalogue ────────────────────────────────────────────────────────────

# Power Platform modelNameHint values -> internal key (None = below GPT-4.1 threshold)
_HINT_TO_KEY: dict[str, str | None] = {
    # GPT-4.1 family
    "GPT41": "gpt41",
    "gpt-4.1": "gpt41",
    "gpt41": "gpt41",
    "GPT41Mini": "gpt41mini",
    "gpt-4.1-mini": "gpt41mini",
    "gpt41mini": "gpt41mini",
    "GPT41Nano": "gpt41nano",
    "gpt-4.1-nano": "gpt41nano",
    "gpt41nano": "gpt41nano",
    # GPT-5 family
    "GPT5": "gpt5",
    "gpt-5": "gpt5",
    "gpt5": "gpt5",
    "GPT5Chat": "gpt5chat",
    "gpt-5-chat": "gpt5chat",
    "gpt5chat": "gpt5chat",
    # o-series reasoning models
    "o1": "o1",
    "o1-preview": "o1",
    "o1-mini": "o1",
    "o3": "o3",
    "o3-mini": "o3",
    "o4-mini": "o4mini",
    "o4mini": "o4mini",
    # Below threshold — not assessed
    "GPT4o": None,
    "gpt-4o": None,
    "gpt-4o-mini": None,
    "gpt-4": None,
    "GPT4": None,
}

# Per-model validation parameters
_MODEL_META: dict[str, dict] = {
    "gpt41": {
        "display": "GPT-4.1",
        "min_length_fail": 50,
        "min_length_warn": 200,
        "max_length_warn": 8_000,
        "check_grounding": False,
        "is_reasoning": False,
        "is_compact": False,
    },
    "gpt41mini": {
        "display": "GPT-4.1 Mini",
        "min_length_fail": 30,
        "min_length_warn": 100,
        "max_length_warn": 3_000,
        "check_grounding": False,
        "is_reasoning": False,
        "is_compact": True,
    },
    "gpt41nano": {
        "display": "GPT-4.1 Nano",
        "min_length_fail": 20,
        "min_length_warn": 75,
        "max_length_warn": 1_500,
        "check_grounding": False,
        "is_reasoning": False,
        "is_compact": True,
    },
    "gpt5": {
        "display": "GPT-5",
        "min_length_fail": 50,
        "min_length_warn": 200,
        "max_length_warn": 30_000,
        "check_grounding": True,
        "is_reasoning": False,
        "is_compact": False,
    },
    "gpt5chat": {
        "display": "GPT-5 Chat",
        "min_length_fail": 50,
        "min_length_warn": 200,
        "max_length_warn": 20_000,
        "check_grounding": True,
        "is_reasoning": False,
        "is_compact": False,
    },
    "o1": {
        "display": "o1",
        "min_length_fail": 30,
        "min_length_warn": 100,
        "max_length_warn": 10_000,
        "check_grounding": False,
        "is_reasoning": True,
        "is_compact": False,
    },
    "o3": {
        "display": "o3",
        "min_length_fail": 30,
        "min_length_warn": 100,
        "max_length_warn": 15_000,
        "check_grounding": True,
        "is_reasoning": True,
        "is_compact": False,
    },
    "o4mini": {
        "display": "o4-mini",
        "min_length_fail": 20,
        "min_length_warn": 75,
        "max_length_warn": 5_000,
        "check_grounding": False,
        "is_reasoning": True,
        "is_compact": True,
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _resolve_model_key(hint: str | None) -> str | None:
    """Return the internal model key for a Power Platform modelNameHint.

    Returns None when the hint is unknown or the model is below the GPT-4.1 threshold.
    """
    if hint is None:
        return None
    if hint in _HINT_TO_KEY:
        return _HINT_TO_KEY[hint]
    # Case-insensitive fallback
    lower = hint.lower()
    for k, v in _HINT_TO_KEY.items():
        if k.lower() == lower:
            return v
    return None


def _load_best_practices(model_key: str) -> str:
    """Read and return the best-practices Markdown for a model key."""
    path = BEST_PRACTICES_DIR / f"{model_key}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "*No best-practices file found for this model.*"


def _load_yaml(path: Path) -> dict:
    """Load a YAML file (Power Platform 'data'); return {} on any failure."""
    if not _YAML_AVAILABLE or not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
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


# ── Validation rules ───────────────────────────────────────────────────────────


def _run_checks(instructions: str, meta: dict) -> list[dict]:
    """Execute all validation checks and return a list of result dicts.

    Each result dict has keys: rule_id, title, severity ("pass"|"warning"|"fail"), detail.
    """
    results: list[dict] = []
    lower = instructions.lower()
    char_count = len(instructions)

    # ── Rule 1: Not empty ──────────────────────────────────────────────────────
    if not instructions.strip():
        results.append(
            {
                "rule_id": "empty-check",
                "title": "Instructions must not be empty",
                "severity": "fail",
                "detail": (
                    "No system instructions are defined. The agent will rely solely on default "
                    "model behaviour, which is unpredictable for production use."
                ),
            }
        )
        return results

    # ── Rule 2: Minimum length ─────────────────────────────────────────────────
    min_fail = meta["min_length_fail"]
    min_warn = meta["min_length_warn"]
    if char_count < min_fail:
        results.append(
            {
                "rule_id": "min-length",
                "title": f"Instructions are critically short ({char_count} chars)",
                "severity": "fail",
                "detail": (
                    f"At only {char_count} characters, the instructions are too brief to meaningfully "
                    f"guide the model. Aim for at least {min_warn} characters to cover persona, "
                    f"purpose, and scope."
                ),
            }
        )
    elif char_count < min_warn:
        results.append(
            {
                "rule_id": "min-length",
                "title": f"Instructions may be too short ({char_count} chars)",
                "severity": "warning",
                "detail": (
                    f"The instructions are {char_count} characters, below the recommended minimum of "
                    f"{min_warn} for {meta['display']}. Consider adding persona, purpose, scope, "
                    f"and constraint sections."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "min-length",
                "title": f"Instruction length is adequate ({char_count:,} chars)",
                "severity": "pass",
                "detail": f"The instructions meet the recommended minimum length for {meta['display']}.",
            }
        )

    # ── Rule 3: Maximum length ─────────────────────────────────────────────────
    max_warn = meta["max_length_warn"]
    if char_count > max_warn:
        results.append(
            {
                "rule_id": "max-length",
                "title": f"Instructions may be too long ({char_count:,} chars)",
                "severity": "warning",
                "detail": (
                    f"At {char_count:,} characters, the instructions exceed the recommended maximum of "
                    f"{max_warn:,} for {meta['display']}. Excessively long prompts can dilute attention "
                    f"and increase latency. Consider condensing or splitting across topics."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "max-length",
                "title": "Instruction length is within the recommended upper bound",
                "severity": "pass",
                "detail": (
                    f"Instructions are within the {meta['display']} recommended limit of {max_warn:,} characters."
                ),
            }
        )

    # ── Rule 4: Persona definition ─────────────────────────────────────────────
    persona_patterns = [
        r"\byou are\b",
        r"\byou're\b",
        r"\byour role\b",
        r"\byour name\b",
        r"\bact as\b",
        r"\byou serve as\b",
        r"\byou function as\b",
    ]
    has_persona = any(re.search(p, lower) for p in persona_patterns)
    if has_persona:
        results.append(
            {
                "rule_id": "has-persona",
                "title": "Persona / role definition detected",
                "severity": "pass",
                "detail": (
                    "The instructions contain a persona or role definition, which helps the model "
                    "maintain a consistent identity and tone across conversations."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "has-persona",
                "title": "No persona or role definition found",
                "severity": "warning",
                "detail": (
                    "Instructions should open with a clear role definition (e.g., 'You are a legal "
                    "assistant for...'). Without this, the model may adopt an inconsistent tone and "
                    "identity across conversations."
                ),
            }
        )

    # ── Rule 5: Purpose statement ──────────────────────────────────────────────
    purpose_patterns = [
        r"\bhelp\b",
        r"\bassist\b",
        r"\banswer\b",
        r"\bprovide\b",
        r"\bsupport\b",
        r"\brespond\b",
        r"\byour (primary |main |key )?purpose\b",
        r"\byour (primary |main |key )?task\b",
        r"\byour (primary |main |key )?goal\b",
        r"\byour (primary |main |key )?job\b",
        r"\byour (primary |main |key )?mission\b",
    ]
    has_purpose = any(re.search(p, lower) for p in purpose_patterns)
    if has_purpose:
        results.append(
            {
                "rule_id": "has-purpose",
                "title": "Purpose statement detected",
                "severity": "pass",
                "detail": (
                    "The instructions describe the agent's purpose, helping users understand what "
                    "to expect and giving the model a clear operational goal."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "has-purpose",
                "title": "No clear purpose statement found",
                "severity": "warning",
                "detail": (
                    "Consider adding a sentence that explicitly states what the agent is designed "
                    "to do (e.g., 'Your primary purpose is to help employees with IT requests.')."
                ),
            }
        )

    # ── Rule 6: Scope constraints ──────────────────────────────────────────────
    constraint_patterns = [
        r"\bdo not\b",
        r"\bdon'?t\b",
        r"\bmust not\b",
        r"\bshould not\b",
        r"\bnever\b",
        r"\bonly\b",
        r"\bexclusively\b",
        r"\bnot allowed\b",
        r"\bprohibited\b",
        r"\brefuse\b",
        r"\boutside (of )?scope\b",
        r"\bout of scope\b",
        r"\bnot (within|in) scope\b",
    ]
    constraint_hits = sum(1 for p in constraint_patterns if re.search(p, lower))
    if constraint_hits >= 2:
        results.append(
            {
                "rule_id": "has-constraints",
                "title": "Scope constraints detected",
                "severity": "pass",
                "detail": (
                    f"The instructions include {constraint_hits} constraint patterns, clearly "
                    "defining what the agent will and will not do."
                ),
            }
        )
    elif constraint_hits == 1:
        results.append(
            {
                "rule_id": "has-constraints",
                "title": "Few scope constraints found (1 detected)",
                "severity": "warning",
                "detail": (
                    "Only one constraint pattern was detected. Adding explicit 'Do not' or 'Only' "
                    "directives clarifies the agent's boundaries and reduces off-topic responses."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "has-constraints",
                "title": "No scope constraints found",
                "severity": "warning",
                "detail": (
                    "Instructions should explicitly state out-of-scope topics or actions. Without "
                    "constraints, the agent may attempt to help with any question regardless of "
                    "relevance or safety."
                ),
            }
        )

    # ── Rule 7: Vague language ─────────────────────────────────────────────────
    vague_words = [
        "sometimes",
        "usually",
        "might",
        "possibly",
        "maybe",
        "perhaps",
        "generally",
        "typically",
        "often",
        "occasionally",
        "in some cases",
    ]
    found_vague = [w for w in vague_words if re.search(r"\b" + re.escape(w) + r"\b", lower)]
    if found_vague:
        preview = ", ".join(found_vague[:4])
        suffix = "..." if len(found_vague) > 4 else ""
        results.append(
            {
                "rule_id": "avoid-vague-language",
                "title": f"Vague language detected: {preview}{suffix}",
                "severity": "warning",
                "detail": (
                    f"The words '{', '.join(found_vague)}' introduce ambiguity into the instructions. "
                    "Prefer deterministic directives: 'always', 'never', 'only', 'must'. Vague "
                    "language leads to inconsistent agent behaviour across conversations."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "avoid-vague-language",
                "title": "No problematic vague language detected",
                "severity": "pass",
                "detail": (
                    "Instructions use deterministic language, which promotes consistent and "
                    "predictable model behaviour."
                ),
            }
        )

    # ── Rule 8: Grounding rules (for models where it matters) ────────────────
    if meta["check_grounding"]:
        grounding_patterns = [
            r"\bgrounding\b",
            r"\bground(ed)? (data|context|document|source|result)\b",
            r"\bsearch result\b",
            r"\bretrieval\b",
            r"\bonly (from|based on|using)\b",
            r"\bexclusively from\b",
            r"\btraceable\b",
            r"\bcite (your |the )?source\b",
            r"\bsource document\b",
        ]
        has_grounding = any(re.search(p, lower) for p in grounding_patterns)
        if has_grounding:
            results.append(
                {
                    "rule_id": "grounding-rules",
                    "title": "Grounding / source attribution rules detected",
                    "severity": "pass",
                    "detail": (
                        "Instructions include grounding directives that restrict the model to defined "
                        "data sources, reducing hallucination risk for this knowledge-capable model."
                    ),
                }
            )
        else:
            results.append(
                {
                    "rule_id": "grounding-rules",
                    "title": f"{meta['display']} benefits from explicit grounding rules",
                    "severity": "warning",
                    "detail": (
                        f"{meta['display']} has extensive world knowledge. For enterprise agents, "
                        "add grounding rules that restrict responses to authoritative sources "
                        "(e.g., 'Answer exclusively from provided search results. Do not use general "
                        "training knowledge.')."
                    ),
                }
            )

    # ── Rule 9: Reasoning model — no redundant process instructions ───────────
    if meta["is_reasoning"]:
        proc_patterns = [
            r"\bthink (step[- ]by[- ]step|through|carefully)\b",
            r"\breason (through|step[- ]by[- ]step|carefully)\b",
            r"\blet'?s think\b",
            r"\bchain[- ]of[- ]thought\b",
            r"\bstep[- ]by[- ]step (reasoning|analysis|thinking)\b",
        ]
        over_specified = any(re.search(p, lower) for p in proc_patterns)
        if over_specified:
            results.append(
                {
                    "rule_id": "reasoning-model-process",
                    "title": "Redundant reasoning process instructions detected",
                    "severity": "warning",
                    "detail": (
                        f"{meta['display']} is a reasoning model that performs internal "
                        "chain-of-thought automatically. Instructions like 'think step by step' are "
                        "redundant and consume token budget without benefit. Focus on desired output "
                        "format and constraints instead."
                    ),
                }
            )
        else:
            results.append(
                {
                    "rule_id": "reasoning-model-process",
                    "title": "No redundant reasoning-process directives found",
                    "severity": "pass",
                    "detail": (
                        f"Instructions are appropriately goal-oriented for {meta['display']}, "
                        "without specifying internal reasoning steps."
                    ),
                }
            )

    # ── Rule 10: Compact model verbosity check ────────────────────────────────
    if meta["is_compact"]:
        compact_threshold = int(meta["max_length_warn"] * 0.65)
        if char_count > compact_threshold:
            results.append(
                {
                    "rule_id": "compact-model-length",
                    "title": f"Instructions may be verbose for {meta['display']}",
                    "severity": "warning",
                    "detail": (
                        f"{meta['display']} is designed for efficiency. Instructions approaching "
                        f"{meta['max_length_warn']:,} characters risk degraded response quality. "
                        f"Aim for fewer than {compact_threshold:,} characters for best results."
                    ),
                }
            )
        else:
            results.append(
                {
                    "rule_id": "compact-model-length",
                    "title": f"Instruction size is appropriate for {meta['display']}",
                    "severity": "pass",
                    "detail": (f"Instructions are concise enough for optimal performance with {meta['display']}."),
                }
            )

    # ── Rule 11: Prompt injection / override patterns ─────────────────────────
    injection_patterns = [
        r"ignore (all |previous |above |prior |system |original )?instructions",
        r"disregard (all |previous |above |prior )?instructions",
        r"override (all |previous |above |prior )?instructions",
        r"forget (all |your |previous )?instructions",
        r"new (role|persona|objective):",
    ]
    suspicious = [p for p in injection_patterns if re.search(p, lower)]
    if suspicious:
        results.append(
            {
                "rule_id": "prompt-injection-risk",
                "title": "Potential prompt injection pattern detected",
                "severity": "fail",
                "detail": (
                    "The instructions contain patterns that could indicate injected user content "
                    "or override language. System instructions must be static and authoritative -- "
                    "review carefully and remove any user-controllable content from the system prompt."
                ),
            }
        )
    else:
        results.append(
            {
                "rule_id": "prompt-injection-risk",
                "title": "No prompt injection patterns detected",
                "severity": "pass",
                "detail": ("Instructions do not contain common prompt injection or instruction-override patterns."),
            }
        )

    return results


# ── Public API ─────────────────────────────────────────────────────────────────


def validate_instructions(instructions: str, model_hint: str | None) -> dict:
    """Validate instructions string directly (without reading from a ZIP file).

    Accepts the raw instructions text and an optional model hint string.
    Returns the same dict structure as :func:`validate_zip_bytes`.
    """
    model_key = _resolve_model_key(model_hint)

    if model_key is None:
        display = model_hint or "Unknown"
        return {
            "model_key": "",
            "model_display": display,
            "best_practices_md": "",
            "results": [
                {
                    "rule_id": "model-not-assessed",
                    "title": f"Model '{display}' is below the assessment threshold",
                    "severity": "warning",
                    "detail": (
                        "Instruction validation is available for GPT-4.1 and higher models "
                        "(GPT-4.1, GPT-4.1 Mini, GPT-4.1 Nano, GPT-5, GPT-5 Chat, o1, o3, "
                        "o4-mini). This agent uses a model outside that set."
                    ),
                }
            ],
            "instructions_length": len(instructions),
        }

    meta = _MODEL_META[model_key]
    best_practices_md = _load_best_practices(model_key)
    results = _run_checks(instructions, meta)

    return {
        "model_key": model_key,
        "model_display": meta["display"],
        "best_practices_md": best_practices_md,
        "results": results,
        "instructions_length": len(instructions),
    }


def _extract_gpt_info_from_solution(work_dir: Path) -> tuple[str | None, str]:
    """Extract model hint and instructions from an extracted solution ZIP.

    Returns (model_hint, instructions).
    """
    bots_dir = work_dir / "bots"
    if not bots_dir.exists():
        return None, ""
    bot_folders = [d for d in bots_dir.iterdir() if d.is_dir()]
    if not bot_folders:
        return None, ""
    schema = bot_folders[0].name

    botcomponents_dir = work_dir / "botcomponents"
    gpt_dir = botcomponents_dir / f"{schema}.gpt.default"
    if not gpt_dir.exists():
        return None, ""

    # Read model hint from data YAML
    gpt_data = _load_yaml(gpt_dir / "data")
    instructions = gpt_data.get("instructions") or ""
    model_hint = gpt_data.get("modelNameHint") or gpt_data.get("modelHint") or None

    # Also try settings inside the data
    settings = gpt_data.get("settings") or {}
    if model_hint is None and settings:
        for _key, sv in settings.items():
            if isinstance(sv, dict):
                hint = sv.get("modelNameHint") or sv.get("modelHint")
                if hint:
                    model_hint = hint
                    break

    # Fallback: try configuration.json for model hint
    if model_hint is None:
        import json

        config_path = work_dir / "bots" / schema / "configuration.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                settings = config.get("settings") or {}
                for _key, sv in settings.items():
                    if isinstance(sv, dict):
                        content = sv.get("content") or sv
                        hint = content.get("modelNameHint") or content.get("modelHint")
                        if hint:
                            model_hint = hint
                            break
            except Exception:
                pass

    return model_hint, instructions


def validate_zip_bytes(zip_bytes: bytes) -> dict:
    """Parse a solution ZIP and validate agent instructions against model best practices.

    Returns a dict suitable for storing in Reflex state::

        {
            "model_key": str,           # internal key or "" if not assessed
            "model_display": str,       # human-readable model name
            "best_practices_md": str,   # full best-practices Markdown
            "results": list[dict],      # [{rule_id, title, severity, detail}, ...]
            "instructions_length": int,
        }

    Raises ``ValueError`` or ``RuntimeError`` on ZIP parse failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, tmp)

        hint, instructions = _extract_gpt_info_from_solution(tmp)

    return validate_instructions(instructions, hint)

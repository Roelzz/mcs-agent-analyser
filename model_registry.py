"""Unified model registry — single source of truth for model hint resolution.

Consolidates the duplicated hint-to-key mappings that previously lived in
linter.py, validator.py, and model_comparison.py.
"""

from __future__ import annotations

from typing import NamedTuple


class ModelInfo(NamedTuple):
    key: str
    provider: str
    api_model_id: str
    display_name: str
    is_assessed: bool


# Canonical registry keyed by internal model key.
_MODELS: dict[str, ModelInfo] = {
    "gpt41": ModelInfo("gpt41", "openai", "gpt-4.1", "GPT-4.1", True),
    "gpt41mini": ModelInfo("gpt41mini", "openai", "gpt-4.1-mini", "GPT-4.1 Mini", True),
    "gpt41nano": ModelInfo("gpt41nano", "openai", "gpt-4.1-nano", "GPT-4.1 Nano", True),
    "gpt5": ModelInfo("gpt5", "openai", "gpt-5", "GPT-5", True),
    "gpt5chat": ModelInfo("gpt5chat", "openai", "gpt-5-chat", "GPT-5 Chat", True),
    "o1": ModelInfo("o1", "openai", "o1", "o1", True),
    "o3": ModelInfo("o3", "openai", "o3", "o3", True),
    "o4mini": ModelInfo("o4mini", "openai", "o4-mini", "o4-mini", True),
    # Legacy / below-threshold models (is_assessed=False)
    "gpt4o": ModelInfo("gpt4o", "openai", "gpt-4o", "GPT-4o", False),
    "gpt4omini": ModelInfo("gpt4omini", "openai", "gpt-4o-mini", "GPT-4o Mini", False),
    "gpt4": ModelInfo("gpt4", "openai", "gpt-4", "GPT-4", False),
    "gpt35turbo": ModelInfo("gpt35turbo", "openai", "gpt-3.5-turbo", "GPT-3.5 Turbo", False),
    # Anthropic
    "sonnet45": ModelInfo("sonnet45", "anthropic", "claude-sonnet-4-5", "Claude Sonnet 4.5", True),
    "sonnet46": ModelInfo("sonnet46", "anthropic", "claude-sonnet-4-6", "Claude Sonnet 4.6", True),
    "opus46": ModelInfo("opus46", "anthropic", "claude-opus-4-6", "Claude Opus 4.6", True),
}

# Hint string → internal key. Covers PascalCase (Power Platform), kebab-case, and lowercase.
_HINT_TO_KEY: dict[str, str] = {
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
    "GPT5Auto": "gpt5",
    "gpt-5-auto": "gpt5",
    "GPT5Reasoning": "gpt5",
    "gpt-5-reasoning": "gpt5",
    "GPT53Chat": "gpt5",
    "gpt-5.3-chat": "gpt5",
    "GPT54Reasoning": "gpt5",
    "gpt-5.4-reasoning": "gpt5",
    # o-series reasoning models
    "o1": "o1",
    "o1-preview": "o1",
    "o1-mini": "o1",
    "o3": "o3",
    "o3-mini": "o3",
    "o4-mini": "o4mini",
    "o4mini": "o4mini",
    # Legacy / below threshold
    "GPT4o": "gpt4o",
    "gpt-4o": "gpt4o",
    "GPT4oMini": "gpt4omini",
    "gpt-4o-mini": "gpt4omini",
    "gpt-4": "gpt4",
    "GPT4": "gpt4",
    "GPT35Turbo": "gpt35turbo",
    "gpt-3.5-turbo": "gpt35turbo",
    "gpt-35-turbo": "gpt35turbo",
    # Anthropic
    "Sonnet45": "sonnet45",
    "sonnet4-5": "sonnet45",
    "sonnet45": "sonnet45",
    "claude-sonnet-4-5": "sonnet45",
    "Sonnet46": "sonnet46",
    "sonnet4-6": "sonnet46",
    "sonnet46": "sonnet46",
    "claude-sonnet-4-6": "sonnet46",
    "Opus46": "opus46",
    "opus4-6": "opus46",
    "opus46": "opus46",
    "claude-opus-4-6": "opus46",
}


def resolve_hint(hint: str | None) -> ModelInfo | None:
    """Resolve a Power Platform modelNameHint to a ModelInfo.

    Returns None when the hint is unknown. Case-insensitive fallback is attempted.
    """
    if not hint:
        return None
    key = _HINT_TO_KEY.get(hint.strip())
    if key:
        return _MODELS.get(key)
    # Case-insensitive fallback
    lower = hint.strip().lower()
    for k, v in _HINT_TO_KEY.items():
        if k.lower() == lower:
            return _MODELS.get(v)
    return None


def get_openai_model_id(hint: str | None) -> str | None:
    """Return the OpenAI API model ID for a hint, or None if unknown/non-OpenAI."""
    info = resolve_hint(hint)
    if info and info.provider == "openai":
        return info.api_model_id
    return None


def get_validator_key(hint: str | None) -> str | None:
    """Return the internal validator key for a hint, or None if below threshold / unknown."""
    info = resolve_hint(hint)
    if info and info.is_assessed:
        return info.key
    return None

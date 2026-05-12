"""Multi-mode LLM audit runner.

Backwards-compatible: the existing `run_lint(profile, ...)` entry point
still produces the original static-config Markdown report. The new
`run_audits(...)` entry point runs any selection of modes (declared in
`data/default_lint_modes.yaml`) in parallel and returns one
`AuditResult` per mode — including transcript-based audits like
sentiment, PII, answer accuracy, and topic routing quality.

The provider abstraction (OpenAI vs Anthropic, model resolution, API
key dispatch) is shared across all modes so adding a new audit only
requires a YAML entry — no code change.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml
from anthropic import AsyncAnthropic
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from models import BotProfile, ConversationTimeline
from model_registry import resolve_hint

_FALLBACK_PROVIDER = "openai"
_FALLBACK_MODEL = "gpt-4.1"

_LINT_UPGRADES: dict[str, str] = {
    "gpt-4o": "gpt-4.1",
    "gpt-4o-mini": "gpt-4.1-mini",
    "gpt-5-chat": "gpt-5",
}

_DEFAULT_MODES_PATH = Path(__file__).parent / "data" / "default_lint_modes.yaml"


# ---------------------------------------------------------------------------
# Audit catalogue
# ---------------------------------------------------------------------------


class AuditMode(BaseModel):
    """Declarative audit mode loaded from YAML."""

    id: str
    name: str
    description: str = ""
    inputs_required: list[str] = Field(default_factory=list)
    default_enabled: bool = False
    system_prompt: str

    @field_validator("inputs_required")
    @classmethod
    def _validate_inputs(cls, v: list[str]) -> list[str]:
        allowed = {"profile", "transcript"}
        for item in v:
            if item not in allowed:
                raise ValueError(f"inputs_required contains unknown input '{item}'; allowed: {sorted(allowed)}")
        return v


class AuditResult(BaseModel):
    """Outcome of running one audit mode against a payload."""

    mode_id: str
    mode_name: str
    markdown: str = ""
    model_used: str = ""
    error: str = ""


def load_audit_modes(path: str | Path | None = None) -> list[AuditMode]:
    """Load audit modes from YAML. Falls back to the bundled default file
    when no path is provided."""
    target = Path(path) if path else _DEFAULT_MODES_PATH
    text = target.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or "modes" not in raw:
        raise ValueError(f"{target} must contain a top-level 'modes' key")
    modes_raw = raw["modes"]
    if not isinstance(modes_raw, list):
        raise ValueError("'modes' must be a list")
    return [AuditMode(**m) for m in modes_raw]


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


def resolve_model(hint: str | None) -> tuple[str, str, bool]:
    """Resolve a Copilot Studio model hint to (provider, model_id, was_fallback).

    Legacy OpenAI models are transparently upgraded to current equivalents.
    """
    info = resolve_hint(hint)
    if info:
        api_id = _LINT_UPGRADES.get(info.api_model_id, info.api_model_id)
        return info.provider, api_id, False
    logger.warning(f"Unknown model hint '{hint}', falling back to {_FALLBACK_PROVIDER}/{_FALLBACK_MODEL}")
    return _FALLBACK_PROVIDER, _FALLBACK_MODEL, True


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def build_component_payload(profile: BotProfile) -> dict:
    """Build the JSON payload sent to the LLM for the static-config audit."""
    components = [comp.model_dump() for comp in profile.components]
    topic_connections = [tc.model_dump() for tc in profile.topic_connections]

    payload: dict = {
        "bot_name": profile.display_name,
        "is_orchestrator": profile.is_orchestrator,
        "model_hint": None,
        "instructions": None,
        "gpt_description": None,
        "components": components,
        "topic_connections": topic_connections,
    }

    if profile.gpt_info:
        payload["model_hint"] = profile.gpt_info.model_hint
        payload["instructions"] = profile.gpt_info.instructions
        payload["gpt_description"] = profile.gpt_info.description

    return payload


def build_transcript_payload(timeline: ConversationTimeline) -> dict:
    """Build a token-efficient JSON payload for transcript-based audits.

    Strips noisy intermediate state (per-step bind updates, low-level
    tracing) but keeps the user/bot messages, plan boundaries, knowledge
    searches, and errors — enough for the LLM to reason about what
    happened without paying tokens for every internal trace event.
    """
    from models import EventType

    keep_types = {
        EventType.USER_MESSAGE,
        EventType.BOT_MESSAGE,
        EventType.ACTION_SEND_ACTIVITY,
        EventType.PLAN_RECEIVED,
        EventType.PLAN_FINISHED,
        EventType.STEP_TRIGGERED,
        EventType.STEP_FINISHED,
        EventType.KNOWLEDGE_SEARCH,
        EventType.GENERATIVE_ANSWER,
        EventType.ERROR,
        EventType.ACTION_AI_BUILDER,
        EventType.ACTION_HTTP_REQUEST,
        EventType.DIALOG_REDIRECT,
    }

    events: list[dict] = []
    for ev in timeline.events:
        if ev.event_type not in keep_types:
            continue
        events.append(
            {
                "position": ev.position,
                "timestamp": ev.timestamp,
                "event_type": ev.event_type.value,
                "summary": ev.summary,
                "topic_name": ev.topic_name,
                "state": ev.state,
                "thought": ev.thought,
                "error": ev.error,
            }
        )

    return {
        "bot_name": timeline.bot_name,
        "conversation_id": timeline.conversation_id,
        "user_query": timeline.user_query,
        "total_elapsed_ms": timeline.total_elapsed_ms,
        "errors": timeline.errors,
        "events": events,
    }


def build_audit_payload(
    mode: AuditMode,
    profile: BotProfile | None,
    timeline: ConversationTimeline | None,
) -> dict:
    """Assemble the JSON payload for one audit mode based on its declared
    `inputs_required`. Modes that need a profile or transcript that
    isn't available raise `ValueError` so the caller can mark the audit
    as skipped rather than crash the run."""
    payload: dict = {}
    if "profile" in mode.inputs_required:
        if profile is None:
            raise ValueError("this audit requires a bot profile but none was provided")
        payload["profile"] = build_component_payload(profile)
    if "transcript" in mode.inputs_required:
        if timeline is None:
            raise ValueError("this audit requires a conversation transcript but none was provided")
        payload["transcript"] = build_transcript_payload(timeline)
    if len(mode.inputs_required) == 1:
        # Flatten single-input payloads so existing prompts continue to
        # work against the same top-level shape (e.g. static_config gets
        # the bot fields directly, not wrapped under a `profile` key).
        only = mode.inputs_required[0]
        return payload[only]
    return payload


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------


async def _audit_openai(api_key: str, model_id: str, system_prompt: str, user_content: str) -> str:
    client = AsyncOpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        response = await client.chat.completions.create(
            model=model_id, temperature=0.3, messages=messages
        )
    except Exception as exc:  # noqa: BLE001 — narrow check on exception text
        # Reasoning / GPT-5-class models reject custom temperature with
        # `unsupported_value` and only accept the default. Retry without it.
        msg = str(exc).lower()
        if "temperature" not in msg or "unsupported" not in msg:
            raise
        logger.info(f"Model '{model_id}' rejected custom temperature; retrying with default")
        response = await client.chat.completions.create(model=model_id, messages=messages)
    return response.choices[0].message.content or ""


async def _audit_anthropic(api_key: str, model_id: str, system_prompt: str, user_content: str) -> str:
    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=model_id,
        max_tokens=4096,
        temperature=0.3,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_content},
        ],
    )
    return response.content[0].text


async def _run_one_audit(
    mode: AuditMode,
    profile: BotProfile | None,
    timeline: ConversationTimeline | None,
    openai_api_key: str,
    anthropic_api_key: str,
) -> AuditResult:
    """Execute one audit mode end-to-end. Captures errors per audit so
    one mode's failure doesn't take down the others."""
    try:
        payload = build_audit_payload(mode, profile, timeline)
    except ValueError as e:
        return AuditResult(mode_id=mode.id, mode_name=mode.name, error=str(e))

    # Static-config audits resolve the model from the bot's hint;
    # transcript audits don't have a "bot model hint" so they fall
    # straight through to the default. This matches the legacy
    # behaviour for the static_config mode.
    hint: str | None = None
    if profile is not None and profile.gpt_info:
        hint = profile.gpt_info.model_hint
    provider, model_id, was_fallback = resolve_model(hint)

    user_content = json.dumps(payload, indent=2, default=str)
    logger.info(f"Running audit '{mode.id}' with {provider}/{model_id} (fallback={was_fallback})")

    try:
        if provider == "anthropic":
            if not anthropic_api_key:
                raise ValueError(
                    f"Audit '{mode.id}' resolved to Anthropic model '{model_id}' but ANTHROPIC_API_KEY is not set."
                )
            markdown = await _audit_anthropic(anthropic_api_key, model_id, mode.system_prompt, user_content)
        else:
            if not openai_api_key:
                raise ValueError(
                    f"Audit '{mode.id}' resolved to OpenAI model '{model_id}' but OPENAI_API_KEY is not set."
                )
            markdown = await _audit_openai(openai_api_key, model_id, mode.system_prompt, user_content)
    except Exception as e:
        return AuditResult(mode_id=mode.id, mode_name=mode.name, error=str(e), model_used=model_id)

    fallback_note = " (fallback — unknown model hint)" if was_fallback else ""
    header = f"> Audit performed by `{model_id}`{fallback_note}\n\n"
    return AuditResult(
        mode_id=mode.id,
        mode_name=mode.name,
        markdown=header + markdown,
        model_used=model_id,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def run_audits(
    profile: BotProfile | None,
    timeline: ConversationTimeline | None,
    mode_ids: list[str],
    custom_prompt: str = "",
    openai_api_key: str = "",
    anthropic_api_key: str = "",
    modes: list[AuditMode] | None = None,
) -> list[AuditResult]:
    """Run a selection of audit modes in parallel and return one
    `AuditResult` per mode. Failures are captured per-mode (so one
    audit crashing doesn't prevent the others from rendering).

    `modes` is the catalogue (defaults to `load_audit_modes()` so callers
    don't have to thread it through). `mode_ids` is the user's
    selection. A `custom_prompt` value adds an ad-hoc audit using the
    inputs `[profile, transcript]` (whichever is available) — it's
    skipped when empty.
    """
    catalogue = modes if modes is not None else load_audit_modes()
    mode_lookup = {m.id: m for m in catalogue}

    selected: list[AuditMode] = []
    for mid in mode_ids:
        if mid in mode_lookup:
            selected.append(mode_lookup[mid])
        else:
            logger.warning(f"Unknown audit mode '{mid}' — skipped")

    if custom_prompt.strip():
        # Custom audits use whatever inputs are available so the user
        # can write transcript-only or profile-only or combined prompts
        # without having to pre-declare which ones.
        custom_inputs: list[str] = []
        if profile is not None:
            custom_inputs.append("profile")
        if timeline is not None:
            custom_inputs.append("transcript")
        selected.append(
            AuditMode(
                id="custom",
                name="Custom Audit",
                description="User-supplied prompt.",
                inputs_required=custom_inputs,
                default_enabled=False,
                system_prompt=custom_prompt.strip(),
            )
        )

    if not selected:
        return []

    coros = [_run_one_audit(m, profile, timeline, openai_api_key, anthropic_api_key) for m in selected]
    return await asyncio.gather(*coros)


async def run_lint(
    profile: BotProfile,
    openai_api_key: str = "",
    anthropic_api_key: str = "",
) -> tuple[str, str]:
    """Backwards-compatible single-mode entry point. Runs only the
    `static_config` audit and returns `(markdown, model_used)`.

    Preserved verbatim so the existing "Instruction Lint" button keeps
    working with the same one-click flow.
    """
    results = await run_audits(
        profile=profile,
        timeline=None,
        mode_ids=["static_config"],
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
    )
    if not results:
        raise ValueError("static_config mode missing from catalogue")
    result = results[0]
    if result.error:
        raise ValueError(result.error)
    return result.markdown, result.model_used

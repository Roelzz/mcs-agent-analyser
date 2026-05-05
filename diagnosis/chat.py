"""Streaming chat with the judge.

After a diagnosis runs, the user can interrogate the verdict through a chat
panel. Each turn re-uses the same redacted payload that produced the verdict
(so the judge has the full trajectory and its own prior reasoning), plus the
chat history so it stays consistent across turns.

Streaming is via OpenAI's `stream=True` chunked responses; the consumer
(`web/state/_diagnosis.py:send_chat_message`) yields each `ChatChunk` to
Reflex, which re-renders the active assistant bubble after every delta.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Literal

from loguru import logger

from diagnosis.judge import _build_payload
from diagnosis.models import ConstraintViolation
from models import BotProfile, ConversationTimeline


_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "judge_chat.md"


@dataclass
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class ChatChunk:
    """One streamed delta from the judge.

    The consumer accumulates `delta`s into the active assistant bubble. The
    final chunk has `done=True`. On error, `error` is set and `done=True` is
    also set so the consumer can finalise the bubble in one branch.
    """

    delta: str = ""
    done: bool = False
    error: str = ""


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _serialise_history(history: list[ChatTurn]) -> list[dict]:
    return [{"role": t.role, "content": t.content} for t in history]


def _build_chat_messages(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
    verdict_raw: dict | None,
    history: list[ChatTurn],
    user_message: str,
    *,
    redact_pii: bool,
) -> list[dict]:
    """Assemble the OpenAI message list. The system message embeds the
    redacted diagnosis payload + the prior verdict; the user/assistant
    messages carry the chat history + the new user question."""
    payload, _redaction_summary = _build_payload(profile, timeline, violations, redact_pii=redact_pii)
    context = {
        "profile": payload.get("profile"),
        "transcript": payload.get("transcript"),
        "violations": payload.get("violations"),
        "verdict": verdict_raw or {},
    }
    system_prompt = _load_prompt() + "\n\n## Context (read-only)\n\n" + json.dumps(context, default=str, indent=2)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in history:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": user_message})
    return messages


async def chat_with_judge_stream(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
    verdict_raw: dict | None,
    history: list[ChatTurn],
    user_message: str,
    *,
    judge_model: str,
    redact_pii: bool = True,
) -> AsyncIterator[ChatChunk]:
    """Yield streamed chunks from the judge. Errors arrive as a single
    ChatChunk with `error` set + `done=True`."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        yield ChatChunk(error="OPENAI_API_KEY is not set", done=True)
        return

    try:
        from openai import AsyncOpenAI
    except ImportError:
        yield ChatChunk(error="openai SDK is not installed", done=True)
        return

    client = AsyncOpenAI(api_key=api_key)
    messages = _build_chat_messages(
        profile,
        timeline,
        violations,
        verdict_raw,
        history,
        user_message,
        redact_pii=redact_pii,
    )

    async def _try_stream(use_temperature: bool) -> AsyncIterator[ChatChunk]:
        kwargs: dict = {"model": judge_model, "messages": messages, "stream": True}
        if use_temperature:
            kwargs["temperature"] = 0.3
        stream = await client.chat.completions.create(**kwargs)
        try:
            async for event in stream:
                choices = getattr(event, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                text = getattr(delta, "content", None) or ""
                if text:
                    yield ChatChunk(delta=text)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 — closing best-effort
                    pass

    try:
        try:
            async for chunk in _try_stream(use_temperature=True):
                yield chunk
        except Exception as exc:  # noqa: BLE001 — narrow check by message
            msg = str(exc).lower()
            if "temperature" in msg and "unsupported" in msg:
                logger.info(f"Chat model '{judge_model}' rejected temperature; retrying without it")
                async for chunk in _try_stream(use_temperature=False):
                    yield chunk
            else:
                raise
    except Exception as exc:  # noqa: BLE001 — surface any final failure
        logger.warning(f"Chat call failed: {exc}")
        yield ChatChunk(error=f"Chat call failed: {exc}", done=True)
        return

    yield ChatChunk(done=True)

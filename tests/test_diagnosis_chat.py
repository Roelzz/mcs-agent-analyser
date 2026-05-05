"""Tests for the chat-with-judge module.

We mock OpenAI's streaming API to avoid network calls. Three concerns:
1. The system prompt + message list embeds the verdict + history correctly.
2. Streaming chunks arrive as `ChatChunk(delta=...)` and the final chunk has `done=True`.
3. Errors arrive as a single `ChatChunk(error=..., done=True)`.
"""

from __future__ import annotations

import asyncio

import pytest

from diagnosis.chat import (
    ChatChunk,
    ChatTurn,
    _build_chat_messages,
    _serialise_history,
    chat_with_judge_stream,
)
from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline, EventType, TimelineEvent


async def _drain(stream) -> list[ChatChunk]:
    out: list[ChatChunk] = []
    async for c in stream:
        out.append(c)
    return out


def _run(coro):
    return asyncio.run(coro)


def _profile() -> BotProfile:
    return BotProfile(display_name="X", schema_name="cr_x")


def _timeline() -> ConversationTimeline:
    return ConversationTimeline(
        bot_name="X",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                position=1,
                summary='User: "hello"',
                timestamp="2024-01-01T00:00:01Z",
            )
        ],
    )


def _verdict_raw() -> dict:
    return {
        "failure_case": 2,
        "index": 23,
        "summary": "Agent invented merchant Contoso",
        "reason_for_failure": "ungrounded fabrication",
        "taxonomy_checklist_reasoning": "rules out other categories",
        "reason_for_index": "step 23 first asserts Contoso",
        "confidence": "medium",
    }


# ---------------------------------------------------------------------------
# History serialisation + message assembly
# ---------------------------------------------------------------------------


class TestSerialiseHistory:
    def test_round_trip(self):
        history = [ChatTurn(role="user", content="hi"), ChatTurn(role="assistant", content="hey")]
        out = _serialise_history(history)
        assert out == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}]


class TestBuildChatMessages:
    def test_system_message_contains_verdict(self):
        msgs = _build_chat_messages(
            _profile(),
            _timeline(),
            violations=[],
            verdict_raw=_verdict_raw(),
            history=[],
            user_message="explain why you said Contoso was invented",
            redact_pii=False,
        )
        assert msgs[0]["role"] == "system"
        sys_content = msgs[0]["content"]
        # The chat prompt is included…
        assert "interrogating that verdict" in sys_content
        # …along with the verdict in the embedded context.
        assert "Contoso" in sys_content
        # The user message is the last message.
        assert msgs[-1] == {
            "role": "user",
            "content": "explain why you said Contoso was invented",
        }

    def test_history_appears_between_system_and_new_user_message(self):
        history = [
            ChatTurn(role="user", content="prior question"),
            ChatTurn(role="assistant", content="prior answer"),
        ]
        msgs = _build_chat_messages(
            _profile(),
            _timeline(),
            violations=[],
            verdict_raw=_verdict_raw(),
            history=history,
            user_message="follow-up",
            redact_pii=False,
        )
        roles = [m["role"] for m in msgs]
        assert roles == ["system", "user", "assistant", "user"]
        assert msgs[1]["content"] == "prior question"
        assert msgs[2]["content"] == "prior answer"
        assert msgs[3]["content"] == "follow-up"

    def test_violations_passed_through(self):
        v = ConstraintViolation(
            rule_id="tool_error_ignored",
            step_index=23,
            severity="critical",
            description="x",
            default_category_seed=FailureCategory.TOOL_MISINTERPRETATION,
        )
        msgs = _build_chat_messages(
            _profile(),
            _timeline(),
            violations=[v],
            verdict_raw=_verdict_raw(),
            history=[],
            user_message="?",
            redact_pii=False,
        )
        assert "tool_error_ignored" in msgs[0]["content"]


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class _FakeChoice:
    def __init__(self, text: str):
        self.delta = type("D", (), {"content": text})()


class _FakeChunk:
    def __init__(self, text: str):
        self.choices = [_FakeChoice(text)]


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()

    async def close(self):
        pass


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks

    async def create(self, **kwargs):
        return _FakeStream(self._chunks)


class _FakeChat:
    def __init__(self, chunks):
        self.completions = _FakeCompletions(chunks)


class _FakeAsyncOpenAI:
    last_kwargs: dict | None = None

    def __init__(self, *args, **kwargs):
        self.api_key = kwargs.get("api_key", "")
        self.chat = _FakeChat(_FakeAsyncOpenAI._chunks)


def test_streaming_yields_deltas_then_done(monkeypatch):
    pytest.importorskip("openai")
    chunks = [_FakeChunk("Hel"), _FakeChunk("lo "), _FakeChunk("world.")]
    _FakeAsyncOpenAI._chunks = chunks
    import openai as _openai

    monkeypatch.setattr(_openai, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    out = _run(
        _drain(
            chat_with_judge_stream(
                _profile(),
                _timeline(),
                violations=[],
                verdict_raw=_verdict_raw(),
                history=[],
                user_message="hi",
                judge_model="gpt-5",
                redact_pii=False,
            )
        )
    )

    deltas = [c.delta for c in out if c.delta]
    assert "".join(deltas) == "Hello world."
    # Last yielded chunk has done=True
    assert out[-1].done is True


def test_missing_api_key_yields_error_chunk(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = _run(
        _drain(
            chat_with_judge_stream(
                _profile(),
                _timeline(),
                violations=[],
                verdict_raw=_verdict_raw(),
                history=[],
                user_message="hi",
                judge_model="gpt-5",
                redact_pii=False,
            )
        )
    )
    assert len(out) == 1
    assert out[0].error
    assert out[0].done is True


def test_call_failure_yields_error_chunk(monkeypatch):
    pytest.importorskip("openai")
    import openai as _openai

    class _BoomCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("boom")

    class _BoomChat:
        completions = _BoomCompletions()

    class _BoomClient:
        def __init__(self, *args, **kwargs):
            self.chat = _BoomChat()

    monkeypatch.setattr(_openai, "AsyncOpenAI", _BoomClient)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    out = _run(
        _drain(
            chat_with_judge_stream(
                _profile(),
                _timeline(),
                violations=[],
                verdict_raw=_verdict_raw(),
                history=[],
                user_message="hi",
                judge_model="gpt-5",
                redact_pii=False,
            )
        )
    )
    assert any(c.error for c in out)
    assert out[-1].done is True


# ---------------------------------------------------------------------------
# Temperature-fallback path (gpt-5 / o-series models reject temperature=0.3)
# ---------------------------------------------------------------------------


def test_streaming_retries_without_temperature_when_unsupported(monkeypatch):
    """Reasoning / GPT-5-class models reject custom temperature with
    'unsupported_value'. The streaming path must catch that, retry without
    the kwarg, and still deliver deltas to the consumer."""
    pytest.importorskip("openai")
    chunks = [_FakeChunk("Re"), _FakeChunk("try "), _FakeChunk("OK.")]
    call_count = {"n": 0}

    class _RetryCompletions:
        async def create(self, **kwargs):
            call_count["n"] += 1
            # First call (with temperature) raises the canonical OpenAI 400.
            if "temperature" in kwargs:
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': \"Unsupported value: 'temperature' does not support 0.3 with this model.\"}}"
                )
            # Second call (without temperature) succeeds with the streamed chunks.
            return _FakeStream(chunks)

    class _RetryChat:
        completions = _RetryCompletions()

    class _RetryClient:
        def __init__(self, *args, **kwargs):
            self.chat = _RetryChat()

    import openai as _openai

    monkeypatch.setattr(_openai, "AsyncOpenAI", _RetryClient)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    out = _run(
        _drain(
            chat_with_judge_stream(
                _profile(),
                _timeline(),
                violations=[],
                verdict_raw=_verdict_raw(),
                history=[],
                user_message="hi",
                judge_model="gpt-5",
                redact_pii=False,
            )
        )
    )

    assert call_count["n"] == 2  # one rejected attempt, one successful retry
    deltas = [c.delta for c in out if c.delta]
    assert "".join(deltas) == "Retry OK."
    assert out[-1].done is True


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------


def test_chat_prompt_file_loads():
    """`prompts/judge_chat.md` must exist and carry the persona text the
    chat module relies on. A typo / move that breaks this is silent at
    import time but produces empty system prompts at runtime."""
    from diagnosis.chat import _load_prompt

    text = _load_prompt()
    assert text  # non-empty
    # Persona signal — the prompt must establish that this is the judge
    # answering interrogations of its own verdict.
    assert "interrogating that verdict" in text or "judge" in text.lower()

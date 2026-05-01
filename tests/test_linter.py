from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linter import build_component_payload, resolve_model, run_lint
from models import BotProfile, ComponentSummary, GptInfo, TopicConnection


# --- resolve_model tests ---


def test_resolve_model_known_hints():
    # OpenAI — PascalCase
    assert resolve_model("GPT41") == ("openai", "gpt-4.1", False)
    assert resolve_model("GPT4o") == ("openai", "gpt-4.1", False)
    assert resolve_model("GPT4oMini") == ("openai", "gpt-4.1-mini", False)
    assert resolve_model("GPT35Turbo") == ("openai", "gpt-3.5-turbo", False)
    assert resolve_model("GPT5Chat") == ("openai", "gpt-5", False)
    assert resolve_model("GPT5Auto") == ("openai", "gpt-5", False)
    # OpenAI — kebab-case (actual YAML values)
    assert resolve_model("gpt-4.1") == ("openai", "gpt-4.1", False)
    assert resolve_model("gpt-5-chat") == ("openai", "gpt-5", False)
    # Anthropic — PascalCase
    assert resolve_model("Sonnet45") == ("anthropic", "claude-sonnet-4-5", False)
    assert resolve_model("Sonnet46") == ("anthropic", "claude-sonnet-4-6", False)
    assert resolve_model("Opus46") == ("anthropic", "claude-opus-4-6", False)
    # Anthropic — kebab-case (actual YAML values)
    assert resolve_model("sonnet4-5") == ("anthropic", "claude-sonnet-4-5", False)
    assert resolve_model("sonnet4-6") == ("anthropic", "claude-sonnet-4-6", False)
    assert resolve_model("opus4-6") == ("anthropic", "claude-opus-4-6", False)


def test_resolve_model_case_insensitive():
    assert resolve_model("gpt41") == ("openai", "gpt-4.1", False)
    assert resolve_model("SONNET45") == ("anthropic", "claude-sonnet-4-5", False)
    assert resolve_model("OPUS46") == ("anthropic", "claude-opus-4-6", False)


def test_resolve_model_unknown_falls_back():
    provider, model_id, was_fallback = resolve_model("SomeNewModel")
    assert provider == "openai"
    assert model_id == "gpt-4.1"
    assert was_fallback is True


def test_resolve_model_none():
    provider, model_id, was_fallback = resolve_model(None)
    assert provider == "openai"
    assert model_id == "gpt-4.1"
    assert was_fallback is True


# --- build_component_payload tests ---


def test_build_component_payload_structure():
    profile = BotProfile(
        display_name="TestBot",
        is_orchestrator=True,
        gpt_info=GptInfo(
            display_name="TestBot",
            description="A test bot",
            instructions="Be helpful.",
            model_hint="GPT41",
        ),
        components=[
            ComponentSummary(kind="DialogComponent", display_name="Greeting", schema_name="bot.topic.Greeting"),
            ComponentSummary(kind="GptComponent", display_name="TestBot", schema_name="bot.gpt.TestBot"),
        ],
        topic_connections=[
            TopicConnection(
                source_schema="bot.topic.A",
                source_display="Topic A",
                target_schema="bot.topic.B",
                target_display="Topic B",
                condition="some condition",
            ),
        ],
    )

    payload = build_component_payload(profile)

    assert payload["bot_name"] == "TestBot"
    assert payload["is_orchestrator"] is True
    assert payload["model_hint"] == "GPT41"
    assert payload["instructions"] == "Be helpful."
    assert payload["gpt_description"] == "A test bot"
    assert len(payload["components"]) == 2
    assert payload["components"][0]["kind"] == "DialogComponent"
    assert len(payload["topic_connections"]) == 1
    assert payload["topic_connections"][0]["source_display"] == "Topic A"


def test_build_component_payload_no_gpt_info():
    profile = BotProfile(display_name="BasicBot", gpt_info=None)

    payload = build_component_payload(profile)

    assert payload["bot_name"] == "BasicBot"
    assert payload["model_hint"] is None
    assert payload["instructions"] is None
    assert payload["gpt_description"] is None
    assert payload["components"] == []
    assert payload["topic_connections"] == []


# --- run_lint mock tests ---


@pytest.mark.anyio
async def test_run_lint_mock_openai():
    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="GPT41", instructions="Be helpful."),
    )

    mock_message = MagicMock()
    mock_message.content = "## 1. Instruction Clarity\n✅ Pass\nLooks good."

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("linter.AsyncOpenAI", return_value=mock_client):
        report, model_used = await run_lint(profile, openai_api_key="fake-key")

    assert model_used == "gpt-4.1"
    assert "gpt-4.1" in report
    assert "Instruction Clarity" in report
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4.1"
    assert call_kwargs["temperature"] == 0.3


@pytest.mark.anyio
async def test_run_lint_mock_anthropic():
    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="Sonnet46", instructions="Be helpful."),
    )

    mock_content_block = MagicMock()
    mock_content_block.text = "## 1. Instruction Clarity\n✅ Pass\nLooks good."

    mock_response = MagicMock()
    mock_response.content = [mock_content_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("linter.AsyncAnthropic", return_value=mock_client):
        report, model_used = await run_lint(profile, anthropic_api_key="fake-key")

    assert model_used == "claude-sonnet-4-6"
    assert "claude-sonnet-4-6" in report
    assert "Instruction Clarity" in report
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-6"
    assert "system" in call_kwargs
    assert len(call_kwargs["system"]) > 0
    assert call_kwargs["temperature"] == 0.3


@pytest.mark.anyio
async def test_run_lint_missing_openai_key():
    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="GPT41", instructions="Be helpful."),
    )
    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        await run_lint(profile, openai_api_key="", anthropic_api_key="fake-key")


@pytest.mark.anyio
async def test_run_lint_missing_anthropic_key():
    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="Sonnet46", instructions="Be helpful."),
    )
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        await run_lint(profile, openai_api_key="fake-key", anthropic_api_key="")


# --- Multi-mode audit runner tests ---


def test_load_audit_modes_default():
    """The bundled YAML catalogue parses correctly and contains the
    expected modes with the right input declarations."""
    from linter import load_audit_modes

    modes = load_audit_modes()
    by_id = {m.id: m for m in modes}

    expected_ids = {"static_config", "summary", "sentiment", "pii", "answer_accuracy", "routing_quality"}
    assert expected_ids.issubset(by_id.keys())

    assert by_id["static_config"].default_enabled is True
    assert by_id["static_config"].inputs_required == ["profile"]

    for mid in ("summary", "sentiment", "pii", "answer_accuracy"):
        assert by_id[mid].default_enabled is False
        assert by_id[mid].inputs_required == ["transcript"]

    assert by_id["routing_quality"].inputs_required == ["profile", "transcript"]
    # Every mode has a non-empty system prompt (the audit content).
    for m in modes:
        assert m.system_prompt.strip()


def test_load_audit_modes_invalid_input():
    """Unknown values in `inputs_required` raise — protects against
    typos in the YAML."""
    import tempfile
    from pathlib import Path

    from linter import load_audit_modes

    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "modes.yaml"
        bad.write_text(
            "modes:\n  - id: bad\n    name: Bad\n    inputs_required: [profile, garbage]\n    system_prompt: hi\n",
            encoding="utf-8",
        )
        with pytest.raises(Exception):
            load_audit_modes(bad)


def test_build_audit_payload_static_config_unwrapped():
    """When a mode declares only `profile`, the payload is the raw
    component payload (not wrapped under a `profile` key) so the
    legacy static_config prompt sees the same shape it always has."""
    from linter import AuditMode, build_audit_payload

    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="GPT41", instructions="Be helpful."),
    )
    mode = AuditMode(
        id="static_config",
        name="Static Config",
        inputs_required=["profile"],
        system_prompt="x",
    )
    payload = build_audit_payload(mode, profile, None)
    assert "bot_name" in payload
    assert payload["bot_name"] == "TestBot"
    assert "profile" not in payload  # not wrapped


def test_build_audit_payload_combined_keeps_keys():
    """Modes that take both inputs return a dict with both top-level
    keys."""
    from models import ConversationTimeline, EventType, TimelineEvent

    from linter import AuditMode, build_audit_payload

    profile = BotProfile(display_name="TestBot")
    timeline = ConversationTimeline(
        bot_name="TestBot",
        events=[
            TimelineEvent(
                event_type=EventType.USER_MESSAGE,
                summary='User: "hi"',
                timestamp="2024-01-01T00:00:00Z",
                position=1,
            ),
        ],
    )
    mode = AuditMode(
        id="routing_quality",
        name="Routing Quality",
        inputs_required=["profile", "transcript"],
        system_prompt="x",
    )
    payload = build_audit_payload(mode, profile, timeline)
    assert "profile" in payload
    assert "transcript" in payload
    assert payload["transcript"]["events"][0]["event_type"] == "UserMessage"


def test_build_audit_payload_filters_noisy_events():
    """The transcript payload drops low-signal trace events
    (BindUpdate, etc.) so we don't pay tokens for orchestrator internals."""
    from models import ConversationTimeline, EventType, TimelineEvent

    from linter import AuditMode, build_audit_payload

    timeline = ConversationTimeline(
        events=[
            TimelineEvent(event_type=EventType.USER_MESSAGE, summary="hi", timestamp="2024-01-01T00:00:00Z"),
            TimelineEvent(event_type=EventType.DIALOG_TRACING, summary="trace noise", timestamp="2024-01-01T00:00:01Z"),
            TimelineEvent(event_type=EventType.VARIABLE_ASSIGNMENT, summary="set var", timestamp="2024-01-01T00:00:02Z"),
            TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="hello", timestamp="2024-01-01T00:00:03Z"),
        ],
    )
    mode = AuditMode(
        id="summary",
        name="Summary",
        inputs_required=["transcript"],
        system_prompt="x",
    )
    payload = build_audit_payload(mode, None, timeline)
    types = [ev["event_type"] for ev in payload["events"]]
    assert types == ["UserMessage", "BotMessage"]


@pytest.mark.anyio
async def test_run_audits_skips_transcript_mode_without_timeline():
    """Selecting a transcript-only mode without a timeline produces an
    AuditResult with `error` set instead of crashing the run."""
    from linter import run_audits

    results = await run_audits(
        profile=BotProfile(display_name="TestBot"),
        timeline=None,
        mode_ids=["summary"],
        openai_api_key="fake-key",
    )
    assert len(results) == 1
    assert results[0].mode_id == "summary"
    assert results[0].error
    assert "transcript" in results[0].error.lower()


@pytest.mark.anyio
async def test_run_audits_parallel_collects_each_result():
    """Multiple mode_ids fire in parallel and every result lands in
    the output list, in selection order."""
    from models import ConversationTimeline, EventType, TimelineEvent

    from linter import run_audits

    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="GPT41", instructions="Be helpful."),
    )
    timeline = ConversationTimeline(
        events=[
            TimelineEvent(event_type=EventType.USER_MESSAGE, summary="hi", timestamp="2024-01-01T00:00:00Z"),
            TimelineEvent(event_type=EventType.BOT_MESSAGE, summary="hello", timestamp="2024-01-01T00:00:01Z"),
        ],
    )

    async def fake_openai(api_key, model_id, system_prompt, user_content):
        # Echo the system prompt's first 12 chars so we can prove the
        # right system prompt routed to the right audit.
        return f"## Result for {system_prompt[:12]}"

    with patch("linter._audit_openai", side_effect=fake_openai):
        results = await run_audits(
            profile=profile,
            timeline=timeline,
            mode_ids=["static_config", "summary"],
            openai_api_key="fake-key",
        )

    assert [r.mode_id for r in results] == ["static_config", "summary"]
    assert all(not r.error for r in results)
    # Each result carries the model_used header.
    for r in results:
        assert "gpt-4.1" in r.markdown


@pytest.mark.anyio
async def test_run_audits_isolates_failures():
    """One mode raising an exception shouldn't take out the others —
    its result has `error` populated, others render normally."""
    from linter import run_audits

    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="GPT41"),
    )

    call_count = 0

    async def flaky(api_key, model_id, system_prompt, user_content):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("upstream timeout")
        return "## OK"

    with patch("linter._audit_openai", side_effect=flaky):
        results = await run_audits(
            profile=profile,
            timeline=None,
            mode_ids=["static_config"],
            custom_prompt="Was the bot polite?",
            openai_api_key="fake-key",
        )

    assert len(results) == 2
    failed = [r for r in results if r.error]
    ok = [r for r in results if not r.error]
    assert len(failed) == 1
    assert "upstream timeout" in failed[0].error
    assert len(ok) == 1


@pytest.mark.anyio
async def test_run_audits_custom_prompt_only():
    """Empty mode_ids + non-empty custom_prompt fires exactly one
    custom audit using whatever inputs are available."""
    from linter import run_audits

    profile = BotProfile(display_name="TestBot", gpt_info=GptInfo(model_hint="GPT41"))

    async def fake_openai(api_key, model_id, system_prompt, user_content):
        # Verify the custom system prompt was passed through.
        assert "polite" in system_prompt
        return "## Custom result"

    with patch("linter._audit_openai", side_effect=fake_openai):
        results = await run_audits(
            profile=profile,
            timeline=None,
            mode_ids=[],
            custom_prompt="Was the bot polite?",
            openai_api_key="fake-key",
        )

    assert len(results) == 1
    assert results[0].mode_id == "custom"
    assert "Custom result" in results[0].markdown


@pytest.mark.anyio
async def test_run_lint_backwards_compatible():
    """The legacy `run_lint(profile)` signature still returns
    `(markdown, model)` — no behaviour change for the existing
    Instruction Lint button."""
    profile = BotProfile(
        display_name="TestBot",
        gpt_info=GptInfo(model_hint="GPT41", instructions="Be helpful."),
    )

    async def fake_openai(api_key, model_id, system_prompt, user_content):
        return "## 1. Instruction Clarity\n✅ Pass\nLooks good."

    with patch("linter._audit_openai", side_effect=fake_openai):
        report, model_used = await run_lint(profile, openai_api_key="fake-key")

    assert model_used == "gpt-4.1"
    assert "Instruction Clarity" in report
    assert "gpt-4.1" in report  # model attribution header

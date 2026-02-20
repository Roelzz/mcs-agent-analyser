from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linter import build_component_payload, resolve_model, run_lint
from models import BotProfile, ComponentSummary, GptInfo, TopicConnection


# --- resolve_model tests ---


def test_resolve_model_known_hints():
    assert resolve_model("GPT41") == ("gpt-4.1", False)
    assert resolve_model("GPT4o") == ("gpt-4.1", False)
    assert resolve_model("GPT4oMini") == ("gpt-4.1-mini", False)
    assert resolve_model("GPT35Turbo") == ("gpt-3.5-turbo", False)


def test_resolve_model_unknown_falls_back():
    model_id, was_fallback = resolve_model("SomeNewModel")
    assert model_id == "gpt-4.1"
    assert was_fallback is True


def test_resolve_model_none():
    model_id, was_fallback = resolve_model(None)
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


# --- run_lint mock test ---


@pytest.mark.anyio
async def test_run_lint_mock():
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
        report, model_used = await run_lint(profile, "fake-key")

    assert model_used == "gpt-4.1"
    assert "gpt-4.1" in report
    assert "Instruction Clarity" in report
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4.1"
    assert call_kwargs["temperature"] == 0.3

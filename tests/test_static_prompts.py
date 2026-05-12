"""Regression tests for the static-prompt extraction layer.

Locks in the parser fields + renderer section introduced to surface
`SearchAndSummarizeContent.additionalInstructions` and the four
`aIModelDefinitions` stubs from the Employee AI Agent (UAT) export.
"""

from pathlib import Path

import pytest

from parser import parse_dialog_json, parse_yaml
from renderer import render_report
from timeline import build_timeline


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "employee_hr_uat"

EXPECTED_MODEL_NAMES = {
    "Response Structure",
    "Ticket Eligibility Checker",
    "Short Description Generation Prompt",
    "Custom prompt 02/09/2026, 12:10:03 PM",
}


@pytest.fixture(scope="module")
def profile():
    profile, _ = parse_yaml(FIXTURE_DIR / "botContent.yml")
    return profile


@pytest.fixture(scope="module")
def report(profile):
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    timeline = build_timeline(activities, {c.schema_name: c.display_name for c in profile.components})
    return render_report(profile, timeline)


def test_ai_builder_models_extracted(profile) -> None:
    assert len(profile.ai_builder_models) == 4
    assert {m.name for m in profile.ai_builder_models} == EXPECTED_MODEL_NAMES


def test_ai_builder_call_sites(profile) -> None:
    assert len(profile.ai_builder_call_sites) == 8
    model_ids = {m.id for m in profile.ai_builder_models}
    assert {cs.model_id for cs in profile.ai_builder_call_sites} == model_ids

    # The "Response Structure" model is invoked in the "Conversational
    # boosting" topic, binding its `AgentResponse` input to the CBResponse
    # text. Lock the binding so a future refactor can't silently drop it.
    response_structure = next(m for m in profile.ai_builder_models if m.name == "Response Structure")
    conv_boost_calls = [
        cs
        for cs in profile.ai_builder_call_sites
        if cs.model_id == response_structure.id and cs.host_topic_display == "Conversational boosting"
    ]
    assert len(conv_boost_calls) == 1
    assert conv_boost_calls[0].input_bindings == {"AgentResponse": "=Global.CBResponse.Text.Content"}


def test_inline_prompt_extracted(profile) -> None:
    assert len(profile.inline_prompts) == 1
    p = profile.inline_prompts[0]
    assert p.kind == "SearchAndSummarizeContent"
    assert p.host_topic_display == "Conversational boosting"
    assert p.output_variable == "Global.CBResponse"
    assert p.response_capture_type == "FullResponse"
    assert p.knowledge_sources_mode == "SearchSpecificKnowledgeSources"
    assert p.auto_send is False
    assert "OUTPUT FORMATTING RULES" in p.text
    assert len(p.text) == 2479


def test_prompts_section_in_report(report: str) -> None:
    assert "## Prompts (static)" in report
    assert "OUTPUT FORMATTING RULES" in report
    # Every AI Builder model name should appear in the section table.
    for name in EXPECTED_MODEL_NAMES:
        assert name in report
    # Dataverse-portal pointer must accompany the AI Builder table since
    # the prompt body isn't in the export.
    assert "AI Builder → Prompts" in report

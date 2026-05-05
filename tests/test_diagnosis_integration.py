"""End-to-end integration tests against real fixtures.

- Bluebot: clean success path → `succeeded=True`, no violations, no critical step.
- bot2: failed first attempt followed by automatic retry that succeeds.
  AgentRx's recovery rule says: critical step is None (recovered), but the
  audit trail records the retry-after-misinterpretation violation.
"""

from __future__ import annotations

from pathlib import Path

from diagnosis import diagnose
from diagnosis.constraints.automatic_retry_after_misinterpretation import (
    RULE_ID as RETRY_RULE,
)
from models import BotProfile, ComponentSummary, GptInfo
from parser import parse_dialog_json, parse_yaml
from timeline import build_timeline


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _profile() -> BotProfile:
    """A minimal profile — the integration test focuses on timeline-driven
    constraints, so we don't need the full Bluebot profile."""
    return BotProfile(
        display_name="X",
        schema_name="cr_x",
        components=[ComponentSummary(kind="Bot", display_name="X", schema_name="cr_x")],
        gpt_info=GptInfo(display_name="X"),
    )


class TestBluebotHappyPath:
    def test_clean_diagnose(self):
        profile, schema_lookup = parse_yaml(FIXTURE_DIR / "bluebot_botContent.yml")
        activities = parse_dialog_json(FIXTURE_DIR / "bluebot_dialog.json")
        timeline = build_timeline(activities, schema_lookup=schema_lookup)
        report = diagnose(profile, timeline, llm=False)
        assert report.succeeded is True
        assert report.critical_step_index is None
        # No critical violations (any audit-trail violations are non-critical)
        assert not [v for v in report.violations if v.severity == "critical"]


class TestBot2RetryPath:
    def test_recovered_retry_marked_succeeded(self):
        activities = parse_dialog_json(FIXTURE_DIR / "bot2_dialog.json")
        timeline = build_timeline(activities, schema_lookup={})
        report = diagnose(_profile(), timeline, llm=False)
        assert report.succeeded is True, (
            "bot2's first attempt failed but the retry succeeded — "
            "AgentRx's recovery rule should mark this as succeeded."
        )
        # The retry-after-misinterpretation rule should still record the
        # first-attempt failure for the audit trail.
        retry_violations = [v for v in report.violations if v.rule_id == RETRY_RULE]
        assert retry_violations, (
            "bot2's failed first attempt should produce a retry-after-misinterpretation "
            "violation even though the conversation recovered"
        )

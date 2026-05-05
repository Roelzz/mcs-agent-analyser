"""Tests for renderer/diagnosis.py — Markdown output."""

from __future__ import annotations

from datetime import datetime, timezone

from diagnosis.models import (
    ConstraintViolation,
    DiagnosisReport,
    FailureCategory,
    Recommendation,
    SecondaryFailure,
)
from renderer.diagnosis import render_diagnosis_md


def _empty_report(**kw) -> DiagnosisReport:
    base = dict(
        transcript_id="t-1",
        bot_id="cr_x",
        outcome="succeeded",
        critical_step_index=None,
        category=FailureCategory.INCONCLUSIVE,
        confidence="high",
        summary="",
        violations=[],
        canned_recommendations=[],
        generated_at=datetime(2026, 5, 5, 14, 30, tzinfo=timezone.utc),
    )
    base.update(kw)
    return DiagnosisReport(**base)


class TestRender:
    def test_succeeded_no_violations_returns_empty(self):
        assert render_diagnosis_md(_empty_report()) == ""

    def test_succeeded_with_violations_renders_audit_trail(self):
        v = ConstraintViolation(
            rule_id="generative_answer.unanswered",
            step_index=17000,
            severity="warn",
            description="First attempt failed; orchestrator retried.",
        )
        out = render_diagnosis_md(_empty_report(violations=[v]))
        assert "## Failure Diagnosis" in out
        assert "Conversation succeeded" in out
        assert "audit trail" in out
        assert "17000" in out

    def test_failed_renders_category_and_evidence(self):
        v = ConstraintViolation(
            rule_id="tool_error_ignored",
            step_index=23,
            severity="critical",
            description="Tool returned ORDER_NOT_FOUND, bot ignored it.",
        )
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.TOOL_MISINTERPRETATION,
            confidence="high",
            critical_step_index=23,
            summary="Tool error was ignored.",
            violations=[v],
            canned_recommendations=[
                Recommendation(source="canned", title="Add empty-result handling", body_md="Check IsBlank()."),
            ],
            judge_model="gpt-5",
        )
        out = render_diagnosis_md(report)
        assert "Misinterpretation" in out
        assert "**Confidence:** High" in out
        assert "position 23" in out
        assert "gpt-5" in out
        assert "Add empty-result handling" in out

    def test_error_state_renders_warning_callout(self):
        report = _empty_report(
            error_state=True,
            error_message="Judge returned non-JSON",
        )
        out = render_diagnosis_md(report)
        assert "judge could not produce a verdict" in out
        assert "Judge returned non-JSON" in out

    def test_redaction_summary_rendered(self):
        v = ConstraintViolation(rule_id="r", step_index=1, severity="critical", description="x")
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.SYSTEM_FAILURE,
            critical_step_index=1,
            violations=[v],
            redaction_summary={"EMAIL": 2, "PHONE": 1},
        )
        out = render_diagnosis_md(report)
        assert "Redacted before LLM call" in out
        assert "email: 2" in out

    def test_evidence_table_includes_category_column(self):
        v = ConstraintViolation(
            rule_id="ungrounded_generative_answer",
            step_index=10,
            severity="critical",
            description="Fell back to GPT defaults.",
            default_category_seed=FailureCategory.INVENTION,
        )
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.INVENTION,
            critical_step_index=10,
            violations=[v],
        )
        out = render_diagnosis_md(report)
        assert "| Step | Rule | Severity | Category | Description |" in out
        # Each violation row should carry the category badge + label.
        assert "Invention of New Information" in out

    def test_categories_detected_line_when_multiple_seeds(self):
        v1 = ConstraintViolation(
            rule_id="r1",
            step_index=10,
            severity="critical",
            description="d1",
            default_category_seed=FailureCategory.TOOL_MISINTERPRETATION,
        )
        v2 = ConstraintViolation(
            rule_id="r2",
            step_index=15,
            severity="warn",
            description="d2",
            default_category_seed=FailureCategory.UNDERSPECIFIED_INTENT,
        )
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.TOOL_MISINTERPRETATION,
            critical_step_index=10,
            violations=[v1, v2],
        )
        out = render_diagnosis_md(report)
        assert "**Categories detected:**" in out
        assert "Misinterpretation of Tool Output" in out
        assert "Underspecified User Intent" in out

    def test_no_breakdown_line_when_only_one_seed(self):
        v = ConstraintViolation(
            rule_id="r",
            step_index=1,
            severity="critical",
            description="x",
            default_category_seed=FailureCategory.SYSTEM_FAILURE,
        )
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.SYSTEM_FAILURE,
            critical_step_index=1,
            violations=[v],
        )
        out = render_diagnosis_md(report)
        assert "Categories detected" not in out

    def test_secondary_findings_section_rendered(self):
        v = ConstraintViolation(rule_id="r", step_index=1, severity="critical", description="x")
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.TOOL_MISINTERPRETATION,
            critical_step_index=1,
            violations=[v],
            secondary_failures=[
                SecondaryFailure(
                    step_index=42,
                    category=FailureCategory.UNDERSPECIFIED_INTENT,
                    reason="user input was ambiguous and bot guessed",
                    severity="medium",
                ),
            ],
        )
        out = render_diagnosis_md(report)
        assert "Secondary findings (LLM judge)" in out
        assert "42" in out
        assert "Underspecified User Intent" in out
        assert "medium" in out

    def test_no_secondary_section_when_empty(self):
        v = ConstraintViolation(rule_id="r", step_index=1, severity="critical", description="x")
        report = _empty_report(
            outcome="failed",
            category=FailureCategory.SYSTEM_FAILURE,
            critical_step_index=1,
            violations=[v],
        )
        out = render_diagnosis_md(report)
        assert "Secondary findings" not in out

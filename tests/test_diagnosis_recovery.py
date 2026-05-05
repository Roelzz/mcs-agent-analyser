"""Tests for diagnosis/recovery.py — the AgentRx critical-step algorithm."""

from __future__ import annotations

from diagnosis.models import ConstraintViolation
from diagnosis.recovery import pick_critical_step
from models import (
    ConversationTimeline,
    GenerativeAnswerTrace,
    ToolCall,
)


def _v(step: int, severity: str = "critical", **kw) -> ConstraintViolation:
    kw.setdefault("rule_id", "rule")
    kw.setdefault("description", "x")
    return ConstraintViolation(step_index=step, severity=severity, **kw)


class TestPickCriticalStep:
    def test_no_violations_returns_none(self):
        assert pick_critical_step([], ConversationTimeline()) is None

    def test_info_only_violations_returns_none(self):
        violations = [_v(5, severity="info"), _v(10, severity="info")]
        assert pick_critical_step(violations, ConversationTimeline()) is None

    def test_critical_unrecovered_returns_first(self):
        violations = [_v(10, severity="warn"), _v(20, severity="critical")]
        timeline = ConversationTimeline()
        crit = pick_critical_step(violations, timeline)
        assert crit is not None and crit.step_index == 10  # first critical-or-warn

    def test_critical_recovered_via_answered_returns_none(self):
        violations = [_v(10, severity="critical")]
        timeline = ConversationTimeline(
            generative_answer_traces=[GenerativeAnswerTrace(position=20, gpt_answer_state="Answered")]
        )
        assert pick_critical_step(violations, timeline) is None

    def test_critical_recovered_via_successful_tool_returns_none(self):
        violations = [_v(10, severity="critical")]
        timeline = ConversationTimeline(tool_calls=[ToolCall(state="completed", position=20, display_name="X")])
        assert pick_critical_step(violations, timeline) is None

    def test_two_violations_first_recovered_second_not(self):
        v1 = _v(10, severity="critical")
        v2 = _v(30, severity="critical")
        timeline = ConversationTimeline(
            tool_calls=[ToolCall(state="completed", position=20, display_name="A")],
            # Nothing after position 30
        )
        crit = pick_critical_step([v1, v2], timeline)
        assert crit is not None and crit.step_index == 30

    def test_violations_sorted_by_step_index(self):
        v_late = _v(50, severity="critical")
        v_early = _v(5, severity="critical")
        crit = pick_critical_step([v_late, v_early], ConversationTimeline())
        assert crit is not None and crit.step_index == 5

    def test_specific_task_dialog_id_evidence_requires_exact_match(self):
        """When a violation's `evidence` carries a `task_dialog_id`, recovery
        is strict — only a successful later tool call for that same
        task_dialog_id counts. A successful unrelated tool call does NOT
        recover, so the violation remains the critical step."""
        v = _v(
            10,
            severity="critical",
            evidence={"task_dialog_id": "td.SearchFlights"},
        )
        timeline = ConversationTimeline(
            tool_calls=[
                ToolCall(
                    state="completed",
                    position=20,
                    display_name="UnrelatedAPI",
                    task_dialog_id="td.UnrelatedAPI",
                )
            ]
        )
        crit = pick_critical_step([v], timeline)
        assert crit is not None and crit.step_index == 10

    def test_recovery_via_specific_task_dialog_id_match(self):
        v = _v(
            10,
            severity="critical",
            evidence={"task_dialog_id": "td.SearchFlights"},
        )
        timeline = ConversationTimeline(
            tool_calls=[
                ToolCall(
                    state="completed",
                    position=25,
                    display_name="SearchFlights",
                    task_dialog_id="td.SearchFlights",
                )
            ]
        )
        assert pick_critical_step([v], timeline) is None

    def test_warn_violation_unrecovered_picked(self):
        """`warn`-severity violations also count as critical-step candidates
        when they aren't recovered. Only `info` is filtered out."""
        v = _v(15, severity="warn")
        timeline = ConversationTimeline()  # no recovery markers
        crit = pick_critical_step([v], timeline)
        assert crit is not None and crit.step_index == 15

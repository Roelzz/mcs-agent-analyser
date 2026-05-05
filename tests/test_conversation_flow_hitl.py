"""Tests for HITL exchange surfacing in `build_conversation_flow_items`.

Issue C from the AgentRx false-positive plan: human-in-the-loop tool calls
were rendered as two opaque "Step start / Step end" rows. Verify the new
`kind="hitl_exchange"` row carries the request fields + the response pairs,
and that the original Triggered/Finished rows are suppressed for that step.
"""

from __future__ import annotations

import json

from models import (
    ConversationTimeline,
    EventType,
    TimelineEvent,
    ToolCall,
    ToolCallObservation,
)
from renderer.sections import (
    _hitl_request_input_keys,
    _hitl_response_pairs,
    _is_hitl_tool_call,
    build_conversation_flow_items,
    group_flow_items,
)


def _ev(event_type: EventType, position: int, **kw) -> TimelineEvent:
    kw.setdefault("timestamp", f"2024-01-01T00:00:{position:02d}Z")
    return TimelineEvent(event_type=event_type, position=position, **kw)


def _hitl_tool_call(*, step_id: str, finished: bool = True, observation: dict | None = None) -> ToolCall:
    obs_input_schema = json.dumps(
        {
            "properties": {
                "attendee_count": {"title": "Number of Attendees"},
                "merchant_name": {"title": "Merchant"},
                "expense_date": {"title": "Date"},
            },
            "required": ["attendee_count", "merchant_name", "expense_date"],
        }
    )
    args = {
        "title": "Customer Dinner Expense Details Needed - €200",
        "message": "Please confirm the merchant, date and attendee count.",
        "assignedTo": "roel@example.com",
        "input": obs_input_schema,
    }
    return ToolCall(
        step_id=step_id,
        task_dialog_id="rrs_agent_orchestrator.action.Humanintheloop-Requestforinformationpreview",
        display_name="human_in_the_loop_request_for_information",
        state="completed" if finished else "inProgress",
        arguments=args,
        observation=ToolCallObservation(structured_content=observation) if observation else None,
        position=20,
        duration_ms=66000,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_hitl_tool_call_matches_humanintheloop(self):
        tc = ToolCall(task_dialog_id="rrs_agent_orchestrator.action.Humanintheloop-Requestforinformationpreview")
        assert _is_hitl_tool_call(tc) is True

    def test_is_hitl_tool_call_matches_request_for_information(self):
        tc = ToolCall(display_name="human_in_the_loop_request_for_information")
        assert _is_hitl_tool_call(tc) is True

    def test_is_hitl_tool_call_negative(self):
        tc = ToolCall(
            task_dialog_id="MCP:zava.expense.create_expense",
            display_name="create_expense",
        )
        assert _is_hitl_tool_call(tc) is False

    def test_request_input_keys_extracted_in_order(self):
        args = {
            "input": json.dumps(
                {
                    "properties": {
                        "attendee_count": {},
                        "merchant_name": {},
                        "expense_date": {},
                    }
                }
            )
        }
        keys = _hitl_request_input_keys(args)
        assert keys == ["attendee_count", "merchant_name", "expense_date"]

    def test_request_input_keys_handles_missing_input(self):
        assert _hitl_request_input_keys({}) == []

    def test_request_input_keys_handles_malformed_json(self):
        assert _hitl_request_input_keys({"input": "{not valid"}) == []

    def test_response_pairs_skips_responder_object_id(self):
        obs = ToolCallObservation(
            structured_content={
                "merchant_name": "Contoso",
                "responderObjectId": "00000000-0000",
            }
        )
        pairs = _hitl_response_pairs(obs)
        keys = [p["key"] for p in pairs]
        assert "merchant_name" in keys
        assert "responderObjectId" not in keys

    def test_response_pairs_empty_when_no_observation(self):
        assert _hitl_response_pairs(None) == []


# ---------------------------------------------------------------------------
# Flow row replacement
# ---------------------------------------------------------------------------


class TestFlowReplacement:
    def test_finished_hitl_emits_single_exchange_row(self):
        tc = _hitl_tool_call(
            step_id="hitl1",
            finished=True,
            observation={
                "attendee_count": "4",
                "merchant_name": "Contoso",
                "expense_date": "2026-03-05",
            },
        )
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="User: please log a dinner"),
            _ev(EventType.STEP_TRIGGERED, 10, step_id="hitl1", topic_name="hitl-topic"),
            _ev(EventType.STEP_FINISHED, 20, step_id="hitl1", state="completed", topic_name="hitl-topic"),
        ]
        timeline = ConversationTimeline(events=events, tool_calls=[tc])
        items = build_conversation_flow_items(timeline)

        # Exactly one hitl_exchange row, and zero generic step rows for hitl1.
        hitl_rows = [it for it in items if it["kind"] == "hitl_exchange"]
        assert len(hitl_rows) == 1
        step_rows_for_hitl = [
            it for it in items if it["kind"] == "event" and it["title"] in {"Action Started", "Action Finished"}
        ]
        assert step_rows_for_hitl == []

        row = hitl_rows[0]
        assert row["title"] == "Human-in-the-loop"
        assert row["hitl_request_title"].startswith("Customer Dinner")
        assert row["hitl_assignee"] == "roel@example.com"
        assert row["hitl_request_input_keys"] == ["attendee_count", "merchant_name", "expense_date"]
        # Response pairs preserved (and ordered as dict iteration order)
        keys = [p["key"] for p in row["hitl_response_pairs"]]
        assert keys == ["attendee_count", "merchant_name", "expense_date"]
        assert row["hitl_state"] == "completed"
        # Duration formatted somehow non-empty
        assert row["hitl_duration_label"] != ""

    def test_inflight_hitl_emits_inprogress_row_with_no_response(self):
        tc = _hitl_tool_call(step_id="hitl1", finished=False, observation=None)
        events = [
            _ev(EventType.USER_MESSAGE, 1, summary="User: please log a dinner"),
            _ev(EventType.STEP_TRIGGERED, 10, step_id="hitl1"),
            # No STEP_FINISHED — still awaiting reviewer.
        ]
        timeline = ConversationTimeline(events=events, tool_calls=[tc])
        items = build_conversation_flow_items(timeline)

        hitl_rows = [it for it in items if it["kind"] == "hitl_exchange"]
        assert len(hitl_rows) == 1
        row = hitl_rows[0]
        assert row["hitl_state"] == "inProgress"
        assert row["hitl_response_pairs"] == []

    def test_non_hitl_step_still_renders_generic_rows(self):
        tc = ToolCall(step_id="reg1", display_name="regular_tool", state="completed")
        events = [
            _ev(EventType.STEP_TRIGGERED, 10, step_id="reg1", topic_name="t"),
            _ev(EventType.STEP_FINISHED, 20, step_id="reg1", state="completed", topic_name="t"),
        ]
        timeline = ConversationTimeline(events=events, tool_calls=[tc])
        items = build_conversation_flow_items(timeline)
        kinds = [it["kind"] for it in items]
        assert "hitl_exchange" not in kinds
        assert items[0]["title"] == "Action Started"
        assert items[1]["title"] == "Action Finished"


# ---------------------------------------------------------------------------
# group_flow_items — multi-plan trace must preserve all plans
# ---------------------------------------------------------------------------


class TestGroupFlowMultiPlan:
    """Regression: when the orchestrator re-plans mid-run (multiple
    PlanReceived without intermediate PlanFinished events), every plan and
    its items must survive grouping. The Zava trace has 5 PlanReceived + 1
    PlanFinished; pre-fix, 4 plans were silently dropped — including the
    one that contained the HITL exchange."""

    def test_two_planreceived_without_planfinished_keeps_both(self):
        items = [
            {"kind": "message", "event_type": "", "plan_identifier": "", "timestamp": "t0"},
            {"kind": "event", "event_type": "PlanReceived", "plan_identifier": "p1-1234", "timestamp": "t1"},
            {"kind": "event", "event_type": "StepTriggered", "plan_identifier": "", "timestamp": "t2"},
            # NEW PlanReceived without a PlanFinished — used to overwrite p1
            {"kind": "event", "event_type": "PlanReceived", "plan_identifier": "p2-5678", "timestamp": "t3"},
            {"kind": "hitl_exchange", "event_type": "StepFinished", "plan_identifier": "", "timestamp": "t4"},
            {"kind": "event", "event_type": "PlanFinished", "plan_identifier": "", "timestamp": "t5"},
        ]
        groups = group_flow_items(items)

        # 1 loose + 2 plan groups
        plan_groups = [g for g in groups if g["is_plan"] == "true"]
        assert len(plan_groups) == 2
        # Plan #1 is "running" (no PlanFinished closed it)
        assert plan_groups[0]["status"] == "running"
        assert "running" in plan_groups[0]["header_summary"].lower()
        # Plan #2 is "completed" (closed by PlanFinished)
        assert plan_groups[1]["status"] == "completed"
        # HITL row landed in plan #2
        hitl_groups = [g for g in plan_groups if any(it["kind"] == "hitl_exchange" for it in g["items"])]
        assert len(hitl_groups) == 1
        assert hitl_groups[0]["plan_identifier"] == "p2-5678"

    def test_no_items_dropped_in_multi_plan(self):
        items = [
            {"kind": "event", "event_type": "PlanReceived", "plan_identifier": "p1", "timestamp": "t1"},
            {"kind": "event", "event_type": "StepTriggered", "plan_identifier": "", "timestamp": "t2"},
            {"kind": "event", "event_type": "StepFinished", "plan_identifier": "", "timestamp": "t3"},
            {"kind": "event", "event_type": "PlanReceived", "plan_identifier": "p2", "timestamp": "t4"},
            {"kind": "event", "event_type": "StepTriggered", "plan_identifier": "", "timestamp": "t5"},
            {"kind": "event", "event_type": "PlanReceived", "plan_identifier": "p3", "timestamp": "t6"},
            {"kind": "event", "event_type": "PlanFinished", "plan_identifier": "", "timestamp": "t7"},
        ]
        groups = group_flow_items(items)
        total_in_groups = sum(len(g["items"]) for g in groups)
        # All 7 items must survive — 0 silent drops.
        assert total_in_groups == len(items)
        # 3 plan groups (one per PlanReceived).
        plan_groups = [g for g in groups if g["is_plan"] == "true"]
        assert len(plan_groups) == 3


# ---------------------------------------------------------------------------
# Response-pair unpacking edge cases (`_hitl_response_pairs`)
# ---------------------------------------------------------------------------


class TestHitlResponsePairsEdgeCases:
    def test_nested_dict_value_json_stringified(self):
        """Some HITL responses include nested objects (e.g. address record).
        These must be JSON-stringified so the rendered card can show them
        as a single value cell instead of crashing on a dict value."""
        obs = ToolCallObservation(
            structured_content={
                "address": {"city": "Amsterdam", "country": "NL"},
                "merchant_name": "Contoso",
            }
        )
        pairs = _hitl_response_pairs(obs)
        keys = {p["key"] for p in pairs}
        assert "address" in keys
        addr_value = next(p["value"] for p in pairs if p["key"] == "address")
        assert "Amsterdam" in addr_value and "NL" in addr_value

    def test_list_value_json_stringified(self):
        obs = ToolCallObservation(
            structured_content={
                "tags": ["urgent", "review"],
                "merchant_name": "Contoso",
            }
        )
        pairs = _hitl_response_pairs(obs)
        tags_value = next(p["value"] for p in pairs if p["key"] == "tags")
        assert "urgent" in tags_value and "review" in tags_value

    def test_none_value_renders_empty_string(self):
        obs = ToolCallObservation(structured_content={"x": None, "y": "ok"})
        pairs = _hitl_response_pairs(obs)
        x_value = next(p["value"] for p in pairs if p["key"] == "x")
        assert x_value == ""

    def test_empty_structured_content_returns_empty_list(self):
        obs = ToolCallObservation(structured_content={})
        assert _hitl_response_pairs(obs) == []

    def test_non_dict_observation_returns_empty_list(self):
        """Some connectors return a list (e.g. `[item, item]`) instead of a
        dict envelope. The renderer must not crash — return [] gracefully."""
        obs = ToolCallObservation(content=[{"x": 1}], structured_content=None)
        # structured_content is None → no key/value pairs to render.
        assert _hitl_response_pairs(obs) == []

    def test_long_value_truncated_to_300_chars(self):
        """The renderer caps each value at 300 chars so a verbose connector
        response doesn't blow the card layout."""
        obs = ToolCallObservation(structured_content={"summary": "x" * 1000})
        pairs = _hitl_response_pairs(obs)
        assert len(pairs[0]["value"]) <= 300

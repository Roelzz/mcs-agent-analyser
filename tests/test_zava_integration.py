"""End-to-end integration test against the Zava expense-flow fixture.

This is the customer transcript that revealed the grouping bug
(`renderer/sections.py:group_flow_items` used to silently drop every plan
except the last one, hiding the HITL exchange). Skipped when the fixture
isn't present so the suite stays green for contributors without the zip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parser import parse_dialog_json, parse_yaml
from renderer.sections import build_conversation_flow_items, group_flow_items
from timeline import build_timeline


_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_DIALOG = _FIXTURE_DIR / "zava_dialog.json"
_BOT = _FIXTURE_DIR / "zava_botContent.yml"

pytestmark = pytest.mark.skipif(
    not (_DIALOG.exists() and _BOT.exists()),
    reason="Zava fixtures not present (customer data, gitignored)",
)


@pytest.fixture(scope="module")
def zava_flow():
    profile, schema_lookup = parse_yaml(_BOT)
    activities = parse_dialog_json(_DIALOG)
    timeline = build_timeline(activities, schema_lookup=schema_lookup)
    items = build_conversation_flow_items(timeline, profile=profile)
    groups = group_flow_items(items)
    return {"timeline": timeline, "items": items, "groups": groups}


def test_no_items_dropped_during_grouping(zava_flow):
    """Every flow item must end up in some group. Pre-fix this dropped 19
    of 27 items because mid-conversation re-plans overwrote each other."""
    items = zava_flow["items"]
    in_groups = sum(len(g["items"]) for g in zava_flow["groups"])
    assert in_groups == len(items), f"group_flow_items dropped items: {len(items)} -> {in_groups}"


def test_every_planreceived_produces_a_plan_group(zava_flow):
    pr_count = sum(1 for it in zava_flow["items"] if it.get("event_type") == "PlanReceived")
    plan_groups = [g for g in zava_flow["groups"] if g["is_plan"] == "true"]
    assert pr_count >= 2, "fixture should have multiple plans (regression sanity)"
    assert len(plan_groups) == pr_count


def test_hitl_exchange_visible_in_grouped_output(zava_flow):
    """The whole reason this fixture is here — the HITL card must end up
    inside a plan group, with the disputed values populated."""
    hitl_in_groups = [it for g in zava_flow["groups"] for it in g["items"] if it.get("kind") == "hitl_exchange"]
    assert len(hitl_in_groups) >= 1, "HITL exchange should appear inside a plan group"
    row = hitl_in_groups[0]
    pair_keys = {p["key"] for p in row["hitl_response_pairs"]}
    # The five values the judge previously called "invented" — should be on
    # the rendered card. (responderObjectId is filtered out.)
    assert "merchant_name" in pair_keys
    assert "expense_date" in pair_keys
    assert "attendee_count" in pair_keys


def test_hitl_exchange_request_metadata_extracted(zava_flow):
    hitl_rows = [it for it in zava_flow["items"] if it.get("kind") == "hitl_exchange"]
    assert hitl_rows, "expected at least one hitl_exchange row"
    row = hitl_rows[0]
    assert row["hitl_request_title"]  # bot's "Customer Dinner Expense Details Needed"
    assert row["hitl_assignee"]  # the email/UPN of the reviewer
    assert isinstance(row["hitl_request_input_keys"], list)
    assert len(row["hitl_request_input_keys"]) >= 3  # bot asked for at least a few fields


def test_mcp_tool_calls_resolve_to_server_component(zava_flow):
    """MCP tool calls have topic_names like `ZavaExpenseMCP:create_new_expense_report`
    where the prefix is the server's display_name with whitespace stripped.
    The link resolver must map all such rows back to the parent MCP server
    component so they get a deep-link icon."""
    mcp_rows = [it for it in zava_flow["items"] if "ZavaExpenseMCP:" in (it.get("topic_name") or "")]
    assert mcp_rows, "fixture should contain MCP tool-call rows"
    for row in mcp_rows:
        assert row["link_target_tab"] == "tools", f"MCP row should link to tools tab; got {row['link_target_tab']!r}"
        assert "ZavaExpenseMCP" in row["link_target_id"], (
            f"MCP row should resolve to the ZavaExpenseMCP server schema; got {row['link_target_id']!r}"
        )

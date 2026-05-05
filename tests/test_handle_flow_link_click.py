"""Unit tests for `DynamicMixin.handle_flow_link_click`.

The handler is wired to every clickable link icon on the Conversation tab —
Conversation Flow rows, Variable Tracker, Performance Waterfall, Phase
Breakdown, Orchestrator Reasoning, HITL exchange. It accepts both naming
conventions used by the row builders (`tools` / `component` / `knowledge`).

Tests instantiate a minimal stand-in for `self` (the Reflex State machinery
isn't needed to validate the routing logic) and invoke the unbound handler
directly. Side effects: `mcs_analyse_tab` and `mcs_topic_explorer_selected`.
The returned EventSpec (or None) is also checked via type-name matching.
"""

from __future__ import annotations

from types import SimpleNamespace

from web.state._dynamic import DynamicMixin


def _stub_state():
    """A duck-typed stand-in for the State subclass that carries only the
    attributes `handle_flow_link_click` reads and writes. Avoids needing the
    full Reflex state machinery for a unit test."""
    return SimpleNamespace(mcs_analyse_tab="profile", mcs_topic_explorer_selected="")


class TestToolsRouting:
    def test_target_tools_switches_tab_and_selects_component(self):
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "tools", "cr_orderstatus")
        assert s.mcs_analyse_tab == "tools"
        assert s.mcs_topic_explorer_selected == "cr_orderstatus"
        # Result is a Reflex EventSpec for the scroll script — not None.
        assert result is not None

    def test_target_component_is_alias_for_tools(self):
        """Variable Tracker / Waterfall rows pass `link_target_kind="component"`
        instead of `"tools"`. Both paths must hit the same destination."""
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "component", "cr_my_topic")
        assert s.mcs_analyse_tab == "tools"
        assert s.mcs_topic_explorer_selected == "cr_my_topic"
        assert result is not None

    def test_tools_with_empty_target_id_still_switches_tab(self):
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "tools", "")
        assert s.mcs_analyse_tab == "tools"
        # Don't blow away whatever the explorer was showing if no id was passed.
        assert s.mcs_topic_explorer_selected == ""
        # We still return the scroll script so the explorer card scrolls in.
        assert result is not None


class TestKnowledgeRouting:
    def test_target_knowledge_switches_tab(self):
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "knowledge", "Bluebot Topic")
        assert s.mcs_analyse_tab == "knowledge"
        # The component explorer selection isn't touched by knowledge links.
        assert s.mcs_topic_explorer_selected == ""
        assert result is not None

    def test_knowledge_with_empty_target_id_returns_none(self):
        """No topic name → no scroll script (nothing to scroll to). Tab still
        switches so the user lands on the right page."""
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "knowledge", "")
        assert s.mcs_analyse_tab == "knowledge"
        assert result is None

    def test_knowledge_topic_with_special_chars_sanitized(self):
        """The DOM id sanitiser replaces non-alphanumerics with '-' so the
        scroll target matches whatever the destination card emits."""
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "knowledge", 'Topic with "quotes" / spaces')
        # We can't easily inspect the script body here, but it must not crash.
        assert result is not None
        assert s.mcs_analyse_tab == "knowledge"


class TestNoOpRouting:
    def test_empty_target_returns_none(self):
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "", "anything")
        assert s.mcs_analyse_tab == "profile"  # unchanged
        assert s.mcs_topic_explorer_selected == ""
        assert result is None

    def test_unknown_target_returns_none(self):
        s = _stub_state()
        result = DynamicMixin.handle_flow_link_click(s, "blah", "x")
        assert s.mcs_analyse_tab == "profile"
        assert result is None

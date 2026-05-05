"""Unit tests for `renderer.sections._build_dialog_link_resolver`.

The resolver maps a `topic_name` (as it appears on a TimelineEvent) to a
`(link_target_tab, link_target_id)` pair. The Conversation Flow / Variable
Tracker / Performance Waterfall click handlers all call into this. The
Zava integration test covers the happy path against a real fixture; this
file pins the resolution rules in isolation."""

from __future__ import annotations

from models import BotProfile, ComponentSummary
from renderer.sections import _build_dialog_link_resolver


def _profile(*components: ComponentSummary) -> BotProfile:
    return BotProfile(
        display_name="Test Bot",
        schema_name="cr_test",
        components=list(components),
    )


def _topic(*, schema: str, display: str, kind: str = "DialogComponent") -> ComponentSummary:
    return ComponentSummary(kind=kind, schema_name=schema, display_name=display)


class TestResolverHappyPath:
    def test_display_name_match_case_insensitive(self):
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_topic_a", display="Order Status")))
        assert resolve("Order Status") == ("tools", "cr_topic_a")
        assert resolve("ORDER STATUS") == ("tools", "cr_topic_a")
        assert resolve("  order status  ") == ("tools", "cr_topic_a")

    def test_schema_name_match_case_insensitive(self):
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_topic_OrderStatus", display="Order Status")))
        assert resolve("cr_topic_OrderStatus") == ("tools", "cr_topic_OrderStatus")
        assert resolve("cr_topic_orderstatus") == ("tools", "cr_topic_OrderStatus")


class TestMcpServerToolPrefix:
    """MCP tool calls are emitted as `<DisplayNameNoSpaces>:<tool>`. The
    resolver must split on `:`, drop the colon-suffix, and match the prefix
    against a whitespace-stripped display_name index."""

    def test_mcp_prefix_matches_display_name_with_spaces(self):
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_topic_zava", display="Zava Expense MCP")))
        assert resolve("ZavaExpenseMCP:create_new_expense_report") == (
            "tools",
            "cr_topic_zava",
        )
        assert resolve("ZavaExpenseMCP:add_new_line_item") == (
            "tools",
            "cr_topic_zava",
        )

    def test_mcp_prefix_matches_hyphenated_display_name(self):
        # e.g. an MCP server called "Foo-Bar Server" emits "FooBarServer:tool"
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_foo", display="Foo-Bar Server")))
        assert resolve("FooBarServer:do_thing") == ("tools", "cr_foo")

    def test_mcp_prefix_with_unknown_server_does_not_resolve(self):
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_topic_zava", display="Zava Expense MCP")))
        assert resolve("UnknownMCP:tool") == ("", "")


class TestNoMatch:
    def test_none_profile_returns_empty(self):
        resolve = _build_dialog_link_resolver(None)
        assert resolve("anything") == ("", "")
        assert resolve("Order Status") == ("", "")

    def test_unknown_topic_name_returns_empty(self):
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_a", display="Topic A")))
        assert resolve("Topic Z") == ("", "")

    def test_empty_topic_name_returns_empty(self):
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="cr_a", display="Topic A")))
        assert resolve("") == ("", "")

    def test_component_without_schema_unaddressable(self):
        # An empty schema_name means the picker can't select it — drop.
        resolve = _build_dialog_link_resolver(_profile(_topic(schema="", display="Phantom Topic")))
        assert resolve("Phantom Topic") == ("", "")

    def test_non_dialogcomponent_kinds_skipped(self):
        # KnowledgeSource / FileAttachment / Variable etc. are not in the index.
        resolve = _build_dialog_link_resolver(
            _profile(
                _topic(schema="cr_kb", display="My KB", kind="KnowledgeSource"),
                _topic(schema="cr_real", display="Real Topic"),
            )
        )
        assert resolve("My KB") == ("", "")
        assert resolve("Real Topic") == ("tools", "cr_real")


class TestDeterministicResolution:
    """Earlier the resolver did fuzzy suffix matching that mis-routed
    namespace-style schemas (e.g. `org.foo.Topic` and `org.bar.Topic` both
    matched on `Topic`). The current resolver uses exact / colon-prefix
    matching only — verify a clean miss when nothing exact matches."""

    def test_namespace_collision_does_not_misroute(self):
        resolve = _build_dialog_link_resolver(
            _profile(
                _topic(schema="org.foo.Topic", display="Foo Topic"),
                _topic(schema="org.bar.Topic", display="Bar Topic"),
            )
        )
        # `Topic` alone is ambiguous → clean miss.
        assert resolve("Topic") == ("", "")
        # Exact display_name still works.
        assert resolve("Foo Topic") == ("tools", "org.foo.Topic")

"""Topic-settings explainer tests.

Coverage policy: every action `kind` encountered in test fixtures must resolve
to either a real KB entry OR an explicit `not yet documented` sentinel — never
silently fill in a synthesised summary. These tests pin that contract.
"""

import pytest

from models import ComponentSummary
from renderer.topic_explainer import (
    _NOT_DOCUMENTED_SUMMARY,
    collect_kinds,
    collect_undocumented,
    explain_component,
    explain_topic,
    load_kb,
    render_explainer_for_topic,
    render_explainer_node_markdown,
)


@pytest.fixture(scope="module")
def kb() -> dict:
    return load_kb()


# ── KB shape ─────────────────────────────────────────────────────────────────


def test_kb_has_required_kinds_for_ct7500_bot(kb):
    """The CT7500 bot relies on these kinds. They must be in the KB."""
    required = {
        "OnRecognizedIntent",
        "SetVariable",
        "SearchAndSummarizeContent",
        "KnowledgeSourceComponent",
        "AdaptiveDialog",
    }
    missing = required - set(kb["kinds"].keys())
    assert not missing, f"KB missing required kinds: {missing}"


def test_kb_entries_have_summary_and_doc(kb):
    """Every kind entry must have both `summary` and `doc` — otherwise it's
    indistinguishable from "not yet documented" and shouldn't be in the KB."""
    for kind, entry in kb["kinds"].items():
        assert isinstance(entry, dict), f"{kind}: entry is not a dict"
        assert entry.get("summary"), f"{kind}: missing `summary`"
        assert entry.get("doc"), f"{kind}: missing `doc`"
        assert entry["doc"].startswith("https://"), f"{kind}: doc URL must be absolute, got {entry['doc']!r}"


def test_kb_enum_property_values_have_summaries(kb):
    """Enum-typed properties must list `values` and each value must have a summary."""
    for kind, entry in kb["kinds"].items():
        for prop_name, prop_entry in (entry.get("properties") or {}).items():
            if prop_entry.get("type") == "enum":
                values = prop_entry.get("values")
                assert isinstance(values, dict) and values, f"{kind}.{prop_name}: enum property without `values`"
                for val_name, val_entry in values.items():
                    assert val_entry.get("summary"), f"{kind}.{prop_name}.{val_name}: missing summary"


# ── Walker behaviour ─────────────────────────────────────────────────────────


def _ct7500_topic() -> ComponentSummary:
    """Builds a ComponentSummary mimicking the CT7500 topic from
    `botContent (4) (2).zip` — the user's real misconfigured bot."""
    return ComponentSummary(
        kind="DialogComponent",
        display_name="CT 7500",
        schema_name="cr365_agentLwPBHm.topic.CT7500",
        raw_dialog={
            "modelDescription": "this topic helps answers the questions about CT7500.",
            "beginDialog": {
                "kind": "OnRecognizedIntent",
                "id": "main",
                "intent": {"triggerQueries": ["CT 7500", "Tell me about CT 7500"]},
                "actions": [
                    {
                        "kind": "SetVariable",
                        "id": "setVariable_tL1WlG",
                        "variable": "Topic.Question",
                        "value": "=System.LastMessage.Text",
                    },
                    {
                        "kind": "SearchAndSummarizeContent",
                        "id": "WQo9eG",
                        "variable": "Topic.Var1",
                        "userInput": "=Topic.Question",
                        "fileSearchDataSource": {"searchFilesMode": {"kind": "SearchAllFiles"}},
                        "knowledgeSources": {"kind": "SearchAllKnowledgeSources"},
                    },
                ],
            },
        },
    )


def test_explainer_walks_ct7500_topic(kb):
    """End-to-end walk of the user's actual topic produces the expected tree."""
    root = explain_topic(_ct7500_topic(), kb)
    assert root is not None
    assert root.kind == "OnRecognizedIntent"
    assert root.documented is True
    assert root.doc_url and "learn.microsoft.com" in root.doc_url

    kinds = collect_kinds(root)
    assert kinds == {"OnRecognizedIntent", "SetVariable", "SearchAndSummarizeContent"}, (
        f"unexpected kinds in walk: {kinds}"
    )


def test_explainer_resolves_searchallknowledgesources_enum(kb):
    """The user's bug — `knowledgeSources.kind: SearchAllKnowledgeSources` —
    must resolve to a property entry whose summary calls out the
    triggerCondition interaction (the whole reason this feature exists)."""
    root = explain_topic(_ct7500_topic(), kb)
    sas = next(c for c in root.children if c.kind == "SearchAndSummarizeContent")
    ks_prop = next(p for p in sas.properties if p.path == "knowledgeSources.kind")
    assert ks_prop.documented is True
    assert ks_prop.value == "SearchAllKnowledgeSources"
    assert "triggerCondition" in (ks_prop.summary or "")


def test_explainer_resolves_setvariable_properties(kb):
    root = explain_topic(_ct7500_topic(), kb)
    sv = next(c for c in root.children if c.kind == "SetVariable")
    paths = {p.path: p for p in sv.properties}
    assert "variable" in paths
    assert paths["variable"].value == "Topic.Question"
    assert paths["variable"].documented is True
    assert "value" in paths
    assert paths["value"].value == "=System.LastMessage.Text"
    assert paths["value"].documented is True


def test_undocumented_kind_emits_sentinel(kb):
    """An invented kind must surface as `documented=False` with a visible
    sentinel — not silently substituted with something plausible."""
    fake_topic = ComponentSummary(
        kind="DialogComponent",
        display_name="Fake",
        schema_name="x.fake",
        raw_dialog={
            "beginDialog": {
                "kind": "OnRecognizedIntent",
                "actions": [
                    {"kind": "SomeFutureActionThatDoesntExist", "id": "x"},
                ],
            }
        },
    )
    root = explain_topic(fake_topic, kb)
    undoc = collect_undocumented(root)
    assert any(n.kind == "SomeFutureActionThatDoesntExist" for n in undoc)
    md = "\n".join(render_explainer_node_markdown(root))
    assert _NOT_DOCUMENTED_SUMMARY in md


def test_explainer_returns_none_for_non_topic_components(kb):
    """Knowledge sources and other non-DialogComponent kinds aren't topics —
    `explain_topic` must return None so callers cleanly skip them."""
    ks = ComponentSummary(
        kind="KnowledgeSourceComponent",
        display_name="A SharePoint source",
        schema_name="x.ks",
        source_kind="SharePointSearchSource",
        trigger_condition_raw="False",
        source_site="https://example/sites/x.pdf",
    )
    assert explain_topic(ks, kb) is None


def test_explain_component_for_knowledge_source(kb):
    """`explain_component` builds an ExplainerNode for non-topic components.

    For a SharePoint knowledge source with `triggerCondition: false`, the
    triggerCondition property must be documented (this is the field whose
    misconfiguration the analyser already detects in trace verdicts)."""
    ks = ComponentSummary(
        kind="KnowledgeSourceComponent",
        display_name="A SharePoint source",
        schema_name="x.ks",
        source_kind="SharePointSearchSource",
        trigger_condition_raw="False",
        source_site="https://example/sites/x.pdf",
    )
    node = explain_component(ks, kb)
    assert node.documented is True
    assert node.kind == "KnowledgeSourceComponent"
    paths = {p.path: p for p in node.properties}
    assert "configuration.source.kind" in paths
    assert paths["configuration.source.kind"].value == "SharePointSearchSource"
    assert paths["configuration.source.kind"].documented is True
    assert "configuration.source.triggerCondition" in paths
    assert paths["configuration.source.triggerCondition"].value == "False"
    assert paths["configuration.source.triggerCondition"].documented is True


def test_render_markdown_renders_full_tree_with_links(kb):
    md = render_explainer_for_topic(_ct7500_topic(), kb)
    assert "Settings explained — CT 7500" in md
    assert "**OnRecognizedIntent**" in md
    assert "**SetVariable**" in md
    assert "**SearchAndSummarizeContent**" in md
    # Microsoft doc links surface for documented kinds
    assert "learn.microsoft.com" in md
    # Property paths render
    assert "`knowledgeSources.kind`" in md
    assert "`SearchAllKnowledgeSources`" in md


def test_explainer_handles_condition_groups(kb):
    """ConditionGroup branches and elseActions must be walked — children of
    each branch's `actions` and the top-level `elseActions` show up as
    children of the ConditionGroup node."""
    topic = ComponentSummary(
        kind="DialogComponent",
        schema_name="x.cond",
        display_name="cond",
        raw_dialog={
            "beginDialog": {
                "kind": "OnRecognizedIntent",
                "actions": [
                    {
                        "kind": "ConditionGroup",
                        "id": "cg",
                        "conditions": [
                            {
                                "id": "c1",
                                "condition": "=Topic.A > 0",
                                "actions": [{"kind": "SetVariable", "id": "sv1"}],
                            }
                        ],
                        "elseActions": [{"kind": "SendActivity", "id": "msg"}],
                    }
                ],
            }
        },
    )
    root = explain_topic(topic, kb)
    cg = next(c for c in root.children if c.kind == "ConditionGroup")
    child_kinds = {c.kind for c in cg.children}
    assert child_kinds == {"SetVariable", "SendActivity"}

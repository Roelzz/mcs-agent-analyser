"""Outcome classification for topic-level SearchAndSummarizeContent traces.

`_classify_trace_outcome` is the single source of truth driving both the
markdown report status badge and the web card status pill. These tests pin
down the verdict for each shape of trace the platform can emit, so changes
to the classifier surface as a clear test failure rather than UI drift.
"""

from models import (
    BotProfile,
    ComponentSummary,
    GenerativeAnswerCitation,
    GenerativeAnswerTrace,
    SearchResult,
)
from renderer.knowledge import _classify_trace_outcome


def _trace(**overrides) -> GenerativeAnswerTrace:
    base = dict(
        topic_name="CT 7500",
        rewritten_keywords="CT 7500 information details specifications",
        rewritten_message="Please provide me with information about the CT 7500.",
        endpoints=[
            "https://share.example/SharedDocs/Brochure.pdf",
            "https://share.example/SharedDocs/Specs.pdf",
        ],
    )
    base.update(overrides)
    return GenerativeAnswerTrace(**base)


def test_outcome_no_search_results_no_errors():
    """The CT 7500 case from `botContent (4) (2).zip` — search ran cleanly,
    returned 0 hits, no fallback. Verdict must be the yellow `No Search Results`
    pill *plus* a plain-English explanation that calls out 0 documents matched
    and surfaces the rewritten query so users can debug the index miss."""
    trace = _trace(
        gpt_answer_state="No Search Results",
        completion_state="NoSearchResults",
        triggered_fallback=False,
        search_results=[],
        search_errors=[],
        search_logs=[],
    )
    icon, label, explanation = _classify_trace_outcome(trace)
    assert (icon, label) == ("🟡", "No Search Results")
    assert "0 documents matched" in explanation
    assert "CT 7500 information details specifications" in explanation
    assert "No fallback to GPT default was triggered" in explanation


def test_outcome_search_errored():
    trace = _trace(
        gpt_answer_state="Error",
        completion_state="Error",
        search_errors=["timeout: backend unreachable"],
    )
    icon, label, explanation = _classify_trace_outcome(trace)
    assert (icon, label) == ("🔴", "Search Errored")
    assert "1 error" in explanation


def test_outcome_shadow_errors_count_too():
    """Errors on the shadow lane alone should still trip the errored verdict —
    they tell us the parallel backend hit a real failure mode worth surfacing."""
    trace = _trace(
        gpt_answer_state="No Search Results",
        completion_state="NoSearchResults",
        shadow_search_errors=["shadow timeout"],
    )
    icon, label, _ = _classify_trace_outcome(trace)
    assert (icon, label) == ("🔴", "Search Errored")


def test_outcome_gpt_fallback_triggered():
    trace = _trace(
        gpt_answer_state="GPT Fallback",
        completion_state="GPTFallback",
        triggered_fallback=True,
    )
    icon, label, explanation = _classify_trace_outcome(trace)
    assert (icon, label) == ("🔴", "GPT Default Fallback")
    assert "training data" in explanation


def test_outcome_answered_grounded():
    trace = _trace(
        gpt_answer_state="Answered",
        completion_state="Answered",
        search_results=[
            SearchResult(name="Brochure", url="https://example/b.pdf", rank_score=0.81),
            SearchResult(name="Specs", url="https://example/s.pdf", rank_score=0.74),
        ],
        citations=[GenerativeAnswerCitation(url="https://example/b.pdf", title="Brochure")],
        summary_text="The CT 7500 is a Spectral CT scanner...",
    )
    icon, label, explanation = _classify_trace_outcome(trace)
    assert (icon, label) == ("🟢", "Answered")
    assert "2 result(s)" in explanation
    assert "1 citation(s)" in explanation


def _ks_component(site: str, trigger: str | None) -> ComponentSummary:
    return ComponentSummary(
        kind="KnowledgeSourceComponent",
        display_name=site.rsplit("/", 1)[-1].replace("%20", " "),
        schema_name="ks_" + site.rsplit("/", 1)[-1].split(".")[0],
        source_kind="SharePointSearchSource",
        source_site=site,
        trigger_condition_raw=trigger,
    )


def test_outcome_topic_only_sources_when_all_endpoints_gated():
    """The CT 7500 case from `botContent (4) (2).zip` — `triggerCondition: false`
    on every endpoint is the documented pattern for "topic-only" sources, NOT a
    misconfiguration on its own. The verdict must surface the configuration but
    redirect to the real likely causes (permissions, URL form, indexing) rather
    than blame the trigger for the empty result."""
    trace = _trace(
        gpt_answer_state="No Search Results",
        completion_state="NoSearchResults",
        endpoints=[
            "https://share.philips.com/sites/AIAssistant/Shared Documents/CT/Spectral CT/Philips Spectral CT 7500 - Premium Specifications - SW 5.2 2024.pdf",
            "https://share.philips.com/sites/AIAssistant/Shared Documents/CT/Spectral CT/Philips Spectral CT 7500 - Product Brochure - 2024.pdf",
        ],
    )
    profile = BotProfile(
        components=[
            # YAML side: percent-encoded URL with `triggerCondition: false`
            _ks_component(
                "https://share.philips.com/sites/AIAssistant/Shared%20Documents/CT/Spectral%20CT/Philips%20Spectral%20CT%207500%20-%20Premium%20Specifications%20-%20SW%205.2%202024.pdf",
                "false",
            ),
            _ks_component(
                "https://share.philips.com/sites/AIAssistant/Shared%20Documents/CT/Spectral%20CT/Philips%20Spectral%20CT%207500%20-%20Product%20Brochure%20-%202024.pdf",
                "false",
            ),
        ]
    )
    icon, label, explanation = _classify_trace_outcome(trace, profile)
    assert (icon, label) == ("🟡", "Topic-Only Sources, No Hits")
    assert "triggerCondition: false" in explanation
    assert "documented pattern" in explanation
    assert "SharePoint permissions" in explanation


def test_outcome_partial_trigger_gating_keeps_no_search_results_with_hint():
    """When only some endpoints are gated off, the generic 'No Search Results'
    verdict still applies but the explanation flags how many were gated."""
    trace = _trace(
        gpt_answer_state="No Search Results",
        completion_state="NoSearchResults",
        endpoints=[
            "https://share.example/SharedDocs/A.pdf",
            "https://share.example/SharedDocs/B.pdf",
        ],
    )
    profile = BotProfile(
        components=[
            _ks_component("https://share.example/SharedDocs/A.pdf", "false"),
            _ks_component("https://share.example/SharedDocs/B.pdf", "true"),
        ]
    )
    icon, label, explanation = _classify_trace_outcome(trace, profile)
    assert (icon, label) == ("🟡", "No Search Results")
    assert "1 of 2 endpoint(s) have `triggerCondition: false`" in explanation


def test_outcome_no_profile_falls_back_to_generic_verdict():
    """Without a profile we can't cross-reference triggers — verdict must remain
    the generic 'No Search Results' (don't fabricate a gated-off diagnosis)."""
    trace = _trace(
        gpt_answer_state="No Search Results",
        completion_state="NoSearchResults",
    )
    icon, label, _ = _classify_trace_outcome(trace, profile=None)
    assert (icon, label) == ("🟡", "No Search Results")


def test_outcome_hits_but_filtered():
    """Hits returned but no summary produced — usually the moderation /
    confidential-data filter dropped the answer. Distinct from `No Search
    Results` because the search itself succeeded."""
    trace = _trace(
        gpt_answer_state="Answer not Found in Search Results",
        completion_state="AnswerNotFoundInSearchResults",
        search_results=[
            SearchResult(name="Doc", url="https://example/d.pdf", rank_score=0.6),
        ],
        citations=[],
        summary_text=None,
        text_summary=None,
    )
    icon, label, explanation = _classify_trace_outcome(trace)
    assert (icon, label) == ("🟡", "Hits but Filtered")
    assert "1 hit" in explanation

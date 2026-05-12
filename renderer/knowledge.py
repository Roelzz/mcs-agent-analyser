from models import (
    BotProfile,
    ConversationTimeline,
    GenerativeAnswerTrace,
    KnowledgeSearchInfo,
)

from ._helpers import (
    _format_duration,
    _parse_execution_time_ms,
)


def _grounding_score(ks: KnowledgeSearchInfo) -> tuple[str, str]:
    count = len(ks.search_results)
    if count == 0:
        return "⚠️", "No Grounding"
    raw = f"{ks.search_query or ''} {ks.search_keywords or ''}".lower()
    stop = {"the", "a", "an", "is", "in", "of", "to", "for", "and", "or", "what", "how", ""}
    terms = {w for w in raw.split() if w not in stop and len(w) > 2}
    if terms:
        hits = sum(
            1
            for r in ks.search_results[:5]
            if any(t in (r.name or "").lower() or t in (r.text or "").lower()[:200] for t in terms)
        )
        relevance = hits / min(count, 5)
    else:
        relevance = 0.5
    if count >= 7 and relevance >= 0.4:
        return "🟢", "Strong"
    elif count >= 3 or relevance >= 0.4:
        return "🟡", "Moderate"
    else:
        return "🟠", "Weak"


def _source_efficiency(ks: KnowledgeSearchInfo) -> str | None:
    queried = set(ks.knowledge_sources)
    used = set(ks.output_knowledge_sources)
    if not queried or not used:
        return None
    contributing = queried & used
    silent = queried - used
    pct = int(len(contributing) / len(queried) * 100)

    if pct >= 80:
        badge = "🟢"
    elif pct >= 50:
        badge = "🟡"
    else:
        badge = "🔴"

    line = f"{badge} **Source efficiency:** {len(contributing)}/{len(queried)} sources returned results ({pct}%)"
    if silent:
        silent_names = ", ".join(f"`{s}`" for s in sorted(silent))
        line += f"\n⚫ **Silent sources** (no results): {silent_names}"
    return line


def _clean_user_message(msg: str) -> str:
    """Clean a user message for display as a group header."""
    return msg.replace("\n", " ").replace("\r", "").strip()


def _compact_sources(src_list: list[str]) -> str:
    """Show all sources for table display."""
    if not src_list:
        return "—"
    return ", ".join(src_list)


def _render_ks_table(searches: list[tuple[int, KnowledgeSearchInfo]]) -> list[str]:
    """Render a numbered search table for a group of KnowledgeSearchInfo items."""
    lines = [
        "| # | Search Query | Keywords | Sources | Duration | Grounding |",
        "| :-- | :-- | :-- | :-- | --: | :-- |",
    ]
    for idx, ks in searches:
        query = (ks.search_query or "—").replace("|", "\\|").replace("\n", " ").replace("\r", "")
        keywords = (ks.search_keywords or "—").replace("|", "\\|").replace("\n", " ").replace("\r", "")
        sources = _compact_sources(ks.knowledge_sources)
        dur_ms = _parse_execution_time_ms(ks.execution_time)
        dur = _format_duration(dur_ms) if dur_ms is not None else (ks.execution_time or "—")
        badge, label = _grounding_score(ks)
        lines.append(f"| {idx} | {query} | {keywords} | {sources} | {dur} | {badge} {label} |")
    lines.append("")
    return lines


def _render_ks_details(searches: list[tuple[int, KnowledgeSearchInfo]]) -> list[str]:
    """Render thought and grounding details for a group of searches."""
    lines: list[str] = []
    for idx, ks in searches:
        if ks.thought:
            lines.append(f"**#{idx} Why searched:** *{ks.thought}*\n")

    for idx, ks in searches:
        has_detail = ks.search_results or ks.search_errors or ks.output_knowledge_sources
        if not has_detail:
            continue
        lines.append(f"\n#### Search #{idx} — Grounding Details\n")

        if ks.output_knowledge_sources:
            out_src = ", ".join(ks.output_knowledge_sources)
            lines.append(f"**Sources used for grounding:** {out_src}\n")
        eff = _source_efficiency(ks)
        if eff:
            lines.append(f"{eff}\n")

        for err in ks.search_errors:
            lines.append(f"> ⚠ Search error: `{err}`\n")

        result_count = len(ks.search_results)
        if result_count == 0:
            lines.append("> ⚠ **No results returned** — response may not be grounded.\n")
        else:
            lines.append(f"**{result_count} result{'s' if result_count != 1 else ''} retrieved:**\n")
            for j, r in enumerate(ks.search_results, 1):
                title = r.name or r.url or f"Result {j}"
                title = title.replace("|", "\\|").replace("\n", " ")
                snippet = (r.text or "").replace("\n", " ").replace("|", "\\|")
                snippet_len = len(r.text or "")
                if snippet_len >= 200:
                    ke_icon = "🟢"
                elif snippet_len >= 50:
                    ke_icon = "🟡"
                else:
                    ke_icon = "🔴"
                if r.url:
                    lines.append(f"{ke_icon} {j}. [{title}]({r.url})" + (f" — {snippet}" if snippet else "") + "\n")
                else:
                    lines.append(f"{ke_icon} {j}. **{title}**" + (f" — {snippet}" if snippet else "") + "\n")
        lines.append("")
    return lines


def render_knowledge_search_section(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> str:
    """Render Knowledge Search section as Markdown.

    Combines three streams the parser may have populated:
    - `knowledge_attributions` (per-turn `KnowledgeTraceData` — citation
      attribution for each answered turn).
    - `knowledge_searches` (orchestrator-level `UniversalSearchToolTraceData`).
    - `generative_answer_traces` (topic-level `SearchAndSummarizeContent`).

    The header summarises all three; the body shows each turn's cited sources
    (from attributions) alongside any orchestrator searches that ran during it.
    """
    searches = timeline.knowledge_searches
    attributions = getattr(timeline, "knowledge_attributions", []) or []
    custom = getattr(timeline, "custom_search_steps", [])
    gen_traces = getattr(timeline, "generative_answer_traces", []) or []
    gk = "✓ On" if (profile and profile.ai_settings and profile.ai_settings.use_model_knowledge) else "✗ Off"
    total = len(searches)

    lines: list[str] = ["## Knowledge Search\n"]

    if not searches and not custom and not gen_traces and not attributions:
        lines.append(f"**0 searches** | General Knowledge: {gk}\n")
        lines.append("No knowledge searches recorded.\n")
        return "\n".join(lines)

    if not searches and not custom and gen_traces and not attributions:
        # Topic-level S&S only — skip orchestrator-search rendering and jump straight to traces.
        lines.append(
            f"**0 orchestrator searches · {len(gen_traces)} topic-level Search & Summarize call"
            f"{'s' if len(gen_traces) != 1 else ''}** | General Knowledge: {gk}\n"
        )
        lines.append(render_generative_answer_traces(gen_traces, profile))
        return "\n".join(lines)

    # Attribution-driven per-turn view: every turn the runtime tagged as
    # knowledge-touching gets its own block, with cited sources up front and
    # any orchestrator searches that ran during it below.
    if attributions:
        answered = sum(1 for a in attributions if (a.completion_state or "").lower() == "answered")
        lines.append(
            f"**{len(attributions)} turn{'s' if len(attributions) != 1 else ''} used knowledge"
            f" · {answered} answered"
            f" · {total} orchestrator search{'es' if total != 1 else ''}**"
            f" | General Knowledge: {gk}\n"
        )

        from collections import OrderedDict

        # Index orchestrator searches by triggering user message so they can be
        # nested under the matching attribution turn.
        searches_by_turn: OrderedDict[str | None, list[tuple[int, KnowledgeSearchInfo]]] = OrderedDict()
        for i, ks in enumerate(searches, 1):
            searches_by_turn.setdefault(ks.triggering_user_message, []).append((i, ks))

        for attribution in attributions:
            lines.append("---\n")
            turn_text = _clean_user_message(attribution.triggering_user_message or "(system-initiated)")
            lines.append(f'### 💬 "{turn_text}"\n')
            badge = "✅" if (attribution.completion_state or "").lower() == "answered" else "⚠"
            lines.append(
                f"{badge} **{attribution.completion_state or 'Unknown'}**"
                f" · searched: {'Yes' if attribution.is_searched else 'No'}\n"
            )
            if attribution.cited_source_names:
                shown = attribution.cited_source_names[:10]
                tail = f" *(+{len(attribution.cited_source_names) - 10} more)*" if len(attribution.cited_source_names) > 10 else ""
                lines.append("**Cited sources:** " + ", ".join(f"`{n}`" for n in shown) + tail + "\n")
            else:
                lines.append("**Cited sources:** _none — answer was not grounded._\n")
            if attribution.failed_source_types:
                lines.append(f"⚠ Failed source types: {', '.join(attribution.failed_source_types)}\n")
            turn_searches = searches_by_turn.get(attribution.triggering_user_message, [])
            if turn_searches:
                lines.append(f"\n_Orchestrator searches this turn ({len(turn_searches)}):_\n")
                lines.extend(_render_ks_table(turn_searches))
                lines.extend(_render_ks_details(turn_searches))

        # System-initiated searches not tied to any turn: render after the attributions list.
        unattached = searches_by_turn.get(None, [])
        if unattached:
            lines.append("---\n")
            lines.append("### 🔧 System-initiated\n")
            lines.extend(_render_ks_table(unattached))
            lines.extend(_render_ks_details(unattached))
    else:
        # Legacy path — no per-turn attribution available, fall back to the
        # previous orchestrator-search-grouped view.
        from collections import OrderedDict

        groups: OrderedDict[str | None, list[tuple[int, KnowledgeSearchInfo]]] = OrderedDict()
        for i, ks in enumerate(searches, 1):
            key = ks.triggering_user_message
            groups.setdefault(key, []).append((i, ks))

        total_turns = len(groups)

        if total_turns <= 1:
            lines.append(f"**{total} search{'es' if total != 1 else ''}** | General Knowledge: {gk}\n")
        else:
            lines.append(
                f"**{total} search{'es' if total != 1 else ''} across {total_turns} user turn{'s' if total_turns != 1 else ''}**"
                f" | General Knowledge: {gk}\n"
            )

        for msg_key, group_searches in groups.items():
            if total_turns > 1:
                lines.append("---\n")
            if msg_key is not None:
                header = _clean_user_message(msg_key)
                lines.append(f'### 💬 "{header}"\n')
            elif total_turns > 1:
                lines.append("### 🔧 System-initiated\n")

            lines.extend(_render_ks_table(group_searches))
            lines.extend(_render_ks_details(group_searches))

    if custom:
        lines.append("\n### Custom Search Topics\n")
        for cs in custom:
            status_icon = "✓" if cs.status == "completed" else ("✗" if cs.status == "failed" else "⏳")
            lines.append(f"**{status_icon} {cs.display_name}** ({cs.status})")
            if cs.thought:
                lines.append(f"> {cs.thought}")
            if cs.error:
                lines.append(f"> ⚠ Error: `{cs.error}`")
            dur_ms = _parse_execution_time_ms(cs.execution_time)
            dur = _format_duration(dur_ms) if dur_ms is not None else (cs.execution_time or "—")
            lines.append(f"Duration: {dur}\n")

    gen_traces = getattr(timeline, "generative_answer_traces", []) or []
    if gen_traces:
        lines.append("")
        lines.append(render_generative_answer_traces(gen_traces, profile))

    return "\n".join(lines)


def _rank_badge(score: float | None) -> str:
    if score is None:
        return "—"
    if score >= 0.75:
        return f"🟢 {score:.2f}"
    if score >= 0.5:
        return f"🟡 {score:.2f}"
    return f"🟠 {score:.2f}"


def _normalize_url(url: str) -> str:
    """URL-decode and lowercase a URL for tolerant matching.

    Trace endpoints arrive decoded ("Shared Documents/...") while the YAML
    `site:` field is percent-encoded ("Shared%20Documents/..."). Normalising
    both sides lets us reliably match endpoint→component without false misses.
    """
    from urllib.parse import unquote

    return unquote(url or "").strip().lower()


def _trigger_disabled_endpoints(
    trace: GenerativeAnswerTrace,
    profile: BotProfile | None,
) -> list[str]:
    """Endpoints whose backing KnowledgeSourceComponent has triggerCondition=false.

    Returned URLs are the original (un-normalised) endpoint strings so callers
    can quote them directly.
    """
    if profile is None or not trace.endpoints:
        return []
    disabled_sites = {
        _normalize_url(c.source_site or "")
        for c in profile.components
        if c.kind == "KnowledgeSourceComponent"
        and (c.trigger_condition_raw or "").strip().lower() == "false"
        and c.source_site
    }
    if not disabled_sites:
        return []
    return [ep for ep in trace.endpoints if _normalize_url(ep) in disabled_sites]


def _classify_trace_outcome(
    trace: GenerativeAnswerTrace,
    profile: BotProfile | None = None,
) -> tuple[str, str, str]:
    """Classify a generative-answer trace into a single human-readable outcome.

    Returns (icon, short_label, plain_english_explanation). The classification
    is derived from fields the platform emits in `GenerativeAnswersSupportData`,
    plus an optional cross-reference against `profile.components` to detect
    the special case where every endpoint maps to a knowledge source whose
    `triggerCondition` is the literal `false` (i.e. the connector is wired up
    but gated off, so no actual backend call is ever made).
    """
    state = (trace.gpt_answer_state or "").strip()
    state_l = state.lower()
    has_results = bool(trace.search_results)
    has_summary = bool(trace.summary_text or trace.text_summary)
    has_errors = bool(trace.search_errors or trace.shadow_search_errors)

    if has_errors:
        n_errors = len(trace.search_errors) + len(trace.shadow_search_errors)
        return (
            "🔴",
            "Search Errored",
            f"Search backend returned {n_errors} error(s); see Search errors below. No grounded answer was produced.",
        )
    if trace.triggered_fallback:
        return (
            "🔴",
            "GPT Default Fallback",
            f"Topic fell back to the GPT default response (state: {state or 'unknown'}). "
            f"The model answered from training data, not from your knowledge sources.",
        )
    if state_l == "answered" and has_summary:
        return (
            "🟢",
            "Answered",
            f"Search returned {len(trace.search_results)} result(s); the summariser produced "
            f"a grounded answer with {len(trace.citations)} citation(s).",
        )
    if has_results and not has_summary:
        return (
            "🟡",
            "Hits but Filtered",
            f"Search returned {len(trace.search_results)} hit(s), but no summary was produced "
            f"(typically blocked by moderation, provenance, or confidential-data filter).",
        )
    if not has_results and not has_errors:
        ep_count = len(trace.endpoints)
        gated = _trigger_disabled_endpoints(trace, profile)
        if ep_count > 0 and len(gated) == ep_count:
            # All endpoints have triggerCondition: false. Per Microsoft's
            # skills-for-copilot-studio repo, this is the documented pattern
            # for "topic-only" sources — i.e. the source is *intentionally*
            # excluded from automatic search and used only via explicit
            # SearchAndSummarizeContent invocation. Don't blame the trigger
            # for the empty result; just surface the configuration and
            # suggest the real likely causes.
            return (
                "🟡",
                "Topic-Only Sources, No Hits",
                f"All {ep_count} endpoint(s) have `triggerCondition: false` — "
                f"the documented pattern for sources used only via explicit "
                f"topic invocation (your topic is calling SearchAndSummarizeContent "
                f"directly, so this configuration is consistent). Empty "
                f"`searchResults`/`searchLogs` therefore likely point to: "
                f"(a) SharePoint permissions for the signed-in user "
                f"(`Sites.Read.All` + `Files.Read.All`), "
                f"(b) URL form (generative answers expects site/library URLs, "
                f"not always direct file URLs), "
                f"(c) indexing not yet complete, or "
                f"(d) content not matching the rewritten query.",
            )
        keyword_hint = (
            f' (rewritten query: "{trace.rewritten_keywords or trace.rewritten_message}")'
            if trace.rewritten_keywords or trace.rewritten_message
            else ""
        )
        partial_gated_hint = (
            f" Note: {len(gated)} of {ep_count} endpoint(s) have `triggerCondition: false` and were never queried."
            if gated and len(gated) < ep_count
            else ""
        )
        return (
            "🟡",
            "No Search Results",
            f"Search ran on {ep_count} endpoint(s) with no errors, but 0 documents matched"
            f"{keyword_hint}. No fallback to GPT default was triggered. "
            f"This usually means the indexed content did not match the rewritten query, "
            f"or the search subsystem returned nothing without logging.{partial_gated_hint}",
        )
    return ("⚪", state or "Unknown", "—")


def _gen_answer_status_badge(
    trace: GenerativeAnswerTrace,
    profile: BotProfile | None = None,
) -> str:
    """Single-glance status for a generative answer."""
    icon, label, _ = _classify_trace_outcome(trace, profile)
    return f"{icon} {label}"


def _safety_line(trace: GenerativeAnswerTrace) -> str:
    bits = [
        ("🟢" if trace.performed_content_moderation else "⚫") + " Moderation",
        ("🟢" if trace.performed_content_provenance else "⚫") + " Provenance",
        ("🔴" if trace.contains_confidential else "🟢") + " Confidential data",
        (
            ("🔴" if trace.triggered_fallback else "🟢")
            + (" GPT default fallback" if trace.triggered_fallback else " No fallback")
        ),
    ]
    return " · ".join(bits)


def _platform_diagnostics_line(trace: GenerativeAnswerTrace) -> str:
    """Compact one-liner exposing the raw platform state strings.

    Surfaces what the SearchAndSummarizeContent node reported so the user
    doesn't have to dig into the trace JSON to distinguish "ran with 0 hits"
    from "errored" or "skipped silently".
    """
    bits = [
        f"`gptAnswerState`: {trace.gpt_answer_state or '—'}",
        f"`completionState`: {trace.completion_state or '—'}",
        f"`triggeredGptFallback`: {str(trace.triggered_fallback).lower()}",
        f"errors: {len(trace.search_errors)}",
        f"logs: {len(trace.search_logs)}",
        f"shadow results: {len(trace.shadow_search_results)}",
    ]
    return " · ".join(bits)


def render_generative_answer_traces(
    traces: list[GenerativeAnswerTrace],
    profile: BotProfile | None = None,
) -> str:
    """Render diagnostic data captured from topic-level SearchAndSummarizeContent nodes.

    Each trace gives a deeper view than the orchestrator-level Knowledge search:
    the full query rewriting chain, token usage per stage, the actual ranked
    results (with verified-rank delta), the citations the LLM produced, and
    safety-pipeline outcomes. We surface all of it here so debugging an
    underperforming generative answer doesn't require unzipping the bot export
    by hand.

    Passing `profile` enables a cross-reference: when every endpoint maps to a
    KnowledgeSourceComponent with `triggerCondition: false`, the verdict is
    upgraded from generic "No Search Results" to "Trigger Gated Off" with a
    pointer to the misconfigured source.
    """
    if not traces:
        return ""

    lines: list[str] = ["## Topic-Level Generative Answers\n"]
    lines.append(
        f"**{len(traces)} topic-level Search & Summarize call"
        f"{'s' if len(traces) != 1 else ''}** "
        "(`SearchAndSummarizeContent` invoked directly inside a topic).\n"
    )

    for i, trace in enumerate(traces, 1):
        topic = trace.topic_name or "(unknown topic)"
        attempt = f"↻ Retry #{trace.attempt_index}" if trace.is_retry else f"#{trace.attempt_index}"
        outcome_icon, outcome_label, outcome_explanation = _classify_trace_outcome(trace, profile)
        lines.append(f"### {attempt} · {topic} · {outcome_icon} {outcome_label}\n")
        lines.append(f"> _{outcome_explanation}_\n")
        lines.append(f"<sub>{_platform_diagnostics_line(trace)}</sub>\n")
        if trace.is_retry and trace.previous_attempt_state:
            lines.append(f"> _Retried because previous attempt result was: **{trace.previous_attempt_state}**_\n")

        # Query transformation chain
        lines.append("**Query transformation**\n")
        lines.append(f"- 🗣  *Original:* {trace.original_message or '—'}")
        if trace.screened_message and trace.screened_message != trace.original_message:
            lines.append(f"- 🛡  *After moderation:* {trace.screened_message}")
        if trace.rewritten_message and trace.rewritten_message != (trace.screened_message or trace.original_message):
            lines.append(f"- ✏️  *Rewritten:* {trace.rewritten_message}")
        if trace.rewritten_keywords:
            lines.append(f"- 🔑  *Keywords:* `{trace.rewritten_keywords}`")
        if trace.hypothetical_snippet_query:
            hyp = trace.hypothetical_snippet_query.replace("\n", " ")
            if len(hyp) > 200:
                hyp = hyp[:200] + "…"
            lines.append(f"- 🧠  *Hypothetical snippet:* {hyp}")
        lines.append("")

        # Token usage / model — now includes total + cached so cache effectiveness is visible
        rewrite_used = trace.rewrite_prompt_tokens is not None or trace.rewrite_completion_tokens is not None
        summarize_used = trace.summarize_prompt_tokens is not None or trace.summarize_completion_tokens is not None
        if rewrite_used or summarize_used:
            lines.append("**LLM cost**\n")
            lines.append("| Stage | Prompt | Completion | Total | Cached | Model |")
            lines.append("| :-- | --: | --: | --: | --: | :-- |")
            if rewrite_used:
                lines.append(
                    f"| Query rewrite | {trace.rewrite_prompt_tokens or '—'} | "
                    f"{trace.rewrite_completion_tokens or '—'} | "
                    f"{trace.rewrite_total_tokens or '—'} | "
                    f"{trace.rewrite_cached_tokens or '—'} | "
                    f"`{trace.rewrite_model or '—'}` |"
                )
            if summarize_used:
                lines.append(
                    f"| Summarization | {trace.summarize_prompt_tokens or '—'} | "
                    f"{trace.summarize_completion_tokens or '—'} | "
                    f"{trace.summarize_total_tokens or '—'} | "
                    f"{trace.summarize_cached_tokens or '—'} | "
                    f"`{trace.summarize_model or '—'}` |"
                )
            lines.append("")

        # Search results — now with snippets and zero-rank anomaly flagging
        if trace.search_results:
            backend = f" · {trace.search_type}" if trace.search_type else ""
            all_zero_rank = len(trace.search_results) > 0 and all(
                (r.rank_score or 0) == 0 for r in trace.search_results
            )
            zero_warn = (
                " ⚠ **All ranks are 0 — search ranker likely disabled or misconfigured**" if all_zero_rank else ""
            )
            lines.append(f"**Search results ({len(trace.search_results)} hits{backend}){zero_warn}**\n")
            for j, r in enumerate(trace.search_results, 1):
                title = (r.name or r.url or f"Result {j}").replace("|", "\\|")
                if r.url:
                    title = f"**{j}. [{title}]({r.url})**"
                else:
                    title = f"**{j}. {title}**"
                rank_bits: list[str] = []
                if r.rank_score is not None:
                    rank_bits.append(f"rank {_rank_badge(r.rank_score)}")
                if r.verified_rank_score is not None and r.rank_score is not None:
                    delta = r.verified_rank_score - r.rank_score
                    rank_bits.append(f"verified Δ {'+' if delta >= 0 else ''}{delta:.3f}")
                meta = " · ".join(rank_bits) if rank_bits else ""
                lines.append(f"{title}" + (f" — _{meta}_" if meta else ""))
                snippet = (r.text or "").strip()
                if snippet:
                    snippet = snippet.replace("\r\n", "\n")
                    # Limit to ~600 chars in markdown to keep the report scannable;
                    # the UI gets the full snippet via state.
                    if len(snippet) > 600:
                        snippet = snippet[:600].rstrip() + "…"
                    for ln in snippet.split("\n"):
                        if ln.strip():
                            lines.append(f"   > {ln}")
                lines.append("")

        # Shadow lane comparison — surfaces backend mismatches (e.g. live=3, shadow=15)
        live_n = len(trace.search_results)
        shadow_n = len(trace.shadow_search_results)
        if shadow_n and shadow_n != live_n:
            verdict = "🟢" if shadow_n <= live_n else "🟠"
            lines.append(
                f"**Shadow search lane:** {verdict} live={live_n}, shadow={shadow_n}"
                f" — {'parity' if shadow_n == live_n else 'mismatch (parallel backend retrieved more results)'}\n"
            )

        # Citations — keep the full snippet so users can audit grounding
        if trace.citations:
            lines.append(f"**Citations ({len(trace.citations)})**\n")
            for j, c in enumerate(trace.citations, 1):
                snippet = (c.snippet or "").replace("\r", "")
                title = c.title or c.url or f"Citation {j}"
                if c.url:
                    lines.append(f"{j}. [{title}]({c.url})")
                else:
                    lines.append(f"{j}. **{title}**")
                if snippet:
                    # Each line of the snippet becomes a blockquote line
                    for ln in snippet.splitlines() or [snippet]:
                        lines.append(f"   > {ln}")
            lines.append("")

        # Safety pipeline + endpoints
        lines.append(f"**Safety pipeline:** {_safety_line(trace)}\n")
        if trace.endpoints:
            lines.append("**Knowledge endpoints queried:**")
            for ep in trace.endpoints:
                lines.append(f"- `{ep}`")
            lines.append("")

        if trace.search_errors:
            for err in trace.search_errors:
                lines.append(f"> ⚠ Search error: `{err}`")
            lines.append("")
        if trace.shadow_search_errors:
            for err in trace.shadow_search_errors:
                lines.append(f"> ⚠ Shadow search error: `{err}`")
            lines.append("")
        if trace.search_logs or trace.shadow_search_logs:
            log_count = len(trace.search_logs) + len(trace.shadow_search_logs)
            log_body = "\n".join(trace.search_logs + trace.shadow_search_logs)
            lines.append(f"<details><summary>Search backend logs ({log_count})</summary>\n")
            lines.append("```")
            lines.append(log_body)
            lines.append("```")
            lines.append("</details>\n")

        # System prompts (collapsible) — gives the deepest debugging signal
        # by exposing exactly what the LLM saw at each stage.
        prompts: list[tuple[str, str | None]] = [
            ("Query-rewrite system prompt", trace.rewrite_system_prompt),
            ("Summarization system prompt (incl. retrieved context)", trace.summarize_system_prompt),
            ("Raw rewrite response", trace.rewrite_raw_response),
        ]
        for label, body in prompts:
            if not body:
                continue
            lines.append(f"<details><summary>{label} ({len(body)} chars)</summary>\n")
            lines.append("```")
            lines.append(body)
            lines.append("```")
            lines.append("</details>\n")

    return "\n".join(lines)


def render_citation_verification_md(timeline: ConversationTimeline) -> str:
    """Markdown equivalent of the dynamic page's Citation Verification
    panel. Flat audit table of every (trace, citation) pair with the
    parent trace's answer / completion state and content moderation +
    provenance flags. Empty when no citations exist."""
    from .dynamic_data import build_citation_panel_rows

    rows = build_citation_panel_rows(timeline.generative_answer_traces)
    if not rows:
        return ""

    def _esc(s: str) -> str:
        return (s or "").replace("|", "\\|").replace("\n", " ").replace("\r", "")

    lines: list[str] = ["## Citation Verification\n"]
    lines.append(
        "_Every citation referenced in the conversation, with the trace's "
        "`gptAnswerState` / `completionState` and content moderation + provenance "
        "flags. Useful for compliance review without expanding each trace card._\n"
    )
    lines.append("| ID | Topic | Title | URL | Answer State | Completion | Moderation | Provenance | Snippet |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        snippet = _esc(r.get("snippet", ""))
        if len(snippet) > 100:
            snippet = snippet[:97] + "…"
        title = _esc(r.get("title", ""))
        if len(title) > 80:
            title = title[:77] + "…"
        url = r.get("url") or ""
        url_cell = f"[link]({url})" if url else "—"
        lines.append(
            f"| `{r.get('citation_id', '—')}` "
            f"| {_esc(r.get('trace_topic', '—'))} "
            f"| {title} "
            f"| {url_cell} "
            f"| {_esc(r.get('answer_state', '—'))} "
            f"| {_esc(r.get('completion_state', '—'))} "
            f"| {_esc(r.get('moderation', '—'))} "
            f"| {_esc(r.get('provenance', '—'))} "
            f"| {snippet} |"
        )
    lines.append("")
    return "\n".join(lines)

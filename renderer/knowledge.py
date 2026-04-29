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
    """Render Knowledge Search section as Markdown, grouped by triggering user message."""
    searches = timeline.knowledge_searches
    custom = getattr(timeline, "custom_search_steps", [])
    gen_traces = getattr(timeline, "generative_answer_traces", []) or []
    gk = "✓ On" if (profile and profile.ai_settings and profile.ai_settings.use_model_knowledge) else "✗ Off"
    total = len(searches)

    lines: list[str] = ["## Knowledge Search\n"]

    if not searches and not custom and not gen_traces:
        lines.append(f"**0 searches** | General Knowledge: {gk}\n")
        lines.append("No knowledge searches recorded.\n")
        return "\n".join(lines)

    if not searches and not custom and gen_traces:
        # Topic-level S&S only — skip orchestrator-search rendering and jump straight to traces.
        lines.append(
            f"**0 orchestrator searches · {len(gen_traces)} topic-level Search & Summarize call"
            f"{'s' if len(gen_traces) != 1 else ''}** | General Knowledge: {gk}\n"
        )
        lines.append(render_generative_answer_traces(gen_traces))
        return "\n".join(lines)

    # Group searches by triggering_user_message (preserve order)
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
            f"**{total} search{'es' if total != 1 else ''} across {total_turns} user turn{'s' if total_turns != 1 else ''}** | General Knowledge: {gk}\n"
        )

    # Render each group
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
        lines.append(render_generative_answer_traces(gen_traces))

    return "\n".join(lines)


def _rank_badge(score: float | None) -> str:
    if score is None:
        return "—"
    if score >= 0.75:
        return f"🟢 {score:.2f}"
    if score >= 0.5:
        return f"🟡 {score:.2f}"
    return f"🟠 {score:.2f}"


def _gen_answer_status_badge(trace: GenerativeAnswerTrace) -> str:
    """Single-glance status for a generative answer."""
    state = trace.gpt_answer_state or "Unknown"
    if trace.triggered_fallback:
        return f"🔴 {state} (fallback triggered)"
    if state.lower() == "answered":
        return f"🟢 {state}"
    if state.lower() in {"noanswer", "notanswered", "noresult"}:
        return f"🟠 {state}"
    return f"🟡 {state}"


def _safety_line(trace: GenerativeAnswerTrace) -> str:
    bits = [
        ("🟢" if trace.performed_content_moderation else "⚫") + " Moderation",
        ("🟢" if trace.performed_content_provenance else "⚫") + " Provenance",
        ("🔴" if trace.contains_confidential else "🟢") + " Confidential data",
        ("🔴" if trace.triggered_fallback else "🟢") + " Fallback",
    ]
    return " · ".join(bits)


def render_generative_answer_traces(traces: list[GenerativeAnswerTrace]) -> str:
    """Render diagnostic data captured from topic-level SearchAndSummarizeContent nodes.

    Each trace gives a deeper view than the orchestrator-level Knowledge search:
    the full query rewriting chain, token usage per stage, the actual ranked
    results (with verified-rank delta), the citations the LLM produced, and
    safety-pipeline outcomes. We surface all of it here so debugging an
    underperforming generative answer doesn't require unzipping the bot export
    by hand.
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
        attempt = (
            f"↻ Retry #{trace.attempt_index}"
            if trace.is_retry
            else f"#{trace.attempt_index}"
        )
        lines.append(f"### {attempt} · {topic} · {_gen_answer_status_badge(trace)}\n")
        if trace.is_retry and trace.previous_attempt_state:
            lines.append(
                f"> _Retried because previous attempt result was: **{trace.previous_attempt_state}**_\n"
            )

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
            all_zero_rank = (
                len(trace.search_results) > 0
                and all((r.rank_score or 0) == 0 for r in trace.search_results)
            )
            zero_warn = " ⚠ **All ranks are 0 — search ranker likely disabled or misconfigured**" if all_zero_rank else ""
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

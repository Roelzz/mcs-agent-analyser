from models import (
    BotProfile,
    ConversationTimeline,
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
    gk = "✓ On" if (profile and profile.ai_settings and profile.ai_settings.use_model_knowledge) else "✗ Off"
    total = len(searches)

    lines: list[str] = ["## Knowledge Search\n"]

    if not searches and not custom:
        lines.append(f"**0 searches** | General Knowledge: {gk}\n")
        lines.append("No knowledge searches recorded.\n")
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

    return "\n".join(lines)

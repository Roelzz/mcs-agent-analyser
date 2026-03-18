"""Structured section rendering for the dynamic analysis view."""

from __future__ import annotations

from datetime import datetime

from models import (
    BotProfile,
    ConversationTimeline,
    CreditEstimate,
    EventType,
)

from model_comparison import build_comparison_markdown
from parser import detect_trigger_overlaps, match_query_to_triggers

from .knowledge import render_knowledge_search_section
from .profile import (
    render_ai_config,
    render_bot_metadata,
    render_bot_profile,
    render_integration_map,
    render_knowledge_coverage,
    render_knowledge_inventory,
    render_knowledge_source_details,
    render_quick_wins,
    render_security_summary,
    render_tool_inventory,
    render_topic_details,
    render_topic_graph,
    render_topic_inventory,
    render_trigger_overlaps,
)
from ._helpers import _format_duration, _parse_execution_time_ms
from .report import render_credit_estimate
from .timeline_render import render_orchestrator_reasoning, render_timeline


def render_report_sections(
    profile: BotProfile,
    timeline: ConversationTimeline | None = None,
) -> tuple[dict[str, str], CreditEstimate | None]:
    """Build individual section markdown strings for the dynamic view.

    Returns a tuple of (sections dict, credit_estimate).
    """
    from timeline import estimate_credits

    if timeline is None:
        timeline = ConversationTimeline()

    # Profile section
    profile_parts = [render_bot_profile(profile)]
    ai_config = render_ai_config(profile)
    if ai_config:
        profile_parts.append(ai_config)
    security = render_security_summary(profile)
    if security:
        profile_parts.append(security)
    profile_parts.append(render_bot_metadata(profile))
    quick_wins = render_quick_wins(profile)
    if quick_wins:
        profile_parts.append(quick_wins)
    overlaps = detect_trigger_overlaps(profile.components)
    trigger_section = render_trigger_overlaps(overlaps)

    # Knowledge section
    knowledge_parts: list[str] = []
    ka = render_knowledge_inventory(profile)
    if ka:
        knowledge_parts.append(ka)
    kcm = render_knowledge_coverage(profile)
    if kcm:
        knowledge_parts.append(kcm)
    ksd = render_knowledge_source_details(profile)
    if ksd:
        knowledge_parts.append(ksd)
    knowledge_parts.append(render_knowledge_search_section(timeline, profile=profile))

    # Tools section
    tools_parts: list[str] = []
    tool_inv = render_tool_inventory(profile)
    if tool_inv:
        tools_parts.append(tool_inv)
    int_map = render_integration_map(profile)
    if int_map:
        tools_parts.append(int_map)

    # Topics section (includes graph + trigger overlaps)
    topics_parts = [render_topic_inventory(profile)]
    if trigger_section:
        topics_parts.append(trigger_section)
    topic_details = render_topic_details(profile, timeline)
    if topic_details:
        topics_parts.append(topic_details)
    topic_graph = render_topic_graph(profile)
    if topic_graph:
        topics_parts.append(topic_graph)

    # Model comparison
    model_parts = [build_comparison_markdown(profile)]

    # Conversation section
    conv_parts = [render_timeline(timeline)]
    reasoning = render_orchestrator_reasoning(timeline)
    if reasoning:
        conv_parts.append(reasoning)

    # Credits section
    credit_estimate = estimate_credits(timeline, profile) if timeline.events else None
    credit_md = render_credit_estimate(credit_estimate, timeline)
    credit_parts = [credit_md] if credit_md else []

    return {
        "profile": "\n".join(profile_parts),
        "knowledge": "\n".join(knowledge_parts),
        "tools": "\n".join(tools_parts),
        "topics": "\n".join(topics_parts),
        "model_comparison": "\n".join(model_parts),
        "conversation": "\n".join(conv_parts),
        "credits": "\n".join(credit_parts),
    }, credit_estimate


# ---------------------------------------------------------------------------
# Conversation flow items
# ---------------------------------------------------------------------------

ACTOR_NAMES = {"bot": "Copilot", "user": "User"}


def _format_clock(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ""


def _ms_between_iso(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (e - s).total_seconds() * 1000
    except Exception:
        return 0.0


def _strip_prefix(text: str, prefix: str) -> str:
    if text.startswith(prefix):
        return text[len(prefix) :].strip()
    return text


def build_conversation_flow_items(timeline: ConversationTimeline) -> list[dict]:
    """Build chat-style flow items from timeline events for UI rendering."""
    items: list[dict] = []

    # Extra detail keys required by rx.foreach (must be uniform across all dicts)
    _detail_defaults = {
        "has_recommendations": "",
        "plan_used_outputs": "",
        "plan_identifier": "",
        "plan_steps": "",
        "error": "",
        "is_final_plan": "",
        "orchestrator_ask": "",
    }

    for ev in timeline.events:
        summary = (ev.summary or "").strip()
        timestamp = _format_clock(ev.timestamp)

        if ev.event_type == EventType.USER_MESSAGE:
            items.append(
                {
                    "kind": "message",
                    "role": "user",
                    "actor": ACTOR_NAMES["user"],
                    "text": _strip_prefix(summary, "User:"),
                    "timestamp": timestamp,
                    "event_type": "",
                    "title": "",
                    "summary": "",
                    "tone": "",
                    "thought": "",
                    "topic_name": "",
                    "state": "",
                    **_detail_defaults,
                }
            )
            continue

        if ev.event_type == EventType.BOT_MESSAGE:
            items.append(
                {
                    "kind": "message",
                    "role": "bot",
                    "actor": ACTOR_NAMES["bot"],
                    "text": _strip_prefix(summary, "Bot:"),
                    "timestamp": timestamp,
                    "event_type": "",
                    "title": "",
                    "summary": "",
                    "tone": "",
                    "thought": "",
                    "topic_name": "",
                    "state": "",
                    **_detail_defaults,
                }
            )
            continue

        if ev.event_type in {
            EventType.PLAN_RECEIVED,
            EventType.PLAN_FINISHED,
            EventType.STEP_TRIGGERED,
            EventType.STEP_FINISHED,
            EventType.KNOWLEDGE_SEARCH,
            EventType.DIALOG_TRACING,
            EventType.DIALOG_REDIRECT,
            EventType.ACTION_TRIGGER_EVAL,
            EventType.ERROR,
        }:
            title_map = {
                EventType.PLAN_RECEIVED: "Plan Received",
                EventType.PLAN_FINISHED: "Plan Finished",
                EventType.STEP_TRIGGERED: "Action Started",
                EventType.STEP_FINISHED: "Action Finished",
                EventType.KNOWLEDGE_SEARCH: "Knowledge Search",
                EventType.DIALOG_TRACING: "Topic Trace",
                EventType.DIALOG_REDIRECT: "Topic Redirect",
                EventType.ACTION_TRIGGER_EVAL: "Condition Eval",
                EventType.ERROR: "Error",
            }
            if ev.event_type == EventType.ERROR:
                tone = "error"
            elif ev.event_type == EventType.ACTION_TRIGGER_EVAL:
                tone = "trace"
            else:
                tone = "info"
            detail = summary
            query = getattr(ev, "search_query", None)
            if ev.event_type == EventType.KNOWLEDGE_SEARCH and query:
                detail = f'Query: "{query}"'

            items.append(
                {
                    "kind": "event",
                    "role": "",
                    "actor": "",
                    "text": "",
                    "event_type": ev.event_type.value,
                    "title": title_map.get(ev.event_type, ev.event_type.value),
                    "summary": detail,
                    "timestamp": timestamp,
                    "tone": tone,
                    "thought": ev.thought or "",
                    "topic_name": ev.topic_name or "",
                    "state": ev.state or "",
                    "has_recommendations": "true" if ev.has_recommendations else "",
                    "plan_used_outputs": ev.plan_used_outputs or "",
                    "plan_identifier": ev.plan_identifier or "",
                    "plan_steps": ", ".join(ev.plan_steps) if ev.plan_steps else "",
                    "error": ev.error or "",
                    "is_final_plan": str(ev.is_final_plan) if ev.is_final_plan is not None else "",
                    "orchestrator_ask": ev.orchestrator_ask or "",
                }
            )

    return items


# ---------------------------------------------------------------------------
# Conversation visual summary
# ---------------------------------------------------------------------------


def _duration_stats(durations: list[float]) -> dict | None:
    """Compute min/max/avg formatted durations from a list of milliseconds."""
    if not durations:
        return None
    avg = sum(durations) / len(durations)
    return {
        "min_fmt": _format_duration(min(durations)),
        "max_fmt": _format_duration(max(durations)),
        "avg_fmt": _format_duration(avg),
        "avg_ms": avg,
    }


def _severity_color(avg_ms: float) -> str:
    """Map average duration to a green→yellow→amber→red severity color."""
    if avg_ms < 1000:
        return "var(--green-9)"
    if avg_ms < 3000:
        return "var(--yellow-9)"
    if avg_ms < 8000:
        return "var(--amber-9)"
    return "var(--red-9)"


def _pair_message_turns(timeline: ConversationTimeline) -> list[dict]:
    """Pair user messages with the next bot message to form chat turns."""
    turns: list[dict] = []
    pending_user: dict | None = None

    for ev in timeline.events:
        if ev.event_type == EventType.USER_MESSAGE:
            pending_user = {
                "user_ts": ev.timestamp,
                "user_msg": (ev.summary or "").replace("User: ", "", 1),
            }
            continue

        if ev.event_type in (EventType.BOT_MESSAGE, EventType.ACTION_SEND_ACTIVITY) and pending_user is not None:
            latency_ms = _ms_between_iso(pending_user.get("user_ts"), ev.timestamp)
            turns.append(
                {
                    "user_ts": pending_user.get("user_ts") or "",
                    "user_msg": pending_user.get("user_msg") or "",
                    "bot_ts": ev.timestamp or "",
                    "bot_msg": (ev.summary or "").replace("Bot: ", "", 1),
                    "latency_ms": latency_ms,
                }
            )
            pending_user = None

    return turns


def build_conversation_visual_summary(timeline: ConversationTimeline) -> dict[str, list[dict]]:
    """Compute KPIs, event mix, latency bands, and highlights from a timeline."""
    user_msgs = sum(1 for e in timeline.events if e.event_type == EventType.USER_MESSAGE)
    bot_msgs = sum(1 for e in timeline.events if e.event_type in (EventType.BOT_MESSAGE, EventType.ACTION_SEND_ACTIVITY))
    errors = sum(1 for e in timeline.events if e.event_type == EventType.ERROR)
    searches = sum(1 for e in timeline.events if e.event_type == EventType.KNOWLEDGE_SEARCH)

    started_steps = [e for e in timeline.events if e.event_type == EventType.STEP_TRIGGERED]
    finished_steps = {e.step_id for e in timeline.events if e.event_type == EventType.STEP_FINISHED and e.step_id}
    orphaned_steps = sum(1 for s in started_steps if s.step_id and s.step_id not in finished_steps)

    turns = _pair_message_turns(timeline)
    latencies = [t["latency_ms"] for t in turns if t["latency_ms"] > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    step_durations = [p.duration_ms for p in timeline.phases if p.duration_ms > 0]
    search_durations = [
        d for ks in timeline.knowledge_searches
        if (d := _parse_execution_time_ms(ks.execution_time)) is not None
    ]

    # KPIs
    kpis = [
        {"label": "User Messages", "value": str(user_msgs), "hint": "Incoming requests", "tone": "neutral"},
        {"label": "Bot Responses", "value": str(bot_msgs), "hint": "Delivered answers", "tone": "neutral"},
        {
            "label": "Avg Turn Latency",
            "value": f"{avg_latency:.0f} ms",
            "hint": "User -> bot response",
            "tone": "neutral" if avg_latency < 4000 else "warn",
        },
        {
            "label": "P95 Turn Latency",
            "value": f"{p95_latency:.0f} ms",
            "hint": "Worst typical latency",
            "tone": "warn" if p95_latency >= 6000 else "neutral",
        },
    ]

    # Event mix
    mix_raw = [
        ("Messages", user_msgs + bot_msgs, "var(--green-9)", latencies),
        ("Steps", len(started_steps), "var(--teal-9)", step_durations),
        ("Search", searches, "var(--amber-9)", search_durations),
        ("Errors", errors, "var(--red-9)", []),
    ]
    mix_total = sum(v for _, v, _, _ in mix_raw) or 1
    event_mix = []
    for label, count, color, durations in mix_raw:
        stats = _duration_stats(durations)
        bar_color = _severity_color(stats["avg_ms"]) if stats else "var(--gray-a5)"
        event_mix.append({
            "label": label,
            "count": str(count),
            "color": color,
            "bar_color": bar_color,
            "pct": f"{(count / mix_total) * 100:.1f}%",
            "min_fmt": stats["min_fmt"] if stats else "",
            "max_fmt": stats["max_fmt"] if stats else "",
            "avg_fmt": stats["avg_fmt"] if stats else "",
        })

    # Latency bands — green→yellow→amber→red severity scale
    bands = [
        ("< 1s", sum(1 for t in turns if t["latency_ms"] < 1000), "var(--green-9)"),
        ("1-3s", sum(1 for t in turns if 1000 <= t["latency_ms"] < 3000), "var(--yellow-9)"),
        ("3-8s", sum(1 for t in turns if 3000 <= t["latency_ms"] < 8000), "var(--amber-9)"),
        (">= 8s", sum(1 for t in turns if t["latency_ms"] >= 8000), "var(--red-9)"),
    ]
    turns_total = len(turns) or 1
    latency_bands = [
        {
            "label": label,
            "count": str(count),
            "color": color,
            "bar_color": color,
            "pct": f"{(count / turns_total) * 100:.1f}%",
            "min_fmt": "",
            "max_fmt": "",
            "avg_fmt": "",
        }
        for label, count, color in bands
    ]

    # Highlights
    highlights = [
        {"title": "Errors", "value": str(errors), "tone": "bad" if errors > 0 else "good"},
        {"title": "Open Steps", "value": str(orphaned_steps), "tone": "bad" if orphaned_steps > 0 else "good"},
        {"title": "Search Calls", "value": str(searches), "tone": "info"},
    ]

    return {
        "kpis": kpis,
        "event_mix": event_mix,
        "latency_bands": latency_bands,
        "highlights": highlights,
    }


# ---------------------------------------------------------------------------
# Topic lifecycle grouping
# ---------------------------------------------------------------------------


def build_topic_lifecycles(timeline: ConversationTimeline) -> list[dict]:
    """Group timeline events by step_id to build per-topic lifecycle cards.

    Each lifecycle dict contains: step_id, name, thought, status, duration_ms,
    duration_label, start, end, error, child_summary, child_count.
    """
    triggers: dict[str, dict] = {}
    finishes: dict[str, dict] = {}

    for ev in timeline.events:
        if ev.event_type == EventType.STEP_TRIGGERED and ev.step_id:
            triggers[ev.step_id] = {
                "name": ev.topic_name or "Unknown",
                "thought": ev.thought or "",
                "start": ev.timestamp,
                "position": ev.position,
                "has_recommendations": ev.has_recommendations,
                "plan_identifier": ev.plan_identifier or "",
            }
        elif ev.event_type == EventType.STEP_FINISHED and ev.step_id:
            finishes[ev.step_id] = {
                "end": ev.timestamp,
                "state": ev.state or "unknown",
                "error": ev.error or "",
                "has_recommendations": ev.has_recommendations,
                "plan_used_outputs": ev.plan_used_outputs or "",
            }

    lifecycles: list[dict] = []
    for step_id in triggers:
        trig = triggers[step_id]
        fin = finishes.get(step_id, {})
        topic_name = trig["name"]

        # Collect child events between trigger and finish
        child_events: list[dict] = []
        trig_pos = trig["position"]
        fin_end = fin.get("end")
        for ev in timeline.events:
            if ev.position <= trig_pos:
                continue
            if fin_end and ev.timestamp and ev.timestamp > fin_end:
                break
            if ev.step_id == step_id:
                continue
            if ev.event_type in {
                EventType.KNOWLEDGE_SEARCH,
                EventType.ACTION_TRIGGER_EVAL,
                EventType.DIALOG_REDIRECT,
                EventType.ACTION_HTTP_REQUEST,
                EventType.ACTION_BEGIN_DIALOG,
            }:
                child_events.append(
                    {
                        "type": ev.event_type.value,
                        "summary": (ev.summary or "")[:80],
                    }
                )

        duration_ms = _ms_between_iso(trig["start"], fin.get("end"))
        child_summary = " → ".join(
            f"{ce['type']}: {ce['summary']}" for ce in child_events
        ) if child_events else ""

        # Merge has_recommendations from trigger or finish
        has_recs = trig.get("has_recommendations") or fin.get("has_recommendations")
        used_outputs = fin.get("plan_used_outputs", "")

        lifecycles.append(
            {
                "step_id": step_id,
                "name": topic_name,
                "thought": trig["thought"],
                "status": fin.get("state", "pending"),
                "duration_ms": str(round(duration_ms, 1)),
                "duration_label": f"{duration_ms:.0f}ms" if duration_ms > 0 else "",
                "start": _format_clock(trig["start"]),
                "end": _format_clock(fin.get("end")),
                "error": fin.get("error") or "",
                "child_summary": child_summary,
                "child_count": str(len(child_events)),
                "has_recommendations": "true" if has_recs else "",
                "used_outputs": used_outputs,
                "plan_identifier": trig.get("plan_identifier", ""),
            }
        )

    # Add redirect-based entries for ACTION_BEGIN_DIALOG events that represent
    # topic transitions (e.g. "Call to Fallback", "Call to GenAIAnsGeneration")
    # not already captured as their own STEP_TRIGGERED lifecycle.
    existing_names = {lc["name"] for lc in lifecycles}
    for ev in timeline.events:
        if ev.event_type != EventType.ACTION_BEGIN_DIALOG:
            continue
        raw = (ev.summary or "")
        # Strip common prefixes
        for prefix in ("Call to ", "Begin "):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        target = raw.strip()
        if not target or target in existing_names:
            continue
        existing_names.add(target)
        lifecycles.append(
            {
                "step_id": f"redirect_{ev.position}",
                "name": target,
                "thought": "",
                "status": "redirected",
                "duration_ms": "0",
                "duration_label": "",
                "start": _format_clock(ev.timestamp),
                "end": "",
                "error": "",
                "child_summary": "",
                "child_count": "0",
                "has_recommendations": "",
                "used_outputs": "",
                "plan_identifier": "",
            }
        )

    return lifecycles


# ---------------------------------------------------------------------------
# Trigger phrase analysis
# ---------------------------------------------------------------------------

# System tool suffixes to exclude from "selected topic" detection
_SYSTEM_TOOL_SUFFIXES = {"UniversalSearchTool", "KnowledgeSource", "GenerateAnswer"}


def _normalize_topic_name(name: str) -> str:
    """Lowercase, strip prefix markers like 'P:', and remove whitespace."""
    return name.lower().replace("p:", "").strip()


def build_trigger_match_items(
    timeline: ConversationTimeline,
    profile: BotProfile,
) -> list[dict]:
    """Build trigger-phrase match items for each user message in the timeline.

    For each user message, runs ``match_query_to_triggers`` against the bot's
    components, resolves which topic was *actually* triggered (filtering out
    system tools), and returns a flat list of dicts safe for Reflex state.

    Each item dict contains:
    - ``user_message``: the original user text
    - ``selected_topic``: display name of actually triggered topic (or "—")
    - ``matches_summary``: pre-formatted string with selected match first
    - ``total_matches``: total matches before cap (for "showing N of M" label)
    """
    if not timeline or not profile:
        return []

    items: list[dict] = []

    # Collect STEP_TRIGGERED events grouped by position relative to user messages
    events = timeline.events
    user_indices: list[int] = []
    for idx, ev in enumerate(events):
        if ev.event_type == EventType.USER_MESSAGE:
            user_indices.append(idx)

    for pos, ui in enumerate(user_indices):
        ev = events[ui]
        user_text = (ev.summary or "").replace("User: ", "", 1).strip()
        if not user_text:
            continue

        # Find orchestrator interpretation and triggered topics between this and next user msg
        next_ui = user_indices[pos + 1] if pos + 1 < len(user_indices) else len(events)
        orchestrator_ask = ""
        for between_ev in events[ui + 1 : next_ui]:
            if between_ev.event_type == EventType.PLAN_RECEIVED_DEBUG and between_ev.orchestrator_ask:
                orchestrator_ask = between_ev.orchestrator_ask
                break

        triggered_topics: list[str] = []
        for between_ev in events[ui + 1 : next_ui]:
            if between_ev.event_type != EventType.STEP_TRIGGERED:
                continue
            tname = between_ev.topic_name or ""
            summary = between_ev.summary or ""
            # Skip system tools
            if any(suffix in tname for suffix in _SYSTEM_TOOL_SUFFIXES):
                continue
            # Only keep CustomTopic steps
            if "(CustomTopic)" in summary or "(Dialog)" in summary:
                triggered_topics.append(tname)

        # Resolve selected topic display name — pick first custom topic
        selected_display = "—"
        if not triggered_topics:
            # No custom topic triggered — show first system tool as fallback
            for between_ev in events[ui + 1 : next_ui]:
                if between_ev.event_type == EventType.STEP_TRIGGERED and between_ev.topic_name:
                    selected_display = f"{between_ev.topic_name} (system)"
                    break
        if triggered_topics:
            # Try to find matching display name from components
            for comp in profile.components:
                if comp.kind != "DialogComponent":
                    continue
                norm_comp = _normalize_topic_name(comp.display_name)
                for tname in triggered_topics:
                    norm_triggered = _normalize_topic_name(tname)
                    if norm_comp == norm_triggered or norm_comp in norm_triggered or norm_triggered in norm_comp:
                        selected_display = comp.display_name
                        break
                if selected_display != "—":
                    break
            # Fallback: use raw name
            if selected_display == "—":
                selected_display = triggered_topics[0]

        # Run trigger matching
        all_matches = match_query_to_triggers(user_text, profile.components, threshold=0.5)
        total_count = len(all_matches)
        capped = all_matches[:8]

        # Build formatted summary string
        lines: list[str] = []
        norm_selected = _normalize_topic_name(selected_display)
        selected_line_added = False

        for m in capped:
            pct = f"{m['score']:.0%}"
            norm_match = _normalize_topic_name(m["display_name"])
            is_selected = (
                norm_selected == norm_match
                or norm_selected in norm_match
                or norm_match in norm_selected
            )
            if is_selected and not selected_line_added:
                lines.insert(0, f"✓ {m['display_name']} ({pct}) — \"{m['best_phrase']}\"")
                selected_line_added = True
            else:
                lines.append(f"· {m['display_name']} ({pct}) — \"{m['best_phrase']}\"")

        # Insert blank separator after selected line
        if selected_line_added and len(lines) > 1:
            lines.insert(1, "")

        matches_summary = "\n".join(lines) if lines else "No matches above threshold"

        # Include orchestrator_ask when it differs from user text
        ask_display = ""
        if orchestrator_ask and orchestrator_ask.strip('"') != user_text:
            ask_display = orchestrator_ask

        items.append(
            {
                "user_message": user_text,
                "selected_topic": selected_display,
                "matches_summary": matches_summary,
                "total_matches": str(total_count),
                "orchestrator_ask": ask_display,
            }
        )

    return items


# ---------------------------------------------------------------------------
# Orchestrator decision timeline
# ---------------------------------------------------------------------------


def build_orchestrator_decision_timeline(timeline: ConversationTimeline) -> list[dict]:
    """Build a flat list of orchestrator decision items grouped by user-message turns.

    Each dict has a ``kind`` key: user_message, interpreted, plan, step, plan_finished.
    All values are strings (Reflex Var constraint).
    """
    items: list[dict] = []
    events = timeline.events
    latest_user_text: str = ""

    for ev in events:
        if ev.event_type == EventType.USER_MESSAGE:
            latest_user_text = (ev.summary or "").replace("User: ", "", 1).strip()
            items.append({
                "kind": "user_message",
                "text": latest_user_text,
                "timestamp": _format_clock(ev.timestamp),
            })
            continue

        if ev.event_type == EventType.PLAN_RECEIVED_DEBUG:
            ask = ev.orchestrator_ask or ""
            if ask and ask != latest_user_text:
                items.append({
                    "kind": "interpreted",
                    "ask": ask,
                    "timestamp": _format_clock(ev.timestamp),
                })
            continue

        if ev.event_type == EventType.PLAN_RECEIVED:
            steps_str = ", ".join(ev.plan_steps) if ev.plan_steps else (ev.summary or "")
            items.append({
                "kind": "plan",
                "steps": steps_str,
                "is_final": str(ev.is_final_plan) if ev.is_final_plan is not None else "",
                "plan_identifier": ev.plan_identifier or "",
                "timestamp": _format_clock(ev.timestamp),
            })
            continue

        if ev.event_type in {EventType.STEP_TRIGGERED, EventType.STEP_FINISHED}:
            import re as _re

            status = ev.state or ""
            duration = ""
            used_outputs = ""
            has_recs = ""
            error = ev.error or ""
            # Parse step_type from summary parenthetical, e.g. "(CustomTopic)"
            _st_match = _re.search(r"\((\w+)\)", ev.summary or "")
            step_type = _st_match.group(1) if _st_match else ""
            if ev.event_type == EventType.STEP_FINISHED:
                m = _re.search(r"\((\d+)ms\)", ev.summary or "")
                duration = f"{m.group(1)}ms" if m else ""
                used_outputs = ev.plan_used_outputs or ""
            if ev.has_recommendations is True:
                has_recs = "true"
            items.append({
                "kind": "step",
                "event_subtype": "triggered" if ev.event_type == EventType.STEP_TRIGGERED else "finished",
                "topic_name": ev.topic_name or "",
                "thought": ev.thought or "",
                "has_recommendations": has_recs,
                "used_outputs": used_outputs,
                "status": status,
                "duration": duration,
                "timestamp": _format_clock(ev.timestamp),
                "plan_identifier": ev.plan_identifier or "",
                "step_type": step_type,
                "error": error,
            })
            continue

        if ev.event_type in {EventType.ACTION_HTTP_REQUEST, EventType.ACTION_BEGIN_DIALOG, EventType.ACTION_TRIGGER_EVAL}:
            action_type_map = {
                EventType.ACTION_HTTP_REQUEST: "HTTP Request",
                EventType.ACTION_BEGIN_DIALOG: "Begin Dialog",
                EventType.ACTION_TRIGGER_EVAL: "Condition Eval",
            }
            items.append({
                "kind": "action",
                "action_type": action_type_map[ev.event_type],
                "topic_name": ev.topic_name or "",
                "summary": (ev.summary or "")[:120],
                "error": ev.error or "",
                "timestamp": _format_clock(ev.timestamp),
            })
            continue

        if ev.event_type == EventType.PLAN_FINISHED:
            is_cancelled = "true" if "cancelled=True" in (ev.summary or "") else "false"
            items.append({
                "kind": "plan_finished",
                "is_cancelled": is_cancelled,
                "timestamp": _format_clock(ev.timestamp),
            })

    return items


# ---------------------------------------------------------------------------
# Plan evolution tracker
# ---------------------------------------------------------------------------


def build_plan_evolution(timeline: ConversationTimeline) -> list[dict]:
    """Compare consecutive PLAN_RECEIVED events to show how plans evolved.

    Only returns data when >1 plan exists in the conversation.
    """
    plan_events = [
        ev for ev in timeline.events if ev.event_type == EventType.PLAN_RECEIVED
    ]
    if len(plan_events) <= 1:
        return []

    results: list[dict] = []
    for idx, ev in enumerate(plan_events):
        current_steps = set(ev.plan_steps)
        added = ""
        removed = ""
        change_summary = ""
        if idx > 0:
            prev_steps = set(plan_events[idx - 1].plan_steps)
            added_set = current_steps - prev_steps
            removed_set = prev_steps - current_steps
            added = ", ".join(sorted(added_set)) if added_set else ""
            removed = ", ".join(sorted(removed_set)) if removed_set else ""
            parts = []
            if added_set:
                parts.append(f"+{len(added_set)} added")
            if removed_set:
                parts.append(f"-{len(removed_set)} removed")
            change_summary = ", ".join(parts) if parts else "No changes"

        results.append({
            "plan_index": str(idx + 1),
            "plan_identifier": ev.plan_identifier or "",
            "is_final": str(ev.is_final_plan) if ev.is_final_plan is not None else "",
            "steps": ", ".join(ev.plan_steps) if ev.plan_steps else "",
            "added_steps": added,
            "removed_steps": removed,
            "change_summary": change_summary,
            "timestamp": _format_clock(ev.timestamp),
        })

    return results


# ---------------------------------------------------------------------------
# Markdown renderers for document view parity
# ---------------------------------------------------------------------------


def render_topic_lifecycles_md(timeline: ConversationTimeline) -> str:
    """Render topic lifecycles as a markdown table."""
    items = build_topic_lifecycles(timeline)
    if not items:
        return ""
    lines = [
        "## Topic Lifecycles\n",
        "| Topic | Status | Duration | Start → End | Thought |",
        "| --- | --- | --- | --- | --- |",
    ]
    for lc in items:
        thought = (lc.get("thought") or "—")[:80].replace("|", "\\|").replace("\n", " ")
        time_range = f"{lc.get('start', '')} → {lc.get('end', '')}" if lc.get("start") else "—"
        lines.append(
            f"| {lc['name']} | {lc['status']} | {lc.get('duration_label') or '—'} | {time_range} | {thought} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_decision_timeline_md(timeline: ConversationTimeline) -> str:
    """Render orchestrator decision timeline as grouped markdown."""
    items = build_orchestrator_decision_timeline(timeline)
    if not items:
        return ""
    lines = ["## Orchestrator Decision Timeline\n"]
    for item in items:
        kind = item.get("kind", "")
        if kind == "user_message":
            lines.append(f"> **User** ({item.get('timestamp', '')}): {item.get('text', '')}\n")
        elif kind == "interpreted":
            lines.append(f"*Interpreted as:* {item.get('ask', '')}\n")
        elif kind == "plan":
            final = " (final)" if item.get("is_final") == "True" else ""
            lines.append(f"- **Plan{final}:** {item.get('steps', '')}")
        elif kind == "step":
            subtype = item.get("event_subtype", "")
            topic = item.get("topic_name", "")
            if subtype == "triggered":
                thought = item.get("thought", "")
                prefix = f" — *{thought}*" if thought else ""
                lines.append(f"  - ▶ {topic}{prefix}")
            else:
                duration = item.get("duration", "")
                status = item.get("status", "")
                lines.append(f"  - ✓ {topic} ({status}, {duration})" if duration else f"  - ✓ {topic} ({status})")
        elif kind == "action":
            lines.append(f"  - ⚡ {item.get('action_type', '')}: {item.get('summary', '')}")
        elif kind == "plan_finished":
            cancelled = " (cancelled)" if item.get("is_cancelled") == "true" else ""
            lines.append(f"- **Plan finished**{cancelled}")
    lines.append("")
    return "\n".join(lines)


def render_plan_evolution_md(timeline: ConversationTimeline) -> str:
    """Render plan evolution as a markdown table."""
    items = build_plan_evolution(timeline)
    if not items:
        return ""
    lines = [
        "## Plan Evolution\n",
        "| Plan # | Final? | Steps | Changes |",
        "| --- | --- | --- | --- |",
    ]
    for p in items:
        final = "Yes" if p.get("is_final") == "True" else "No" if p.get("is_final") else "—"
        steps = (p.get("steps") or "—").replace("|", "\\|")
        changes = p.get("change_summary") or "—"
        lines.append(f"| {p['plan_index']} | {final} | {steps} | {changes} |")
    lines.append("")
    return "\n".join(lines)


def render_trigger_analysis_md(
    timeline: ConversationTimeline,
    profile: BotProfile,
) -> str:
    """Render trigger phrase analysis as markdown sections."""
    items = build_trigger_match_items(timeline, profile)
    if not items:
        return ""
    lines = ["## Trigger Phrase Analysis\n"]
    for item in items:
        user_msg = item.get("user_message", "")
        selected = item.get("selected_topic", "—")
        lines.append(f"### \"{user_msg}\"\n")
        lines.append(f"**Selected topic:** {selected}\n")
        ask = item.get("orchestrator_ask", "")
        if ask:
            lines.append(f"*Orchestrator interpretation:* {ask}\n")
        summary = item.get("matches_summary", "")
        if summary:
            lines.append("```")
            lines.append(summary)
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def render_conversation_summary_md(timeline: ConversationTimeline) -> str:
    """Render conversation visual summary as markdown tables."""
    data = build_conversation_visual_summary(timeline)
    if not data or not data.get("kpis"):
        return ""
    lines = ["## Conversation Summary\n"]

    # KPIs
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for kpi in data["kpis"]:
        lines.append(f"| {kpi['label']} | {kpi['value']} |")
    lines.append("")

    # Event mix
    mix = data.get("event_mix", [])
    if mix:
        lines.append("### Event Mix\n")
        lines.append("| Category | Count | % |")
        lines.append("| --- | --- | --- |")
        for m in mix:
            lines.append(f"| {m['label']} | {m['count']} | {m['pct']} |")
        lines.append("")

    # Latency bands
    bands = data.get("latency_bands", [])
    if bands:
        lines.append("### Latency Distribution\n")
        lines.append("| Band | Count | % |")
        lines.append("| --- | --- | --- |")
        for b in bands:
            lines.append(f"| {b['label']} | {b['count']} | {b['pct']} |")
        lines.append("")

    return "\n".join(lines)


def render_conversation_flow_md(timeline: ConversationTimeline) -> str:
    """Render conversation flow as markdown."""
    items = build_conversation_flow_items(timeline)
    if not items:
        return ""
    lines = ["## Conversation Flow\n"]
    for item in items:
        kind = item.get("kind", "")
        ts = item.get("timestamp", "")
        ts_prefix = f"[{ts}] " if ts else ""
        if kind == "message":
            role = item.get("role", "")
            actor = item.get("actor", role)
            text = item.get("text", "")
            lines.append(f"> **{actor}** {ts_prefix}: {text}\n")
        elif kind == "event":
            title = item.get("title", "")
            summary = item.get("summary", "")
            thought = item.get("thought", "")
            line = f"- {ts_prefix}**{title}**: {summary}"
            if thought:
                line += f" — *{thought}*"
            lines.append(line)
    lines.append("")
    return "\n".join(lines)

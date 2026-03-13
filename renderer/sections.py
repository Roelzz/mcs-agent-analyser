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
from parser import detect_trigger_overlaps

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
from .report import render_credit_estimate
from .timeline_render import render_orchestrator_reasoning, render_timeline


def render_report_sections(
    profile: BotProfile,
    timeline: ConversationTimeline,
) -> tuple[dict[str, str], CreditEstimate | None]:
    """Build individual section markdown strings for the dynamic view.

    Returns a tuple of (sections dict, credit_estimate).
    """
    from timeline import estimate_credits

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
    if trigger_section:
        profile_parts.append(trigger_section)

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

    # Topics section (includes graph)
    topics_parts = [render_topic_inventory(profile)]
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
                EventType.ERROR: "Error",
            }
            tone = "error" if ev.event_type == EventType.ERROR else "info"
            detail = summary
            query = getattr(ev, "search_query", None)
            if ev.event_type == EventType.KNOWLEDGE_SEARCH and query:
                detail = f'Query: "{query}"'

            items.append(
                {
                    "kind": "event",
                    "event_type": ev.event_type.value,
                    "title": title_map.get(ev.event_type, ev.event_type.value),
                    "summary": detail,
                    "timestamp": timestamp,
                    "tone": tone,
                }
            )

    return items


# ---------------------------------------------------------------------------
# Conversation visual summary
# ---------------------------------------------------------------------------


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

        if ev.event_type == EventType.BOT_MESSAGE and pending_user is not None:
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
    bot_msgs = sum(1 for e in timeline.events if e.event_type == EventType.BOT_MESSAGE)
    errors = sum(1 for e in timeline.events if e.event_type == EventType.ERROR)
    searches = sum(1 for e in timeline.events if e.event_type == EventType.KNOWLEDGE_SEARCH)

    started_steps = [e for e in timeline.events if e.event_type == EventType.STEP_TRIGGERED]
    finished_steps = {e.step_id for e in timeline.events if e.event_type == EventType.STEP_FINISHED and e.step_id}
    orphaned_steps = sum(1 for s in started_steps if s.step_id and s.step_id not in finished_steps)

    turns = _pair_message_turns(timeline)
    latencies = [t["latency_ms"] for t in turns if t["latency_ms"] > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

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
        ("Messages", user_msgs + bot_msgs, "var(--green-9)"),
        ("Steps", len(started_steps), "var(--teal-9)"),
        ("Search", searches, "var(--amber-9)"),
        ("Errors", errors, "var(--red-9)"),
    ]
    mix_total = sum(v for _, v, _ in mix_raw) or 1
    event_mix = [
        {
            "label": label,
            "count": str(count),
            "color": color,
            "pct": f"{(count / mix_total) * 100:.1f}%",
        }
        for label, count, color in mix_raw
    ]

    # Latency bands
    bands = [
        ("< 1s", sum(1 for t in turns if t["latency_ms"] < 1000), "var(--green-9)"),
        ("1-3s", sum(1 for t in turns if 1000 <= t["latency_ms"] < 3000), "var(--blue-9)"),
        ("3-8s", sum(1 for t in turns if 3000 <= t["latency_ms"] < 8000), "var(--amber-9)"),
        (">= 8s", sum(1 for t in turns if t["latency_ms"] >= 8000), "var(--red-9)"),
    ]
    turns_total = len(turns) or 1
    latency_bands = [
        {
            "label": label,
            "count": str(count),
            "color": color,
            "pct": f"{(count / turns_total) * 100:.1f}%",
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

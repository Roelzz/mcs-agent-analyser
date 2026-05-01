"""Structured section rendering for the dynamic analysis view."""

from __future__ import annotations

from datetime import datetime

from models import (
    BotProfile,
    ConversationTimeline,
    CreditEstimate,
    EventType,
    ExecutionPhase,
    TimelineEvent,
)

from model_comparison import build_comparison_markdown
from parser import detect_trigger_overlaps, match_query_to_triggers

# ---------------------------------------------------------------------------
# Trigger score lookup (shared by multiple builders)
# ---------------------------------------------------------------------------


def _build_component_name_map(profile: BotProfile) -> dict[str, str]:
    """Build a map from normalized topic names to component display_names.

    Maps: display_name (lower), schema suffix (lower), schema (lower) → display_name.
    This bridges the gap between timeline event topic_names (from resolve_topic_name)
    and component display_names (used as keys in match_query_to_triggers results).
    """
    name_map: dict[str, str] = {}
    for c in profile.components:
        dn = c.display_name
        dn_lower = dn.lower().strip()
        name_map[dn_lower] = dn
        # Schema suffix: "rrs_demo.topic.Dutchy" → "dutchy"
        if c.schema_name:
            suffix = c.schema_name.rsplit(".", 1)[-1].lower()
            if suffix not in name_map:
                name_map[suffix] = dn
            name_map[c.schema_name.lower()] = dn
    return name_map


def _build_dialog_link_resolver(profile: "BotProfile | None"):
    """Returns a function `topic_name -> (link_target_tab, link_target_id)`.

    Used by Conversation Flow rows (and other linked surfaces) to
    deep-link into the Tools tab. After PR #18 collapsed the Topics tab
    into Tools, every DialogComponent target lives on the same tab and
    is keyed by `schema_name` — the picker key used by the Component
    Explorer's `select_topic_in_explorer(schema_name)` event.

    Returns `("", "")` when profile is None or the name can't be
    resolved.
    """
    if profile is None:
        return lambda _name: ("", "")

    by_key: dict = {}
    for c in profile.components:
        if c.kind != "DialogComponent":
            continue
        dn_lower = (c.display_name or "").lower().strip()
        if dn_lower:
            by_key.setdefault(dn_lower, c)
        if c.schema_name:
            sl = c.schema_name.lower()
            by_key.setdefault(sl, c)
            suffix = c.schema_name.rsplit(".", 1)[-1].lower()
            by_key.setdefault(suffix, c)

    def resolve(topic_name: str) -> tuple[str, str]:
        if not topic_name:
            return ("", "")
        comp = by_key.get(topic_name.lower().strip())
        if comp is None:
            return ("", "")
        # Always Tools tab (post-#18), always keyed by schema_name to
        # match the Component Explorer picker.
        return ("tools", comp.schema_name or comp.display_name or "")

    return resolve


def _resolve_score_for_topic(
    topic_name: str,
    scores: dict[str, float],
    name_map: dict[str, str],
) -> float | None:
    """Look up the trigger match score for a topic, handling name mismatches.

    Tries: exact match → normalized match → alias via component name map.
    """
    if not topic_name:
        return None
    # Exact match
    if topic_name in scores:
        return scores[topic_name]
    # Normalized match
    tn_lower = topic_name.lower().strip()
    for key, score in scores.items():
        if key.lower().strip() == tn_lower:
            return score
    # Alias via component name map: topic_name → display_name → score
    display_name = name_map.get(tn_lower)
    if display_name and display_name in scores:
        return scores[display_name]
    # Substring containment (e.g. topic "Dutchy" matches component "Ask Dutchy")
    for key, score in scores.items():
        if tn_lower in key.lower() or key.lower() in tn_lower:
            return score
    return None


def _build_trigger_score_lookup(
    timeline: ConversationTimeline,
    profile: BotProfile,
) -> dict[int, dict[str, float]]:
    """Map user_message_index -> {topic_name: score} for trigger matching.

    For each user message, runs ``match_query_to_triggers`` against profile
    components. Also checks for native IntentRecognition events — those take
    precedence over computed scores when both exist.
    """
    events = timeline.events
    lookup: dict[int, dict[str, float]] = {}

    # Collect user message indices
    user_indices: list[int] = []
    for idx, ev in enumerate(events):
        if ev.event_type == EventType.USER_MESSAGE:
            user_indices.append(idx)

    for pos, ui in enumerate(user_indices):
        ev = events[ui]
        user_text = (ev.summary or "").replace("User: ", "", 1).strip().strip('"')
        if not user_text:
            continue

        next_ui = user_indices[pos + 1] if pos + 1 < len(user_indices) else len(events)

        # Computed scores from trigger matching
        matches = match_query_to_triggers(user_text, profile.components, threshold=0.0)
        scores: dict[str, float] = {}
        for m in matches:
            scores[m["display_name"]] = m["score"]

        # Override with native IntentRecognition events if present
        for between_ev in events[ui + 1 : next_ui]:
            if between_ev.event_type == EventType.INTENT_RECOGNITION and between_ev.intent_score is not None:
                topic = between_ev.topic_name or ""
                if topic:
                    scores[topic] = between_ev.intent_score

        lookup[ui] = scores

    return lookup


def _find_latest_user_index(events: list, current_idx: int) -> int | None:
    """Walk backwards from current_idx to find the most recent USER_MESSAGE index."""
    for i in range(current_idx - 1, -1, -1):
        if events[i].event_type == EventType.USER_MESSAGE:
            return i
    return None


def _format_trigger_score(score: float | None) -> str:
    """Format a 0-1 score as a labelled percentage string, or empty if None."""
    if score is None:
        return ""
    return f"Routing score: {score:.0%}"


def _trigger_score_color(score: float | None) -> str:
    """Return a Radix color scheme name for a trigger score."""
    if score is None:
        return "gray"
    if score >= 0.7:
        return "green"
    if score >= 0.4:
        return "amber"
    return "red"


def _best_trigger_phrase(user_text: str, topic_name: str, components: list) -> str:
    """Find the best matching trigger phrase for a topic given a user query."""
    matches = match_query_to_triggers(user_text, components, threshold=0.0)
    for m in matches:
        if m["display_name"] == topic_name:
            return m.get("best_phrase", "")
    return ""


# Deferred imports — `renderer/report.py` and `renderer/timeline_render.py`
# both import from this module, so importing them at the top here would
# create a circular dependency. They sit below the trigger-score helpers
# above (which both `report` and `timeline_render` consume). The
# `noqa` markers below acknowledge the deliberate ordering.
from .knowledge import render_knowledge_search_section  # noqa: E402
from .profile import (  # noqa: E402
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
from ._helpers import _compute_idle_gaps, _format_duration, _is_genuine_idle, _parse_timestamp_to_epoch_ms  # noqa: E402
from .report import render_credit_estimate  # noqa: E402
from .timeline_render import render_orchestrator_reasoning, render_timeline  # noqa: E402


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
    # Runtime tool call analysis
    if timeline.tool_calls:
        from .tools import render_tool_analysis

        tool_analysis = render_tool_analysis(timeline, profile)
        if tool_analysis:
            tools_parts.append(tool_analysis)

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


def group_flow_items(items: list[dict]) -> list[dict]:
    """Group conversation flow items into plan cards + loose groups.

    The orchestrator emits a `PlanReceived` event at the start of every
    plan and a `PlanFinished` at the end. Everything between them is
    part of that plan's execution. Grouping makes long, multi-plan
    conversations dramatically more readable in the UI — each plan
    becomes a collapsible card with a status pill (running / completed
    / cancelled), instead of a flat undifferentiated stream.

    Returns a list of group dicts. Two shapes:

    - **Plan group** (`is_plan == "true"`): header + items list. Status
      derives from `PlanFinished.summary` ("cancelled=True/False"); a
      plan that never gets a `PlanFinished` is reported as `running`.

    - **Loose group** (`is_plan == ""`): items not enclosed in any plan
      (typically `UserMessage` / `BotMessage` / standalone errors).
      No header rendered.

    Group-row dict keys (uniform across both shapes for ``rx.foreach``):
      ``is_plan``, ``plan_identifier``, ``status``, ``status_tone``,
      ``header_summary``, ``first_timestamp``, ``items`` (list of flow
      row dicts).
    """

    groups: list[dict] = []
    current_plan: dict | None = None
    loose: dict | None = None

    def _empty_loose() -> dict:
        return {
            "is_plan": "",
            "plan_identifier": "",
            "status": "",
            "status_tone": "neutral",
            "header_summary": "",
            "first_timestamp": "",
            "items": [],
        }

    def _close_loose() -> None:
        nonlocal loose
        if loose is not None and loose["items"]:
            groups.append(loose)
        loose = None

    def _close_plan(status: str, status_tone: str) -> None:
        nonlocal current_plan
        if current_plan is None:
            return
        current_plan["status"] = status
        current_plan["status_tone"] = status_tone
        n = len(current_plan["items"])
        pid = current_plan["plan_identifier"]
        short_pid = pid[:8] if pid else "<unknown>"
        current_plan["header_summary"] = f"Plan {short_pid} — {n} event{'s' if n != 1 else ''}"
        groups.append(current_plan)
        current_plan = None

    for item in items:
        et = item.get("event_type", "")
        if et == "PlanReceived":
            _close_loose()
            current_plan = {
                "is_plan": "true",
                "plan_identifier": item.get("plan_identifier") or "",
                "status": "running",
                "status_tone": "info",
                "header_summary": "",  # filled when closed
                "first_timestamp": item.get("timestamp", ""),
                "items": [item],
            }
            continue
        if et == "PlanFinished" and current_plan is not None:
            current_plan["items"].append(item)
            summary_text = (item.get("summary") or "").lower()
            cancelled = "cancelled=true" in summary_text
            _close_plan(
                "cancelled" if cancelled else "completed",
                "bad" if cancelled else "good",
            )
            continue
        if current_plan is not None:
            current_plan["items"].append(item)
        else:
            if loose is None:
                loose = _empty_loose()
            loose["items"].append(item)

    # Flush — a plan that never received PlanFinished stays as "running".
    if current_plan is not None:
        n = len(current_plan["items"])
        pid = current_plan["plan_identifier"]
        short_pid = pid[:8] if pid else "<unknown>"
        current_plan["status"] = "running"
        current_plan["status_tone"] = "info"
        current_plan["header_summary"] = f"Plan {short_pid} — {n} event{'s' if n != 1 else ''} (running)"
        groups.append(current_plan)
    _close_loose()
    return groups


def build_conversation_flow_items(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> list[dict]:
    """Build chat-style flow items from timeline events for UI rendering."""
    items: list[dict] = []

    # Build trigger score lookup if profile is available
    score_lookup: dict[int, dict[str, float]] = {}
    name_map: dict[str, str] = {}
    if profile is not None:
        score_lookup = _build_trigger_score_lookup(timeline, profile)
        name_map = _build_component_name_map(profile)
    dialog_link = _build_dialog_link_resolver(profile)

    # Per-step tool-call lookup so STEP_TRIGGERED / STEP_FINISHED flow
    # rows can render AUTO/MANUAL binding counts.
    tool_call_by_step: dict[str, object] = {tc.step_id: tc for tc in timeline.tool_calls if tc.step_id}

    # Extra detail keys required by rx.foreach (must be uniform across all dicts)
    _detail_defaults = {
        "has_recommendations": "",
        "plan_used_outputs": "",
        "plan_identifier": "",
        "plan_steps": "",
        "error": "",
        "is_final_plan": "",
        "orchestrator_ask": "",
        "trigger_score": "",
        "trigger_phrase": "",
        "trigger_score_color": "gray",
        # Deep-link target — empty when the row has no actionable destination.
        # Populated for events that name a topic / tool / knowledge action so
        # the Conversation Flow row can hyperlink into the relevant tab.
        "link_target_tab": "",
        "link_target_id": "",
        # Stable per-row id (set after the loop). The banner / error summary
        # uses `flow_id` as the deep-link target_id so clicks scroll to the
        # exact row. `flow_row_id` is the pre-built DOM id (`row-<flow_id>`)
        # so component code doesn't have to concat at render time.
        "flow_id": "",
        "flow_row_id": "",
        # Pretty-printed JSON of the underlying TimelineEvent — surfaced via
        # the per-row copy button + raw-JSON accordion so the user can
        # quickly grab the activity payload (helpful when filing bugs
        # against Microsoft).
        "raw_json": "",
        # AUTO/MANUAL binding counts for STEP_TRIGGERED / STEP_FINISHED
        # rows — sourced from the correlated `ToolCall.arguments` and
        # `ToolCall.auto_filled_argument_names`. Empty string when the
        # row isn't a step or has no matching tool call.
        "auto_filled_count": "",
        "manual_filled_count": "",
    }

    latest_user_idx: int | None = None

    for idx, ev in enumerate(timeline.events):
        summary = (ev.summary or "").strip()
        timestamp = _format_clock(ev.timestamp)

        if ev.event_type == EventType.USER_MESSAGE:
            latest_user_idx = idx
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
            items[-1]["raw_json"] = _flow_event_raw_json(ev)
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
            items[-1]["raw_json"] = _flow_event_raw_json(ev)
            continue

        if ev.event_type in {
            EventType.PLAN_RECEIVED,
            EventType.PLAN_FINISHED,
            EventType.STEP_TRIGGERED,
            EventType.STEP_FINISHED,
            EventType.KNOWLEDGE_SEARCH,
            EventType.GENERATIVE_ANSWER,
            EventType.DIALOG_TRACING,
            EventType.DIALOG_REDIRECT,
            EventType.ACTION_TRIGGER_EVAL,
            EventType.ORCHESTRATOR_THINKING,
            EventType.ERROR,
            EventType.ACTION_AI_BUILDER,
        }:
            title_map = {
                EventType.PLAN_RECEIVED: "Plan Received",
                EventType.PLAN_FINISHED: "Plan Finished",
                EventType.STEP_TRIGGERED: "Action Started",
                EventType.STEP_FINISHED: "Action Finished",
                EventType.KNOWLEDGE_SEARCH: "Knowledge Search",
                EventType.GENERATIVE_ANSWER: "Generative Answer",
                EventType.DIALOG_TRACING: "Topic Trace",
                EventType.DIALOG_REDIRECT: "Topic Redirect",
                EventType.ACTION_TRIGGER_EVAL: "Condition Eval",
                EventType.ORCHESTRATOR_THINKING: "Orchestrator Thinking",
                EventType.ERROR: "Error",
                EventType.ACTION_AI_BUILDER: "AI Builder",
            }
            if ev.event_type == EventType.ERROR:
                tone = "error"
            elif ev.event_type == EventType.GENERATIVE_ANSWER:
                tone = "error" if ev.state == "failed" else "info"
            elif ev.event_type in (EventType.ACTION_TRIGGER_EVAL, EventType.ORCHESTRATOR_THINKING):
                tone = "trace"
            else:
                tone = "info"
            detail = summary
            query = getattr(ev, "search_query", None)
            if ev.event_type == EventType.KNOWLEDGE_SEARCH and query:
                detail = f'Query: "{query}"'

            # Add trigger scores for step triggered/finished events (only for matching topics)
            trigger_score_str = ""
            trigger_phrase_str = ""
            trigger_color = "gray"
            if (
                ev.event_type in {EventType.STEP_TRIGGERED, EventType.STEP_FINISHED}
                and latest_user_idx is not None
                and score_lookup
            ):
                topic = ev.topic_name or ""
                scores = score_lookup.get(latest_user_idx, {})
                score = _resolve_score_for_topic(topic, scores, name_map)
                if score is not None:
                    trigger_score_str = _format_trigger_score(score)
                    trigger_color = _trigger_score_color(score)
                    if profile is not None:
                        user_text = (
                            (timeline.events[latest_user_idx].summary or "").replace("User: ", "", 1).strip().strip('"')
                        )
                        if user_text:
                            resolved_name = name_map.get(topic.lower().strip(), topic)
                            trigger_phrase_str = _best_trigger_phrase(user_text, resolved_name, profile.components)

            # AUTO/MANUAL binding counts — only meaningful for step rows
            # that have a correlated tool call.
            auto_count_str = ""
            manual_count_str = ""
            if (
                ev.event_type in (EventType.STEP_TRIGGERED, EventType.STEP_FINISHED)
                and ev.step_id
                and ev.step_id in tool_call_by_step
            ):
                tc = tool_call_by_step[ev.step_id]
                args = getattr(tc, "arguments", {}) or {}
                auto_names = set(getattr(tc, "auto_filled_argument_names", []) or [])
                if args:
                    auto_count = sum(1 for k in args if k in auto_names)
                    manual_count = len(args) - auto_count
                    if auto_count > 0:
                        auto_count_str = str(auto_count)
                    if manual_count > 0:
                        manual_count_str = str(manual_count)

            # Deep-link target for events that point at a concrete artifact:
            # - dialog-name-bearing events (step trigger/finish, topic
            #   trace/redirect, condition eval) resolve to topics or tools.
            # - knowledge searches and generative answers route to the
            #   Knowledge tab. Generative answers carry the topic_name as a
            #   hint so the destination can scroll to the right card.
            link_tab, link_id = "", ""
            if ev.event_type in (
                EventType.STEP_TRIGGERED,
                EventType.STEP_FINISHED,
                EventType.DIALOG_TRACING,
                EventType.DIALOG_REDIRECT,
                EventType.ACTION_TRIGGER_EVAL,
            ):
                link_tab, link_id = dialog_link(ev.topic_name or "")
            elif ev.event_type == EventType.KNOWLEDGE_SEARCH:
                link_tab = "knowledge"
            elif ev.event_type == EventType.GENERATIVE_ANSWER:
                link_tab = "knowledge"
                link_id = f"gen:{(ev.topic_name or '').strip()}" if ev.topic_name else ""

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
                    "trigger_score": trigger_score_str,
                    "trigger_phrase": trigger_phrase_str,
                    "trigger_score_color": trigger_color,
                    "link_target_tab": link_tab,
                    "link_target_id": link_id,
                    "auto_filled_count": auto_count_str,
                    "manual_filled_count": manual_count_str,
                }
            )
            items[-1]["raw_json"] = _flow_event_raw_json(ev)

    for idx, item in enumerate(items):
        item["flow_id"] = f"flow-{idx}"
        item["flow_row_id"] = f"row-flow-{idx}"

    return items


def _flow_event_raw_json(ev) -> str:
    """Pretty-print the TimelineEvent for the per-row 'Raw JSON' accordion
    + copy button. Pydantic v2 carries `model_dump_json` which respects
    the model schema. Stripped of trailing whitespace so the accordion
    doesn't leave dangling lines."""
    try:
        return ev.model_dump_json(indent=2, exclude_none=True).strip()
    except Exception:
        return ""


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


def _active_duration(phase: ExecutionPhase, idle_gaps: list[tuple[int, int]]) -> float:
    """Phase duration minus any idle time that falls within its span."""
    if not phase.start or not phase.end or not idle_gaps:
        return phase.duration_ms
    p_start = _parse_timestamp_to_epoch_ms(phase.start)
    p_end = _parse_timestamp_to_epoch_ms(phase.end)
    if p_start is None or p_end is None:
        return phase.duration_ms
    idle_in_phase = sum(
        min(gap_end, p_end) - max(gap_start, p_start)
        for gap_start, gap_end in idle_gaps
        if gap_start < p_end and gap_end > p_start
    )
    return max(phase.duration_ms - idle_in_phase, 0)


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
    bot_msgs = sum(
        1 for e in timeline.events if e.event_type in (EventType.BOT_MESSAGE, EventType.ACTION_SEND_ACTIVITY)
    )
    errors = sum(1 for e in timeline.events if e.event_type == EventType.ERROR)
    orchestrator_count = sum(1 for e in timeline.events if e.event_type == EventType.ORCHESTRATOR_THINKING)
    searches = sum(1 for e in timeline.events if e.event_type == EventType.KNOWLEDGE_SEARCH) + len(
        timeline.custom_search_steps
    )

    started_steps = [e for e in timeline.events if e.event_type == EventType.STEP_TRIGGERED]
    finished_steps = {e.step_id for e in timeline.events if e.event_type == EventType.STEP_FINISHED and e.step_id}
    orphaned_steps = sum(1 for s in started_steps if s.step_id and s.step_id not in finished_steps)

    turns = _pair_message_turns(timeline)
    latencies = [t["latency_ms"] for t in turns if t["latency_ms"] > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    custom_search_names = {cs.display_name for cs in timeline.custom_search_steps}

    def _is_search_phase(p: ExecutionPhase) -> bool:
        return p.phase_type == "KnowledgeSource" or p.label in custom_search_names

    def _is_orchestrator_phase(p: ExecutionPhase) -> bool:
        return p.phase_type == "OrchestratorThinking"

    idle_gaps = _compute_idle_gaps(timeline.events)
    search_durations = [
        d
        for d in (_active_duration(p, idle_gaps) for p in timeline.phases if p.duration_ms > 0 and _is_search_phase(p))
        if d > 0
    ]
    orchestrator_durations = [p.duration_ms for p in timeline.phases if p.duration_ms > 0 and _is_orchestrator_phase(p)]
    # Per-step (phase, active-duration) so we can identify the slowest one
    # by name. User wait/idle gaps are already subtracted by `_active_duration`.
    step_phase_durations: list[tuple[str, float]] = [
        (p.label, _active_duration(p, idle_gaps))
        for p in timeline.phases
        if p.duration_ms > 0 and not _is_search_phase(p) and not _is_orchestrator_phase(p)
    ]
    step_phase_durations = [(label, d) for label, d in step_phase_durations if d > 0]
    step_durations = [d for _, d in step_phase_durations]

    # KPI values
    avg_latency_str = f"{avg_latency:.0f} ms" if latencies else "—"
    p95_latency_str = f"{p95_latency:.0f} ms" if latencies else "—"

    # KPIs
    kpis = [
        {"label": "User Messages", "value": str(user_msgs), "hint": "Incoming requests", "tone": "neutral"},
        {"label": "Bot Responses", "value": str(bot_msgs), "hint": "Delivered answers", "tone": "neutral"},
        {
            "label": "Avg Turn Latency",
            "value": avg_latency_str,
            "hint": "User -> bot response",
            "tone": "neutral" if not latencies or avg_latency < 4000 else "warn",
        },
        {
            "label": "P95 Turn Latency",
            "value": p95_latency_str,
            "hint": "Worst typical latency",
            "tone": "warn" if latencies and p95_latency >= 6000 else "neutral",
        },
    ]

    # Slowest step (excluding user wait/idle) — points to the single most
    # expensive non-search, non-orchestrator phase. Surface the phase label
    # in the hint so the user knows where to look.
    if step_phase_durations:
        slowest_label, slowest_ms = max(step_phase_durations, key=lambda lbl_d: lbl_d[1])
        slowest_value = f"{slowest_ms / 1000:.1f}s" if slowest_ms >= 1000 else f"{slowest_ms:.0f} ms"
        kpis.append(
            {
                "label": "Slowest Step",
                "value": slowest_value,
                "hint": f"{slowest_label} (excl. user wait)",
                "tone": "warn" if slowest_ms >= 4000 else "neutral",
            }
        )

    # Plans completed vs cancelled — `PLAN_FINISHED.summary` carries
    # `(cancelled=True|False)` from timeline.py:676. Surface as a single
    # KPI ("3 / 4 completed") so the user sees both numbers at once.
    plan_finished_events = [e for e in timeline.events if e.event_type == EventType.PLAN_FINISHED]
    if plan_finished_events:
        cancelled_plans = sum(1 for e in plan_finished_events if "cancelled=True" in (e.summary or ""))
        total_plans = len(plan_finished_events)
        completed_plans = total_plans - cancelled_plans
        kpis.append(
            {
                "label": "Plans Completed",
                "value": f"{completed_plans} / {total_plans}",
                "hint": f"{cancelled_plans} cancelled" if cancelled_plans else "all completed",
                "tone": "warn" if cancelled_plans > 0 else "neutral",
            }
        )

    # Tool-call success rate — fraction of orchestrator-invoked tool calls
    # that finished with state == "completed". Hidden when there are no
    # tool calls (transcripts without orchestrator activity).
    if timeline.tool_calls:
        total_calls = len(timeline.tool_calls)
        success_calls = sum(1 for tc in timeline.tool_calls if tc.state == "completed")
        success_pct = (success_calls / total_calls) * 100
        kpis.append(
            {
                "label": "Tool Success Rate",
                "value": f"{success_pct:.0f}%",
                "hint": f"{success_calls} / {total_calls} succeeded",
                "tone": "warn" if success_pct < 95 else "neutral",
            }
        )

    # Event mix
    mix_raw = [
        ("Messages", user_msgs + bot_msgs, "var(--green-9)", latencies),
        ("Steps", len(started_steps), "var(--teal-9)", step_durations),
        ("Search", searches, "var(--amber-9)", search_durations),
        ("Orchestrator", orchestrator_count, "var(--blue-9)", orchestrator_durations),
        ("Errors", errors, "var(--red-9)", []),
    ]
    mix_total = sum(v for _, v, _, _ in mix_raw) or 1
    event_mix = []
    for label, count, color, durations in mix_raw:
        stats = _duration_stats(durations)
        bar_color = _severity_color(stats["avg_ms"]) if stats else "var(--gray-a5)"
        event_mix.append(
            {
                "label": label,
                "count": str(count),
                "color": color,
                "bar_color": bar_color,
                "pct": f"{(count / mix_total) * 100:.1f}%",
                "min_fmt": stats["min_fmt"] if stats else "",
                "max_fmt": stats["max_fmt"] if stats else "",
                "avg_fmt": stats["avg_fmt"] if stats else "",
            }
        )

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
        child_summary = " → ".join(f"{ce['type']}: {ce['summary']}" for ce in child_events) if child_events else ""

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
        raw = ev.summary or ""
        # Strip common prefixes
        for prefix in ("Call to ", "Begin "):
            if raw.startswith(prefix):
                raw = raw[len(prefix) :]
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
            is_selected = norm_selected == norm_match or norm_selected in norm_match or norm_match in norm_selected
            if is_selected and not selected_line_added:
                lines.insert(0, f'✓ {m["display_name"]} ({pct}) — "{m["best_phrase"]}"')
                selected_line_added = True
            else:
                lines.append(f'· {m["display_name"]} ({pct}) — "{m["best_phrase"]}"')

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
# Performance waterfall
# ---------------------------------------------------------------------------


_WATERFALL_CATEGORY: dict[str, tuple[str, str]] = {
    # event_type.value → (category_label, css color)
    "UserMessage": ("Message", "var(--green-9)"),
    "BotMessage": ("Message", "var(--green-9)"),
    "ActionSendActivity": ("Message", "var(--green-9)"),
    "PlanReceived": ("Plan", "var(--blue-9)"),
    "PlanFinished": ("Plan", "var(--blue-9)"),
    "PlanReceivedDebug": ("Plan", "var(--blue-9)"),
    "StepTriggered": ("Action", "var(--teal-9)"),
    "StepFinished": ("Action", "var(--teal-9)"),
    "ActionHttpRequest": ("Action", "var(--teal-9)"),
    "ActionBeginDialog": ("Action", "var(--teal-9)"),
    "ActionQA": ("Action", "var(--teal-9)"),
    "ActionAIBuilder": ("AI Builder", "var(--purple-9)"),
    "KnowledgeSearch": ("Knowledge", "var(--amber-9)"),
    "GenerativeAnswer": ("Knowledge", "var(--amber-9)"),
    "OrchestratorThinking": ("Orchestrator", "var(--violet-9)"),
    "IntentRecognition": ("Orchestrator", "var(--violet-9)"),
    "DialogTracing": ("Trace", "var(--gray-9)"),
    "DialogRedirect": ("Trace", "var(--gray-9)"),
    "ActionTriggerEval": ("Trace", "var(--gray-9)"),
    "VariableAssignment": ("Trace", "var(--gray-9)"),
    "Error": ("Error", "var(--red-9)"),
}


def _waterfall_category(event_type: EventType) -> tuple[str, str]:
    return _WATERFALL_CATEGORY.get(event_type.value, ("Other", "var(--gray-9)"))


def _format_gap(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f} s"
    return f"{ms / 60_000:.1f} m"


def build_performance_waterfall(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> list[dict]:
    """Build a one-row-per-timed-activity waterfall view exposing the gap
    between each consecutive event so the user can spot bottlenecks.

    The Gantt chart shows phase durations; the waterfall shows the
    *gaps* between activities — distinct debugging signals. A long gap
    between e.g. PlanReceived and StepTriggered points to orchestrator
    reasoning latency; a long gap between BotMessage and UserMessage
    is just user think time (and is suppressed since it's idle).

    Bar widths are proportional to gap_ms / max_gap so the worst
    offender is easiest to spot. Idle gaps (`_is_genuine_idle`) are
    excluded so the user's own delay doesn't drown out the signal.

    When `profile` is provided, rows that name a known component get
    a `link_target_id` (schema_name) so the UI can hyperlink them to
    the Tools tab Component Explorer. Knowledge events get a
    `link_target_kind="knowledge"` so they jump to the Knowledge tab.
    """
    dialog_link = _build_dialog_link_resolver(profile)

    timed: list[tuple[int, TimelineEvent]] = []
    for ev in timeline.events:
        ms = _parse_timestamp_to_epoch_ms(ev.timestamp or "")
        if ms is not None:
            timed.append((ms, ev))
    timed.sort(key=lambda x: x[0])
    if len(timed) < 2:
        return []

    # Gaps in ms — first event has zero gap (anchor row).
    rows: list[dict] = []
    max_gap = 0.0
    for i, (ms, ev) in enumerate(timed):
        if i == 0:
            gap_ms = 0.0
            is_idle = False
        else:
            prev_ms, prev_ev = timed[i - 1]
            gap_ms = float(ms - prev_ms)
            is_idle = _is_genuine_idle(prev_ev, ev)
            if is_idle:
                gap_ms = 0.0
        max_gap = max(max_gap, gap_ms)
        category, color = _waterfall_category(ev.event_type)
        label = ev.summary or ev.event_type.value
        # Trim long summaries so the row stays readable.
        if len(label) > 80:
            label = label[:77] + "…"

        # Resolve link target. Knowledge / generative-answer events
        # always link to the Knowledge tab. Step / dialog events link
        # to Tools tab Component Explorer when the topic_name resolves
        # to a profile component.
        link_kind = ""
        link_id = ""
        if ev.event_type in (EventType.KNOWLEDGE_SEARCH, EventType.GENERATIVE_ANSWER):
            link_kind = "knowledge"
            link_id = ev.topic_name or ""
        elif ev.topic_name:
            link_tab, link_target = dialog_link(ev.topic_name)
            if link_tab == "tools" and link_target:
                link_kind = "component"
                link_id = link_target

        rows.append(
            {
                "label": label,
                "category": category,
                "color": color,
                "gap_ms": gap_ms,
                "gap_fmt": _format_gap(gap_ms) if gap_ms > 0 else "—",
                "is_idle": "true" if is_idle else "",
                "topic_name": ev.topic_name or "",
                "timestamp": _format_clock(ev.timestamp),
                "link_target_kind": link_kind,
                "link_target_id": link_id,
            }
        )
    # Convert gap_ms to width_pct against the max so the widest bar is
    # ~100%. Empty bars get a 0% width (rendered as a thin marker only).
    for row in rows:
        gap = row["gap_ms"]
        pct = (gap / max_gap * 100.0) if max_gap > 0 else 0.0
        row["width_pct"] = f"{pct:.1f}%"
        # State stringification — Reflex stores everything as JSON-safe.
        row["gap_ms"] = f"{gap:.0f}"
    return rows


# ---------------------------------------------------------------------------
# Orchestrator decision timeline
# ---------------------------------------------------------------------------


def build_orchestrator_decision_timeline(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> list[dict]:
    """Build a flat list of orchestrator decision items grouped by user-message turns.

    Each dict has a ``kind`` key: user_message, interpreted, plan, step, plan_finished.
    All values are strings (Reflex Var constraint).
    """
    items: list[dict] = []
    events = timeline.events
    latest_user_text: str = ""
    latest_user_idx: int | None = None

    # Build trigger score lookup if profile is available
    score_lookup: dict[int, dict[str, float]] = {}
    name_map: dict[str, str] = {}
    if profile is not None:
        score_lookup = _build_trigger_score_lookup(timeline, profile)
        name_map = _build_component_name_map(profile)

    for idx, ev in enumerate(events):
        if ev.event_type == EventType.USER_MESSAGE:
            latest_user_text = (ev.summary or "").replace("User: ", "", 1).strip()
            latest_user_idx = idx
            items.append(
                {
                    "kind": "user_message",
                    "text": latest_user_text,
                    "timestamp": _format_clock(ev.timestamp),
                }
            )
            continue

        if ev.event_type == EventType.PLAN_RECEIVED_DEBUG:
            ask = ev.orchestrator_ask or ""
            if ask and ask != latest_user_text:
                items.append(
                    {
                        "kind": "interpreted",
                        "ask": ask,
                        "timestamp": _format_clock(ev.timestamp),
                    }
                )
            continue

        if ev.event_type == EventType.PLAN_RECEIVED:
            steps_str = ", ".join(ev.plan_steps) if ev.plan_steps else (ev.summary or "")
            items.append(
                {
                    "kind": "plan",
                    "steps": steps_str,
                    "is_final": str(ev.is_final_plan) if ev.is_final_plan is not None else "",
                    "plan_identifier": ev.plan_identifier or "",
                    "timestamp": _format_clock(ev.timestamp),
                }
            )
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

            # Look up trigger score for this step's specific topic only
            trigger_score_str = ""
            trigger_phrase_str = ""
            trigger_color = "gray"
            if ev.event_type == EventType.STEP_TRIGGERED and latest_user_idx is not None and score_lookup:
                topic = ev.topic_name or ""
                scores = score_lookup.get(latest_user_idx, {})
                score = _resolve_score_for_topic(topic, scores, name_map)
                if score is not None:
                    trigger_score_str = _format_trigger_score(score)
                    trigger_color = _trigger_score_color(score)
                    if profile is not None and latest_user_text:
                        resolved_name = name_map.get(topic.lower().strip(), topic)
                        trigger_phrase_str = _best_trigger_phrase(latest_user_text, resolved_name, profile.components)

            items.append(
                {
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
                    "trigger_score": trigger_score_str,
                    "trigger_phrase": trigger_phrase_str,
                    "trigger_score_color": trigger_color,
                }
            )
            continue

        if ev.event_type in {
            EventType.ACTION_HTTP_REQUEST,
            EventType.ACTION_BEGIN_DIALOG,
            EventType.ACTION_TRIGGER_EVAL,
        }:
            action_type_map = {
                EventType.ACTION_HTTP_REQUEST: "HTTP Request",
                EventType.ACTION_BEGIN_DIALOG: "Begin Dialog",
                EventType.ACTION_TRIGGER_EVAL: "Condition Eval",
            }
            items.append(
                {
                    "kind": "action",
                    "action_type": action_type_map[ev.event_type],
                    "topic_name": ev.topic_name or "",
                    "summary": (ev.summary or "")[:120],
                    "error": ev.error or "",
                    "timestamp": _format_clock(ev.timestamp),
                }
            )
            continue

        if ev.event_type == EventType.ORCHESTRATOR_THINKING:
            import re as _re_orch

            dur_match = _re_orch.search(r"\((\d+)ms\)", ev.summary or "")
            duration = f"{dur_match.group(1)}ms" if dur_match else ""
            items.append(
                {
                    "kind": "orchestrator_thinking",
                    "summary": (ev.summary or "").replace("Orchestrator: ", "", 1)[:120],
                    "duration": duration,
                    "timestamp": _format_clock(ev.timestamp),
                }
            )
            continue

        if ev.event_type == EventType.PLAN_FINISHED:
            is_cancelled = "true" if "cancelled=True" in (ev.summary or "") else "false"
            items.append(
                {
                    "kind": "plan_finished",
                    "is_cancelled": is_cancelled,
                    "timestamp": _format_clock(ev.timestamp),
                }
            )

    return items


# ---------------------------------------------------------------------------
# Plan evolution tracker
# ---------------------------------------------------------------------------


def build_plan_evolution(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> list[dict]:
    """Compare consecutive PLAN_RECEIVED events to show how plans evolved.

    Only returns data when >1 plan exists in the conversation.
    """
    plan_events = [ev for ev in timeline.events if ev.event_type == EventType.PLAN_RECEIVED]
    if len(plan_events) <= 1:
        return []

    # Build score lookup for per-step scores
    score_lookup: dict[int, dict[str, float]] = {}
    name_map: dict[str, str] = {}
    if profile is not None:
        score_lookup = _build_trigger_score_lookup(timeline, profile)
        name_map = _build_component_name_map(profile)

    # Map plan events to their event index for user message lookup
    plan_event_indices: list[int] = []
    for i, ev in enumerate(timeline.events):
        if ev.event_type == EventType.PLAN_RECEIVED:
            plan_event_indices.append(i)

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

        # Compute per-step scores
        step_scores_str = ""
        if score_lookup and idx < len(plan_event_indices):
            plan_ev_idx = plan_event_indices[idx]
            user_idx = _find_latest_user_index(timeline.events, plan_ev_idx)
            if user_idx is not None:
                scores = score_lookup.get(user_idx, {})
                scored_parts = []
                for step_name in ev.plan_steps:
                    score = _resolve_score_for_topic(step_name, scores, name_map)
                    if score is not None:
                        scored_parts.append(f"{step_name} ({score:.0%})")
                if scored_parts:
                    step_scores_str = ", ".join(scored_parts)

        results.append(
            {
                "plan_index": str(idx + 1),
                "plan_identifier": ev.plan_identifier or "",
                "is_final": str(ev.is_final_plan) if ev.is_final_plan is not None else "",
                "steps": ", ".join(ev.plan_steps) if ev.plan_steps else "",
                "added_steps": added,
                "removed_steps": removed,
                "change_summary": change_summary,
                "timestamp": _format_clock(ev.timestamp),
                "step_scores": step_scores_str,
            }
        )

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
        "| Topic | Status | Duration | Start → End | Thought | Children | Plan |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for lc in items:
        thought = (lc.get("thought") or "—").replace("|", "\\|").replace("\n", " ")
        time_range = f"{lc.get('start', '')} → {lc.get('end', '')}" if lc.get("start") else "—"
        child_summary = (lc.get("child_summary") or "—").replace("|", "\\|").replace("\n", " ")
        child_count = lc.get("child_count", "")
        if child_count:
            child_str = f"{child_summary} ({child_count})"
        else:
            child_str = child_summary
        plan_id = (lc.get("plan_identifier") or "—").replace("|", "\\|")
        lines.append(
            f"| {lc['name']} | {lc['status']} | {lc.get('duration_label') or '—'} | {time_range} | {thought} | {child_str} | {plan_id} |"
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
                score = item.get("trigger_score", "")
                prefix = f" — *{thought}*" if thought else ""
                score_suffix = f" [{score}]" if score else ""
                lines.append(f"  - ▶ {topic}{score_suffix}{prefix}")
            else:
                duration = item.get("duration", "")
                status = item.get("status", "")
                lines.append(f"  - ✓ {topic} ({status}, {duration})" if duration else f"  - ✓ {topic} ({status})")
        elif kind == "action":
            lines.append(f"  - ⚡ {item.get('action_type', '')}: {item.get('summary', '')}")
        elif kind == "orchestrator_thinking":
            summary = item.get("summary", "")
            lines.append(f"  - ⏳ {summary}")
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
        "| Plan # | Final? | Steps | Changes | Routing Scores |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in items:
        final = "Yes" if p.get("is_final") == "True" else "No" if p.get("is_final") else "—"
        steps = (p.get("steps") or "—").replace("|", "\\|")
        changes = p.get("change_summary") or "—"
        scores = (p.get("step_scores") or "—").replace("|", "\\|")
        lines.append(f"| {p['plan_index']} | {final} | {steps} | {changes} | {scores} |")
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
        lines.append(f'### "{user_msg}"\n')
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


def render_conversation_flow_md(timeline: ConversationTimeline, profile: BotProfile | None = None) -> str:
    """Render conversation flow as markdown.

    StepTriggered / StepFinished rows append AUTO=N / MANUAL=N badges
    when the correlated tool call has bound arguments — same data the
    dynamic page uses for its inline binding badges.
    """
    items = build_conversation_flow_items(timeline, profile=profile)
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
            badges: list[str] = []
            auto_n = item.get("auto_filled_count", "")
            manual_n = item.get("manual_filled_count", "")
            if auto_n:
                badges.append(f"AUTO={auto_n}")
            if manual_n:
                badges.append(f"MANUAL={manual_n}")
            if badges:
                line += f" `{' / '.join(badges)}`"
            if thought:
                line += f" — *{thought}*"
            lines.append(line)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Variable Tracker markdown
# ---------------------------------------------------------------------------


def _md_escape(s: str) -> str:
    """Minimal escape for markdown table cells (pipes + newlines)."""
    return (s or "").replace("|", "\\|").replace("\n", " ").replace("\r", "")


def render_variable_tracker_md(timeline: ConversationTimeline, profile: BotProfile | None = None) -> str:
    """Markdown equivalent of the dynamic page's Variable Tracker card.

    Renders three sub-sections (one per `card_kind`) so the markdown
    report carries the same orchestrator tool calls + Topic / Global
    variable assignments + topic-level Generative Answer harvesting that
    the inline UI shows. Empty when the conversation has none of the
    three.
    """
    from .dynamic_data import build_variable_tracker_rows

    rows = build_variable_tracker_rows(timeline, profile)
    if not rows:
        return ""

    tool_calls = [r for r in rows if r["card_kind"] == "tool_call"]
    var_assigns = [r for r in rows if r["card_kind"] == "variable_assignment"]
    gen_answers = [r for r in rows if r["card_kind"] == "generative_answer"]

    lines: list[str] = ["## Variable Tracker\n"]
    lines.append(
        "_Inputs, outputs, and harvested values across the conversation: orchestrator "
        "tool calls (AUTO/MANUAL bindings), Topic / Global variable assignments, and "
        "topic-level Generative Answer traces._\n"
    )

    if tool_calls:
        lines.append("### Tool Calls\n")
        lines.append("| Time | Tool | Step Type | State | Duration | AUTO | MANUAL | Output |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in tool_calls:
            args = r.get("arguments", []) or []
            auto_n = sum(1 for a in args if a.get("auto_filled") == "true")
            manual_n = len(args) - auto_n
            output = _md_escape(r.get("output_preview") or "—")
            if len(output) > 80:
                output = output[:77] + "…"
            lines.append(
                f"| `{r['timestamp'] or '—'}` "
                f"| {_md_escape(r['display_name'])} "
                f"| {_md_escape(r['step_type'])} "
                f"| {_md_escape(r['state'])} "
                f"| {_md_escape(r['duration'])} "
                f"| {auto_n if auto_n else '—'} "
                f"| {manual_n if manual_n else '—'} "
                f"| {output} |"
            )
        lines.append("")

    if var_assigns:
        lines.append("### Topic / Global Variable Assignments\n")
        lines.append("| # | Time | Scope | Variable | Value |")
        lines.append("|---|---|---|---|---|")
        for i, r in enumerate(var_assigns, 1):
            value = _md_escape(r.get("var_value") or "")
            if len(value) > 80:
                value = value[:77] + "…"
            lines.append(
                f"| {i} | `{r['timestamp'] or '—'}` "
                f"| {_md_escape(r['var_scope'] or '—')} "
                f"| `{_md_escape(r['var_name'] or '—')}` "
                f"| {value} |"
            )
        lines.append("")

    if gen_answers:
        lines.append("### Topic-Level Generative Answers\n")
        lines.append("| # | Time | Topic | Output Variable | Answer State | Citations | Summary |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, r in enumerate(gen_answers, 1):
            summary_preview = _md_escape(r.get("ga_summary") or "")
            if len(summary_preview) > 80:
                summary_preview = summary_preview[:77] + "…"
            output_var = r.get("ga_output_variable") or "—"
            lines.append(
                f"| {i} | `{r['timestamp'] or '—'}` "
                f"| {_md_escape(r['topic_name'] or '—')} "
                f"| `{_md_escape(output_var)}` "
                f"| {_md_escape(r['state'])} "
                f"| {r.get('ga_citation_count', '0')} "
                f"| {summary_preview} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Performance Waterfall markdown
# ---------------------------------------------------------------------------


def render_performance_waterfall_md(
    timeline: ConversationTimeline,
    profile: BotProfile | None = None,
) -> str:
    """Markdown equivalent of the dynamic page's Performance Waterfall.

    Renders a table with timestamp, category, activity label, gap to
    the previous activity, and a small unicode-block bar so the static
    output still hints at proportions. Idle gaps (user-think time, HITL
    waits) are suppressed via `_is_genuine_idle`, matching the UI.
    """
    rows = build_performance_waterfall(timeline, profile)
    if not rows:
        return ""

    lines: list[str] = ["## Performance Waterfall\n"]
    lines.append(
        "_Time gap between consecutive activities — the bar width is proportional "
        "to the longest gap so the slowest step is easiest to spot. User-think idle "
        "time is suppressed._\n"
    )
    lines.append("| Time | Category | Activity | Gap |  |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        # `width_pct` is "12.5%" — strip the % and convert to a 0..20 char bar
        pct_str = (r.get("width_pct") or "0%").rstrip("%")
        try:
            pct = float(pct_str)
        except (ValueError, TypeError):
            pct = 0.0
        bar_len = int(round(pct * 0.20))  # 100% = 20 blocks
        bar = "█" * bar_len if bar_len else ("·" if r.get("gap_fmt") not in ("—", "") else "")
        label = _md_escape(r.get("label") or "")
        if len(label) > 60:
            label = label[:57] + "…"
        lines.append(
            f"| `{r.get('timestamp') or '—'}` "
            f"| {_md_escape(r.get('category', ''))} "
            f"| {label} "
            f"| {_md_escape(r.get('gap_fmt') or '—')} "
            f"| `{bar}` |"
        )
    lines.append("")
    return "\n".join(lines)

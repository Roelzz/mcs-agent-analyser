from models import (
    BotProfile,
    ConversationTimeline,
    CreditEstimate,
    CreditLineItem,
    EventType,
)

from ._helpers import (
    _sanitize_mermaid,
    _sanitize_table_cell,
)
from .knowledge import render_knowledge_search_section
from .profile import (
    render_ai_config,
    render_bot_metadata,
    render_bot_profile,
    render_integration_map,
    render_knowledge_coverage,
    render_knowledge_inventory,
    render_quick_wins,
    render_security_summary,
    render_tool_inventory,
    render_topic_details,
    render_topic_graph,
    render_topic_inventory,
    render_trigger_overlaps,
)
from .timeline_render import (
    render_gantt_chart,
    render_mermaid_sequence,
    render_orchestrator_reasoning,
    render_timeline,
)


def render_report(profile: BotProfile, timeline: ConversationTimeline | None = None) -> str:
    """Render complete Markdown report.

    Section order per plan F2:
    1. Heading
    2. TL;DR
    3. AI Config
    4. Security Inventory
    5. Bot Profile metadata
    6. Execution diagrams (sequence + gantt)
    7. Conversation trace
    8. Orchestrator reasoning
    9. Agent instructions (part of AI Config)
    10. Topic Inventory
    11. Tool Inventory
    12. Integration Map
    13. Topic graph
    14. Knowledge Inventory
    15. Deep dive (topic details + knowledge search)
    """
    from timeline import estimate_credits

    if timeline is None:
        timeline = ConversationTimeline()

    # 1. Heading
    sections = [render_bot_profile(profile)]

    # Compute credit estimate upfront (used in TL;DR and as its own section)
    credit_estimate = estimate_credits(timeline, profile) if timeline.events else None

    # 2. TL;DR
    sections.append(render_tldr(profile, timeline, credit_estimate))

    # 2.5 Quick Wins
    quick_wins = render_quick_wins(profile)
    if quick_wins:
        sections.append(quick_wins)

    # 2.6 Trigger Overlaps
    from parser import detect_trigger_overlaps

    overlaps = detect_trigger_overlaps(profile.components)
    trigger_overlap_section = render_trigger_overlaps(overlaps)
    if trigger_overlap_section:
        sections.append(trigger_overlap_section)

    # 3. AI Config (includes system instructions)
    ai_config = render_ai_config(profile)
    if ai_config:
        sections.append(ai_config)

    # 4. Security Inventory
    security = render_security_summary(profile)
    if security:
        sections.append(security)

    # 5. Bot Profile metadata
    sections.append(render_bot_metadata(profile))

    # 6. Execution diagrams
    if timeline.events:
        has_steps = timeline.phases or any(
            e.event_type in (EventType.STEP_TRIGGERED, EventType.USER_MESSAGE) for e in timeline.events
        )
        if has_steps:
            sections.append(render_mermaid_sequence(timeline))
        gantt = render_gantt_chart(timeline)
        if gantt:
            sections.append(gantt)

    # 7. Conversation trace
    sections.append(render_timeline(timeline, skip_diagrams=True))

    # 8. Orchestrator reasoning
    reasoning = render_orchestrator_reasoning(timeline)
    if reasoning:
        sections.append(reasoning)

    # --- Inventories (static capabilities) ---

    # 10. Topic Inventory
    sections.append(render_topic_inventory(profile))

    # 11. Tool Inventory
    tool_inv = render_tool_inventory(profile)
    if tool_inv:
        sections.append(tool_inv)

    # 12. Integration Map
    int_map = render_integration_map(profile)
    if int_map:
        sections.append(int_map)

    # 13. Topic graph
    topic_graph = render_topic_graph(profile)
    if topic_graph:
        sections.append(topic_graph)

    # 14. Knowledge Inventory
    ka = render_knowledge_inventory(profile)
    if ka:
        sections.append(ka)

    # 14.5 Knowledge Coverage
    kcm = render_knowledge_coverage(profile)
    if kcm:
        sections.append(kcm)

    # --- Deep dive (runtime trace detail) ---

    # 15. Topic details + knowledge search
    topic_details = render_topic_details(profile, timeline)
    if topic_details:
        sections.append(topic_details)

    sections.append(render_knowledge_search_section(timeline, profile=profile))

    # 16. MCS Credit Estimate (last section)
    credit_section = render_credit_estimate(credit_estimate, timeline)
    if credit_section:
        sections.append(credit_section)

    return "\n".join(sections)


def render_transcript_report(
    title: str,
    timeline: ConversationTimeline,
    metadata: dict,
) -> str:
    """Render Markdown report for a transcript (no bot profile data)."""
    sections = [f"# {title}\n"]

    # Session summary table from metadata
    session = metadata.get("session_info")
    if session:
        sections.append("## Session Summary\n")
        lines = ["| Property | Value |", "| --- | --- |"]
        if session.get("startTimeUtc"):
            lines.append(f"| Start Time | {session['startTimeUtc']} |")
        if session.get("endTimeUtc"):
            lines.append(f"| End Time | {session['endTimeUtc']} |")
        if session.get("type"):
            lines.append(f"| Session Type | {session['type']} |")
        if session.get("outcome"):
            lines.append(f"| Outcome | {session['outcome']} |")
        if session.get("outcomeReason"):
            lines.append(f"| Outcome Reason | {session['outcomeReason']} |")
        if session.get("turnCount") is not None:
            lines.append(f"| Turn Count | {session['turnCount']} |")
        if session.get("impliedSuccess") is not None:
            lines.append(f"| Implied Success | {session['impliedSuccess']} |")
        lines.append("")
        sections.append("\n".join(lines))

    sections.append(render_knowledge_search_section(timeline))

    reasoning = render_orchestrator_reasoning(timeline)
    if reasoning:
        sections.append(reasoning)

    # Conversation trace (reuses existing render_timeline which includes
    # sequence diagram, gantt, phase breakdown, event log, errors)
    sections.append(render_timeline(timeline))

    return "\n".join(sections)


def render_tldr(
    profile: BotProfile, timeline: ConversationTimeline, credit_estimate: CreditEstimate | None = None
) -> str:
    """Render TL;DR summary section."""
    lines = ["## TL;DR\n"]

    # Bot type
    if profile.is_orchestrator:
        lines.append(f"**{profile.display_name}** is an orchestrator agent")
    else:
        lines.append(f"**{profile.display_name}** is a conversational agent")

    # Auth
    if profile.authentication_mode != "Unknown":
        auth = profile.authentication_mode
        if profile.authentication_trigger != "Unknown":
            auth += f" ({profile.authentication_trigger})"
        lines.append(f" with **{auth}** authentication")

    lines.append(".\n")

    # Tool breakdown
    tools = [c for c in profile.components if c.tool_type]
    if tools:
        type_counts: dict[str, int] = {}
        for t in tools:
            tt = t.tool_type or "Unknown"
            type_counts[tt] = type_counts.get(tt, 0) + 1
        parts = [f"{count} {ttype}" for ttype, count in sorted(type_counts.items())]
        lines.append(f"**Tools:** {', '.join(parts)}\n")

    # Component counts
    total = len(profile.components)
    active = sum(1 for c in profile.components if c.state == "Active")
    lines.append(f"**Components:** {total} total, {active} active\n")

    # Knowledge
    ks = [c for c in profile.components if c.kind in ("KnowledgeSourceComponent", "FileAttachmentComponent")]
    if ks:
        lines.append(f"**Knowledge:** {len(ks)} sources\n")

    # Credit estimate
    if credit_estimate and credit_estimate.total_credits > 0:
        lines.append(f"**Estimated Credits:** {credit_estimate.total_credits:.0f} (estimate)\n")

    return "\n".join(lines)


def render_credit_estimate(estimate: CreditEstimate, timeline: ConversationTimeline) -> str:
    """Render credit estimation section with summary, breakdown table, and Mermaid diagram."""
    if not estimate or not estimate.line_items:
        return ""

    lines: list[str] = []

    # Count by type
    type_counts: dict[str, int] = {}
    type_credits: dict[str, float] = {}
    for item in estimate.line_items:
        type_counts[item.step_type] = type_counts.get(item.step_type, 0) + 1
        type_credits[item.step_type] = type_credits.get(item.step_type, 0) + item.credits

    user_turns = sum(1 for e in timeline.events if e.event_type == EventType.USER_MESSAGE)

    # Section 1: Summary table
    lines.append("## MCS Credit Estimate\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total Credits | {estimate.total_credits:.0f} |")
    lines.append(f"| User Turns | {user_turns} |")
    if "generative_answer" in type_counts:
        lines.append(f"| Generative Answers | {type_counts['generative_answer']} |")
    if "agent_action" in type_counts:
        lines.append(f"| Agent Actions | {type_counts['agent_action']} |")
    if "classic_answer" in type_counts:
        lines.append(f"| Classic Answers | {type_counts['classic_answer']} |")
    if "flow_action" in type_counts:
        lines.append(f"| Flow Actions | {type_counts['flow_action']} |")
    lines.append("")

    # Section 2: Per-step breakdown
    lines.append("### Credit Breakdown\n")
    lines.append("| # | Step | Type | Credits | Detail |")
    lines.append("|---|---|---|---|---|")
    for i, item in enumerate(estimate.line_items, 1):
        name = _sanitize_table_cell(item.step_name)
        detail = _sanitize_table_cell(item.detail)
        lines.append(f"| {i} | {name} | {item.step_type} | {item.credits:.0f} | {detail} |")
    lines.append(f"| | **Total** | | **{estimate.total_credits:.0f}** | |")
    lines.append("")

    # Section 3: Mermaid sequence diagram
    lines.append("### Credit Flow\n")
    lines.append("```mermaid")
    lines.append("sequenceDiagram")
    lines.append("    participant U as User")
    lines.append("    participant O as Orchestrator")
    lines.append("    participant KS as Knowledge Search")
    lines.append("    participant T as Tools/Agents")

    # Group line items by user turn using PLAN_RECEIVED boundaries
    user_messages: list[str] = []

    # Walk events to build turn boundaries
    plan_positions: list[int] = []
    for event in timeline.events:
        if event.event_type == EventType.USER_MESSAGE:
            msg = (
                event.summary.replace('User: "', "").rstrip('"')
                if event.summary.startswith('User: "')
                else event.summary
            )
            user_messages.append(msg[:50])
        elif event.event_type == EventType.PLAN_RECEIVED:
            plan_positions.append(event.position)

    # Assign line items to turns based on plan positions
    if plan_positions:
        turn_idx = 0
        turns_data: list[tuple[str, list[CreditLineItem]]] = []
        current_items: list[CreditLineItem] = []
        msg_idx = 0

        for item in estimate.line_items:
            # Check if we've passed a plan boundary
            while turn_idx < len(plan_positions) - 1 and item.position >= plan_positions[turn_idx + 1]:
                msg = user_messages[msg_idx] if msg_idx < len(user_messages) else f"Turn {turn_idx + 1}"
                turns_data.append((msg, current_items))
                current_items = []
                turn_idx += 1
                msg_idx += 1
            current_items.append(item)

        msg = user_messages[msg_idx] if msg_idx < len(user_messages) else f"Turn {turn_idx + 1}"
        turns_data.append((msg, current_items))
    else:
        # No plan boundaries — single turn
        msg = user_messages[0] if user_messages else "Conversation"
        turns_data = [(msg, estimate.line_items)]

    for turn_num, (user_msg, items) in enumerate(turns_data, 1):
        if not items:
            continue

        safe_msg = _sanitize_mermaid(user_msg)
        lines.append(f"    U->>O: {safe_msg}")
        lines.append(f"    Note right of O: Plan received (turn {turn_num})")

        turn_credits = 0.0
        for item in items:
            safe_name = _sanitize_mermaid(item.step_name)
            if item.step_type == "generative_answer":
                lines.append(f"    O->>KS: {safe_name}")
                lines.append(f"    Note right of KS: {item.credits:.0f} credits (generative answer)")
                lines.append("    KS-->>O: Results")
            else:
                lines.append(f"    O->>T: {safe_name}")
                lines.append(f"    Note right of T: {item.credits:.0f} credits ({item.step_type})")
                lines.append("    T-->>O: Results")
            turn_credits += item.credits

        lines.append("    O->>U: Response")
        lines.append(f"    Note right of O: Turn {turn_num} total: {turn_credits:.0f} credits")
        lines.append("")

    lines.append(f"    Note over U,T: Session total: {estimate.total_credits:.0f} credits (estimate)")
    lines.append("```\n")

    # Warnings
    if estimate.warnings:
        lines.append("### Estimation Caveats\n")
        for w in estimate.warnings:
            lines.append(f"> - {w}")

    return "\n".join(lines)

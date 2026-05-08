from models import (
    BotProfile,
    ConversationTimeline,
    CreditEstimate,
    CreditLineItem,
    EventType,
    InstructionDiff,
)

from ._helpers import (
    _sanitize_mermaid,
    _sanitize_table_cell,
    empty_section_stub,
)
from model_comparison import build_comparison_markdown
from .knowledge import render_knowledge_search_section
from .tools import render_tool_analysis
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
    render_topic_settings_explained,
    render_trigger_overlaps,
)
from .timeline_render import (
    render_gantt_chart,
    render_mermaid_sequence,
    render_orchestrator_reasoning,
    render_timeline,
)


def render_instruction_drift(diff: InstructionDiff) -> str:
    """Render instruction drift warning section."""
    lines = [
        "## \u26a0\ufe0f Instruction Drift Detected\n",
        f"Instructions have changed since last analysis (change ratio: {diff.change_ratio:.0%}).\n",
    ]
    if diff.unified_diff:
        lines.append("```diff")
        lines.append(diff.unified_diff)
        lines.append("```\n")
    return "\n".join(lines)


def render_report(
    profile: BotProfile,
    timeline: ConversationTimeline | None = None,
    instruction_diff: InstructionDiff | None = None,
    custom_findings: list[dict] | None = None,
) -> str:
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
    from .knowledge import render_citation_verification_md
    from .sections import (
        render_conversation_flow_md,
        render_conversation_summary_md,
        render_decision_timeline_md,
        render_performance_waterfall_md,
        render_plan_evolution_md,
        render_topic_lifecycles_md,
        render_trigger_analysis_md,
        render_variable_tracker_md,
    )

    if timeline is None:
        timeline = ConversationTimeline()

    # Track sections that legitimately have no data so we can render
    # both an in-place stub and a top-of-report coverage summary.
    skipped: list[tuple[str, str]] = []

    def _stub(title: str, reason: str) -> str:
        skipped.append((title, reason))
        return empty_section_stub(title, reason)

    # 1. Heading
    sections = [render_bot_profile(profile)]

    # Compute credit estimate upfront (used in TL;DR and as its own section)
    credit_estimate = estimate_credits(timeline, profile) if timeline.events else None

    # 2. TL;DR
    sections.append(render_tldr(profile, timeline, credit_estimate))

    # 2.05 Reserve a slot for the coverage summary; we fill it after every
    # other section has been built so we know what was rendered vs. skipped.
    coverage_slot = len(sections)
    sections.append("")

    # 2.07 Raw Events parser-audit table — gives the user direct visibility
    # into what the parser saw before any analysis section. If a downstream
    # panel says "no knowledge searches", the user can scroll up and verify
    # that no knowledge-event signatures were actually present.
    raw_events = _render_raw_events(timeline)
    if raw_events:
        sections.append(raw_events)

    # 2.1 Instruction drift warning (if significant)
    if instruction_diff and instruction_diff.is_significant:
        sections.append(render_instruction_drift(instruction_diff))

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

    # Custom rule findings
    if custom_findings:
        cf_lines = ["## Custom Rule Findings\n"]
        for f in custom_findings:
            sev = f.get("severity", "info")
            cat = f.get("category", "")
            text = f.get("text", f.get("message", ""))
            badge = {"fail": "\U0001f534", "warning": "\U0001f7e1", "info": "\U0001f535"}.get(sev, "\u26aa")
            cat_str = f" [{cat}]" if cat else ""
            cf_lines.append(f"- {badge} **{sev}**{cat_str} — {text}")
        cf_lines.append("")
        sections.append("\n".join(cf_lines))
    else:
        sections.append("<!-- custom-rules-insert -->")

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
    else:
        sections.append(_stub("Execution Diagrams", "build_timeline produced 0 timeline events from this dialog"))

    # 7. Conversation trace
    sections.append(render_timeline(timeline, skip_diagrams=True))

    # 7.1 Conversation visual summary
    conv_summary = render_conversation_summary_md(timeline)
    if conv_summary:
        sections.append(conv_summary)
    else:
        sections.append(_stub("Conversation Summary", "no events to compute KPIs from — see Raw Events"))

    # 7.2 Conversation flow (with AUTO/MANUAL binding annotations on
    # plan-step rows when a profile is available).
    conv_flow = render_conversation_flow_md(timeline, profile=profile)
    if conv_flow:
        sections.append(conv_flow)
    else:
        sections.append(_stub("Conversation Flow", "no message or trace events extracted — see Raw Events"))

    # 7.3 Performance Waterfall — between-activity gap-time table
    waterfall = render_performance_waterfall_md(timeline, profile=profile)
    if waterfall:
        sections.append(waterfall)
    else:
        sections.append(
            _stub("Performance Waterfall", "fewer than 2 timed activities — nothing to compare gaps between")
        )

    # 7.4 Variable Tracker — orchestrator tool calls, Topic / Global
    # variable assignments, and topic-level Generative Answer harvesting.
    var_tracker = render_variable_tracker_md(timeline, profile=profile)
    if var_tracker:
        sections.append(var_tracker)
    else:
        sections.append(
            _stub(
                "Variable Tracker",
                "the parser matched no tool-call / variable-assignment / generative-answer signatures in this dialog",
            )
        )

    # 8. Orchestrator reasoning
    reasoning = render_orchestrator_reasoning(timeline)
    if reasoning:
        sections.append(reasoning)
    else:
        sections.append(
            _stub("Orchestrator Reasoning", "the parser found no orchestrator-thinking events in this dialog")
        )

    # 8.1 Orchestrator decision timeline
    decision_timeline = render_decision_timeline_md(timeline)
    if decision_timeline:
        sections.append(decision_timeline)
    else:
        sections.append(_stub("Orchestrator Decision Timeline", "no user messages or plan/step events to sequence"))

    # 8.2 Plan evolution
    plan_evo = render_plan_evolution_md(timeline)
    if plan_evo:
        sections.append(plan_evo)
    else:
        sections.append(_stub("Plan Evolution", "fewer than 2 plans received — need ≥2 to compare"))

    # 8.3 Topic lifecycles
    topic_lc = render_topic_lifecycles_md(timeline)
    if topic_lc:
        sections.append(topic_lc)
    else:
        sections.append(_stub("Topic Lifecycles", "no STEP_TRIGGERED events extracted — see Raw Events"))

    # 8.4 Failure Diagnosis (AgentRx-style heuristic pass — LLM judge is
    # opt-in via the Reflex Diagnose button; CLI runs heuristics only).
    if timeline.events:
        from diagnosis import diagnose
        from .diagnosis import render_diagnosis_md

        report = diagnose(profile, timeline, llm=False)
        diag_md = render_diagnosis_md(report)
        if diag_md:
            sections.append(diag_md)

    # --- Inventories (static capabilities) ---

    # 10. Topic Inventory
    sections.append(render_topic_inventory(profile))

    # 11. Tool Inventory
    tool_inv = render_tool_inventory(profile)
    if tool_inv:
        sections.append(tool_inv)
    else:
        sections.append(_stub("Tool Inventory", "no `tool_type` components in this bot's `botContent.yml`"))

    # 11.5 Tool Call Analysis (runtime — from dialog.json)
    if timeline.tool_calls:
        tool_analysis = render_tool_analysis(timeline, profile)
        if tool_analysis:
            sections.append(tool_analysis)
        else:
            sections.append(_stub("Tool Call Analysis", "tool calls present but produced no analysable detail"))
    else:
        sections.append(
            _stub(
                "Tool Call Analysis",
                "no STEP_TRIGGERED / STEP_FINISHED runtime events extracted — see Raw Events",
            )
        )

    # 12. Integration Map
    int_map = render_integration_map(profile)
    if int_map:
        sections.append(int_map)

    # 12.1 Model Comparison
    model_cmp = build_comparison_markdown(profile)
    if model_cmp:
        sections.append(model_cmp)

    # 13. Topic graph
    topic_graph = render_topic_graph(profile)
    if topic_graph:
        sections.append(topic_graph)

    # 13.5 Topic Settings Explained — per-action walk with KB-sourced summaries
    settings_explained = render_topic_settings_explained(profile)
    if settings_explained:
        sections.append(settings_explained)

    # 14. Knowledge Inventory
    ka = render_knowledge_inventory(profile)
    if ka:
        sections.append(ka)

    # 14.5 Knowledge Coverage
    kcm = render_knowledge_coverage(profile)
    if kcm:
        sections.append(kcm)

    # 14.6 Knowledge Source Details
    ksd = render_knowledge_source_details(profile)
    if ksd:
        sections.append(ksd)

    # --- Deep dive (runtime trace detail) ---

    # 15. Topic details + knowledge search
    topic_details = render_topic_details(profile, timeline)
    if topic_details:
        sections.append(topic_details)
    else:
        sections.append(_stub("Topic Details", "no topics with external calls and no triggered-topic coverage data"))

    sections.append(render_knowledge_search_section(timeline, profile=profile))

    # 15.05 Citation Verification — flat audit table of every (trace,
    # citation) pair with answer / completion / moderation / provenance
    # flags. Mirrors the dynamic Knowledge tab's panel.
    citation_audit = render_citation_verification_md(timeline)
    if citation_audit:
        sections.append(citation_audit)
    else:
        sections.append(
            _stub(
                "Citation Verification",
                "the parser matched no `valueType=GenerativeAnswersSupportData` events — if your conversation used"
                " knowledge, check Raw Events above for the event signature it shipped under",
            )
        )

    # 15.1 Trigger phrase analysis
    trigger_analysis = render_trigger_analysis_md(timeline, profile)
    if trigger_analysis:
        sections.append(trigger_analysis)
    else:
        sections.append(_stub("Trigger Phrase Analysis", "no user messages to match against trigger phrases"))

    # 16. MCS Credit Estimate (last section)
    credit_section = render_credit_estimate(credit_estimate, timeline)
    if credit_section:
        sections.append(credit_section)

    sections[coverage_slot] = _render_coverage_summary(sections, skipped, coverage_slot)

    return "\n".join(sections)


def _render_coverage_summary(sections: list[str], skipped: list[tuple[str, str]], slot: int) -> str:
    """Build the report-coverage summary that goes near the top.

    `sections` already contains everything else; `slot` is the index of the
    placeholder we wrote earlier and excludes from the count.
    """
    rendered_count = sum(1 for i, s in enumerate(sections) if i != slot and s)
    total = rendered_count + len(skipped)
    lines = [
        "## Report Coverage\n",
        f"**{rendered_count} of {total} sections rendered.** {len(skipped)} stubbed — the parser found no events matching their patterns.\n",
        "_See **Raw Events** below for the full list of event types the parser saw, and which ones it recognised. If a section is stubbed but you expected data, the parser may need to learn a new event signature._\n",
    ]
    if skipped:
        lines.append("| Section | Why it stubbed |")
        lines.append("| --- | --- |")
        for title, reason in skipped:
            lines.append(f"| {_sanitize_table_cell(title)} | {_sanitize_table_cell(reason)} |")
        lines.append("")
    else:
        lines.append("_All sections rendered with data._\n")
    return "\n".join(lines)


def _render_raw_events(timeline: ConversationTimeline) -> str:
    """Render the parser-audit table — what valueTypes/actionTypes/attachments
    the parser saw and whether it recognised each one.

    This is the user-facing version of `parser.build_raw_event_index`. It
    sits near the top of the report so the user can verify what the parser
    extracted before reading any analysis section.
    """
    idx = timeline.raw_event_index or {}
    if not idx or not (idx.get("value_types") or idx.get("action_types")):
        return ""

    lines = [
        "## Raw Events (parser audit)\n",
        f"{len(timeline.events)} timeline events extracted. Below: every event-type signature in the source dialog, "
        "with the parser's recognition status. Anything marked ❌ is the parser drifting from the export format — "
        "we'll need to teach it the new signature.\n",
    ]

    vts = idx.get("value_types", [])
    if vts:
        lines.append("### `valueType` / event name\n")
        lines.append("| name | count | recognised | mapped to |")
        lines.append("| --- | ---: | :---: | --- |")
        for r in vts:
            mark = "✅" if r["recognised"] else "❌"
            lines.append(
                f"| `{_sanitize_table_cell(r['name'])}` | {r['count']} | {mark} | {_sanitize_table_cell(r['mapped_to'] or '—')} |"
            )
        lines.append("")

    ats = idx.get("action_types", [])
    if ats:
        lines.append("### `actionType` (inside `DialogTracingInfo.actions[]`)\n")
        lines.append("| name | count | recognised | mapped to |")
        lines.append("| --- | ---: | :---: | --- |")
        for r in ats:
            mark = "✅" if r["recognised"] else "❌"
            lines.append(
                f"| `{_sanitize_table_cell(r['name'])}` | {r['count']} | {mark} | {_sanitize_table_cell(r['mapped_to'] or 'generic trace')} |"
            )
        lines.append("")

    aks = idx.get("attachment_kinds", [])
    if aks:
        lines.append("### Attachment content types\n")
        lines.append("| contentType | count |")
        lines.append("| --- | ---: |")
        for r in aks:
            lines.append(f"| `{_sanitize_table_cell(r['name'])}` | {r['count']} |")
        lines.append("")

    return "\n".join(lines)


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

    # Tool call analysis (runtime)
    if timeline.tool_calls:
        tool_analysis = render_tool_analysis(timeline)
        if tool_analysis:
            sections.append(tool_analysis)

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

"""Renderers for conversation analysis features."""

from __future__ import annotations

from conversation_analysis import (
    AlignmentReport,
    DeadCodeReport,
    DelegationReport,
    KnowledgeEffectivenessReport,
    LatencyReport,
    PlanDiffReport,
    ResponseQualityReport,
    TurnEfficiencyReport,
)


# ---------------------------------------------------------------------------
# Feature 1: Turn Efficiency
# ---------------------------------------------------------------------------


def render_turn_efficiency(report: TurnEfficiencyReport) -> str:
    """Render turn efficiency analysis as markdown."""
    if not report.turns:
        return ""

    lines: list[str] = []
    lines.append("### Turn Efficiency Analysis")
    lines.append("")

    # Summary
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Turns | {len(report.turns)} |")
    lines.append(f"| Avg Plans/Turn | {report.avg_plans_per_turn:.1f} |")
    lines.append(f"| Avg Tools/Turn | {report.avg_tools_per_turn:.1f} |")
    lines.append(f"| Avg Thinking Ratio | {report.avg_thinking_ratio:.0%} |")
    lines.append(f"| Inefficient Turns | {report.inefficient_turn_count} |")
    lines.append("")

    # Per-turn table
    lines.append("| Turn | User Message | Plans | Tools | Searches | Thinking | Total | Flags |")
    lines.append("| :-- | :-- | --: | --: | --: | --: | --: | :-- |")
    for t in report.turns:
        msg = t.user_message.replace("|", "\\|")[:60]
        flags = ", ".join(t.flags) if t.flags else "—"
        lines.append(
            f"| {t.turn_index} | {msg} | {t.plan_count} | {t.tool_call_count} | "
            f"{t.knowledge_search_count} | {t.thinking_ms:.0f}ms | {t.total_ms:.0f}ms | {flags} |"
        )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 2: Dead Code Detection
# ---------------------------------------------------------------------------


def render_dead_code(report: DeadCodeReport) -> str:
    """Render dead code detection results as markdown."""
    lines: list[str] = []
    lines.append("### Dead Code Detection")
    lines.append("")

    if not report.dead_items:
        lines.append("All components have runtime evidence of being used.")
        lines.append("")
        return "\n".join(lines)

    lines.append(
        f"**{len(report.dead_items)}** of **{report.total_components}** components "
        f"({report.dead_ratio:.0%}) have no runtime evidence of usage."
    )
    lines.append("")

    lines.append("| Kind | Display Name | Schema Name |")
    lines.append("| :-- | :-- | :-- |")
    for item in report.dead_items:
        lines.append(f"| {item.component_kind} | {item.display_name} | `{item.schema_name}` |")
    lines.append("")

    lines.append(
        "> These components were never triggered in the analyzed conversations. "
        "Consider removing them to reduce orchestrator confusion and bot sprawl."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 3: Plan Diff
# ---------------------------------------------------------------------------


def render_plan_diffs(report: PlanDiffReport) -> str:
    """Render plan diff analysis as markdown."""
    if not report.diffs:
        return ""

    lines: list[str] = []
    lines.append("### Plan Evolution Diffs")
    lines.append("")

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Re-plans | {report.total_replans} |")
    lines.append(f"| Thrashing Detected | {report.thrashing_count} |")
    lines.append(f"| Scope Creep | {report.scope_creep_count} |")
    lines.append("")

    for diff in report.diffs:
        badge = " **THRASHING**" if diff.is_thrashing else ""
        lines.append(f"**Turn {diff.turn_index}**{badge}")
        if diff.orchestrator_ask:
            lines.append(f"> Ask: *{diff.orchestrator_ask}*")
        if diff.added_steps:
            lines.append(f"- Added: {', '.join(f'`{s}`' for s in diff.added_steps)}")
        if diff.removed_steps:
            lines.append(f"- Removed: {', '.join(f'`{s}`' for s in diff.removed_steps)}")
        if not diff.added_steps and not diff.removed_steps:
            lines.append("- Steps reordered (same set)")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 4: Knowledge Source Effectiveness
# ---------------------------------------------------------------------------


def render_knowledge_effectiveness(report: KnowledgeEffectivenessReport) -> str:
    """Render knowledge source effectiveness report as markdown."""
    if not report.sources:
        return ""

    lines: list[str] = []
    lines.append("### Knowledge Source Effectiveness")
    lines.append("")

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Searches | {report.total_searches} |")
    lines.append(f"| Avg Sources/Search | {report.avg_sources_per_search:.1f} |")
    lines.append(f"| Zero-Result Searches | {report.zero_result_searches} |")
    lines.append("")

    lines.append("| Source | Queries | Contributions | Hit Rate | Errors | Avg Results |")
    lines.append("| :-- | --: | --: | --: | --: | --: |")
    for src in report.sources:
        badge = "🟢" if src.hit_rate >= 0.6 else ("🟡" if src.hit_rate >= 0.3 else "🔴")
        lines.append(
            f"| {src.source_name} | {src.query_count} | {src.contribution_count} | "
            f"{badge} {src.hit_rate:.0%} | {src.error_count} | {src.avg_result_count:.1f} |"
        )
    lines.append("")

    # Flag low-performing sources
    low_performers = [s for s in report.sources if s.hit_rate < 0.1 and s.query_count >= 3]
    if low_performers:
        lines.append("> **Low-performing sources** (queried 3+ times, <10% contribution):")
        for s in low_performers:
            lines.append(
                f"> - `{s.source_name}` — queried {s.query_count} times, contributed {s.contribution_count} times"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 5: Response Quality Scorecard
# ---------------------------------------------------------------------------


def render_response_quality(report: ResponseQualityReport) -> str:
    """Render response quality scorecard as markdown."""
    if not report.items:
        return ""

    lines: list[str] = []
    lines.append("### Response Quality Scorecard")
    lines.append("")

    total = report.grounded_count + report.ungrounded_count
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Responses | {total} |")
    lines.append(f"| Grounded | {report.grounded_count} |")
    lines.append(f"| Ungrounded | {report.ungrounded_count} |")
    lines.append(f"| High Hallucination Risk | {report.high_risk_count} |")
    lines.append(f"| Swallowed Errors | {report.swallowed_error_count} |")
    lines.append("")

    # Only show flagged items
    flagged = [item for item in report.items if item.flags]
    if flagged:
        lines.append("| Turn | Risk | Source | Flags |")
        lines.append("| --: | :-- | :-- | :-- |")
        for item in flagged:
            risk_badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.hallucination_risk, "⚪")
            flags = "; ".join(item.flags)
            lines.append(
                f"| {item.turn_index} | {risk_badge} {item.hallucination_risk} | {item.grounding_source} | {flags} |"
            )
        lines.append("")
    else:
        lines.append("All responses appear grounded.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 6: Multi-Agent Delegation
# ---------------------------------------------------------------------------


def render_delegation_analysis(report: DelegationReport) -> str:
    """Render multi-agent delegation analysis as markdown."""
    if not report.configured_agents and not report.delegations:
        return ""

    lines: list[str] = []
    lines.append("### Multi-Agent Delegation Analysis")
    lines.append("")

    lines.append(f"**Configured agents:** {len(report.configured_agents)}")
    if report.configured_agents:
        lines.append(f"  {', '.join(f'`{a}`' for a in report.configured_agents)}")
    lines.append("")

    if report.dead_agents:
        lines.append(f"**Dead agents** (never delegated to): {', '.join(f'`{a}`' for a in report.dead_agents)}")
        lines.append("")

    if report.failing_agents:
        lines.append(f"**Always-failing agents:** {', '.join(f'`{a}`' for a in report.failing_agents)}")
        lines.append("")

    if report.delegations:
        lines.append("| Agent | Type | State | Duration | Reasoning |")
        lines.append("| :-- | :-- | :-- | --: | :-- |")
        for d in report.delegations:
            state_badge = {"completed": "✅", "failed": "❌", "inProgress": "⏳"}.get(d.state, "⚪")
            thought = (d.thought or "—")[:80].replace("|", "\\|")
            lines.append(
                f"| {d.agent_name} | {d.tool_type or '—'} | {state_badge} {d.state} | "
                f"{d.duration_ms:.0f}ms | {thought} |"
            )
        lines.append("")

    # Per-agent stats
    if report.agent_stats:
        lines.append("**Agent Statistics:**")
        lines.append("")
        lines.append("| Agent | Calls | Successes | Failures | Success Rate |")
        lines.append("| :-- | --: | --: | --: | --: |")
        for name, stats in report.agent_stats.items():
            calls = stats["calls"]
            rate = stats["successes"] / calls * 100 if calls > 0 else 0
            lines.append(f"| {name} | {calls} | {stats['successes']} | {stats['failures']} | {rate:.0f}% |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 7: Latency Bottleneck Heatmap
# ---------------------------------------------------------------------------


def render_latency_heatmap(report: LatencyReport) -> str:
    """Render latency bottleneck analysis as markdown."""
    if not report.turns:
        return ""

    lines: list[str] = []
    lines.append("### Latency Bottleneck Analysis")
    lines.append("")

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Turns Analyzed | {len(report.turns)} |")
    lines.append(f"| Turns with Bottleneck (>50%) | {report.bottleneck_turn_count} |")
    lines.append(f"| Avg Thinking % | {report.avg_thinking_pct:.0f}% |")
    lines.append(f"| Avg Tool Execution % | {report.avg_tool_pct:.0f}% |")
    lines.append("")

    # Per-turn breakdown
    lines.append("| Turn | Message | Total | Thinking | Tools | Knowledge | Other | Bottleneck |")
    lines.append("| --: | :-- | --: | --: | --: | --: | --: | :-- |")
    for t in report.turns:
        msg = t.user_message.replace("|", "\\|")[:40]
        seg_map = {s.category: s for s in t.segments}
        thinking = seg_map.get("thinking")
        tool = seg_map.get("tool")
        knowledge = seg_map.get("knowledge")
        other = seg_map.get("other")
        bottleneck = f"**{t.bottleneck}**" if t.bottleneck else "—"

        think_cell = f"{thinking.duration_ms:.0f}ms ({thinking.percentage:.0f}%)" if thinking else "—"
        tool_cell = f"{tool.duration_ms:.0f}ms ({tool.percentage:.0f}%)" if tool else "—"
        know_cell = f"{knowledge.duration_ms:.0f}ms ({knowledge.percentage:.0f}%)" if knowledge else "—"
        other_cell = f"{other.duration_ms:.0f}ms" if other else "—"

        lines.append(
            f"| {t.turn_index} | {msg} | {t.total_ms:.0f}ms | "
            f"{think_cell} | {tool_cell} | {know_cell} | {other_cell} | {bottleneck} |"
        )
    lines.append("")

    # Mermaid stacked bar chart (using Gantt as approximation)
    if len(report.turns) <= 10:
        lines.append("```mermaid")
        lines.append("gantt")
        lines.append("    title Time Breakdown per Turn")
        lines.append("    dateFormat X")
        lines.append("    axisFormat %s ms")
        for t in report.turns:
            lines.append(f"    section Turn {t.turn_index}")
            offset = 0
            for seg in t.segments:
                dur = max(1, int(seg.duration_ms))
                lines.append(f"    {seg.label} :{offset}, {offset + dur}")
                offset += dur
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature 8: Instruction Alignment
# ---------------------------------------------------------------------------


def render_instruction_alignment(report: AlignmentReport) -> str:
    """Render instruction-to-behavior alignment report as markdown."""
    if report.directives_found == 0:
        return ""

    lines: list[str] = []
    lines.append("### Instruction-to-Behavior Alignment")
    lines.append("")

    score_badge = "🟢" if report.coverage_score >= 0.8 else ("🟡" if report.coverage_score >= 0.5 else "🔴")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Directives Detected | {report.directives_found} |")
    lines.append(f"| Violations Found | {len(report.violations)} |")
    lines.append(f"| Compliance Score | {score_badge} {report.coverage_score:.0%} |")
    lines.append("")

    if report.violations:
        lines.append("| Directive | Violation Type | Evidence |")
        lines.append("| :-- | :-- | :-- |")
        for v in report.violations:
            vtype_badge = {
                "language_mismatch": "🌐",
                "missing_escalation": "⚠️",
                "scope_breach": "🚫",
            }.get(v.violation_type, "❓")
            evidence = v.evidence.replace("|", "\\|")[:80]
            lines.append(f"| {v.directive} | {vtype_badge} {v.violation_type} | {evidence} |")
        lines.append("")
    else:
        lines.append("No violations detected in the analyzed conversation.")
        lines.append("")

    return "\n".join(lines)

"""Tool call analysis — async chain detection, statistics, rendering."""

from __future__ import annotations

from collections import defaultdict

from models import (
    BotProfile,
    ConversationTimeline,
    ToolCall,
    ToolCallChain,
    ToolCallObservation,
    ToolStatistics,
)

from ._helpers import (
    _format_duration,
    _make_participant_id,
    _pct,
    _sanitize_mermaid,
    _sanitize_table_cell,
)


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def detect_async_chains(tool_calls: list[ToolCall]) -> list[ToolCallChain]:
    """Detect async/polling patterns: repeated taskDialogId with shared argument values."""
    by_task = defaultdict(list)
    for tc in tool_calls:
        by_task[tc.task_dialog_id].append(tc)

    chains: list[ToolCallChain] = []
    chain_idx = 0

    for task_id, calls in by_task.items():
        if len(calls) < 2:
            continue

        # Find argument keys whose values are constant across all calls
        if calls[0].arguments:
            shared_keys = [
                k for k in calls[0].arguments if all(c.arguments.get(k) == calls[0].arguments[k] for c in calls[1:])
            ]
        else:
            shared_keys = []

        # Only form a chain if there are shared correlation keys or it's clearly polling
        if not shared_keys and len(calls) < 3:
            continue

        chain_idx += 1
        chain_id = f"chain-{chain_idx}"

        # Extract status progression from observations
        status_progression: list[str] = []
        for c in calls:
            c.chain_id = chain_id
            status = _extract_status(c)
            if status:
                status_progression.append(status)

        total_ms = sum(c.duration_ms for c in calls)

        chains.append(
            ToolCallChain(
                chain_id=chain_id,
                task_dialog_id=task_id,
                display_name=calls[0].display_name,
                calls=calls,
                correlation_keys=shared_keys,
                total_duration_ms=total_ms,
                final_state=calls[-1].state,
                status_progression=status_progression,
            )
        )

    return chains


def compute_tool_statistics(tool_calls: list[ToolCall]) -> list[ToolStatistics]:
    """Compute per-tool aggregate statistics."""
    by_name: dict[str, list[ToolCall]] = defaultdict(list)
    for tc in tool_calls:
        by_name[tc.display_name].append(tc)

    stats: list[ToolStatistics] = []
    for name, calls in sorted(by_name.items()):
        durations = [c.duration_ms for c in calls if c.duration_ms > 0]
        success = sum(1 for c in calls if c.state == "completed")
        failure = sum(1 for c in calls if c.state == "failed")
        total = len(calls)

        stats.append(
            ToolStatistics(
                tool_name=name,
                tool_type=calls[0].tool_type,
                call_count=total,
                success_count=success,
                failure_count=failure,
                success_rate=success / total if total > 0 else 0.0,
                avg_duration_ms=sum(durations) / len(durations) if durations else 0.0,
                min_duration_ms=min(durations) if durations else 0.0,
                max_duration_ms=max(durations) if durations else 0.0,
                total_duration_ms=sum(durations),
            )
        )

    return stats


def build_tool_inventory(profile: BotProfile, tool_calls: list[ToolCall]) -> list[dict]:
    """Cross-reference configured tools (YAML) vs called tools (dialog.json)."""
    # Configured tools from profile
    configured: dict[str, dict] = {}
    for comp in profile.components:
        if comp.tool_type and comp.schema_name:
            configured[comp.schema_name] = {
                "schema_name": comp.schema_name,
                "display_name": comp.display_name,
                "tool_type": comp.tool_type,
                "configured": True,
                "called": False,
                "call_count": 0,
            }

    # Match calls to configured tools
    call_counts: dict[str, int] = defaultdict(int)
    for tc in tool_calls:
        matched = False
        # Direct match
        if tc.task_dialog_id in configured:
            configured[tc.task_dialog_id]["called"] = True
            configured[tc.task_dialog_id]["call_count"] += 1
            matched = True
        # MCP match
        elif tc.task_dialog_id.startswith("MCP:"):
            parts = tc.task_dialog_id.split(":")
            if len(parts) >= 3:
                mcp_schema = ":".join(parts[1:-1])
                for schema in configured:
                    if mcp_schema == schema or mcp_schema.endswith(f".{schema}"):
                        configured[schema]["called"] = True
                        configured[schema]["call_count"] += 1
                        matched = True
                        break
        if not matched:
            call_counts[tc.task_dialog_id] += 1

    rows = list(configured.values())

    # Add unconfigured but called tools
    for task_id, count in call_counts.items():
        rows.append(
            {
                "schema_name": task_id,
                "display_name": task_id.split(".")[-1] if "." in task_id else task_id,
                "tool_type": "Unknown",
                "configured": False,
                "called": True,
                "call_count": count,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_tool_call_flow(tool_calls: list[ToolCall], chains: list[ToolCallChain]) -> str:
    """Generate Mermaid sequence diagram for tool invocations."""
    if not tool_calls:
        return ""

    chain_lookup = {c.chain_id: c for c in chains}
    seen_participants: set[str] = set()
    lines = ["```mermaid", "sequenceDiagram"]
    lines.append("    participant Orch as Orchestrator")

    # Collect participants
    for tc in tool_calls:
        pid = _make_participant_id(tc.display_name)
        if pid not in seen_participants:
            seen_participants.add(pid)
            label = _sanitize_mermaid(tc.display_name)
            type_suffix = f" ({tc.tool_type})" if tc.tool_type else ""
            lines.append(f"    participant {pid} as {label}{type_suffix}")

    # Render calls
    active_chain: str | None = None
    for tc in tool_calls:
        pid = _make_participant_id(tc.display_name)
        status = "OK" if tc.state == "completed" else "FAIL"
        duration = _format_duration(tc.duration_ms) if tc.duration_ms > 0 else ""

        # Chain loop markers
        if tc.chain_id and tc.chain_id != active_chain:
            if active_chain:
                lines.append("    end")
            chain = chain_lookup.get(tc.chain_id)
            chain_label = f"Async chain ({len(chain.calls)} calls)" if chain else "Chain"
            lines.append(f"    loop {_sanitize_mermaid(chain_label)}")
            active_chain = tc.chain_id
        elif not tc.chain_id and active_chain:
            lines.append("    end")
            active_chain = None

        thought_note = ""
        if tc.thought:
            short = _sanitize_mermaid(tc.thought[:60])
            thought_note = f"    Note right of Orch: {short}"

        lines.append(f"    Orch->>+{pid}: {_sanitize_mermaid(tc.display_name)}")
        if thought_note:
            lines.append(thought_note)
        lines.append(f"    {pid}-->>-Orch: {status} {duration}")

    if active_chain:
        lines.append("    end")

    lines.append("```")
    return "\n".join(lines)


def render_tool_statistics_section(stats: list[ToolStatistics], total_elapsed_ms: float) -> str:
    """Render per-tool statistics as a markdown table."""
    if not stats:
        return ""

    total_tool_ms = sum(s.total_duration_ms for s in stats)
    lines = [
        "### Tool Statistics",
        "",
        f"Total tool execution time: **{_format_duration(total_tool_ms)}** "
        f"({_pct(total_tool_ms, total_elapsed_ms)} of conversation)",
        "",
        "| Tool | Type | Calls | Success | Avg | Min | Max | Total |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for s in stats:
        rate = f"{s.success_rate:.0%}"
        lines.append(
            f"| {_sanitize_table_cell(s.tool_name)} "
            f"| {s.tool_type or '—'} "
            f"| {s.call_count} "
            f"| {rate} "
            f"| {_format_duration(s.avg_duration_ms)} "
            f"| {_format_duration(s.min_duration_ms)} "
            f"| {_format_duration(s.max_duration_ms)} "
            f"| {_format_duration(s.total_duration_ms)} |"
        )

    return "\n".join(lines)


def render_async_chains_section(chains: list[ToolCallChain]) -> str:
    """Render async chain summaries."""
    if not chains:
        return ""

    lines = ["### Async / Polling Chains", ""]
    for chain in chains:
        progression = " → ".join(chain.status_progression) if chain.status_progression else "—"
        lines.append(
            f"**{_sanitize_table_cell(chain.display_name)}** — {len(chain.calls)} calls, {_format_duration(chain.total_duration_ms)}"
        )
        lines.append(f"- Status: {progression}")
        if chain.correlation_keys:
            lines.append(f"- Correlation keys: `{'`, `'.join(chain.correlation_keys)}`")
        lines.append(f"- Final state: {chain.final_state}")
        lines.append("")

    return "\n".join(lines)


def render_tool_reasoning_section(tool_calls: list[ToolCall]) -> str:
    """Render orchestrator thought per tool selection."""
    calls_with_thought = [tc for tc in tool_calls if tc.thought]
    if not calls_with_thought:
        return ""

    lines = [
        "### Orchestrator Reasoning",
        "",
        "| # | Tool | Thought |",
        "| ---: | --- | --- |",
    ]

    for i, tc in enumerate(calls_with_thought, 1):
        thought = _sanitize_table_cell(tc.thought or "")
        lines.append(f"| {i} | {_sanitize_table_cell(tc.display_name)} | {thought} |")

    return "\n".join(lines)


def render_tool_call_details(tool_calls: list[ToolCall]) -> str:
    """Render per-call detail with arguments, observation summary, raw JSON."""
    if not tool_calls:
        return ""

    lines = ["### Tool Call Details", ""]

    for i, tc in enumerate(tool_calls, 1):
        status_icon = "✅" if tc.state == "completed" else "❌"
        duration = _format_duration(tc.duration_ms) if tc.duration_ms > 0 else "—"
        tool_type = f" ({tc.tool_type})" if tc.tool_type else ""

        lines.append(f"#### {i}. {tc.display_name}{tool_type} {status_icon} {duration}")
        lines.append("")

        if tc.thought:
            lines.append(f"> {tc.thought}")
            lines.append("")

        if tc.arguments:
            lines.append("**Arguments:**")
            lines.append("")
            lines.append("| Key | Value |")
            lines.append("| --- | --- |")
            for k, v in tc.arguments.items():
                lines.append(f"| `{k}` | {_sanitize_table_cell(str(v))} |")
            lines.append("")

        if tc.observation:
            summary = _summarize_observation(tc.observation)
            if summary:
                lines.append(f"**Response:** {summary}")
                lines.append("")

            if tc.observation.raw_json:
                lines.append("<details><summary>Raw JSON</summary>")
                lines.append("")
                lines.append(f"```json\n{tc.observation.raw_json}\n```")
                lines.append("")
                lines.append("</details>")
                lines.append("")

        if tc.error:
            lines.append(f"**Error:** {tc.error}")
            lines.append("")

    return "\n".join(lines)


def render_tool_analysis(timeline: ConversationTimeline, profile: BotProfile | None = None) -> str:
    """Top-level tool call analysis rendering — returns complete markdown section."""
    if not timeline.tool_calls:
        return ""

    chains = detect_async_chains(timeline.tool_calls)
    stats = compute_tool_statistics(timeline.tool_calls)

    sections = ["## Tool Call Analysis", ""]
    sections.append(f"**{len(timeline.tool_calls)} tool call(s)** detected in this conversation.")
    if chains:
        sections.append(f" {len(chains)} async chain(s) identified.")
    sections.append("")

    # Tool inventory (only with profile)
    if profile:
        inventory = build_tool_inventory(profile, timeline.tool_calls)
        configured = sum(1 for r in inventory if r["configured"])
        called = sum(1 for r in inventory if r["called"])
        sections.append(f"Configured: {configured} | Called: {called}")
        sections.append("")

    # Mermaid flow diagram
    flow = render_tool_call_flow(timeline.tool_calls, chains)
    if flow:
        sections.append(flow)
        sections.append("")

    # Statistics
    stat_section = render_tool_statistics_section(stats, timeline.total_elapsed_ms)
    if stat_section:
        sections.append(stat_section)
        sections.append("")

    # Async chains
    chain_section = render_async_chains_section(chains)
    if chain_section:
        sections.append(chain_section)
        sections.append("")

    # Orchestrator reasoning
    reasoning = render_tool_reasoning_section(timeline.tool_calls)
    if reasoning:
        sections.append(reasoning)
        sections.append("")

    # Call details
    details = render_tool_call_details(timeline.tool_calls)
    if details:
        sections.append(details)

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Web UI data builder
# ---------------------------------------------------------------------------


def build_tool_call_analysis_data(timeline: ConversationTimeline, profile: BotProfile | None = None) -> dict:
    """Build structured dicts for web UI state population."""
    if not timeline.tool_calls:
        return {
            "kpis": [],
            "stats_rows": [],
            "chain_rows": [],
            "reasoning_rows": [],
            "detail_rows": [],
            "flow_mermaid": "",
            "inventory_rows": [],
        }

    chains = detect_async_chains(timeline.tool_calls)
    stats = compute_tool_statistics(timeline.tool_calls)

    total_tool_ms = sum(s.total_duration_ms for s in stats)

    # KPIs
    kpis = [
        {"label": "Tool Calls", "value": str(len(timeline.tool_calls)), "hint": "Total invocations", "tone": "neutral"},
        {"label": "Unique Tools", "value": str(len(stats)), "hint": "Distinct tools called", "tone": "neutral"},
        {
            "label": "Tool Time",
            "value": _format_duration(total_tool_ms),
            "hint": _pct(total_tool_ms, timeline.total_elapsed_ms) + " of conversation",
            "tone": "neutral",
        },
    ]
    failures = sum(1 for tc in timeline.tool_calls if tc.state == "failed")
    if failures:
        kpis.append({"label": "Failures", "value": str(failures), "hint": "Tool calls that failed", "tone": "negative"})
    if chains:
        kpis.append(
            {"label": "Async Chains", "value": str(len(chains)), "hint": "Polling/retry patterns", "tone": "neutral"}
        )

    # Stats rows
    stats_rows = [
        {
            "tool": s.tool_name,
            "type": s.tool_type or "—",
            "calls": s.call_count,
            "success_rate": f"{s.success_rate:.0%}",
            "success_color": "green" if s.success_rate >= 0.9 else ("amber" if s.success_rate >= 0.7 else "red"),
            "avg_duration": _format_duration(s.avg_duration_ms),
            "total_duration": _format_duration(s.total_duration_ms),
        }
        for s in stats
    ]

    # Chain rows
    chain_rows = [
        {
            "chain_id": c.chain_id,
            "tool": c.display_name,
            "call_count": len(c.calls),
            "call_count_label": f"{len(c.calls)} calls",
            "status_label": " → ".join(c.status_progression) if c.status_progression else "",
            "correlation_label": ", ".join(c.correlation_keys) if c.correlation_keys else "",
            "total_duration": _format_duration(c.total_duration_ms),
            "final_state": c.final_state,
        }
        for c in chains
    ]

    # Reasoning rows
    reasoning_rows = [
        {
            "index": i + 1,
            "tool": tc.display_name,
            "thought": tc.thought or "",
        }
        for i, tc in enumerate(timeline.tool_calls)
        if tc.thought
    ]

    # Detail rows
    detail_rows = [
        {
            "index": i + 1,
            "index_label": f"#{i + 1}",
            "accordion_value": f"tool-{i + 1}",
            "tool": tc.display_name,
            "tool_type": tc.tool_type or "",
            "state": tc.state,
            "duration": _format_duration(tc.duration_ms) if tc.duration_ms > 0 else "—",
            "duration_ms": tc.duration_ms,
            "thought": tc.thought or "",
            "arguments": tc.arguments,
            "arguments_text": "\n".join(f"{k}: {v}" for k, v in tc.arguments.items()) if tc.arguments else "",
            "arguments_count": len(tc.arguments),
            "observation_summary": _summarize_observation(tc.observation) if tc.observation else "",
            "observation_json": tc.observation.raw_json if tc.observation and tc.observation.raw_json else "",
            "error": tc.error or "",
            "chain_id": tc.chain_id or "",
        }
        for i, tc in enumerate(timeline.tool_calls)
    ]

    # Flow mermaid (strip fences for web rendering)
    flow = render_tool_call_flow(timeline.tool_calls, chains)
    flow_mermaid = ""
    if flow:
        flow_lines = flow.strip().split("\n")
        if flow_lines and flow_lines[0].startswith("```"):
            flow_lines = flow_lines[1:]
        if flow_lines and flow_lines[-1].startswith("```"):
            flow_lines = flow_lines[:-1]
        flow_mermaid = "\n".join(flow_lines)

    # Inventory rows (only with profile)
    inventory_rows = []
    if profile:
        inventory = build_tool_inventory(profile, timeline.tool_calls)
        inventory_rows = [
            {
                "name": r["display_name"],
                "schema": r["schema_name"],
                "type": r["tool_type"],
                "configured": r["configured"],
                "called": r["called"],
                "call_count": r["call_count"],
            }
            for r in inventory
        ]

    return {
        "kpis": kpis,
        "stats_rows": stats_rows,
        "chain_rows": chain_rows,
        "reasoning_rows": reasoning_rows,
        "detail_rows": detail_rows,
        "flow_mermaid": flow_mermaid,
        "inventory_rows": inventory_rows,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_status(tc: ToolCall) -> str:
    """Try to extract a status string from a tool call's observation."""
    if not tc.observation or not tc.observation.structured_content:
        return ""
    sc = tc.observation.structured_content
    # Common patterns: status field, Status field
    for key in ("status", "Status", "state", "State"):
        if key in sc and isinstance(sc[key], str):
            return sc[key]
    # Check inside content array
    if tc.observation.content:
        for item in tc.observation.content:
            if isinstance(item, dict):
                for key in ("status", "Status"):
                    if key in item and isinstance(item[key], str):
                        return item[key]
    return ""


def _summarize_observation(obs: ToolCallObservation) -> str:
    """Extract a human-readable summary from an observation."""
    if not obs:
        return ""

    parts: list[str] = []

    if obs.structured_content and isinstance(obs.structured_content, dict):
        sc = obs.structured_content
        # Status
        for key in ("status", "Status"):
            if key in sc:
                parts.append(f"Status: {sc[key]}")
                break
        # SQL query
        for key in ("sql", "SQL", "query", "sql_query"):
            if key in sc and isinstance(sc[key], str):
                sql_preview = sc[key][:100].replace("\n", " ")
                parts.append(f"SQL: `{sql_preview}`")
                break
        # Row count
        for key in ("row_count", "rowCount", "rows"):
            if key in sc:
                val = sc[key]
                if isinstance(val, (int, float)):
                    parts.append(f"Rows: {int(val)}")
                elif isinstance(val, list):
                    parts.append(f"Rows: {len(val)}")
                break
        # Error
        for key in ("error", "Error", "errorMessage"):
            if key in sc and sc[key]:
                parts.append(f"Error: {sc[key]}")
                break

    if parts:
        return " | ".join(parts)

    # Fallback: content array text
    if obs.content:
        for item in obs.content:
            if isinstance(item, dict) and "text" in item:
                return str(item["text"])
            if isinstance(item, str):
                return item

    if obs.raw_json:
        return obs.raw_json

    return ""

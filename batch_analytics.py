import re
from collections import defaultdict

from models import (
    BatchAnalyticsSummary,
    ConversationTimeline,
    EventType,
    FailureMode,
    TopicUsage,
)

_GUID_PATTERN = re.compile(r"[0-9a-f]{8,}")


def _normalize_error(error: str) -> str:
    """Strip numbers and GUIDs from error string for grouping."""
    return _GUID_PATTERN.sub("<ID>", error).strip()


def _is_success_heuristic(timeline: ConversationTimeline) -> bool:
    """Heuristic: no errors + has at least one BOT_MESSAGE event."""
    if timeline.errors:
        return False
    return any(e.event_type == EventType.BOT_MESSAGE for e in timeline.events)


def _has_escalation(timeline: ConversationTimeline) -> bool:
    """Check for STEP_TRIGGERED events with escalation-related topic names."""
    for event in timeline.events:
        if event.event_type == EventType.STEP_TRIGGERED and event.topic_name:
            if re.search(r"escalat|transfer", event.topic_name, re.IGNORECASE):
                return True
    return False


def aggregate_timelines(
    timelines: list[ConversationTimeline],
    metadata_list: list[dict] | None = None,
) -> BatchAnalyticsSummary:
    """Aggregate multiple conversation timelines into a batch summary."""
    count = len(timelines)
    if count == 0:
        return BatchAnalyticsSummary()

    total_elapsed = sum(t.total_elapsed_ms for t in timelines)
    avg_elapsed = total_elapsed / count

    success_count = 0
    escalation_count = 0

    # Topic usage: topic_name -> {count, total_duration, errors}
    topic_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_duration": 0.0, "errors": 0})

    # Failure modes: normalized_pattern -> {count, example_ids}
    failure_groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "example_ids": []})

    for i, timeline in enumerate(timelines):
        meta = metadata_list[i] if metadata_list and i < len(metadata_list) else None

        # Success detection
        if meta:
            outcome = meta.get("session_info", {}).get("outcome")
            if outcome == "Resolved":
                success_count += 1
        elif _is_success_heuristic(timeline):
            success_count += 1

        # Escalation detection
        if _has_escalation(timeline):
            escalation_count += 1

        # Topic usage from STEP_TRIGGERED events
        for event in timeline.events:
            if event.event_type == EventType.STEP_TRIGGERED and event.topic_name:
                stats = topic_stats[event.topic_name]
                stats["count"] += 1
                if event.error:
                    stats["errors"] += 1

        # Match topic durations from phases
        for phase in timeline.phases:
            label = phase.label
            if label in topic_stats:
                topic_stats[label]["total_duration"] += phase.duration_ms

        # Failure mode grouping
        for error in timeline.errors:
            normalized = _normalize_error(error)
            group = failure_groups[normalized]
            group["count"] += 1
            conv_id = timeline.conversation_id or f"timeline-{i}"
            if len(group["example_ids"]) < 3 and conv_id not in group["example_ids"]:
                group["example_ids"].append(conv_id)

    failure_count = count - success_count

    topic_usage = sorted(
        [
            TopicUsage(
                topic_name=name,
                invocation_count=stats["count"],
                avg_duration_ms=(stats["total_duration"] / stats["count"] if stats["count"] > 0 else 0.0),
                error_count=stats["errors"],
            )
            for name, stats in topic_stats.items()
        ],
        key=lambda t: t.invocation_count,
        reverse=True,
    )

    failure_modes = sorted(
        [
            FailureMode(
                error_pattern=pattern,
                count=data["count"],
                example_conversation_ids=data["example_ids"],
            )
            for pattern, data in failure_groups.items()
        ],
        key=lambda f: f.count,
        reverse=True,
    )

    return BatchAnalyticsSummary(
        conversation_count=count,
        avg_elapsed_ms=avg_elapsed,
        success_count=success_count,
        failure_count=failure_count,
        escalation_count=escalation_count,
        success_rate=success_count / count,
        escalation_rate=escalation_count / count,
        topic_usage=topic_usage,
        failure_modes=failure_modes,
        total_credits_estimated=0.0,
        avg_credits_per_conversation=0.0,
    )


def render_batch_report(summary: BatchAnalyticsSummary) -> str:
    """Render a batch analytics summary as a markdown report."""
    lines: list[str] = []

    lines.append("# Batch Analytics Report")
    lines.append("")

    # Overview table
    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Conversations | {summary.conversation_count} |")
    lines.append(f"| Success Rate | {summary.success_rate:.1%} |")
    lines.append(f"| Avg Elapsed Time | {summary.avg_elapsed_ms:.0f} ms |")
    lines.append(f"| Escalation Rate | {summary.escalation_rate:.1%} |")
    lines.append(f"| Successes | {summary.success_count} |")
    lines.append(f"| Failures | {summary.failure_count} |")
    lines.append(f"| Escalations | {summary.escalation_count} |")
    lines.append("")

    # Top 10 topics
    if summary.topic_usage:
        lines.append("## Top Topics by Invocation")
        lines.append("")
        lines.append("| Topic | Invocations | Avg Duration (ms) | Errors |")
        lines.append("|-------|-------------|-------------------|--------|")
        for topic in summary.topic_usage[:10]:
            lines.append(
                f"| {topic.topic_name} | {topic.invocation_count} | {topic.avg_duration_ms:.0f} | {topic.error_count} |"
            )
        lines.append("")

    # Failure modes
    if summary.failure_modes:
        lines.append("## Failure Modes")
        lines.append("")
        lines.append("| Error Pattern | Count | Example Conversations |")
        lines.append("|---------------|-------|-----------------------|")
        for fm in summary.failure_modes:
            examples = ", ".join(fm.example_conversation_ids)
            lines.append(f"| {fm.error_pattern} | {fm.count} | {examples} |")
        lines.append("")

    # Mermaid pie chart
    lines.append("## Conversation Outcomes")
    lines.append("")
    lines.append("```mermaid")
    lines.append("pie title Conversation Outcomes")
    lines.append(f'    "Success" : {summary.success_count}')
    lines.append(f'    "Failure" : {summary.failure_count}')
    lines.append(f'    "Escalation" : {summary.escalation_count}')
    lines.append("```")
    lines.append("")

    return "\n".join(lines)

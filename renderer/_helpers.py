IDLE_THRESHOLD_MS = 5000  # gaps > 5s are shown as idle markers

ACTOR_NAMES: dict[str, str] = {
    "User": "User",
    "AI": "Orchestrator",
    "Bot": "Agent",
    "KS": "Knowledge Search",
    "Conn": "Connectors",
    "QA": "QA Engine",
    "Eval": "Evaluator",
    "Err": "Errors",
    "Sys": "System",
}


def _parse_execution_time_ms(raw: str | None) -> float | None:
    """Parse .NET TimeSpan 'HH:MM:SS.fffffff' to milliseconds."""
    if not raw:
        return None
    import re

    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", raw)
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return (h * 3600 + mi * 60 + s) * 1000


def _format_duration(ms: float) -> str:
    """Format milliseconds to human-readable duration."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds % 60
    return f"{minutes}m {remaining:.1f}s"


def _pct(part: float, total: float) -> str:
    """Calculate percentage string."""
    if total <= 0:
        return "—"
    return f"{(part / total) * 100:.1f}%"


def _sanitize_mermaid(text: str) -> str:
    """Sanitize text for Mermaid diagram labels."""
    # Replace unicode symbols with ASCII-safe equivalents
    text = text.replace("→", "to")
    text = text.replace("—", "-")
    text = text.replace("✓", "OK")
    text = text.replace("✗", "FAIL")
    text = text.replace("⚠", "WARN")
    # Remove characters that are Mermaid syntax tokens
    text = text.replace('"', "")
    text = text.replace("'", "")
    text = text.replace("%", "pct")
    text = text.replace("\n", " ")
    text = text.replace("\r", "")
    text = text.replace("#", "")
    text = text.replace(";", ",")
    text = text.replace(":", " -")
    text = text.replace("[", "")
    text = text.replace("]", "")
    text = text.replace("(", "")
    text = text.replace(")", "")
    text = text.replace("{", "")
    text = text.replace("}", "")
    text = text.replace("|", "")
    text = text.replace("<", "")
    text = text.replace(">", "")
    return text[:80]


def _make_participant_id(name: str) -> str:
    """Create a valid Mermaid participant ID from a name."""
    # Remove spaces and special chars
    clean = "".join(c for c in name if c.isalnum() or c == "_")
    return clean or "Unknown"


def _topic_display(name: str) -> str:
    """Prefix topic names with 'Topic - ' to distinguish them from system actors."""
    pid = _make_participant_id(name)
    if pid in ACTOR_NAMES:
        return ACTOR_NAMES[pid]
    return f"Topic - {name}"


def _sanitize_table_cell(text: str) -> str:
    """Sanitize text for markdown table cells."""
    return text.replace("|", "/").replace("\n", " ").replace("\r", "")


def _parse_timestamp_to_epoch_ms(ts: str) -> int | None:
    """Parse ISO timestamp to epoch milliseconds."""
    if not ts:
        return None
    from datetime import datetime, timezone

    try:
        cleaned = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, OSError):
        return None


def _is_genuine_idle(prev_event: "TimelineEvent", next_event: "TimelineEvent") -> bool:
    """Determine if a gap between two events is genuine idle (waiting for user/human).

    Returns True only when:
    - prev is BOT_MESSAGE or ACTION_SEND_ACTIVITY and next is USER_MESSAGE (user thinking)
    - prev is STEP_TRIGGERED with a "human in the loop" topic (HITL approval wait)
    """
    from models import EventType

    if (
        prev_event.event_type in (EventType.BOT_MESSAGE, EventType.ACTION_SEND_ACTIVITY)
        and next_event.event_type == EventType.USER_MESSAGE
    ):
        return True
    if (
        prev_event.event_type == EventType.STEP_TRIGGERED
        and prev_event.topic_name
        and "human in the loop" in prev_event.topic_name.lower()
    ):
        return True
    return False


def _compute_idle_gaps(events: list["TimelineEvent"]) -> list[tuple[int, int]]:
    """Return (start_epoch_ms, end_epoch_ms) pairs for all idle gaps in timeline."""
    timed = []
    for ev in events:
        ms = _parse_timestamp_to_epoch_ms(ev.timestamp or "")
        if ms is not None:
            timed.append((ms, ev))
    timed.sort(key=lambda x: x[0])
    gaps = []
    for i in range(1, len(timed)):
        gap_ms = timed[i][0] - timed[i - 1][0]
        if gap_ms > IDLE_THRESHOLD_MS and _is_genuine_idle(timed[i - 1][1], timed[i][1]):
            gaps.append((timed[i - 1][0], timed[i][0]))
    return gaps

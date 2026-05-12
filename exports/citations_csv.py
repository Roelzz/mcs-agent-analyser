"""Render `ConversationTimeline.citation_sources` as CSV for download."""

from __future__ import annotations

import csv
import io

from models import ConversationTimeline


CSV_HEADER = [
    "turn_message",
    "completion_state",
    "source_name",
    "source_url",
    "snippet_chars",
    "snippet_text",
]


def render_citations_csv(timeline: ConversationTimeline) -> str:
    """Render `timeline.citation_sources` as a CSV string.

    Columns: turn_message, completion_state (best-effort from
    knowledge_attributions match), source_name, source_url,
    snippet_chars, snippet_text.
    Snippet text is CSV-escaped (quotes doubled, embedded newlines kept).
    Returns a string ready for `rx.download(data=…, filename=…)`.
    """

    # Index attributions by their triggering turn so the completion_state
    # lookup is O(1) per citation. Multiple attributions can share a turn —
    # last one wins, which matches how the timeline renders them.
    completion_by_turn: dict[str, str] = {}
    for attr in timeline.knowledge_attributions:
        if attr.triggering_user_message is None:
            continue
        if attr.completion_state:
            completion_by_turn[attr.triggering_user_message] = attr.completion_state

    buffer = io.StringIO()
    # QUOTE_MINIMAL + the default '"' quotechar handles the embedded newlines
    # and double-quotes that show up in grounded snippet bodies. Excel and
    # numbers both parse this correctly.
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(CSV_HEADER)

    for citation in timeline.citation_sources:
        turn = citation.triggering_user_message or ""
        completion = completion_by_turn.get(turn, "") if turn else ""
        snippet = citation.text or ""
        writer.writerow(
            [
                turn,
                completion,
                citation.name or "",
                citation.url or "",
                len(snippet),
                snippet,
            ]
        )

    return buffer.getvalue()

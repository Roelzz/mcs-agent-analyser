"""Pure-function data builders shared between the dynamic Reflex page
state and the markdown report renderers.

Originally these lived inside `web/state/_upload.py`; factored out so
the report layer (`renderer/report.py`) can reuse them without
importing from the web layer.

Public functions:
- `build_variable_tracker_rows(timeline, profile)` — three card kinds
  (tool_call / variable_assignment / generative_answer) in one
  uniform row list.
- `build_citation_panel_rows(traces)` — flat list of every
  (trace, citation) pair with answer / completion / moderation flags.
"""

from __future__ import annotations

from ._helpers import _format_duration

_VAR_TRACKER_STATE_TONE = {
    "completed": "good",
    "failed": "bad",
    "inProgress": "info",
    "Answered": "good",
    "Answer not Found in Search Results": "warn",
    "No Search Results": "warn",
    "GPT Fallback": "warn",
}


def _empty_var_row() -> dict:
    """Default values so every Variable Tracker row has the same keys
    (Reflex's rx.foreach requires uniform shape across all items)."""
    return {
        "card_kind": "",
        "row_id": "",
        "display_name": "",
        "step_type": "",
        "state": "",
        "state_tone": "neutral",
        "duration": "",
        "timestamp": "",
        "topic_name": "",
        "thought": "",
        "arguments": [],
        "has_arguments": "",
        "output_preview": "",
        "output_full": "",
        "has_output": "",
        "error": "",
        "var_scope": "",
        "var_name": "",
        "var_value": "",
        "ga_original": "",
        "ga_rewritten": "",
        "ga_keywords": "",
        "ga_summary": "",
        "ga_citation_count": "0",
        "ga_output_variable": "",
    }


def _format_clock(ts: str | None) -> str:
    """ISO timestamp -> HH:MM:SS slice."""
    if not ts:
        return ""
    try:
        from datetime import datetime as _dt

        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return _dt.fromisoformat(ts).strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ts[:19]


def _resolve_topic_search_summarize_variables(profile) -> dict[str, str]:
    """Walk each topic's `raw_dialog` for SearchAndSummarizeContent action
    nodes and map topic display name → output variable. Used to attribute a
    generative-answer trace's harvested value to the variable it writes."""
    sink: dict[str, str] = {}
    if profile is None:
        return sink
    for comp in profile.components:
        if comp.kind != "DialogComponent" or not comp.raw_dialog:
            continue

        def _walk(node: object, comp_name: str) -> None:
            if isinstance(node, dict):
                if node.get("kind") == "SearchAndSummarizeContent":
                    v = node.get("variable")
                    if v and comp_name:
                        sink[comp_name] = str(v)
                for sub in node.values():
                    _walk(sub, comp_name)
            elif isinstance(node, list):
                for item in node:
                    _walk(item, comp_name)

        _walk(comp.raw_dialog, comp.display_name)
    return sink


def _tool_call_var_row(tc) -> dict:
    """Variable Tracker row for one orchestrator-invoked tool call."""
    arg_rows = [
        {
            "name": name,
            "value": str(value),
            "auto_filled": "true" if name in tc.auto_filled_argument_names else "",
        }
        for name, value in tc.arguments.items()
    ]
    output_preview = ""
    output_full = ""
    if tc.observation is not None:
        output_full = tc.observation.raw_json or ""
        if tc.observation.structured_content:
            sc = tc.observation.structured_content
            if isinstance(sc, dict):
                keys = list(sc.keys())[:5]
                output_preview = "{" + ", ".join(keys) + (", …" if len(sc) > len(keys) else "") + "}"
            else:
                output_preview = str(sc)[:120]
        elif tc.observation.content:
            first = tc.observation.content[0] if tc.observation.content else None
            if isinstance(first, dict):
                output_preview = (first.get("text") or first.get("content") or "")[:120]
            elif first is not None:
                output_preview = str(first)[:120]
    row = _empty_var_row()
    row.update(
        {
            "card_kind": "tool_call",
            "row_id": f"var-row-tc-{tc.step_id}" if tc.step_id else "",
            "display_name": tc.display_name or tc.task_dialog_id or tc.step_id or "(tool call)",
            "step_type": tc.step_type or "—",
            "state": tc.state or "—",
            "state_tone": _VAR_TRACKER_STATE_TONE.get(tc.state, "info"),
            "duration": _format_duration(tc.duration_ms) if tc.duration_ms else "—",
            "timestamp": _format_clock(tc.finish_timestamp or tc.trigger_timestamp),
            "thought": tc.thought or "",
            "arguments": arg_rows,
            "has_arguments": "true" if arg_rows else "",
            "output_preview": output_preview,
            "output_full": output_full,
            "has_output": "true" if (output_preview or output_full) else "",
            "error": tc.error or "",
        }
    )
    return row


def _variable_assignment_var_row(ev, idx: int) -> dict:
    """Variable Tracker row for a Topic / Global SetVariable event.
    Parses the `{Scope.title()} {var_id} = {value}` summary format from
    timeline.py."""
    summary = ev.summary or ""
    scope = ""
    name = ""
    value = ""
    if " = " in summary:
        left, value = summary.split(" = ", 1)
        left_parts = left.split(" ", 1)
        if len(left_parts) == 2:
            scope, name = left_parts
        else:
            name = left
    row = _empty_var_row()
    row.update(
        {
            "card_kind": "variable_assignment",
            "row_id": f"var-row-va-{idx}",
            "display_name": name or summary,
            "step_type": "Variable",
            "state": "set",
            "state_tone": "info",
            "timestamp": _format_clock(ev.timestamp),
            "var_scope": scope,
            "var_name": name,
            "var_value": value,
        }
    )
    return row


def _generative_answer_var_row(trace, idx: int, topic_to_var: dict[str, str]) -> dict:
    """Variable Tracker row for a topic-level Generative Answer trace.
    Cross-resolves the topic's SearchAndSummarizeContent output variable so
    the user can see which Topic/Global slot the generated answer fills."""
    output_var = topic_to_var.get(trace.topic_name or "", "")
    row = _empty_var_row()
    row.update(
        {
            "card_kind": "generative_answer",
            "row_id": f"var-row-ga-{idx}",
            "display_name": trace.topic_name or "Generative Answer",
            "step_type": "Topic Generative Answer",
            "state": trace.gpt_answer_state or "—",
            "state_tone": _VAR_TRACKER_STATE_TONE.get(trace.gpt_answer_state or "", "info"),
            "timestamp": _format_clock(trace.timestamp),
            "topic_name": trace.topic_name or "",
            "ga_original": trace.original_message or "",
            "ga_rewritten": trace.rewritten_message or "",
            "ga_keywords": trace.rewritten_keywords or "",
            "ga_summary": trace.summary_text or trace.text_summary or "",
            "ga_citation_count": str(len(trace.citations)),
            "ga_output_variable": output_var,
        }
    )
    return row


def build_citation_panel_rows(traces) -> list[dict]:
    """Flat audit list of every (trace, citation) pair across the
    conversation. Each row carries the trace's answer / completion state
    and content moderation / provenance flags so the user can audit
    grounding from a single table without drilling into each trace card.

    Used by the Citation Verification panel on the Knowledge tab AND
    by the markdown report's Citation Verification section.
    """
    panel: list[dict] = []
    for trace_idx, trace in enumerate(traces, 1):
        if not trace.citations:
            continue
        answer_state = trace.gpt_answer_state or "—"
        completion_state = trace.completion_state or "—"
        if answer_state == "Answered":
            ans_tone = "good"
        elif answer_state in (
            "Answer not Found in Search Results",
            "GPT Fallback",
            "No Search Results",
        ):
            ans_tone = "warn"
        else:
            ans_tone = "neutral"
        moderation = "Yes" if trace.performed_content_moderation else "No"
        provenance = "Yes" if trace.performed_content_provenance else "No"
        for cit_idx, c in enumerate(trace.citations, 1):
            snippet = (c.snippet or "").replace("\r", "")
            panel.append(
                {
                    "citation_id": f"T{trace_idx}·C{cit_idx}",
                    "trace_topic": trace.topic_name or "—",
                    "title": c.title or c.url or f"Citation {cit_idx}",
                    "url": c.url or "",
                    "snippet": snippet,
                    "answer_state": answer_state,
                    "answer_state_tone": ans_tone,
                    "completion_state": completion_state,
                    "moderation": moderation,
                    "moderation_tone": "good" if moderation == "Yes" else "neutral",
                    "provenance": provenance,
                    "provenance_tone": "good" if provenance == "Yes" else "neutral",
                }
            )
    return panel


def build_variable_tracker_rows(timeline, profile=None) -> list[dict]:
    """Unified Variable Tracker row list, time-sorted, covering three card
    kinds: orchestrator tool calls, Topic/Global variable assignments, and
    topic-level Generative Answer traces. All rows share `_empty_var_row`'s
    keys so rx.foreach over the mixed list stays well-typed; the UI branches
    on `card_kind`."""
    from models import EventType

    topic_to_var = _resolve_topic_search_summarize_variables(profile)
    rows: list[dict] = []
    for tc in timeline.tool_calls:
        if tc.task_dialog_id == "P:UniversalSearchTool":
            continue
        rows.append(_tool_call_var_row(tc))
    for idx, ev in enumerate(timeline.events):
        if ev.event_type == EventType.VARIABLE_ASSIGNMENT:
            rows.append(_variable_assignment_var_row(ev, idx))
    for idx, trace in enumerate(timeline.generative_answer_traces):
        rows.append(_generative_answer_var_row(trace, idx, topic_to_var))
    rows.sort(key=lambda r: (r.get("timestamp") or ""))
    return rows

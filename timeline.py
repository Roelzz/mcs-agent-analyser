import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from models import (
    BotProfile,
    ConversationTimeline,
    CreditEstimate,
    CreditLineItem,
    CustomSearchStep,
    EventType,
    ExecutionPhase,
    GenerativeAnswerCitation,
    GenerativeAnswerTrace,
    KnowledgeSearchInfo,
    SearchResult,
    TimelineEvent,
    ToolCall,
    ToolCallObservation,
)


# Standard UUID v4 pattern — used as a last-resort fallback to pull the
# conversation id out of a bot text reply (e.g. "Conversation ID:
# ed082483-aa8e-47c7-a8fd-a7225d26c37b") when the export shape doesn't
# carry it as a structured field.
_UUID_IN_TEXT_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


@dataclass
class _TimelineState:
    """Mutable accumulator for build_timeline processing."""

    events: list[TimelineEvent] = field(default_factory=list)
    phases: list[ExecutionPhase] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    knowledge_searches: list[KnowledgeSearchInfo] = field(default_factory=list)
    custom_search_steps: list[CustomSearchStep] = field(default_factory=list)
    pending_ks_query: dict | None = None
    pending_ks_info: KnowledgeSearchInfo | None = None
    pending_ks_thought: str | None = None
    pending_ks_execution_time: str | None = None
    pending_ks_results: list[SearchResult] = field(default_factory=list)
    pending_ks_errors: list[str] = field(default_factory=list)
    bot_name: str = ""
    conversation_id: str = ""
    user_query: str = ""
    latest_user_text: str | None = None
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    step_triggers: dict[str, tuple[str, str]] = field(default_factory=dict)  # step_id -> (ts, type)
    step_trigger_thoughts: dict[str, str | None] = field(default_factory=dict)  # step_id -> thought
    tool_display_names: dict[str, str] = field(default_factory=dict)
    pending_custom_searches: dict[str, CustomSearchStep] = field(default_factory=dict)
    pending_tool_args: dict[str, dict[str, str]] = field(default_factory=dict)  # step_id -> arguments
    # step_id → list of argument names that were AUTO-filled by the
    # orchestrator (vs. MANUAL bindings authored in the YAML). Sourced
    # from `DynamicPlanStepBindUpdate.value.autoFilledArguments`.
    pending_auto_filled: dict[str, list[str]] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    generative_answer_traces: list[GenerativeAnswerTrace] = field(default_factory=list)
    last_step_topic: str | None = None  # most recent in-progress topic, for trace attribution
    # attempts within the current user turn — reset to 0 on each USER_MESSAGE
    turn_attempt_count: int = 0
    last_attempt_state: str | None = None  # gptAnswerState of the most recent attempt, used as retry reason


def _parse_timestamp(ts: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts:
        return None
    try:
        # Handle .NET-style timestamps with 7 fractional digits
        ts = ts.rstrip("Z").rstrip("+00:00")
        if "+" in ts and ts.count("+") > 0:
            # Has timezone offset like +00:00
            parts = ts.rsplit("+", 1)
            ts_part = parts[0]
        else:
            ts_part = ts

        # Truncate fractional seconds to 6 digits (Python max)
        if "." in ts_part:
            main, frac = ts_part.split(".", 1)
            frac = frac[:6]
            ts_part = f"{main}.{frac}"

        return datetime.fromisoformat(ts_part).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _epoch_to_iso(epoch_ms: int | float | None) -> str | None:
    """Convert epoch milliseconds to ISO string."""
    if epoch_ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _coerce_timestamp(value: object) -> str | None:
    """Normalise a timestamp field to an ISO string.

    Different dialog.json shapes carry timestamps as ISO strings, Unix
    epoch seconds, or epoch milliseconds. Some Dataverse-style transcripts
    also pair a `timestamp` (seconds, int) with a `timestampMs` (ms, int).
    Always emit an ISO string so `TimelineEvent.timestamp: str | None`
    validates regardless of source format.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    if isinstance(value, bool):  # bools are ints in Python; reject them
        return None
    if isinstance(value, (int, float)):
        # Heuristic: ≥10^12 is milliseconds, otherwise seconds. Year 2001 in
        # seconds is ≈10^9; year 33658 in seconds is ≈10^12, well past anything
        # we'd see as a real epoch-seconds value.
        epoch_ms = value if value >= 1e12 else value * 1000
        return _epoch_to_iso(epoch_ms)
    return None


def _get_timestamp(activity: dict) -> str | None:
    """Get the best available timestamp from an activity, normalised to ISO.

    Preference order:
      1. `timestampMs` (high-precision millisecond field, when present)
      2. `timestamp`   (ISO string OR epoch seconds/ms — coerced)
      3. `channelData["webchat:internal:received-at"]` (ms epoch fallback)
    """
    for key in ("timestampMs", "timestamp"):
        coerced = _coerce_timestamp(activity.get(key))
        if coerced:
            return coerced
    channel_data = activity.get("channelData") or {}
    return _coerce_timestamp(channel_data.get("webchat:internal:received-at"))


def _normalize_role(value: object) -> str:
    """Normalise an activity's `from.role` to the string vocabulary the
    timeline classifier expects: ``"bot"``, ``"user"``, or ``""``.

    Different `dialog.json` shapes encode the role differently:

    - **Bot-Framework-style** dialog exports (and the chat-bot test transcripts
      Coolify users tend to paste): integer enum where ``0`` = bot and
      ``1`` = user.
    - **Modern transcript exports**: already a string (``"bot"``, ``"user"``,
      ``"channel"``).
    - **Some shapes**: stringified int (``"0"``, ``"1"``).

    `parse_transcript_json` (transcript.py) already does this normalisation
    for the transcript-only upload path, but `parse_dialog_json` (parser.py)
    did not — meaning bot/user messages were silently dropped from the
    timeline when the dialog.json carried int-encoded roles. Doing the
    normalisation here, in the single consumer, fixes both parser paths
    in one place.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        # bool is a subclass of int — guard against it
        return ""
    if isinstance(value, int):
        if value == 0:
            return "bot"
        if value == 1:
            return "user"
        return ""
    if isinstance(value, str):
        s = value.strip()
        if s == "0":
            return "bot"
        if s == "1":
            return "user"
        return s
    return ""


def _extract_adaptive_card_text(attachments: list) -> str:
    """Extract readable text from Adaptive Card attachments."""
    texts: list[str] = []

    def _extract_from_elements(elements: list) -> None:
        for el in elements:
            if len(texts) >= 2:
                return
            if el.get("type") == "TextBlock" and el.get("text"):
                texts.append(el["text"])
            # Recurse into containers and column sets
            for child_key in ("items", "columns", "body"):
                children = el.get(child_key, []) or []
                if children:
                    _extract_from_elements(children)

    for att in attachments:
        if len(texts) >= 2:
            break
        content = att.get("content", {}) or {}
        body = content.get("body", []) or []
        _extract_from_elements(body)

    if texts:
        combined = " | ".join(texts)
        return combined[:150] + "..." if len(combined) > 150 else combined
    return "[Adaptive Card]"


def _ms_between(start: str | None, end: str | None) -> float:
    """Calculate milliseconds between two ISO timestamps."""
    dt_start = _parse_timestamp(start)
    dt_end = _parse_timestamp(end)
    if dt_start and dt_end:
        return (dt_end - dt_start).total_seconds() * 1000
    return 0.0


def _finalize_knowledge_search(state: _TimelineState) -> None:
    """Flush pending knowledge search state into a KnowledgeSearchInfo and append it."""
    if state.pending_ks_info:
        if state.pending_ks_execution_time is not None:
            state.pending_ks_info.execution_time = state.pending_ks_execution_time
            state.pending_ks_info.search_results = state.pending_ks_results
            state.pending_ks_info.search_errors = state.pending_ks_errors
        state.knowledge_searches.append(state.pending_ks_info)
        state.pending_ks_info = None
        state.pending_ks_execution_time = None
        state.pending_ks_results = []
        state.pending_ks_errors = []


def _build_phase(
    topic: str,
    value: dict,
    trigger_ts: str | None,
    end_ts: str | None,
    duration_ms: float,
    state_str: str,
    trigger_type: str = "",
) -> ExecutionPhase:
    """Construct an ExecutionPhase from step trigger/finish data."""
    return ExecutionPhase(
        label=topic,
        phase_type=trigger_type or (value.get("type", "") if "type" in value else ""),
        start=trigger_ts,
        end=end_ts,
        duration_ms=duration_ms,
        state=state_str,
    )


def _build_generative_answer_trace(
    value: dict,
    position: int,
    timestamp: str | None,
    triggering_user_message: str | None,
    topic_name: str | None,
) -> GenerativeAnswerTrace:
    """Extract a GenerativeAnswerTrace from a `GenerativeAnswersSupportData` event value.

    All nested `.get()` calls are defensive — `summarizationOpenAIResponse` and
    `queryRewrittingOpenAIResponse` may be null when the LLM call was skipped or
    failed, and shadow/verified blocks may be absent on older runtimes.
    """
    rewrite_resp = value.get("queryRewrittingOpenAIResponse") or {}
    rewrite_usage = rewrite_resp.get("CapiResourceUsage") or {}
    summarize_resp = value.get("summarizationOpenAIResponse") or {}
    summarize_usage = summarize_resp.get("CapiResourceUsage") or {}
    summarize_result = (summarize_resp.get("Result") or {}) if isinstance(summarize_resp, dict) else {}

    raw_results = value.get("searchResults") or []
    raw_verified = value.get("verifiedSearchResults") or []
    raw_shadow = value.get("ShadowSearchResults") or value.get("shadowSearchResults") or []

    # Index verified results by URL so we can attach the verified score back
    # onto the matching base result without losing the original ordering.
    verified_by_url: dict[str, float] = {}
    for r in raw_verified:
        url = r.get("url") or r.get("Url")
        score = r.get("rankScore")
        if url and isinstance(score, (int, float)):
            verified_by_url[url] = float(score)

    def _to_search_result(r: dict, attach_verified: bool = False) -> SearchResult:
        url = r.get("url") or r.get("Url")
        score = r.get("rankScore")
        return SearchResult(
            name=r.get("name") or r.get("Name") or (url.rsplit("/", 1)[-1] if url else None),
            url=url,
            text=r.get("snippet") or r.get("Snippet") or r.get("text") or r.get("Text"),
            file_type=r.get("fileType") or r.get("FileType"),
            result_type=r.get("searchType") or r.get("Type"),
            rank_score=float(score) if isinstance(score, (int, float)) else None,
            verified_rank_score=verified_by_url.get(url) if attach_verified and url else None,
        )

    search_results = [_to_search_result(r, attach_verified=True) for r in raw_results[:25]]
    shadow_results = [_to_search_result(r) for r in raw_shadow[:25]]

    # Citations
    raw_citations = (summarize_result.get("TextCitations") or []) if isinstance(summarize_result, dict) else []
    citations = [
        GenerativeAnswerCitation(
            url=c.get("Url") or c.get("url"),
            snippet=c.get("Text") or c.get("text") or c.get("Snippet"),
            title=c.get("Title") or c.get("title"),
        )
        for c in raw_citations
    ]

    # Determine search backend type from first result if not explicit on the event
    search_type = None
    if search_results:
        search_type = search_results[0].result_type

    def _opt_int(v: object) -> int | None:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return int(v)
        return None

    # `HypotheticalSnippetQuery` lives nested under .Response.HypotheticalSnippetQuery
    # in newer payloads — fall back to the legacy top-level location for compatibility.
    rewrite_response_inner = rewrite_resp.get("Response") or {}
    if isinstance(rewrite_response_inner, dict):
        hypo_query = rewrite_response_inner.get("HypotheticalSnippetQuery") or rewrite_resp.get(
            "HypotheticalSnippetQuery"
        )
    else:
        hypo_query = rewrite_resp.get("HypotheticalSnippetQuery")

    return GenerativeAnswerTrace(
        position=position,
        timestamp=timestamp,
        topic_name=topic_name,
        triggering_user_message=triggering_user_message,
        activity_id=value.get("activityId"),
        original_message=value.get("message"),
        screened_message=value.get("screenedMessage"),
        rewritten_message=value.get("rewrittenMessage"),
        rewritten_keywords=value.get("rewrittenMessageKeywords"),
        hypothetical_snippet_query=hypo_query,
        rewrite_prompt_tokens=_opt_int(rewrite_usage.get("PromptTokens")),
        rewrite_completion_tokens=_opt_int(rewrite_usage.get("CompletionTokens")),
        rewrite_total_tokens=_opt_int(rewrite_usage.get("TotalTokens")),
        rewrite_cached_tokens=_opt_int(rewrite_usage.get("CachedTokens")),
        rewrite_model=rewrite_usage.get("ModelName"),
        rewrite_system_prompt=rewrite_resp.get("Prompt") if isinstance(rewrite_resp, dict) else None,
        rewrite_raw_response=rewrite_resp.get("responseString") if isinstance(rewrite_resp, dict) else None,
        summarize_prompt_tokens=_opt_int(summarize_usage.get("PromptTokens")),
        summarize_completion_tokens=_opt_int(summarize_usage.get("CompletionTokens")),
        summarize_total_tokens=_opt_int(summarize_usage.get("TotalTokens")),
        summarize_cached_tokens=_opt_int(summarize_usage.get("CachedTokens")),
        summarize_model=summarize_usage.get("ModelName"),
        summarize_system_prompt=summarize_resp.get("Prompt") if isinstance(summarize_resp, dict) else None,
        endpoints=list(value.get("endpoints") or []),
        search_results=search_results,
        shadow_search_results=shadow_results,
        search_errors=[str(e) for e in (value.get("searchErrors") or [])],
        search_logs=[str(e) for e in (value.get("searchLogs") or [])],
        search_terms_used=[str(t) for t in (value.get("searchTerms") or [])],
        shadow_search_terms=[str(t) for t in (value.get("ShadowSearchTerms") or [])],
        shadow_search_logs=[str(e) for e in (value.get("ShadowSearchLogs") or [])],
        shadow_search_errors=[str(e) for e in (value.get("ShadowSearchErrors") or [])],
        search_type=search_type,
        summary_text=summarize_result.get("Summary") if isinstance(summarize_result, dict) else None,
        text_summary=summarize_result.get("TextSummary") if isinstance(summarize_result, dict) else None,
        raw_summary=summarize_resp.get("RawSummary") if isinstance(summarize_resp, dict) else None,
        citations=citations,
        performed_content_moderation=bool(value.get("performedContentModerationCheck")),
        performed_content_provenance=bool(value.get("performedContentProvenanceCheck")),
        contains_confidential=bool(
            summarize_result.get("ContainsConfidentialData") if isinstance(summarize_result, dict) else False
        ),
        filtered_summary=value.get("filteredOpenAISummary"),
        screened_summary=value.get("screenedOpenAISummary"),
        gpt_answer_state=value.get("gptAnswerState"),
        completion_state=value.get("completionState"),
        triggered_fallback=bool(value.get("triggeredGptFallback")),
    )


def _process_trace_event(
    activity: dict,
    state: _TimelineState,
    schema_lookup: dict[str, str],
    timestamp: str | None,
    position: int,
) -> None:
    """Process a single event or trace activity, updating state in place."""
    act_type = activity.get("type", "")
    value_type = activity.get("valueType", "") or activity.get("name", "")
    value = activity.get("value", {}) or {}

    # `GenerativeAnswersSupportData` arrives both as type="event" (orchestrator)
    # and as type="message" (when the runtime stamps a textual hint such as
    # "Answer not Found in Search Results" alongside the diagnostic blob).
    # Handle both shapes through the same branch.
    if value_type == "GenerativeAnswersSupportData" and act_type in ("event", "message"):
        trace = _build_generative_answer_trace(
            value,
            position=position,
            timestamp=timestamp,
            triggering_user_message=state.latest_user_text,
            topic_name=state.last_step_topic,
        )
        state.turn_attempt_count += 1
        trace.attempt_index = state.turn_attempt_count
        trace.is_retry = state.turn_attempt_count > 1
        trace.previous_attempt_state = state.last_attempt_state if trace.is_retry else None
        state.last_attempt_state = trace.gpt_answer_state
        state.generative_answer_traces.append(trace)
        answer_state = trace.gpt_answer_state or "unknown"
        citations_n = len(trace.citations)
        results_n = len(trace.search_results)
        attempt_label = f"#{trace.attempt_index}" + (" (retry)" if trace.is_retry else "")
        summary_bits = [f"Generative answer {attempt_label}: {answer_state}"]
        if results_n:
            summary_bits.append(f"{results_n} hits")
        if citations_n:
            summary_bits.append(f"{citations_n} citations")
        if trace.triggered_fallback:
            summary_bits.append("FALLBACK")
        answered = (trace.gpt_answer_state or "").lower() == "answered"
        event_state = None if (answered and not trace.triggered_fallback) else "failed"
        state.events.append(
            TimelineEvent(
                timestamp=timestamp,
                position=position,
                event_type=EventType.GENERATIVE_ANSWER,
                topic_name=trace.topic_name,
                summary=" • ".join(summary_bits),
                state=event_state,
            )
        )
        return

    if act_type == "event":
        if value_type == "DynamicPlanReceived":
            steps = value.get("steps", [])
            step_names = []
            for s in steps:
                from parser import resolve_topic_name

                step_names.append(resolve_topic_name(s, schema_lookup))
            tools_summary = ", ".join(step_names) if step_names else "unknown"
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.PLAN_RECEIVED,
                    summary=f"Plan: [{tools_summary}]",
                    plan_identifier=value.get("planIdentifier"),
                    is_final_plan=value.get("isFinalPlan"),
                    plan_steps=step_names,
                )
            )
            for td in value.get("toolDefinitions", []):
                schema = td.get("schemaName", "")
                display = td.get("displayName", "")
                if schema and display:
                    state.tool_display_names[schema] = display

        elif value_type == "DynamicPlanReceivedDebug":
            ask = value.get("ask", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.PLAN_RECEIVED_DEBUG,
                    summary=f'Ask: "{ask}"',
                    plan_identifier=value.get("planIdentifier"),
                    orchestrator_ask=ask or None,
                    is_final_plan=value.get("isFinalPlan"),
                )
            )

        elif value_type == "DynamicPlanStepTriggered":
            task_dialog_id = value.get("taskDialogId", "")
            from parser import resolve_topic_name

            topic = resolve_topic_name(task_dialog_id, schema_lookup)
            step_type = value.get("type", "")
            step_id = value.get("stepId", "")

            if step_id and timestamp:
                state.step_triggers[step_id] = (timestamp, step_type)
            if step_id:
                state.step_trigger_thoughts[step_id] = value.get("thought")

            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.STEP_TRIGGERED,
                    topic_name=topic,
                    summary=f"Step start: {topic} ({step_type})",
                    state="inProgress",
                    step_id=step_id,
                    plan_identifier=value.get("planIdentifier"),
                    thought=value.get("thought"),
                    has_recommendations=value.get("hasRecommendations"),
                )
            )
            state.last_step_topic = topic

            if task_dialog_id == "P:UniversalSearchTool":
                state.pending_ks_thought = value.get("thought")

            if value.get("type") == "CustomTopic" and "search" in task_dialog_id.lower():
                state.pending_custom_searches[task_dialog_id] = CustomSearchStep(
                    task_dialog_id=task_dialog_id,
                    display_name=state.tool_display_names.get(task_dialog_id, task_dialog_id.split(".")[-1]),
                    thought=value.get("thought"),
                    status="inProgress",
                )

        elif value_type == "DynamicPlanStepFinished":
            task_dialog_id = value.get("taskDialogId", "")
            if task_dialog_id == "P:UniversalSearchTool":
                observation = value.get("observation") or {}
                sr = observation.get("search_result") or {}
                raw_results = sr.get("search_results") or []
                step_results = [
                    SearchResult(
                        name=r.get("Name"),
                        url=r.get("Url"),
                        text=r.get("Text"),
                        file_type=r.get("FileType"),
                        result_type=r.get("Type"),
                    )
                    for r in raw_results[:10]
                ]
                step_errors = list(sr.get("search_errors") or [])
                if state.pending_ks_info:
                    state.pending_ks_info.execution_time = value.get("executionTime")
                    state.pending_ks_info.search_results = step_results
                    state.pending_ks_info.search_errors = step_errors
                    state.knowledge_searches.append(state.pending_ks_info)
                    state.pending_ks_info = None
                    state.pending_ks_execution_time = None
                    state.pending_ks_results = []
                    state.pending_ks_errors = []
                else:
                    state.pending_ks_execution_time = value.get("executionTime")
                    state.pending_ks_results = step_results
                    state.pending_ks_errors = step_errors

            if task_dialog_id in state.pending_custom_searches:
                step = state.pending_custom_searches.pop(task_dialog_id)
                step.status = value.get("state", "unknown")
                err = value.get("error")
                if err:
                    step.error = err.get("message") if isinstance(err, dict) else str(err)
                step.execution_time = value.get("executionTime")
                state.custom_search_steps.append(step)

            from parser import resolve_topic_name

            topic = resolve_topic_name(task_dialog_id, schema_lookup)
            step_state = value.get("state", "")
            step_id = value.get("stepId", "")
            error = value.get("error")

            duration_ms = 0.0
            trigger_info = state.step_triggers.get(step_id)
            trigger_ts = trigger_info[0] if trigger_info else None
            trigger_type = trigger_info[1] if trigger_info else ""
            if trigger_ts and timestamp:
                duration_ms = _ms_between(trigger_ts, timestamp)

            error_msg = None
            if error and isinstance(error, dict):
                error_msg = error.get("message", str(error))
                state.errors.append(f"{topic}: {error_msg}")
            elif step_state == "failed":
                error_msg = "Step failed"
                state.errors.append(f"{topic}: failed")

            # Format planUsedOutputs into readable string
            raw_used_outputs = value.get("planUsedOutputs") or {}
            plan_used_outputs_str = None
            if raw_used_outputs and isinstance(raw_used_outputs, dict):
                sources = [k for k in raw_used_outputs.keys()]
                if sources:
                    plan_used_outputs_str = f"Used outputs from: {', '.join(sources)}"

            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.STEP_FINISHED,
                    topic_name=topic,
                    summary=f"Step end: {topic} [{step_state}]"
                    + (f" ({duration_ms:.0f}ms)" if duration_ms > 0 else ""),
                    state=step_state,
                    error=error_msg,
                    step_id=step_id,
                    plan_identifier=value.get("planIdentifier"),
                    has_recommendations=value.get("hasRecommendations"),
                    plan_used_outputs=plan_used_outputs_str,
                )
            )

            state.phases.append(
                _build_phase(topic, value, trigger_ts, timestamp, duration_ms, step_state, trigger_type)
            )

            # Build ToolCall for all non-knowledge-search tools
            if task_dialog_id != "P:UniversalSearchTool":
                raw_observation = value.get("observation")
                tc_observation = None
                if raw_observation is not None:
                    import json as _json

                    raw_json = None
                    try:
                        raw_json = _json.dumps(raw_observation, indent=2, default=str)
                    except (TypeError, ValueError):
                        pass
                    obs_content = raw_observation.get("content", []) if isinstance(raw_observation, dict) else []
                    obs_structured = (
                        raw_observation.get("structuredContent") if isinstance(raw_observation, dict) else None
                    )
                    tc_observation = ToolCallObservation(
                        content=obs_content,
                        structured_content=obs_structured,
                        raw_json=raw_json,
                    )

                # Build a readable display name for tool calls
                tc_display = topic
                if task_dialog_id.startswith("MCP:"):
                    # MCP:<schema>:<tool_name> — extract just the tool function name
                    mcp_parts = task_dialog_id.split(":")
                    if len(mcp_parts) >= 3:
                        tc_display = mcp_parts[-1]

                state.tool_calls.append(
                    ToolCall(
                        step_id=step_id,
                        plan_identifier=value.get("planIdentifier"),
                        task_dialog_id=task_dialog_id,
                        display_name=tc_display,
                        step_type=trigger_type,
                        thought=state.step_trigger_thoughts.get(step_id),
                        arguments=state.pending_tool_args.pop(step_id, {}),
                        auto_filled_argument_names=state.pending_auto_filled.pop(step_id, []),
                        observation=tc_observation,
                        state=step_state,
                        error=error_msg,
                        execution_time=value.get("executionTime"),
                        duration_ms=duration_ms,
                        trigger_timestamp=trigger_ts,
                        finish_timestamp=timestamp,
                        position=position,
                    )
                )

        elif value_type == "DynamicPlanFinished":
            was_cancelled = value.get("wasCancelled", False)
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.PLAN_FINISHED,
                    summary=f"Plan finished (cancelled={was_cancelled})",
                    plan_identifier=value.get("planId"),
                )
            )

        elif value_type == "DialogTracingInfo":
            ACTION_TYPE_MAP = {
                "HttpRequestAction": EventType.ACTION_HTTP_REQUEST,
                "InvokeFlowAction": EventType.ACTION_HTTP_REQUEST,
                "BeginDialog": EventType.ACTION_BEGIN_DIALOG,
                "SendActivity": EventType.ACTION_SEND_ACTIVITY,
                "ConditionGroup": EventType.ACTION_TRIGGER_EVAL,
                "ConditionItem": EventType.ACTION_TRIGGER_EVAL,
                "InvokeAIBuilderModelAction": EventType.ACTION_AI_BUILDER,
            }

            SUMMARY_TEMPLATES = {
                EventType.ACTION_HTTP_REQUEST: "HTTP call in {topic}",
                EventType.ACTION_QA: "QA in {topic}",
                EventType.ACTION_TRIGGER_EVAL: "Evaluate: {topic}",
                EventType.ACTION_BEGIN_DIALOG: "Call to {topic}",
                EventType.ACTION_SEND_ACTIVITY: "Send response in {topic}",
                EventType.ACTION_AI_BUILDER: "AI Builder model in {topic}",
            }

            actions = value.get("actions", [])
            for action in actions:
                topic_id = action.get("topicId", "")
                action_type = action.get("actionType", "")
                exception = action.get("exception", "")
                from parser import resolve_topic_name

                topic = resolve_topic_name(topic_id, schema_lookup)

                if exception:
                    state.errors.append(f"{topic}.{action_type}: {exception}")

                event_type = ACTION_TYPE_MAP.get(action_type, EventType.DIALOG_TRACING)
                template = SUMMARY_TEMPLATES.get(event_type)
                if template:
                    summary = template.format(topic=topic)
                else:
                    summary = f"{action_type} in {topic}"

                state.events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        position=position,
                        event_type=event_type,
                        topic_name=topic,
                        summary=summary,
                    )
                )

        elif value_type == "DynamicPlanStepBindUpdate":
            bind_task_dialog_id = value.get("taskDialogId", "")
            bind_step_id = value.get("stepId", "")
            bind_arguments = value.get("arguments", {}) or {}
            bind_auto_filled = value.get("autoFilledArguments", []) or []

            # Generic: capture arguments for any tool
            if bind_step_id and bind_arguments:
                state.pending_tool_args[bind_step_id] = {k: str(v) for k, v in bind_arguments.items()}
            # Capture which argument names were auto-filled (vs manually bound)
            # so the Variable Tracker panel can badge each row.
            if bind_step_id:
                state.pending_auto_filled[bind_step_id] = [
                    str(name) for name in bind_auto_filled if isinstance(name, str)
                ]

            # Existing knowledge search argument capture (preserve exactly)
            if bind_task_dialog_id == "P:UniversalSearchTool":
                state.pending_ks_query = {
                    "search_query": bind_arguments.get("search_query"),
                    "search_keywords": bind_arguments.get("search_keywords"),
                }

        elif value_type == "UniversalSearchToolTraceData":
            sources = value.get("knowledgeSources", [])
            source_names = [s.split(".")[-1] if "." in s else s for s in sources]
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.KNOWLEDGE_SEARCH,
                    summary=f"Knowledge search: [{', '.join(source_names[:3])}]"
                    + (f" (+{len(source_names) - 3})" if len(source_names) > 3 else ""),
                )
            )

            def _clean_source(s: str) -> str:
                """Clean a raw knowledge source identifier to a display name."""
                if ".file." in s:
                    filename_with_id = s.split(".file.", 1)[1]
                    return re.sub(r"_[A-Za-z0-9]{3,}$", "", filename_with_id)
                base = re.sub(r"_[A-Za-z0-9]{3,}$", "", s)
                return base.split(".")[-1]

            cleaned = [_clean_source(s) for s in sources]
            deduped = list(dict.fromkeys(cleaned))
            output_sources = value.get("outputKnowledgeSources", [])
            output_cleaned = [_clean_source(s) for s in output_sources]
            output_deduped = list(dict.fromkeys(output_cleaned))
            state.pending_ks_info = KnowledgeSearchInfo(
                position=position,
                timestamp=timestamp,
                knowledge_sources=deduped,
                thought=state.pending_ks_thought,
                output_knowledge_sources=output_deduped,
                triggering_user_message=state.latest_user_text,
                **(state.pending_ks_query or {}),
            )
            state.pending_ks_query = None
            state.pending_ks_thought = None
            # If DynamicPlanStepFinished already arrived (inverted order), commit now
            if state.pending_ks_execution_time is not None:
                state.pending_ks_info.execution_time = state.pending_ks_execution_time
                state.pending_ks_info.search_results = state.pending_ks_results
                state.pending_ks_info.search_errors = state.pending_ks_errors
                state.knowledge_searches.append(state.pending_ks_info)
                state.pending_ks_info = None
                state.pending_ks_execution_time = None
                state.pending_ks_results = []
                state.pending_ks_errors = []

        elif value_type == "IntentRecognition":
            matched_intent = value.get("matchedIntent") or value.get("intent", "")
            confidence = value.get("confidence") or value.get("score")
            intent_score = None
            if confidence is not None:
                try:
                    intent_score = float(confidence)
                except (ValueError, TypeError):
                    pass
            topic = matched_intent or "Unknown"
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.INTENT_RECOGNITION,
                    topic_name=topic,
                    summary=f"Intent: {topic} ({intent_score:.0%})" if intent_score is not None else f"Intent: {topic}",
                    intent_score=intent_score,
                )
            )

        elif value_type == "ErrorCode":
            error_code = value.get("ErrorCode", "Unknown")
            state.errors.append(f"ErrorCode: {error_code}")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.ERROR,
                    summary=f"Error: {error_code}",
                    error=error_code,
                )
            )

    elif act_type == "trace":
        if value_type == "VariableAssignment":
            var_id = value.get("id", "")
            new_value = str(value.get("newValue", ""))[:80]
            scope = value.get("type", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.VARIABLE_ASSIGNMENT,
                    summary=f"{scope.title()} {var_id} = {new_value}",
                )
            )

        elif value_type == "DialogRedirect":
            target_id = value.get("targetDialogId", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.DIALOG_REDIRECT,
                    summary=f"Redirect → {target_id[:40]}",
                )
            )

        elif value.get("ErrorCode"):
            error_code = value["ErrorCode"]
            state.errors.append(f"ErrorCode: {error_code}")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.ERROR,
                    summary=f"Error: {error_code}",
                    error=error_code,
                )
            )


_THINKING_THRESHOLD_MS = 1000  # gaps > 1s between events are orchestrator thinking


def _synthesize_orchestrator_phases(state: _TimelineState) -> None:
    """Detect orchestrator thinking gaps and insert synthetic events + phases.

    Patterns detected:
    - UserMessage → PlanReceived (initial planning)
    - StepFinished → PlanReceived (planning next step)
    - StepFinished → PlanFinished (finalizing)

    The preceding step's phase_type determines the label context.
    """
    if not state.events:
        return

    # Build a lookup: step finished topic → phase_type
    phase_type_by_label: dict[str, str] = {}
    for p in state.phases:
        if p.label and p.phase_type:
            phase_type_by_label[p.label] = p.phase_type

    insertions: list[tuple[int, TimelineEvent, ExecutionPhase]] = []

    for i in range(len(state.events) - 1):
        ev = state.events[i]
        nxt = state.events[i + 1]

        # Detect valid gap patterns
        is_thinking_gap = False
        context_label = ""

        if ev.event_type == EventType.STEP_FINISHED and nxt.event_type in (
            EventType.PLAN_RECEIVED,
            EventType.PLAN_FINISHED,
        ):
            is_thinking_gap = True
            prev_type = phase_type_by_label.get(ev.topic_name or "", "")
            if prev_type == "KnowledgeSource":
                context_label = f"Processing: {ev.topic_name or 'search results'}"
            elif nxt.event_type == EventType.PLAN_FINISHED:
                context_label = "Finalizing plan"
            else:
                context_label = f"Planning after: {ev.topic_name or 'step'}"

        elif ev.event_type == EventType.USER_MESSAGE and nxt.event_type == EventType.PLAN_RECEIVED:
            is_thinking_gap = True
            context_label = "Planning response"

        if not is_thinking_gap:
            continue

        if not ev.timestamp or not nxt.timestamp:
            continue

        gap_ms = _ms_between(ev.timestamp, nxt.timestamp)
        if gap_ms < _THINKING_THRESHOLD_MS:
            continue

        # Create synthetic event and phase
        position = ev.position
        event = TimelineEvent(
            timestamp=ev.timestamp,
            position=position,
            event_type=EventType.ORCHESTRATOR_THINKING,
            summary=f"Orchestrator: {context_label} ({gap_ms:.0f}ms)",
        )
        phase = ExecutionPhase(
            label=context_label,
            phase_type="OrchestratorThinking",
            start=ev.timestamp,
            end=nxt.timestamp,
            duration_ms=gap_ms,
            state="completed",
        )
        insertions.append((i + 1, event, phase))

    # Insert in reverse order to preserve indices
    for idx, event, phase in reversed(insertions):
        state.events.insert(idx, event)
        state.phases.append(phase)


def build_timeline(activities: list[dict], schema_lookup: dict[str, str]) -> ConversationTimeline:
    """Build a ConversationTimeline from sorted activities and schema name lookup."""
    state = _TimelineState()

    for activity in activities:
        act_type = activity.get("type", "")
        from_info = activity.get("from", {}) or {}
        role = _normalize_role(from_info.get("role"))
        timestamp = _get_timestamp(activity)
        channel_data = activity.get("channelData", {}) or {}
        position = channel_data.get("webchat:internal:position", 0)

        # Track bot name and conversation id. The conversation id can live
        # in a few places depending on the export shape:
        #   1. `activity.conversation.id` (Bot Framework default).
        #   2. `activity.conversationId` (top-level alias some runtimes emit).
        #   3. `activity.channelData.conversationId` (webchat / DirectLine).
        #   4. Inside the value blob of certain trace events (e.g.
        #      `GenerativeAnswersSupportData`).
        #   5. Last-resort fallback: parsed from a bot text message that
        #      replies to a `/debug conversationID` request — chat-bot
        #      test transcripts (`Test via CB`) only carry the id this way.
        if not state.bot_name and from_info.get("name"):
            if role == "bot":
                state.bot_name = from_info["name"]
        if not state.conversation_id:
            conv = activity.get("conversation") or {}
            if isinstance(conv, dict) and conv.get("id"):
                state.conversation_id = conv["id"]
            elif activity.get("conversationId"):
                state.conversation_id = activity["conversationId"]
            else:
                cd = activity.get("channelData") or {}
                if isinstance(cd, dict) and cd.get("conversationId"):
                    state.conversation_id = cd["conversationId"]
                else:
                    val = activity.get("value")
                    if isinstance(val, dict) and val.get("conversationId"):
                        state.conversation_id = val["conversationId"]
        if not state.conversation_id and act_type == "message" and role == "bot":
            text = activity.get("text") or ""
            m = _UUID_IN_TEXT_RE.search(text)
            if m:
                state.conversation_id = m.group(0)

        # Track time range
        if timestamp:
            if not state.first_timestamp:
                state.first_timestamp = timestamp
            state.last_timestamp = timestamp

        # Skip typing indicators and streaming
        if act_type == "typing":
            continue

        # `GenerativeAnswersSupportData` can arrive as type="message" (when the runtime
        # stamps a textual hint like "Answer not Found in Search Results") OR as
        # type="event". Both shapes carry the full diagnostic value blob — route them
        # through the trace processor before the normal message branches.
        if activity.get("name") == "GenerativeAnswersSupportData" and act_type in ("event", "message"):
            _process_trace_event(activity, state, schema_lookup, timestamp, position)
            continue

        # User message
        if act_type == "message" and role == "user":
            state.turn_attempt_count = 0
            state.last_attempt_state = None
            text = activity.get("text", "")
            if text:
                state.latest_user_text = text
            if not state.user_query and text:
                state.user_query = text
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.USER_MESSAGE,
                    summary=f'User: "{text}"' if text else "User message",
                )
            )
            continue

        # Bot message
        if act_type == "message" and role == "bot":
            text = activity.get("text", "")
            # Check for attachments (adaptive cards)
            attachments = activity.get("attachments", []) or []
            if not text and attachments:
                text = _extract_adaptive_card_text(attachments)
            clean_text = text.replace("\n", " ").replace("\r", "")
            state.events.append(
                TimelineEvent(
                    timestamp=timestamp,
                    position=position,
                    event_type=EventType.BOT_MESSAGE,
                    summary=f"Bot: {clean_text}" if clean_text else "Bot message",
                )
            )
            continue

        # Delegate event and trace activity types to helper
        if act_type in ("event", "trace"):
            _process_trace_event(activity, state, schema_lookup, timestamp, position)

    _finalize_knowledge_search(state)
    _synthesize_orchestrator_phases(state)

    total_elapsed = _ms_between(state.first_timestamp, state.last_timestamp)

    return ConversationTimeline(
        bot_name=state.bot_name,
        conversation_id=state.conversation_id,
        user_query=state.user_query,
        events=state.events,
        phases=state.phases,
        errors=state.errors,
        total_elapsed_ms=total_elapsed,
        knowledge_searches=state.knowledge_searches,
        custom_search_steps=state.custom_search_steps,
        tool_calls=state.tool_calls,
        generative_answer_traces=state.generative_answer_traces,
    )


# --- Credit rate constants ---

CREDIT_CLASSIC_ANSWER = 1
CREDIT_GENERATIVE_ANSWER = 2
CREDIT_AGENT_ACTION = 5
CREDIT_TENANT_GRAPH = 10
CREDIT_FLOW_ACTIONS_PER_100 = 13

# Tool types that are agent actions (5 credits each)
AGENT_ACTION_TOOL_TYPES = {
    "ConnectorTool",
    "ConnectedAgent",
    "ChildAgent",
    "A2AAgent",
    "MCPServer",
    "ExternalAgent",
    "CUATool",
    "FlowTool",
}


def _build_tool_type_lookup(profile: BotProfile) -> dict[str, str]:
    """Build taskDialogId -> tool_type lookup from profile components."""
    lookup: dict[str, str] = {}
    for comp in profile.components:
        if comp.tool_type and comp.schema_name:
            lookup[comp.schema_name] = comp.tool_type
    return lookup


def resolve_tool_types(timeline: ConversationTimeline, profile: BotProfile) -> None:
    """Resolve tool_type on each ToolCall by matching taskDialogId against profile components."""
    lookup = _build_tool_type_lookup(profile)
    for tc in timeline.tool_calls:
        if tc.tool_type:
            continue
        # Direct match
        if tc.task_dialog_id in lookup:
            tc.tool_type = lookup[tc.task_dialog_id]
            continue
        # MCP format: MCP:<schema>:<tool_name> — extract schema between first and last colon
        if tc.task_dialog_id.startswith("MCP:"):
            parts = tc.task_dialog_id.split(":")
            if len(parts) >= 3:
                mcp_schema = ":".join(parts[1:-1])
                for schema, tt in lookup.items():
                    if mcp_schema == schema or mcp_schema.endswith(f".{schema}"):
                        tc.tool_type = tt
                        break


def estimate_credits(timeline: ConversationTimeline, profile: BotProfile) -> CreditEstimate:
    """Estimate MCS credit consumption from timeline events.

    Walks events in order, classifying each billable step:
    - KnowledgeSource / P:UniversalSearchTool → 2 credits (generative answer)
    - Agent/tool steps (ConnectedAgent, ChildAgent, etc.) → 5 credits (agent action)
    - CustomTopic under generative orchestration → 5 credits (agent action / topic transition)
    - CustomTopic under classic recognizer → 1 credit (classic answer)
    - HTTP/connector calls not inside already-counted steps → 5 credits (agent action)
    """
    line_items: list[CreditLineItem] = []
    warnings: list[str] = []
    tool_type_lookup = _build_tool_type_lookup(profile)
    is_generative = profile.recognizer_kind == "GenerativeAIRecognizer"

    # Track which positions have been billed via STEP_TRIGGERED to avoid double-counting
    billed_step_positions: set[int] = set()
    # Track active step context (position range where HTTP calls are already covered)
    active_step_topics: set[str] = set()

    for event in timeline.events:
        if event.event_type == EventType.STEP_TRIGGERED:
            summary = event.summary or ""
            topic = event.topic_name or ""
            position = event.position

            # Extract step type from summary: "Step start: TopicName (StepType)"
            step_type_raw = ""
            if "(" in summary and summary.endswith(")"):
                step_type_raw = summary.rsplit("(", 1)[-1].rstrip(")")

            # Check taskDialogId pattern via topic name matching against tool_type_lookup
            resolved_tool_type = None
            for schema, tt in tool_type_lookup.items():
                if topic in schema or schema.endswith(f".{topic}") or topic == schema:
                    resolved_tool_type = tt
                    break

            # Classify the step
            if "P:UniversalSearchTool" in summary or "KnowledgeSource" in step_type_raw:
                line_items.append(
                    CreditLineItem(
                        step_name=f"Knowledge Search: {topic}",
                        step_type="generative_answer",
                        credits=CREDIT_GENERATIVE_ANSWER,
                        detail=f"KnowledgeSource via {topic}",
                        position=position,
                    )
                )
            elif step_type_raw == "Agent" or resolved_tool_type in AGENT_ACTION_TOOL_TYPES:
                tool_label = resolved_tool_type or "Agent"
                line_items.append(
                    CreditLineItem(
                        step_name=topic,
                        step_type="agent_action",
                        credits=CREDIT_AGENT_ACTION,
                        detail=f"{tool_label} tool",
                        position=position,
                    )
                )
            elif step_type_raw == "CustomTopic":
                if is_generative:
                    line_items.append(
                        CreditLineItem(
                            step_name=topic,
                            step_type="agent_action",
                            credits=CREDIT_AGENT_ACTION,
                            detail="Topic transition (generative orchestration)",
                            position=position,
                        )
                    )
                else:
                    line_items.append(
                        CreditLineItem(
                            step_name=topic,
                            step_type="classic_answer",
                            credits=CREDIT_CLASSIC_ANSWER,
                            detail="Classic topic execution",
                            position=position,
                        )
                    )
            else:
                # Unknown step type — still count as agent action if under generative orchestration
                if is_generative:
                    line_items.append(
                        CreditLineItem(
                            step_name=topic or "Unknown step",
                            step_type="agent_action",
                            credits=CREDIT_AGENT_ACTION,
                            detail=f"Orchestrator step ({step_type_raw or 'unknown'})",
                            position=position,
                        )
                    )

            billed_step_positions.add(position)
            active_step_topics.add(topic)

        elif event.event_type == EventType.STEP_FINISHED:
            topic = event.topic_name or ""
            active_step_topics.discard(topic)

        elif event.event_type == EventType.ACTION_HTTP_REQUEST:
            # Only bill if not already inside a counted step
            if event.position not in billed_step_positions and not active_step_topics:
                topic = event.topic_name or "HTTP call"
                line_items.append(
                    CreditLineItem(
                        step_name=f"HTTP: {topic}",
                        step_type="agent_action",
                        credits=CREDIT_AGENT_ACTION,
                        detail="Connector/HTTP action",
                        position=event.position,
                    )
                )

        elif event.event_type == EventType.ACTION_BEGIN_DIALOG:
            # Topic transition outside of an active step — agent action under generative orchestration
            if is_generative and not active_step_topics and event.position not in billed_step_positions:
                topic = event.topic_name or "Dialog"
                line_items.append(
                    CreditLineItem(
                        step_name=f"Topic transition: {topic}",
                        step_type="agent_action",
                        credits=CREDIT_AGENT_ACTION,
                        detail="BeginDialog (generative orchestration)",
                        position=event.position,
                    )
                )

    # Add standard warnings
    warnings.append("Cannot detect tenant graph grounding (10 credits) — not in transcript data")
    warnings.append("Cannot detect AI tool tier (basic/standard/premium) — no token counts in transcript")
    warnings.append("Cannot distinguish reasoning model surcharge — no model identifier in trace")
    if is_generative:
        warnings.append("CustomTopic steps counted as agent actions (5 credits) under generative orchestration")

    total_credits = sum(item.credits for item in line_items)

    return CreditEstimate(
        line_items=line_items,
        total_credits=total_credits,
        warnings=warnings,
    )

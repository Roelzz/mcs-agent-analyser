"""Dynamic analysis view state mixin."""

from __future__ import annotations

import reflex as rx


def _md_to_segments(md: str) -> list[dict]:
    """Split a Markdown string into text / mermaid fence segments."""
    if not md:
        return []
    segments: list[dict] = []
    remaining = md
    fence_open = "```mermaid"
    fence_close = "```"
    while remaining:
        start = remaining.find(fence_open)
        if start == -1:
            segments.append({"type": "text", "content": remaining})
            break
        if start > 0:
            segments.append({"type": "text", "content": remaining[:start]})
        rest = remaining[start + len(fence_open) :]
        end = rest.find(fence_close)
        if end == -1:
            segments.append({"type": "text", "content": fence_open + rest})
            break
        mermaid_src = rest[:end].strip()
        segments.append({"type": "mermaid", "content": mermaid_src})
        remaining = rest[end + len(fence_close) :]
    return segments


class DynamicMixin(rx.State, mixin=True):
    """State for the dynamic analysis view."""

    # Active sub-tab
    mcs_analyse_tab: str = "profile"

    # Section markdown (one per sub-tab)
    mcs_section_profile: str = ""
    mcs_section_knowledge: str = ""
    mcs_section_tools: str = ""
    mcs_section_topics: str = ""
    mcs_section_model_comparison: str = ""
    mcs_section_conversation: str = ""
    mcs_section_credits: str = ""

    # Credit table data
    mcs_credit_rows: list[dict] = []
    mcs_credit_total: float = 0.0
    mcs_credit_assumptions: list[str] = []
    mcs_credit_step_rows: list[dict] = []
    mcs_credit_mermaid: str = ""

    # Conversation flow
    mcs_conversation_flow: list[dict] = []
    # Conversation flow grouped into plan cards + loose-message groups.
    # Built from `mcs_conversation_flow` via `renderer.sections.group_flow_items`.
    mcs_conversation_flow_groups: list[dict] = []
    # Conversation Flow filter state. Empty values = no filter applied.
    mcs_flow_filter_text: str = ""
    mcs_flow_filter_types: list[str] = []
    mcs_conversation_flow_source: str = ""  # "snapshot" | "transcript" | ""

    # Custom rule findings for dynamic view
    mcs_custom_findings: list[dict] = []

    # ── Profile tab ──────────────────────────────────────────────────────────
    mcs_profile_kpis: list[dict] = []
    mcs_profile_ai_config: list[dict] = []
    mcs_profile_instructions_len: str = ""
    mcs_profile_instructions_text: str = ""
    mcs_profile_instruction_drift: dict = {}
    mcs_profile_starters: list[dict] = []
    mcs_profile_security_chips: list[dict] = []
    mcs_profile_bot_meta: list[dict] = []
    mcs_profile_env_vars: list[dict] = []
    mcs_profile_connectors: list[dict] = []
    mcs_profile_conn_refs: list[dict] = []
    mcs_profile_conn_defs: list[dict] = []
    mcs_profile_quick_wins: list[dict] = []
    mcs_profile_trigger_overlaps: list[dict] = []

    # ── Tools tab ────────────────────────────────────────────────────────────
    mcs_tools_kpis: list[dict] = []
    mcs_tools_rows: list[dict] = []
    mcs_tools_mermaid: str = ""
    mcs_tools_external_calls: list[dict] = []
    # Runtime tool call analysis
    mcs_tools_call_count: int = 0
    mcs_tools_stats_rows: list[dict] = []
    mcs_tools_chain_rows: list[dict] = []
    mcs_tools_reasoning_rows: list[dict] = []
    mcs_tools_detail_rows: list[dict] = []
    mcs_tools_flow_mermaid: str = ""
    mcs_tools_inventory_rows: list[dict] = []

    # ── Knowledge tab ────────────────────────────────────────────────────────
    mcs_knowledge_kpis: list[dict] = []
    mcs_knowledge_sources: list[dict] = []
    mcs_knowledge_files: list[dict] = []
    mcs_knowledge_coverage: list[dict] = []
    mcs_knowledge_source_details: list[dict] = []
    mcs_knowledge_searches: list[dict] = []
    mcs_knowledge_custom_steps: list[dict] = []
    mcs_knowledge_general_enabled: bool = False
    # Citation Verification panel — flat list of every (trace, citation)
    # pair across the conversation with answer_state, completion_state,
    # moderation/provenance flags. Lets the user audit grounding at a
    # glance without expanding each generative-answer card.
    mcs_knowledge_citation_panel: list[dict] = []
    # Topic-level Search & Summarize diagnostic traces (one row per call,
    # plus expandable child rows for results and citations).
    mcs_generative_traces: list[dict] = []
    mcs_generative_topics: list[str] = []  # topic names that emitted at least one trace

    # ── Topics tab ───────────────────────────────────────────────────────────
    mcs_topics_kpis: list[dict] = []
    mcs_topics_summary: list[dict] = []
    mcs_topics_user_rows: list[dict] = []
    mcs_topics_orch_rows: list[dict] = []
    mcs_topics_system_rows: list[dict] = []
    mcs_topics_external_calls: list[dict] = []
    mcs_topics_coverage: list[dict] = []
    mcs_topics_coverage_summary: str = ""
    mcs_topics_anomalies: list[dict] = []
    mcs_topics_mermaid: str = ""
    mcs_topics_trigger_matches: list[dict] = []

    # ── Routing tab ───────────────────────────────────────────────────────────
    mcs_routing_lifecycles: list[dict] = []
    mcs_routing_decisions: list[dict] = []
    mcs_routing_plan_evolution: list[dict] = []

    # ── Model tab ────────────────────────────────────────────────────────────
    mcs_model_kpis: list[dict] = []
    mcs_model_configured: list[dict] = []
    mcs_model_strengths: list[str] = []
    mcs_model_limitations: list[str] = []
    mcs_model_recommendation: str = ""
    mcs_model_catalogue: list[dict] = []

    # Visual summary
    mcs_conv_kpis: list[dict] = []
    mcs_conv_event_mix: list[dict] = []
    mcs_conv_latency_bands: list[dict] = []
    mcs_conv_highlights: list[dict] = []

    # ── Conversation tab (structured) ────────────────────────────────────────
    mcs_conv_metadata: list[dict] = []
    # Conversation GUID surfaced in the page header next to the agent name.
    mcs_conversation_id: str = ""
    # Deep-link target id used by Conversation Flow → other tabs. Each tab
    # row whose identity matches this opens its accordion + scrolls into
    # view. Cleared next time another link is clicked.
    mcs_highlight_target_id: str = ""
    mcs_conv_phases: list[dict] = []
    mcs_conv_event_log: list[dict] = []
    mcs_conv_errors: list[str] = []
    # Error/exception banner — one row per ERROR-toned flow item with the
    # `flow_id` deep-link target so the user can jump straight to the row.
    mcs_conv_error_banner: list[dict] = []
    mcs_conv_reasoning: list[dict] = []
    mcs_conv_sequence_mermaid: str = ""
    mcs_conv_gantt_mermaid: str = ""
    # Variable Tracker — per-tool-call arguments + outputs surfaced as
    # cards on the Conversation tab. Each row corresponds to one
    # `ToolCall` from the timeline; arguments are rendered with
    # AUTO/MANUAL badges when the orchestrator auto-filled them.
    mcs_conv_variables: list[dict] = []

    # ── Insights tab (conversation analysis features) ──────────────────────
    # Turn Efficiency
    mcs_ins_turn_kpis: list[dict] = []
    mcs_ins_turn_rows: list[dict] = []
    # Response Quality
    mcs_ins_quality_kpis: list[dict] = []
    mcs_ins_quality_rows: list[dict] = []
    # Dead Code
    mcs_ins_dead_summary: str = ""
    mcs_ins_dead_rows: list[dict] = []
    # Plan Diff
    mcs_ins_plan_kpis: list[dict] = []
    mcs_ins_plan_diffs: list[dict] = []
    # Knowledge Effectiveness
    mcs_ins_ke_kpis: list[dict] = []
    mcs_ins_ke_rows: list[dict] = []
    mcs_ins_ke_warnings: list[str] = []
    # Delegation
    mcs_ins_deleg_kpis: list[dict] = []
    mcs_ins_deleg_rows: list[dict] = []
    mcs_ins_deleg_warnings: list[str] = []
    # Latency
    mcs_ins_latency_kpis: list[dict] = []
    mcs_ins_latency_rows: list[dict] = []
    mcs_ins_latency_mermaid: str = ""
    # Alignment
    mcs_ins_align_kpis: list[dict] = []
    mcs_ins_align_rows: list[dict] = []

    @rx.var
    def has_dynamic_sections(self) -> bool:
        return bool(self.mcs_section_profile or self.mcs_section_conversation or self.mcs_conversation_flow_source)

    @rx.var
    def mcs_current_section_segments(self) -> list[dict]:
        """Segments for the currently active sub-tab."""
        section_map = {
            "profile": self.mcs_section_profile,
            "knowledge": self.mcs_section_knowledge,
            "tools": self.mcs_section_tools,
            "topics": self.mcs_section_topics,
            "conversation": self.mcs_section_conversation,
            "credits": self.mcs_section_credits,
        }
        md = section_map.get(self.mcs_analyse_tab, "")
        return _md_to_segments(md)

    @rx.var
    def has_mcs_custom_findings(self) -> bool:
        return bool(self.mcs_custom_findings)

    @rx.var
    def has_mcs_conversation_flow(self) -> bool:
        return bool(self.mcs_conversation_flow)

    @rx.var
    def has_mcs_conv_visual_summary(self) -> bool:
        return bool(self.mcs_conv_kpis)

    @rx.var
    def has_mcs_conv_detail(self) -> bool:
        return bool(self.mcs_conv_metadata)

    @rx.var
    def has_mcs_tools_runtime(self) -> bool:
        return self.mcs_tools_call_count > 0

    @rx.var
    def has_mcs_quality(self) -> bool:
        return bool(
            self.mcs_credit_rows
            or self.mcs_ins_quality_kpis
            or self.mcs_ins_dead_rows
            or self.mcs_ins_dead_summary
            or self.mcs_ins_align_kpis
            or self.mcs_profile_quick_wins
        )

    @rx.event
    def set_mcs_analyse_tab(self, tab: str):
        self.mcs_analyse_tab = tab

    @rx.event
    def copy_flow_row_json(self, raw_json: str):
        """Copy a Conversation Flow row's serialized TimelineEvent to the
        clipboard. Wired to the per-row copy button — small but valued
        when filing bugs against Microsoft about a specific activity."""
        yield rx.set_clipboard(raw_json)
        yield rx.toast("Activity JSON copied", duration=2000)

    # ── Conversation Flow filter wiring ─────────────────────────────────────

    # User-facing filter chip → set of EventType values it covers. Coarser
    # than the raw event types so the UI stays readable; lets a single click
    # filter on "all message events" rather than asking the user to know
    # the difference between USER_MESSAGE and BOT_MESSAGE.
    _FLOW_FILTER_CHIP_TO_TYPES: dict[str, list[str]] = {
        "Messages": ["UserMessage", "BotMessage"],
        "Plans": ["PlanReceived", "PlanFinished"],
        "Actions": ["StepTriggered", "StepFinished", "ActionBeginDialog", "ActionSendActivity", "ActionHttpRequest", "ActionQA"],
        "Knowledge": ["KnowledgeSearch", "GenerativeAnswer"],
        "Traces": ["DialogTracing", "DialogRedirect", "ActionTriggerEval", "OrchestratorThinking", "IntentRecognition", "VariableAssignment"],
        "Errors": ["Error"],
    }

    @rx.event
    def set_mcs_flow_filter_text(self, value: str):
        self.mcs_flow_filter_text = value

    @rx.event
    def toggle_mcs_flow_filter_chip(self, chip: str):
        """Toggle a user-facing filter chip on/off."""
        current = list(self.mcs_flow_filter_types)
        if chip in current:
            current.remove(chip)
        else:
            current.append(chip)
        self.mcs_flow_filter_types = current

    @rx.event
    def clear_mcs_flow_filters(self):
        self.mcs_flow_filter_text = ""
        self.mcs_flow_filter_types = []

    @rx.var
    def mcs_conversation_flow_groups_filtered(self) -> list[dict]:
        """Apply the active text + type filters to the grouped flow.

        Filter logic:
          - When both filters are empty, returns the groups unchanged.
          - Otherwise iterates each group, keeps only items that match
            BOTH the text filter (substring across summary / text /
            thought / topic_name, case-insensitive) AND the type
            filter (item.kind == "message" matches the "Messages" chip;
            event types match via the chip→types lookup).
          - Drops groups whose filtered item list is empty.
        """
        text = (self.mcs_flow_filter_text or "").lower().strip()
        chips = list(self.mcs_flow_filter_types or [])
        if not text and not chips:
            return list(self.mcs_conversation_flow_groups)

        # Resolve chips → set of event_type strings + a special "message" flag
        wanted_types: set[str] = set()
        wants_messages = False
        for chip in chips:
            if chip == "Messages":
                wants_messages = True
            for t in self._FLOW_FILTER_CHIP_TO_TYPES.get(chip, []):
                wanted_types.add(t)

        out: list[dict] = []
        for group in self.mcs_conversation_flow_groups:
            filtered_items: list[dict] = []
            for item in group["items"]:
                # Type filter
                if chips:
                    is_message = item.get("kind") == "message"
                    et = item.get("event_type") or ""
                    if not ((wants_messages and is_message) or et in wanted_types):
                        continue
                # Text filter
                if text:
                    hay = " ".join(
                        [
                            item.get("summary", "") or "",
                            item.get("text", "") or "",
                            item.get("thought", "") or "",
                            item.get("topic_name", "") or "",
                            item.get("title", "") or "",
                        ]
                    ).lower()
                    if text not in hay:
                        continue
                filtered_items.append(item)
            if filtered_items:
                out.append({**group, "items": filtered_items})
        return out

    @rx.var
    def mcs_conversation_flow_match_count(self) -> int:
        """Total number of flow items after filter is applied."""
        return sum(len(g["items"]) for g in self.mcs_conversation_flow_groups_filtered)

    @rx.var
    def mcs_conversation_flow_total_count(self) -> int:
        """Total number of flow items pre-filter."""
        return sum(len(g["items"]) for g in self.mcs_conversation_flow_groups)

    @rx.var
    def mcs_flow_filter_active(self) -> bool:
        return bool(self.mcs_flow_filter_text) or bool(self.mcs_flow_filter_types)

    @rx.event
    def set_dynamic_link_target(self, tab: str, target_id: str):
        """Conversation Flow → tab deep-link. Sets the active tab and the
        highlight target id, then yields a small JS that:

        1. Scrolls the destination row into view (`id="row-<target_id>"`).
        2. Auto-opens the row's first closed Settings accordion so the user
           lands directly on the artifact's detail.

        The auto-open uses Radix's `data-state="closed"` attribute on the
        accordion trigger button — a no-op if the accordion is already open.
        Tab switch happens before the script runs so the destination DOM
        exists.
        """
        if tab:
            self.mcs_analyse_tab = tab
        self.mcs_highlight_target_id = target_id or ""
        if not target_id:
            return
        # Escape single quotes for safe interpolation into the JS literal.
        safe = target_id.replace("'", "\\'")
        return rx.call_script(
            "setTimeout(function(){"
            f"  var el = document.getElementById('row-{safe}');"
            "  if (!el) { return; }"
            "  el.scrollIntoView({block:'center', behavior:'smooth'});"
            "  var trig = el.querySelector('[data-state=\"closed\"]');"
            "  if (trig) { trig.click(); }"
            "}, 120);"
        )

    @rx.event
    def clear_dynamic_link_target(self):
        """Clear the highlight after the user navigates away or starts a
        fresh action."""
        self.mcs_highlight_target_id = ""

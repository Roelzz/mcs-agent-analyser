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
    mcs_conv_phases: list[dict] = []
    mcs_conv_event_log: list[dict] = []
    mcs_conv_errors: list[str] = []
    mcs_conv_reasoning: list[dict] = []
    mcs_conv_sequence_mermaid: str = ""
    mcs_conv_gantt_mermaid: str = ""

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

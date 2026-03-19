import json
import tempfile
import zipfile
from pathlib import Path

import reflex as rx
from loguru import logger

from instruction_store import save_snapshot  # noqa: E402
from model_comparison import _MODEL_CATALOGUE, _resolve_catalogue_key  # noqa: E402
from parser import detect_trigger_overlaps, parse_dialog_json, parse_yaml, validate_connections  # noqa: E402
from renderer import render_instruction_drift, render_report, render_transcript_report  # noqa: E402
from renderer._helpers import _format_duration, _parse_execution_time_ms, _pct  # noqa: E402
from renderer.timeline_render import render_gantt_chart, render_mermaid_sequence  # noqa: E402
from renderer.knowledge import _grounding_score, _source_efficiency  # noqa: E402
from renderer.profile import (  # noqa: E402
    _AUTOMATION_TRIGGERS,
    _CATEGORY_ORDER,
    _SYSTEM_TRIGGERS,
    _classify_component,
    detect_topic_graph_anomalies,
    render_integration_map,
    render_topic_graph,
)
from renderer.sections import (  # noqa: E402
    _ms_between_iso,
    build_conversation_flow_items,
    build_conversation_visual_summary,
    build_orchestrator_decision_timeline,
    build_plan_evolution,
    build_topic_lifecycles,
    build_trigger_match_items,
    render_report_sections,
)
from timeline import build_timeline  # noqa: E402
from transcript import parse_transcript_json  # noqa: E402
from utils import safe_extractall  # noqa: E402

from web.state._base import _clear_bot_profile, _save_bot_profile


class UploadMixin(rx.State, mixin=True):
    """Upload vars and handlers."""

    # Upload vars
    is_processing: bool = False
    upload_error: str = ""
    upload_stage: str = ""
    paste_json: str = ""

    @rx.event
    def set_paste_json(self, value: str):
        self.paste_json = value

    # --- Upload handlers ---

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        if not files:
            self.upload_error = "No files selected."
            return

        self.is_processing = True
        self.upload_error = ""
        self.upload_stage = "Detecting file format..."
        yield

        try:
            names = [f.filename for f in files]
            exts = [Path(n).suffix.lower() for n in names]

            if len(files) == 1 and exts[0] == ".zip":
                self.upload_stage = "Extracting and parsing bot export..."
                yield
                await self._process_bot_zip(files)
            elif len(files) == 2:
                has_yaml = any(e in (".yml", ".yaml") for e in exts)
                has_json = any(e == ".json" for e in exts)
                if has_yaml and has_json:
                    self.upload_stage = "Parsing bot configuration..."
                    yield
                    await self._process_bot_files(files)
                else:
                    self.upload_error = (
                        f"Two files uploaded but expected botContent.yml + dialog.json. Got: {', '.join(names)}"
                    )
            elif len(files) == 1 and exts[0] == ".json":
                self.upload_stage = "Parsing transcript..."
                yield
                await self._process_transcript(files)
            else:
                self.upload_error = (
                    "Could not detect upload type. Accepted formats:\n"
                    "- 1 .zip file (bot export)\n"
                    "- botContent.yml + dialog.json (2 files)\n"
                    "- 1 .json file (transcript)"
                )
        except Exception as e:
            logger.error(f"Upload processing failed: {e}")
            self.upload_error = f"Processing failed: {e}"
        finally:
            self.is_processing = False
            self.upload_stage = ""
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]
            if self.report_markdown:  # type: ignore[attr-defined]
                yield rx.redirect("/analysis/dynamic")

    @rx.event
    async def handle_paste_submit(self):
        text = self.paste_json.strip()
        if not text:
            self.upload_error = "Paste field is empty."
            return

        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            self.upload_error = f"Invalid JSON: {e}"
            return

        self.is_processing = True
        self.upload_error = ""
        self.upload_stage = "Parsing transcript..."
        yield

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = Path(tmpdir) / "pasted_transcript.json"
                json_path.write_text(text)

                activities, metadata = parse_transcript_json(json_path)
                timeline = build_timeline(activities, {})
                title = "Pasted Transcript"
                self.report_markdown = render_transcript_report(title, timeline, metadata)  # type: ignore[attr-defined]
                self.report_title = title  # type: ignore[attr-defined]
                self.report_source = "upload"  # type: ignore[attr-defined]
                self.lint_report_markdown = ""  # type: ignore[attr-defined]
                self.bot_profile_json = ""  # type: ignore[attr-defined]
                self.report_custom_findings = []  # type: ignore[attr-defined]
                _clear_bot_profile()

                self._populate_dynamic_sections(None, timeline, "transcript")
                self.paste_json = ""
        except Exception as e:
            logger.error(f"Paste processing failed: {e}")
            self.upload_error = f"Processing failed: {e}"
        finally:
            self.is_processing = False
            self.upload_stage = ""
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]
            if self.report_markdown:  # type: ignore[attr-defined]
                yield rx.redirect("/analysis/dynamic")

    async def _process_bot_zip(self, files: list[rx.UploadFile]):
        if len(files) != 1:
            self.upload_error = "Upload exactly one .zip file."
            return

        upload_file = files[0]
        data = await upload_file.read()

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / upload_file.filename
            zip_path.write_bytes(data)

            if not zipfile.is_zipfile(zip_path):
                self.upload_error = "File is not a valid zip archive."
                return

            extract_dir = Path(tmpdir) / "extracted"
            with zipfile.ZipFile(zip_path) as zf:
                safe_extractall(zf, extract_dir)

            yaml_files = list(extract_dir.rglob("botContent.yml"))
            json_files = list(extract_dir.rglob("dialog.json"))

            if not yaml_files:
                self.upload_error = "No botContent.yml found in zip."
                return
            if not json_files:
                self.upload_error = "No dialog.json found in zip."
                return

            profile, schema_lookup = parse_yaml(yaml_files[0])
            activities = parse_dialog_json(json_files[0])
            timeline = build_timeline(activities, schema_lookup)
            self.report_markdown = render_report(profile, timeline)  # type: ignore[attr-defined]
            self.report_title = profile.display_name  # type: ignore[attr-defined]
            self.report_source = "upload"  # type: ignore[attr-defined]
            self.bot_profile_json = profile.model_dump_json()  # type: ignore[attr-defined]
            _save_bot_profile(self.bot_profile_json)  # type: ignore[attr-defined]
            self._evaluate_custom_rules(profile)  # type: ignore[attr-defined]

            instruction_diff = save_snapshot(profile)
            if instruction_diff and instruction_diff.is_significant:
                self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]

            self._populate_dynamic_sections(profile, timeline, "snapshot")

    async def _process_bot_files(self, files: list[rx.UploadFile]):
        if len(files) != 2:
            self.upload_error = "Upload exactly 2 files: botContent.yml and dialog.json."
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            yml_path = None
            json_path = None

            for f in files:
                data = await f.read()
                fpath = Path(tmpdir) / f.filename
                fpath.write_bytes(data)
                if f.filename.endswith(".yml") or f.filename.endswith(".yaml"):
                    yml_path = fpath
                elif f.filename.endswith(".json"):
                    json_path = fpath

            if not yml_path:
                self.upload_error = "No .yml file found. Upload botContent.yml."
                return
            if not json_path:
                self.upload_error = "No .json file found. Upload dialog.json."
                return

            profile, schema_lookup = parse_yaml(yml_path)
            activities = parse_dialog_json(json_path)
            timeline = build_timeline(activities, schema_lookup)
            self.report_markdown = render_report(profile, timeline)  # type: ignore[attr-defined]
            self.report_title = profile.display_name  # type: ignore[attr-defined]
            self.report_source = "upload"  # type: ignore[attr-defined]
            self.bot_profile_json = profile.model_dump_json()  # type: ignore[attr-defined]
            _save_bot_profile(self.bot_profile_json)  # type: ignore[attr-defined]
            self._evaluate_custom_rules(profile)  # type: ignore[attr-defined]

            instruction_diff = save_snapshot(profile)
            if instruction_diff and instruction_diff.is_significant:
                self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]

            self._populate_dynamic_sections(profile, timeline, "snapshot")

    async def _process_transcript(self, files: list[rx.UploadFile]):
        if len(files) != 1:
            self.upload_error = "Upload exactly one transcript .json file."
            return

        upload_file = files[0]
        data = await upload_file.read()

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / upload_file.filename
            json_path.write_bytes(data)

            activities, metadata = parse_transcript_json(json_path)
            timeline = build_timeline(activities, {})
            title = json_path.stem
            self.report_markdown = render_transcript_report(title, timeline, metadata)  # type: ignore[attr-defined]
            self.report_title = title  # type: ignore[attr-defined]
            self.report_source = "upload"  # type: ignore[attr-defined]
            self.bot_profile_json = ""  # type: ignore[attr-defined]
            self.report_custom_findings = []  # type: ignore[attr-defined]
            _clear_bot_profile()

            self._populate_dynamic_sections(None, timeline, "transcript")

    def _populate_dynamic_sections(
        self,
        profile,
        timeline,
        source: str,
    ) -> None:
        """Populate dynamic analysis state from profile and timeline."""
        if profile is not None:
            sections, credit_estimate = render_report_sections(profile, timeline)
            self.mcs_section_profile = sections["profile"]  # type: ignore[attr-defined]
            self.mcs_section_knowledge = sections["knowledge"]  # type: ignore[attr-defined]
            self.mcs_section_tools = sections["tools"]  # type: ignore[attr-defined]
            self.mcs_section_topics = sections["topics"]  # type: ignore[attr-defined]
            self.mcs_section_model_comparison = sections["model_comparison"]  # type: ignore[attr-defined]
            self.mcs_section_conversation = sections["conversation"]  # type: ignore[attr-defined]
            self.mcs_section_credits = sections["credits"]  # type: ignore[attr-defined]
        else:
            credit_estimate = None
            self.mcs_section_profile = ""  # type: ignore[attr-defined]
            self.mcs_section_knowledge = ""  # type: ignore[attr-defined]
            self.mcs_section_tools = ""  # type: ignore[attr-defined]
            self.mcs_section_topics = ""  # type: ignore[attr-defined]
            self.mcs_section_model_comparison = ""  # type: ignore[attr-defined]
            self.mcs_section_conversation = ""  # type: ignore[attr-defined]
            self.mcs_section_credits = ""  # type: ignore[attr-defined]

        # Conversation flow
        if timeline is not None:
            self.mcs_conversation_flow = build_conversation_flow_items(timeline, profile=profile)  # type: ignore[attr-defined]
        else:
            self.mcs_conversation_flow = []  # type: ignore[attr-defined]
        self.mcs_conversation_flow_source = source  # type: ignore[attr-defined]

        # Visual summary
        if timeline is not None:
            summary = build_conversation_visual_summary(timeline)
            self.mcs_conv_kpis = summary["kpis"]  # type: ignore[attr-defined]
            self.mcs_conv_event_mix = summary["event_mix"]  # type: ignore[attr-defined]
            self.mcs_conv_latency_bands = summary["latency_bands"]  # type: ignore[attr-defined]
            self.mcs_conv_highlights = summary["highlights"]  # type: ignore[attr-defined]
        else:
            self.mcs_conv_kpis = []  # type: ignore[attr-defined]
            self.mcs_conv_event_mix = []  # type: ignore[attr-defined]
            self.mcs_conv_latency_bands = []  # type: ignore[attr-defined]
            self.mcs_conv_highlights = []  # type: ignore[attr-defined]

        # Credit rows for the credits panel
        logger.info(
            f"Credits debug: credit_estimate={credit_estimate is not None}, "
            f"line_items={len(credit_estimate.line_items) if credit_estimate else 'N/A'}, "
            f"total={credit_estimate.total_credits if credit_estimate else 'N/A'}"
        )
        if credit_estimate and credit_estimate.line_items:
            type_counts: dict[str, int] = {}
            type_credits: dict[str, float] = {}
            for item in credit_estimate.line_items:
                type_counts[item.step_type] = type_counts.get(item.step_type, 0) + 1
                type_credits[item.step_type] = type_credits.get(item.step_type, 0) + item.credits

            rows = []
            meter_defs = [
                ("classic_answer", "Classic answer", "1"),
                ("generative_answer", "Generative answer", "2"),
                ("agent_action", "Agent action", "5"),
                ("flow_action", "Agent flow actions", "13 / 100"),
            ]
            for step_type, meter_label, rate in meter_defs:
                if step_type in type_counts:
                    rows.append(
                        {
                            "meter": meter_label,
                            "count": str(type_counts[step_type]),
                            "rate": rate,
                            "credits": f"{type_credits[step_type]:.0f}",
                        }
                    )
            logger.info(f"Credits panel: {len(rows)} rows, total={credit_estimate.total_credits}, rows={rows}")
            self.mcs_credit_rows = rows  # type: ignore[attr-defined]
            self.mcs_credit_total = credit_estimate.total_credits  # type: ignore[attr-defined]
            self.mcs_credit_assumptions = credit_estimate.warnings  # type: ignore[attr-defined]
            logger.info(
                f"State after set: mcs_credit_total={self.mcs_credit_total}, "  # type: ignore[attr-defined]
                f"mcs_credit_rows={self.mcs_credit_rows}"  # type: ignore[attr-defined]
            )
        else:
            logger.info("Credits panel: no credit_estimate or empty line_items, setting defaults")
            self.mcs_credit_rows = []  # type: ignore[attr-defined]
            self.mcs_credit_total = 0.0  # type: ignore[attr-defined]
            self.mcs_credit_assumptions = []  # type: ignore[attr-defined]

        # Custom findings for dynamic view
        self.mcs_custom_findings = self.report_custom_findings  # type: ignore[attr-defined]

        # ── Structured data for native panels ────────────────────────────────
        if timeline is not None:
            self._populate_conversation_data(timeline)
        if profile is not None:
            self._populate_profile_data(profile)
            self._populate_tools_data(profile)
            self._populate_knowledge_data(profile, timeline)
            self._populate_topics_data(profile, timeline)
            self._populate_model_data(profile)
        else:
            self._clear_panel_data()

        # Set default tab based on profile presence
        if profile is not None:
            self.mcs_analyse_tab = "profile"  # type: ignore[attr-defined]
        else:
            self.mcs_analyse_tab = "conversation"  # type: ignore[attr-defined]

    # ── Profile tab data extraction ──────────────────────────────────────────

    def _populate_profile_data(self, profile) -> None:
        """Extract structured data for the Profile tab."""
        # Classify components
        by_cat: dict[str, list] = {}
        for comp in profile.components:
            cat = _classify_component(comp)
            if cat:
                by_cat.setdefault(cat, []).append(comp)

        user_topics = by_cat.get("user_topics", [])
        tools = [c for c in profile.components if c.tool_type]

        # Quick wins
        quick_wins: list[dict] = []
        for comp in profile.components:
            if comp.kind == "DialogComponent" and comp.state != "Active":
                quick_wins.append({"severity": "warn", "icon": "alert-triangle", "text": f'Disabled topic: "{comp.display_name}"'})
        for comp in profile.components:
            if (
                comp.kind == "DialogComponent"
                and not comp.trigger_queries
                and comp.trigger_kind
                and comp.trigger_kind not in _SYSTEM_TRIGGERS
                and comp.trigger_kind not in _AUTOMATION_TRIGGERS
            ):
                quick_wins.append({"severity": "warn", "icon": "alert-triangle", "text": f'No trigger queries: "{comp.display_name}"'})
        for comp in profile.components:
            if comp.kind == "DialogComponent":
                desc = comp.description
                if desc is None or len(desc) < 10 or desc.strip() == comp.display_name.strip():
                    if desc is None:
                        _reason = "missing"
                    elif len(desc) < 10:
                        _reason = f'too short: "{desc}"'
                    else:
                        _reason = "matches display name"
                    quick_wins.append({"severity": "info", "icon": "info", "text": f'Weak description: "{comp.display_name}" — {_reason}'})
        trigger_kinds = {c.trigger_kind for c in profile.components if c.trigger_kind}
        for trigger in ("OnError", "OnUnknownIntent", "OnEscalate"):
            if trigger not in trigger_kinds:
                quick_wins.append({"severity": "warn", "icon": "alert-triangle", "text": f"Missing system topic: {trigger}"})
        conn_issues = validate_connections(profile)
        for issue in conn_issues:
            sev = "warn" if issue["severity"] == "warning" else "info"
            quick_wins.append({"severity": sev, "icon": "alert-triangle" if sev == "warn" else "info", "text": issue["message"]})

        # KPIs
        total_comps = sum(len(v) for k, v in by_cat.items() if k in _CATEGORY_ORDER)
        self.mcs_profile_kpis = [  # type: ignore[attr-defined]
            {"label": "Components", "value": str(total_comps), "hint": "Total config items", "tone": "neutral"},
            {"label": "User Topics", "value": str(len(user_topics)), "hint": "Trigger-based", "tone": "neutral"},
            {"label": "Tools", "value": str(len(tools)), "hint": "Agent tools", "tone": "neutral"},
            {"label": "Quick Wins", "value": str(len(quick_wins)), "hint": "Actionable issues", "tone": "warn" if quick_wins else "neutral"},
        ]

        # AI Configuration
        ai_config: list[dict] = []
        instructions_len = ""
        starters: list[dict] = []
        if profile.gpt_info:
            gpt = profile.gpt_info
            if gpt.model_hint:
                ai_config.append({"property": "Model", "value": gpt.model_hint})
            if gpt.knowledge_sources_kind:
                ai_config.append({"property": "Knowledge Sources", "value": gpt.knowledge_sources_kind})
            ai_config.append({"property": "Web Browsing", "value": "Yes" if gpt.web_browsing else "No"})
            ai_config.append({"property": "Code Interpreter", "value": "Yes" if gpt.code_interpreter else "No"})
            if gpt.instructions:
                instructions_len = f"{len(gpt.instructions):,} chars"
                ai_config.append({"property": "Instructions", "value": instructions_len})
            starters = [{"title": s.get("title", "—"), "message": s.get("message", "—")} for s in gpt.conversation_starters]
        self.mcs_profile_ai_config = ai_config  # type: ignore[attr-defined]
        self.mcs_profile_instructions_len = instructions_len  # type: ignore[attr-defined]
        self.mcs_profile_starters = starters  # type: ignore[attr-defined]

        # Security chips
        auth_display = profile.authentication_mode
        if profile.authentication_trigger != "Unknown":
            auth_display += f" ({profile.authentication_trigger})"
        self.mcs_profile_security_chips = [  # type: ignore[attr-defined]
            {"title": "Auth Mode", "value": auth_display, "tone": "good" if profile.authentication_mode != "Unknown" else "info"},
            {"title": "Access Control", "value": profile.access_control_policy, "tone": "good" if profile.access_control_policy != "Unknown" else "info"},
            {"title": "Agent Connectable", "value": "Yes" if profile.is_agent_connectable else "No", "tone": "info"},
        ]

        # Bot metadata
        meta: list[dict] = [
            {"property": "Schema Name", "value": profile.schema_name},
            {"property": "Bot ID", "value": profile.bot_id},
            {"property": "Channels", "value": ", ".join(profile.channels) if profile.channels else "None"},
            {"property": "Recognizer", "value": profile.recognizer_kind},
            {"property": "Orchestrator", "value": "Yes" if profile.is_orchestrator else "No"},
            {"property": "Authentication", "value": auth_display},
            {"property": "Generative Actions", "value": "Enabled" if profile.generative_actions_enabled else "Disabled"},
        ]
        self.mcs_profile_bot_meta = meta  # type: ignore[attr-defined]

        # Environment variables
        self.mcs_profile_env_vars = [  # type: ignore[attr-defined]
            {
                "name": v.get("name", v.get("displayName", "—")),
                "type": v.get("type", "—"),
                "value": str(v.get("value", v.get("defaultValue", "—"))),
            }
            for v in profile.environment_variables
        ]

        # Connectors
        self.mcs_profile_connectors = [  # type: ignore[attr-defined]
            {
                "name": c.get("displayName", c.get("name", "—")),
                "type": c.get("type", c.get("kind", "—")),
                "description": (c.get("description") or "—")[:200],
            }
            for c in profile.connectors
        ]

        # Connection references
        conn_refs: list[dict] = []
        for ref in profile.connection_references:
            connector = ref.get("connectorId", "—")
            if "/" in connector:
                connector = connector.rsplit("/", 1)[-1]
            conn_refs.append({
                "name": ref.get("displayName", ref.get("connectionReferenceLogicalName", "—")),
                "connector": connector,
                "custom": "Yes" if ref.get("customConnectorId") else "No",
            })
        self.mcs_profile_conn_refs = conn_refs  # type: ignore[attr-defined]

        # Connector definitions
        self.mcs_profile_conn_defs = [  # type: ignore[attr-defined]
            {
                "name": cd.get("displayName", "—"),
                "type": cd.get("connectorType", "—"),
                "custom": "Yes" if cd.get("isCustom") else "No",
                "operations": str(cd.get("operationCount", 0)),
                "mcp": "Yes" if cd.get("hasMCP") else "No",
            }
            for cd in profile.connector_definitions
        ]

        # Quick wins + trigger overlaps
        self.mcs_profile_quick_wins = quick_wins  # type: ignore[attr-defined]
        overlaps = detect_trigger_overlaps(profile.components)
        self.mcs_profile_trigger_overlaps = [  # type: ignore[attr-defined]
            {
                "topic_a": o["topic_a"],
                "topic_b": o["topic_b"],
                "overlap_pct": f"{o['overlap_pct']}%",
                "shared_tokens": ", ".join(o["shared_tokens"][:8]),
            }
            for o in overlaps
        ]

    # ── Tools tab data extraction ────────────────────────────────────────────

    def _populate_tools_data(self, profile) -> None:
        """Extract structured data for the Tools tab."""
        tools = [c for c in profile.components if c.tool_type]
        connector_tools = sum(1 for t in tools if t.tool_type == "ConnectorTool")
        agent_tools = sum(1 for t in tools if t.tool_type in ("ChildAgent", "ConnectedAgent", "A2AAgent"))
        mcp_servers = sum(1 for t in tools if t.tool_type == "MCPServer")

        self.mcs_tools_kpis = [  # type: ignore[attr-defined]
            {"label": "Total Tools", "value": str(len(tools)), "hint": "Configured", "tone": "neutral"},
            {"label": "Connector Tools", "value": str(connector_tools), "hint": "API integrations", "tone": "neutral"},
            {"label": "Agent Tools", "value": str(agent_tools), "hint": "Child/Connected/A2A", "tone": "neutral"},
            {"label": "MCP Servers", "value": str(mcp_servers), "hint": "Model Context Protocol", "tone": "neutral"},
        ]

        _type_colors = {
            "ConnectorTool": "blue",
            "ChildAgent": "green",
            "ConnectedAgent": "teal",
            "A2AAgent": "cyan",
            "MCPServer": "purple",
            "FlowTool": "amber",
        }
        self.mcs_tools_rows = [  # type: ignore[attr-defined]
            {
                "name": t.display_name,
                "tool_type": t.tool_type or "—",
                "connector": t.connector_display_name or "—",
                "mode": t.connection_mode or "—",
                "state": t.state,
                "description": (t.description or t.model_description or "—")[:200],
                "type_color": _type_colors.get(t.tool_type or "", "gray"),
            }
            for t in tools
        ]

        # External calls detail (per-action rows from action_details, deduplicated)
        from collections import Counter
        raw_ext: list[tuple[str, str, str, str]] = []
        for c in profile.components:
            if c.kind == "DialogComponent" and c.has_external_calls and c.action_details:
                for detail in c.action_details:
                    raw_ext.append((
                        c.display_name,
                        detail.get("kind", "—"),
                        detail.get("connector_display_name") or detail.get("connection_reference") or "—",
                        detail.get("operation_id") or "—",
                    ))
        ext_rows: list[dict] = []
        for (topic, kind, connector, operation), count in Counter(raw_ext).items():
            op_display = f"{operation} (×{count})" if count > 1 else operation
            ext_rows.append({
                "topic": topic,
                "kind": kind,
                "connector": connector,
                "operation": op_display,
            })
        self.mcs_tools_external_calls = ext_rows  # type: ignore[attr-defined]

        # Mermaid integration map — extract raw source without fences
        int_map = render_integration_map(profile)
        if int_map:
            # Strip ```mermaid and ``` fences
            lines = int_map.split("\n")
            mermaid_lines: list[str] = []
            in_fence = False
            for line in lines:
                if line.strip() == "```mermaid":
                    in_fence = True
                    continue
                if line.strip() == "```" and in_fence:
                    in_fence = False
                    continue
                if in_fence:
                    mermaid_lines.append(line)
            self.mcs_tools_mermaid = "\n".join(mermaid_lines)  # type: ignore[attr-defined]
        else:
            self.mcs_tools_mermaid = ""  # type: ignore[attr-defined]

    # ── Knowledge tab data extraction ────────────────────────────────────────

    def _populate_knowledge_data(self, profile, timeline) -> None:
        """Extract structured data for the Knowledge tab."""
        ks_comps = [c for c in profile.components if c.kind == "KnowledgeSourceComponent"]
        file_comps = [c for c in profile.components if c.kind == "FileAttachmentComponent"]
        searches = timeline.knowledge_searches if timeline is not None else []
        custom_steps = getattr(timeline, "custom_search_steps", []) if timeline is not None else []

        active_count = sum(1 for c in ks_comps + file_comps if c.state == "Active")
        self.mcs_knowledge_kpis = [  # type: ignore[attr-defined]
            {"label": "Knowledge Sources", "value": str(len(ks_comps)), "hint": "Configured sources", "tone": "neutral"},
            {"label": "File Attachments", "value": str(len(file_comps)), "hint": "Uploaded files", "tone": "neutral"},
            {"label": "Active", "value": str(active_count), "hint": "Currently enabled", "tone": "neutral"},
            {"label": "Searches", "value": str(len(searches)), "hint": "In this session", "tone": "neutral"},
        ]

        # Knowledge sources table
        self.mcs_knowledge_sources = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "source_type": c.source_kind or "—",
                "site": c.source_site or "—",
                "status": "Active" if c.state == "Active" else "Inactive",
                "status_tone": "good" if c.state == "Active" else "bad",
                "trigger": c.trigger_condition_raw or "auto",
            }
            for c in ks_comps
        ]

        # File attachments table
        self.mcs_knowledge_files = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "file_type": c.file_type or "—",
                "status": "Active" if c.state == "Active" else "Inactive",
                "status_tone": "good" if c.state == "Active" else "bad",
            }
            for c in file_comps
        ]

        # Coverage table
        coverage: list[dict] = []
        for comp in ks_comps + file_comps:
            source_type = comp.source_kind or comp.file_type or comp.kind.replace("Component", "")
            trigger = comp.trigger_condition_raw or "—"
            notes_parts: list[str] = []
            if comp.state != "Active":
                notes_parts.append("Inactive")
            if trigger in ("false", "False"):
                notes_parts.append("Trigger disabled")
            elif trigger in ("—", "None"):
                notes_parts.append("Always-on")
            coverage.append({
                "name": comp.display_name,
                "source_type": source_type,
                "state": comp.state,
                "trigger": trigger,
                "notes": "; ".join(notes_parts) if notes_parts else "—",
            })
        self.mcs_knowledge_coverage = coverage  # type: ignore[attr-defined]

        # Source details
        self.mcs_knowledge_source_details = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "source_type": c.source_kind or "—",
                "site": c.source_site or "—",
                "description": c.description or "",
            }
            for c in ks_comps
            if c.description or c.source_kind
        ]

        # Search results
        search_rows: list[dict] = []
        for i, ks in enumerate(searches, 1):
            badge, label = _grounding_score(ks)
            grounding_tone = "good" if label == "Strong" else ("info" if label == "Moderate" else "bad")
            dur_ms = _parse_execution_time_ms(ks.execution_time)
            dur = _format_duration(dur_ms) if dur_ms is not None else (ks.execution_time or "—")
            eff = _source_efficiency(ks)
            # Flatten results into a displayable summary string
            result_count = len(ks.search_results)
            result_lines: list[str] = []
            for j, r in enumerate(ks.search_results[:5], 1):
                title = r.name or r.url or f"Result {j}"
                snippet_len = len(r.text or "")
                quality_icon = "🟢" if snippet_len >= 200 else ("🟡" if snippet_len >= 50 else "🔴")
                snippet = (r.text or "").replace("\n", " ")
                result_lines.append(f"{quality_icon} {j}. {title}" + (f" — {snippet}" if snippet else ""))
            results_text = "\n".join(result_lines) if result_lines else ""
            # Clean up efficiency string (strip markdown)
            eff_clean = ""
            if eff:
                eff_clean = eff.replace("**", "").replace("`", "").replace("🟢 ", "").replace("🟡 ", "").replace("🔴 ", "").replace("⚫ ", "")
            search_rows.append({
                "index": str(i),
                "query": ks.search_query or "—",
                "keywords": ks.search_keywords or "—",
                "sources": ", ".join(ks.knowledge_sources) if ks.knowledge_sources else "—",
                "duration": dur,
                "grounding_label": f"{badge} {label}",
                "grounding_tone": grounding_tone,
                "thought": ks.thought or "",
                "output_sources": ", ".join(ks.output_knowledge_sources) if ks.output_knowledge_sources else "",
                "efficiency": eff_clean,
                "errors": "; ".join(ks.search_errors) if ks.search_errors else "",
                "result_count": str(result_count),
                "results_text": results_text,
            })
        self.mcs_knowledge_searches = search_rows  # type: ignore[attr-defined]

        # Custom search steps
        self.mcs_knowledge_custom_steps = [  # type: ignore[attr-defined]
            {
                "name": cs.display_name,
                "status": cs.status,
                "thought": cs.thought or "",
                "error": cs.error or "",
                "duration": _format_duration(_parse_execution_time_ms(cs.execution_time) or 0),
            }
            for cs in custom_steps
        ]

        # General knowledge flag
        self.mcs_knowledge_general_enabled = bool(  # type: ignore[attr-defined]
            profile.ai_settings and profile.ai_settings.use_model_knowledge
        )

    # ── Topics tab data extraction ───────────────────────────────────────────

    def _populate_topics_data(self, profile, timeline) -> None:
        """Extract structured data for the Topics tab."""
        from models import EventType

        by_cat: dict[str, list] = {}
        for comp in profile.components:
            cat = _classify_component(comp)
            if cat:
                by_cat.setdefault(cat, []).append(comp)

        user_topics = by_cat.get("user_topics", [])
        system_topics = by_cat.get("system_topics", []) + by_cat.get("automation_topics", [])
        orch_topics = by_cat.get("orchestrator_topics", [])

        # KPIs
        external_calls_total = sum(1 for c in profile.components if c.kind == "DialogComponent" and c.has_external_calls)
        self.mcs_topics_kpis = [  # type: ignore[attr-defined]
            {"label": "User Topics", "value": str(len(user_topics)), "hint": "Trigger-based", "tone": "neutral"},
            {"label": "System Topics", "value": str(len(system_topics)), "hint": "System + Automation", "tone": "neutral"},
            {"label": "Orchestrator", "value": str(len(orch_topics)), "hint": "Task/Agent dialogs", "tone": "neutral"},
            {"label": "External Calls", "value": str(external_calls_total), "hint": "Topics with actions", "tone": "neutral"},
        ]

        # Category summary
        cat_order = ["user_topics", "system_topics", "automation_topics", "orchestrator_topics", "skills", "custom_entities", "variables", "settings"]
        cat_display = {
            "user_topics": ("User Topics", "user-round"),
            "system_topics": ("System Topics", "settings"),
            "automation_topics": ("Automation Topics", "bot"),
            "orchestrator_topics": ("Orchestrator Topics", "network"),
            "skills": ("Skills & Connectors", "puzzle"),
            "custom_entities": ("Custom Entities", "database"),
            "variables": ("Variables", "variable"),
            "settings": ("Settings", "sliders"),
        }
        summary_rows: list[dict] = []
        for cat in cat_order:
            comps = by_cat.get(cat, [])
            if not comps:
                continue
            display, icon = cat_display.get(cat, (cat, "list"))
            active = sum(1 for c in comps if c.state == "Active")
            summary_rows.append({
                "category": display,
                "count": str(len(comps)),
                "active": str(active),
                "inactive": str(len(comps) - active),
                "icon": icon,
            })
        self.mcs_topics_summary = summary_rows  # type: ignore[attr-defined]

        # User topics detail
        self.mcs_topics_user_rows = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "schema": c.schema_name,
                "state": c.state,
                "triggers": ", ".join(c.trigger_queries[:3]) + ("..." if len(c.trigger_queries) > 3 else "") if c.trigger_queries else "—",
                "description": (c.description or "—")[:150],
            }
            for c in user_topics
        ]

        # Orchestrator topics detail
        self.mcs_topics_orch_rows = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "state": c.state,
                "tool_type": c.tool_type or c.action_kind or "—",
                "connector": c.connector_display_name or "—",
                "mode": c.connection_mode or "—",
            }
            for c in orch_topics
        ]

        # System/automation topics detail
        self.mcs_topics_system_rows = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "schema": c.schema_name,
                "state": c.state,
                "trigger": c.trigger_kind or "—",
            }
            for c in system_topics
        ]

        # External calls (moved to Tools tab — just clear this legacy var)
        self.mcs_topics_external_calls = []  # type: ignore[attr-defined]

        # Coverage
        dialog_comps = [
            c for c in profile.components
            if c.kind == "DialogComponent"
            and c.trigger_kind not in (_SYSTEM_TRIGGERS | _AUTOMATION_TRIGGERS | {None})
            and c.dialog_kind not in ("TaskDialog", "AgentDialog")
        ]
        if timeline is not None:
            triggered_names = {
                ev.topic_name for ev in timeline.events
                if ev.event_type == EventType.STEP_TRIGGERED and ev.topic_name
            }
        else:
            triggered_names = set()
        triggered_count = sum(1 for c in dialog_comps if c.display_name in triggered_names)
        untriggered = [c for c in dialog_comps if c.display_name not in triggered_names]
        self.mcs_topics_coverage_summary = f"{triggered_count} of {len(dialog_comps)} user topics triggered"  # type: ignore[attr-defined]
        self.mcs_topics_coverage = [  # type: ignore[attr-defined]
            {
                "name": c.display_name,
                "state": c.state,
                "has_external_calls": "Yes" if c.has_external_calls else "No",
            }
            for c in untriggered
        ]

        # Trigger phrase analysis + topic lifecycles + orchestrator decisions (Routing tab)
        if timeline is not None:
            self.mcs_topics_trigger_matches = build_trigger_match_items(timeline, profile)  # type: ignore[attr-defined]
            self.mcs_routing_lifecycles = build_topic_lifecycles(timeline)  # type: ignore[attr-defined]
            self.mcs_routing_decisions = build_orchestrator_decision_timeline(timeline, profile=profile)  # type: ignore[attr-defined]
            self.mcs_routing_plan_evolution = build_plan_evolution(timeline, profile=profile)  # type: ignore[attr-defined]
        else:
            self.mcs_topics_trigger_matches = []  # type: ignore[attr-defined]
            self.mcs_routing_lifecycles = []  # type: ignore[attr-defined]
            self.mcs_routing_decisions = []  # type: ignore[attr-defined]
            self.mcs_routing_plan_evolution = []  # type: ignore[attr-defined]

        # Graph anomalies
        anomalies = detect_topic_graph_anomalies(profile)
        self.mcs_topics_anomalies = [  # type: ignore[attr-defined]
            {"title": "Orphaned Topics", "value": str(anomalies["orphaned"]), "tone": "bad" if anomalies["orphaned"] > 0 else "good"},
            {"title": "Dead Ends", "value": str(anomalies["dead_ends"]), "tone": "bad" if anomalies["dead_ends"] > 0 else "good"},
            {"title": "Cycles", "value": str(anomalies["cycles"]), "tone": "bad" if anomalies["cycles"] > 0 else "good"},
        ]

        # Mermaid topic graph — extract raw source
        topic_graph = render_topic_graph(profile)
        if topic_graph:
            lines = topic_graph.split("\n")
            mermaid_lines: list[str] = []
            in_fence = False
            for line in lines:
                if line.strip() == "```mermaid":
                    in_fence = True
                    continue
                if line.strip() == "```" and in_fence:
                    in_fence = False
                    continue
                if in_fence:
                    mermaid_lines.append(line)
            self.mcs_topics_mermaid = "\n".join(mermaid_lines)  # type: ignore[attr-defined]
        else:
            self.mcs_topics_mermaid = ""  # type: ignore[attr-defined]

    # ── Model tab data extraction ────────────────────────────────────────────

    def _populate_model_data(self, profile) -> None:
        """Extract structured data for the Model tab."""
        hint = profile.gpt_info.model_hint if profile.gpt_info else None
        cat_key = _resolve_catalogue_key(hint)
        entry = _MODEL_CATALOGUE.get(cat_key) if cat_key else None

        if entry:
            self.mcs_model_kpis = [  # type: ignore[attr-defined]
                {"label": "Model", "value": entry["display"], "hint": hint or "—", "tone": "neutral"},
                {"label": "Tier", "value": entry["tier"], "hint": "Model category", "tone": "neutral"},
                {"label": "Context Window", "value": entry["context_window"], "hint": "Max tokens", "tone": "neutral"},
                {"label": "Cost Tier", "value": entry["cost_tier"], "hint": "Relative cost", "tone": "neutral"},
            ]
            self.mcs_model_configured = [  # type: ignore[attr-defined]
                {"property": "Model", "value": entry["display"]},
                {"property": "Tier", "value": entry["tier"]},
                {"property": "Context Window", "value": entry["context_window"]},
                {"property": "Cost Tier", "value": entry["cost_tier"]},
            ]
            self.mcs_model_strengths = entry.get("strengths", [])  # type: ignore[attr-defined]
            self.mcs_model_limitations = entry.get("limitations", [])  # type: ignore[attr-defined]
            self.mcs_model_recommendation = entry.get("recommendation", "")  # type: ignore[attr-defined]
        else:
            display = hint or "Unknown"
            self.mcs_model_kpis = [  # type: ignore[attr-defined]
                {"label": "Model", "value": display, "hint": "Configured model", "tone": "neutral"},
                {"label": "Tier", "value": "Unknown", "hint": "Not in catalogue", "tone": "info"},
                {"label": "Context Window", "value": "—", "hint": "", "tone": "neutral"},
                {"label": "Cost Tier", "value": "—", "hint": "", "tone": "neutral"},
            ]
            self.mcs_model_configured = [{"property": "Model Hint", "value": display}]  # type: ignore[attr-defined]
            self.mcs_model_strengths = []  # type: ignore[attr-defined]
            self.mcs_model_limitations = []  # type: ignore[attr-defined]
            self.mcs_model_recommendation = ""  # type: ignore[attr-defined]

        # Full catalogue
        catalogue: list[dict] = []
        for key, info in _MODEL_CATALOGUE.items():
            catalogue.append({
                "model": info["display"],
                "tier": info["tier"],
                "context": info["context_window"],
                "cost": info["cost_tier"],
                "is_current": "yes" if key == cat_key else "no",
            })
        self.mcs_model_catalogue = catalogue  # type: ignore[attr-defined]

    # ── Conversation tab data extraction ────────────────────────────────────

    def _populate_conversation_data(self, timeline) -> None:
        """Extract structured data for the Conversation detail panel."""
        from models import EventType

        # Metadata
        self.mcs_conv_metadata = [  # type: ignore[attr-defined]
            {"property": "Bot Name", "value": timeline.bot_name or "—"},
            {"property": "Conversation ID", "value": timeline.conversation_id or "—"},
            {"property": "User Query", "value": timeline.user_query or "—"},
            {"property": "Total Elapsed", "value": _format_duration(timeline.total_elapsed_ms) if timeline.total_elapsed_ms else "—"},
        ]

        # Phase breakdown
        total_ms = timeline.total_elapsed_ms or 0.0
        _phase_status_tone = {"completed": "good", "failed": "bad"}
        self.mcs_conv_phases = [  # type: ignore[attr-defined]
            {
                "label": p.label,
                "phase_type": p.phase_type,
                "duration": _format_duration(p.duration_ms),
                "pct": _pct(p.duration_ms, total_ms),
                "status": p.state,
                "status_tone": _phase_status_tone.get(p.state, "info"),
            }
            for p in timeline.phases
        ]

        # Event log
        _event_type_colors: dict[str, str] = {
            "USER_MESSAGE": "green",
            "BOT_MESSAGE": "green",
            "PLAN_RECEIVED": "blue",
            "PLAN_FINISHED": "blue",
            "STEP_TRIGGERED": "teal",
            "STEP_FINISHED": "teal",
            "KNOWLEDGE_SEARCH": "amber",
            "ERROR": "red",
            "ACTION_HTTP_REQUEST": "purple",
            "ACTION_QA": "purple",
            "ACTION_TRIGGER_EVAL": "purple",
            "DIALOG_TRACING": "gray",
            "DIALOG_REDIRECT": "gray",
        }
        self.mcs_conv_event_log = [  # type: ignore[attr-defined]
            {
                "index": str(i),
                "position": str(ev.position),
                "event_type": ev.event_type.name,
                "summary": ev.summary[:200],
                "type_color": _event_type_colors.get(ev.event_type.name, "gray"),
            }
            for i, ev in enumerate(timeline.events, 1)
        ]

        # Errors
        self.mcs_conv_errors = list(timeline.errors)  # type: ignore[attr-defined]

        # Orchestrator reasoning — enriched with finish data
        import re as _re_reason

        # Build finish lookup by step_id
        finish_lookup: dict[str, object] = {}
        for _fev in timeline.events:
            if _fev.event_type == EventType.STEP_FINISHED and _fev.step_id:
                finish_lookup[_fev.step_id] = _fev

        reasoning: list[dict] = []
        step_num = 0
        last_ask = ""
        for ev in timeline.events:
            # Track preceding PlanReceivedDebug for orchestrator_ask
            if ev.event_type == EventType.PLAN_RECEIVED_DEBUG and ev.orchestrator_ask:
                last_ask = ev.orchestrator_ask

            if ev.event_type == EventType.STEP_TRIGGERED and ev.thought:
                step_num += 1
                # Parse step_type from summary parenthetical
                _st_m = _re_reason.search(r"\((\w+)\)", ev.summary or "")
                step_type = _st_m.group(1) if _st_m else ""

                # Pair with finish event
                fin_ev = finish_lookup.get(ev.step_id) if ev.step_id else None
                fin_status = ""
                fin_error = ""
                fin_has_recs = ""
                fin_used_outputs = ""
                duration_label = ""
                if fin_ev:
                    fin_status = fin_ev.state or ""
                    fin_error = fin_ev.error or ""
                    if fin_ev.has_recommendations:
                        fin_has_recs = "true"
                    fin_used_outputs = fin_ev.plan_used_outputs or ""
                    dur_ms = _ms_between_iso(ev.timestamp, fin_ev.timestamp)
                    if dur_ms > 0:
                        duration_label = f"{dur_ms:.0f}ms"

                # Merge has_recommendations from trigger or finish
                has_recs = "true" if ev.has_recommendations or fin_has_recs else ""

                reasoning.append({
                    "step": str(step_num),
                    "topic": ev.topic_name or "—",
                    "reasoning": ev.thought,
                    "step_type": step_type,
                    "orchestrator_ask": last_ask,
                    "status": fin_status,
                    "duration": duration_label,
                    "error": fin_error,
                    "has_recommendations": has_recs,
                    "used_outputs": fin_used_outputs,
                })
        self.mcs_conv_reasoning = reasoning  # type: ignore[attr-defined]

        # Mermaid diagrams — strip fences
        def _strip_mermaid_fences(md: str) -> str:
            lines = md.split("\n")
            result: list[str] = []
            in_fence = False
            for line in lines:
                if line.strip() == "```mermaid":
                    in_fence = True
                    continue
                if line.strip() == "```" and in_fence:
                    in_fence = False
                    continue
                if in_fence:
                    result.append(line)
            return "\n".join(result)

        seq = render_mermaid_sequence(timeline)
        self.mcs_conv_sequence_mermaid = _strip_mermaid_fences(seq) if seq else ""  # type: ignore[attr-defined]

        gantt = render_gantt_chart(timeline)
        self.mcs_conv_gantt_mermaid = _strip_mermaid_fences(gantt) if gantt else ""  # type: ignore[attr-defined]

    # ── Clear all panel data ─────────────────────────────────────────────────

    def _clear_panel_data(self) -> None:
        """Reset all structured panel state vars."""
        self.mcs_profile_kpis = []  # type: ignore[attr-defined]
        self.mcs_profile_ai_config = []  # type: ignore[attr-defined]
        self.mcs_profile_instructions_len = ""  # type: ignore[attr-defined]
        self.mcs_profile_starters = []  # type: ignore[attr-defined]
        self.mcs_profile_security_chips = []  # type: ignore[attr-defined]
        self.mcs_profile_bot_meta = []  # type: ignore[attr-defined]
        self.mcs_profile_env_vars = []  # type: ignore[attr-defined]
        self.mcs_profile_connectors = []  # type: ignore[attr-defined]
        self.mcs_profile_conn_refs = []  # type: ignore[attr-defined]
        self.mcs_profile_conn_defs = []  # type: ignore[attr-defined]
        self.mcs_profile_quick_wins = []  # type: ignore[attr-defined]
        self.mcs_profile_trigger_overlaps = []  # type: ignore[attr-defined]
        self.mcs_tools_kpis = []  # type: ignore[attr-defined]
        self.mcs_tools_rows = []  # type: ignore[attr-defined]
        self.mcs_tools_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_tools_external_calls = []  # type: ignore[attr-defined]
        self.mcs_knowledge_kpis = []  # type: ignore[attr-defined]
        self.mcs_knowledge_sources = []  # type: ignore[attr-defined]
        self.mcs_knowledge_files = []  # type: ignore[attr-defined]
        self.mcs_knowledge_coverage = []  # type: ignore[attr-defined]
        self.mcs_knowledge_source_details = []  # type: ignore[attr-defined]
        self.mcs_knowledge_searches = []  # type: ignore[attr-defined]
        self.mcs_knowledge_custom_steps = []  # type: ignore[attr-defined]
        self.mcs_knowledge_general_enabled = False  # type: ignore[attr-defined]
        self.mcs_topics_kpis = []  # type: ignore[attr-defined]
        self.mcs_topics_summary = []  # type: ignore[attr-defined]
        self.mcs_topics_user_rows = []  # type: ignore[attr-defined]
        self.mcs_topics_orch_rows = []  # type: ignore[attr-defined]
        self.mcs_topics_system_rows = []  # type: ignore[attr-defined]
        self.mcs_topics_external_calls = []  # type: ignore[attr-defined]
        self.mcs_topics_coverage = []  # type: ignore[attr-defined]
        self.mcs_topics_coverage_summary = ""  # type: ignore[attr-defined]
        self.mcs_topics_anomalies = []  # type: ignore[attr-defined]
        self.mcs_topics_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_topics_trigger_matches = []  # type: ignore[attr-defined]
        self.mcs_routing_lifecycles = []  # type: ignore[attr-defined]
        self.mcs_routing_decisions = []  # type: ignore[attr-defined]
        self.mcs_routing_plan_evolution = []  # type: ignore[attr-defined]
        self.mcs_model_kpis = []  # type: ignore[attr-defined]
        self.mcs_model_configured = []  # type: ignore[attr-defined]
        self.mcs_model_strengths = []  # type: ignore[attr-defined]
        self.mcs_model_limitations = []  # type: ignore[attr-defined]
        self.mcs_model_recommendation = ""  # type: ignore[attr-defined]
        self.mcs_model_catalogue = []  # type: ignore[attr-defined]
        self.mcs_conv_metadata = []  # type: ignore[attr-defined]
        self.mcs_conv_phases = []  # type: ignore[attr-defined]
        self.mcs_conv_event_log = []  # type: ignore[attr-defined]
        self.mcs_conv_errors = []  # type: ignore[attr-defined]
        self.mcs_conv_reasoning = []  # type: ignore[attr-defined]
        self.mcs_conv_sequence_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_conv_gantt_mermaid = ""  # type: ignore[attr-defined]

    def new_upload(self):
        self.report_markdown = ""  # type: ignore[attr-defined]
        self.report_title = ""  # type: ignore[attr-defined]
        self.report_source = ""  # type: ignore[attr-defined]
        self.upload_error = ""
        self.paste_json = ""
        self.bot_profile_json = ""  # type: ignore[attr-defined]
        self.report_custom_findings = []  # type: ignore[attr-defined]
        _clear_bot_profile()
        self.lint_report_markdown = ""  # type: ignore[attr-defined]
        self.is_linting = False  # type: ignore[attr-defined]
        self.lint_error = ""  # type: ignore[attr-defined]
        # Clear dynamic analysis state
        self.mcs_section_profile = ""  # type: ignore[attr-defined]
        self.mcs_section_knowledge = ""  # type: ignore[attr-defined]
        self.mcs_section_tools = ""  # type: ignore[attr-defined]
        self.mcs_section_topics = ""  # type: ignore[attr-defined]
        self.mcs_section_model_comparison = ""  # type: ignore[attr-defined]
        self.mcs_section_conversation = ""  # type: ignore[attr-defined]
        self.mcs_section_credits = ""  # type: ignore[attr-defined]
        self.mcs_conversation_flow = []  # type: ignore[attr-defined]
        self.mcs_conversation_flow_source = ""  # type: ignore[attr-defined]
        self.mcs_conv_kpis = []  # type: ignore[attr-defined]
        self.mcs_conv_event_mix = []  # type: ignore[attr-defined]
        self.mcs_conv_latency_bands = []  # type: ignore[attr-defined]
        self.mcs_conv_highlights = []  # type: ignore[attr-defined]
        self.mcs_credit_rows = []  # type: ignore[attr-defined]
        self.mcs_credit_total = 0.0  # type: ignore[attr-defined]
        self.mcs_credit_assumptions = []  # type: ignore[attr-defined]
        self.mcs_custom_findings = []  # type: ignore[attr-defined]
        self.mcs_conv_metadata = []  # type: ignore[attr-defined]
        self.mcs_conv_phases = []  # type: ignore[attr-defined]
        self.mcs_conv_event_log = []  # type: ignore[attr-defined]
        self.mcs_conv_errors = []  # type: ignore[attr-defined]
        self.mcs_conv_reasoning = []  # type: ignore[attr-defined]
        self.mcs_conv_sequence_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_conv_gantt_mermaid = ""  # type: ignore[attr-defined]
        self._clear_panel_data()
        return rx.redirect("/dashboard")

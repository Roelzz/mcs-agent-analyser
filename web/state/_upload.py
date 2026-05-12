import json
import tempfile
import zipfile
from pathlib import Path

import reflex as rx
from loguru import logger

from exports.citations_csv import render_citations_csv  # noqa: E402
from instruction_store import save_snapshot  # noqa: E402
from model_comparison import _MODEL_CATALOGUE, _resolve_catalogue_key  # noqa: E402
from models import ConversationTimeline  # noqa: E402
from parser import detect_trigger_overlaps, parse_dialog_json, parse_yaml, validate_connections  # noqa: E402
from renderer import render_instruction_drift, render_report, render_transcript_report  # noqa: E402
from renderer._helpers import _format_duration, _parse_execution_time_ms, _pct  # noqa: E402
from renderer.timeline_render import render_gantt_chart, render_mermaid_sequence  # noqa: E402
from renderer.knowledge import _classify_trace_outcome, _grounding_score, _source_efficiency  # noqa: E402
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
    build_performance_waterfall,
    build_plan_evolution,
    build_topic_lifecycles,
    build_trigger_match_items,
    render_report_sections,
)
from timeline import build_timeline  # noqa: E402
from transcript import parse_transcript_json  # noqa: E402
from utils import safe_extractall  # noqa: E402

from web.state._base import _clear_bot_profile, _save_bot_profile


from renderer.dynamic_data import build_citation_panel_rows, build_variable_tracker_rows  # noqa: E402,F401 — re-exported


def _describe_ai_model_fields(schema: dict) -> list[str]:
    """Flatten an `aIModelDefinitions.inputType`/`outputType` JSON-schema-ish
    dict into a list of field names for display. Mirrors the helper in
    `renderer/prompts.py` so the dashboard and the markdown report show the
    same labels."""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        return list(props.keys())
    inner = schema.get("schema")
    if isinstance(inner, dict):
        inner_props = inner.get("properties")
        if isinstance(inner_props, dict) and inner_props:
            return list(inner_props.keys())
    return [k for k in schema.keys() if k not in {"type", "kind"}]


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
            paste_text = self.paste_json.strip()

            if len(files) == 1 and exts[0] == ".zip":
                if paste_text:
                    # Zip already contains a dialog.json — paste is ignored.
                    self.upload_error = "Note: pasted JSON ignored — using the dialog.json inside the zip instead."
                self.upload_stage = "Extracting and parsing bot export..."
                yield
                await self._process_bot_zip(files)
            elif len(files) == 2:
                has_yaml = any(e in (".yml", ".yaml") for e in exts)
                has_json = any(e == ".json" for e in exts)
                if has_yaml and has_json:
                    if paste_text:
                        # Two-file upload already has its own json — paste ignored.
                        self.upload_error = "Note: pasted JSON ignored — using the uploaded dialog.json instead."
                    self.upload_stage = "Parsing bot configuration..."
                    yield
                    await self._process_bot_files(files)
                else:
                    self.upload_error = (
                        f"Two files uploaded but expected botContent.yml + dialog.json. Got: {', '.join(names)}"
                    )
            elif len(files) == 1 and exts[0] in (".yml", ".yaml") and paste_text:
                # The combined case — uploaded yml + pasted dialog json.
                # Validate the paste before running the pipeline so a bad
                # paste produces a useful error rather than a parser crash.
                try:
                    json.loads(paste_text)
                except json.JSONDecodeError as e:
                    self.upload_error = f"Invalid pasted JSON: {e}"
                    return
                self.upload_stage = "Parsing bot configuration + pasted transcript..."
                yield
                await self._process_yml_plus_paste(files[0], paste_text)
                self.paste_json = ""
            elif len(files) == 1 and exts[0] == ".json":
                self.upload_stage = "Parsing transcript..."
                yield
                await self._process_transcript(files)
            elif len(files) == 1 and exts[0] in (".yml", ".yaml"):
                # Single yml without a paired dialog — surface the same error
                # as before but point at the paste path so the user sees the
                # combine option.
                self.upload_error = (
                    "botContent.yml uploaded but no dialog.json — pair it with "
                    "a pasted transcript JSON below, or upload both files together."
                )
            else:
                self.upload_error = (
                    "Could not detect upload type. Accepted formats:\n"
                    "- 1 .zip file (bot export)\n"
                    "- botContent.yml + dialog.json (2 files, OR one yml + a pasted transcript)\n"
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
    async def handle_paste_submit(self, files: list[rx.UploadFile]):
        """Triggered by the "Paste & Analyse" button. Receives any files
        currently held in the upload drop zone alongside `self.paste_json`,
        so a user who dropped a `botContent.yml` and pasted `dialog.json`
        can click EITHER button to get the full analysis.
        """
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
        yield

        # If a single yml file is also uploaded, run the combined pipeline.
        yml_files = [f for f in (files or []) if (f.filename or "").lower().endswith((".yml", ".yaml"))]
        non_yml_files = [f for f in (files or []) if not (f.filename or "").lower().endswith((".yml", ".yaml"))]

        try:
            if len(yml_files) == 1 and not non_yml_files:
                self.upload_stage = "Parsing bot configuration + pasted transcript..."
                yield
                await self._process_yml_plus_paste(yml_files[0], text)
                self.paste_json = ""
            else:
                # Transcript-only fallback (legacy paste behaviour).
                self.upload_stage = "Parsing transcript..."
                yield
                with tempfile.TemporaryDirectory() as tmpdir:
                    json_path = Path(tmpdir) / "pasted_transcript.json"
                    json_path.write_text(text, encoding="utf-8")

                    activities, metadata = parse_transcript_json(json_path)
                    timeline = build_timeline(activities, {})
                    title = "Pasted Transcript"
                    self.report_markdown = render_transcript_report(title, timeline, metadata)  # type: ignore[attr-defined]
                    self.report_title = title  # type: ignore[attr-defined]
                    self.report_source = "upload"  # type: ignore[attr-defined]
                    self.lint_report_markdown = ""  # type: ignore[attr-defined]
                    self.bot_profile_json = ""  # type: ignore[attr-defined]
                    self.timeline_json = ""  # type: ignore[attr-defined]
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

    def _finalize_full_analysis(self, profile, timeline) -> None:
        """Apply the shared post-parse bookkeeping for any "full" (profile +
        timeline) upload path: render the report, persist the profile, run
        custom rules, take an instruction-drift snapshot, and populate the
        dynamic-tab sections. Used by `_process_bot_zip`,
        `_process_bot_files`, and `_process_yml_plus_paste` so the three
        full-analysis paths cannot drift apart.
        """
        self.report_markdown = render_report(profile, timeline)  # type: ignore[attr-defined]
        self.report_title = profile.display_name  # type: ignore[attr-defined]
        self.report_source = "upload"  # type: ignore[attr-defined]
        self.bot_profile_json = profile.model_dump_json()  # type: ignore[attr-defined]
        # Persist the parsed timeline so transcript-based audit modes
        # (sentiment, PII, accuracy, routing quality) can rehydrate it
        # without re-parsing the dialog.json.
        self.timeline_json = timeline.model_dump_json() if timeline is not None else ""  # type: ignore[attr-defined]
        _save_bot_profile(self.bot_profile_json)  # type: ignore[attr-defined]
        self._evaluate_custom_rules(profile)  # type: ignore[attr-defined]

        instruction_diff = save_snapshot(profile)
        if instruction_diff and instruction_diff.is_significant:
            self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]

        self._populate_dynamic_sections(profile, timeline, "snapshot")

        if instruction_diff and instruction_diff.is_significant:
            self.mcs_profile_instruction_drift = {  # type: ignore[attr-defined]
                "change_ratio": f"{instruction_diff.change_ratio:.0%}",
                "unified_diff": instruction_diff.unified_diff or "",
                "is_significant": "true",
            }
        else:
            self.mcs_profile_instruction_drift = {}  # type: ignore[attr-defined]

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
            timeline = build_timeline(activities, schema_lookup, profile=profile)
            self._finalize_full_analysis(profile, timeline)

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
            timeline = build_timeline(activities, schema_lookup, profile=profile)
            self._finalize_full_analysis(profile, timeline)

    async def _process_yml_plus_paste(self, yml_file: rx.UploadFile, paste_text: str):
        """Run the full bot+timeline pipeline using an uploaded `botContent.yml`
        and a pasted `dialog.json` string. Mirrors `_process_bot_files` but
        reads the JSON from text rather than a second uploaded file."""
        yml_data = await yml_file.read()
        with tempfile.TemporaryDirectory() as tmpdir:
            yml_path = Path(tmpdir) / (yml_file.filename or "botContent.yml")
            yml_path.write_bytes(yml_data)
            json_path = Path(tmpdir) / "pasted_dialog.json"
            json_path.write_text(paste_text, encoding="utf-8")

            profile, schema_lookup = parse_yaml(yml_path)
            activities = parse_dialog_json(json_path)
            timeline = build_timeline(activities, schema_lookup, profile=profile)
            self._finalize_full_analysis(profile, timeline)

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
            self.timeline_json = ""  # type: ignore[attr-defined]
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
            self.mcs_section_conversation = sections["conversation"]  # type: ignore[attr-defined]
            self.mcs_section_credits = sections["credits"]  # type: ignore[attr-defined]
        else:
            credit_estimate = None
            self.mcs_section_profile = ""  # type: ignore[attr-defined]
            self.mcs_section_knowledge = ""  # type: ignore[attr-defined]
            self.mcs_section_tools = ""  # type: ignore[attr-defined]
            self.mcs_section_conversation = ""  # type: ignore[attr-defined]
            self.mcs_section_credits = ""  # type: ignore[attr-defined]

        # Conversation flow + plan-tree groupings.
        if timeline is not None:
            from renderer.sections import group_flow_items

            flow_items = build_conversation_flow_items(timeline, profile=profile)
            self.mcs_conversation_flow = flow_items  # type: ignore[attr-defined]
            self.mcs_conversation_flow_groups = group_flow_items(flow_items)  # type: ignore[attr-defined]
        else:
            self.mcs_conversation_flow = []  # type: ignore[attr-defined]
            self.mcs_conversation_flow_groups = []  # type: ignore[attr-defined]
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
        if credit_estimate:
            self.mcs_credit_total = credit_estimate.total_credits  # type: ignore[attr-defined]
            self.mcs_credit_assumptions = credit_estimate.warnings  # type: ignore[attr-defined]
            if credit_estimate.line_items:
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
                # Per-step breakdown rows
                step_rows = []
                for i, item in enumerate(credit_estimate.line_items, 1):
                    step_rows.append(
                        {
                            "index": str(i),
                            "step_name": item.step_name,
                            "step_type": item.step_type,
                            "credits": f"{item.credits:.0f}",
                            "detail": item.detail or "",
                        }
                    )
                self.mcs_credit_step_rows = step_rows  # type: ignore[attr-defined]
                # Credit flow Mermaid
                from renderer.report import render_credit_estimate as _render_credit_md

                credit_md = _render_credit_md(credit_estimate, timeline) if timeline else ""
                # Extract mermaid source from the markdown
                mermaid_src = ""
                if "```mermaid" in credit_md:
                    _lines = credit_md.split("\n")
                    _in_fence = False
                    _mermaid_lines: list[str] = []
                    for _line in _lines:
                        if _line.strip() == "```mermaid":
                            _in_fence = True
                            continue
                        if _line.strip() == "```" and _in_fence:
                            _in_fence = False
                            continue
                        if _in_fence:
                            _mermaid_lines.append(_line)
                    mermaid_src = "\n".join(_mermaid_lines)
                self.mcs_credit_mermaid = mermaid_src  # type: ignore[attr-defined]
                logger.info(
                    f"State after set: mcs_credit_total={self.mcs_credit_total}, "  # type: ignore[attr-defined]
                    f"mcs_credit_rows={self.mcs_credit_rows}"  # type: ignore[attr-defined]
                )
            else:
                logger.info("Credits panel: no line_items, warnings preserved")
                self.mcs_credit_rows = []  # type: ignore[attr-defined]
                self.mcs_credit_step_rows = []  # type: ignore[attr-defined]
                self.mcs_credit_mermaid = ""  # type: ignore[attr-defined]
        else:
            logger.info("Credits panel: no credit_estimate, setting defaults")
            self.mcs_credit_rows = []  # type: ignore[attr-defined]
            self.mcs_credit_total = 0.0  # type: ignore[attr-defined]
            self.mcs_credit_assumptions = []  # type: ignore[attr-defined]
            self.mcs_credit_step_rows = []  # type: ignore[attr-defined]
            self.mcs_credit_mermaid = ""  # type: ignore[attr-defined]

        # Custom findings for dynamic view
        self.mcs_custom_findings = self.report_custom_findings  # type: ignore[attr-defined]

        # ── Structured data for native panels ────────────────────────────────
        if timeline is not None:
            self._populate_conversation_data(timeline, profile)
        if profile is not None:
            self._populate_profile_data(profile)
            self._populate_tools_data(profile, timeline)
            self._populate_knowledge_data(profile, timeline)
            self._populate_topics_data(profile, timeline)
            self._populate_model_data(profile)
        else:
            self._clear_panel_data()
            # Transcript-only: still populate runtime tool call data if available
            if timeline is not None and timeline.tool_calls:
                from renderer.tools import build_tool_call_analysis_data

                tool_data = build_tool_call_analysis_data(timeline)
                self.mcs_tools_call_count = len(timeline.tool_calls)  # type: ignore[attr-defined]
                self.mcs_tools_stats_rows = tool_data["stats_rows"]  # type: ignore[attr-defined]
                self.mcs_tools_flow_mermaid = tool_data["flow_mermaid"]  # type: ignore[attr-defined]
                self.mcs_tools_kpis = tool_data["kpis"]  # type: ignore[attr-defined]

        # ── Conversation analysis insights ─────────────────────────────────
        self._populate_insights_data(profile, timeline)

        # ── Coverage summary ───────────────────────────────────────────────
        # Walk every gated dashboard panel and record which ones will render
        # an empty-state card so the user gets a one-line summary instead of
        # silently missing sections.
        self._populate_coverage_summary(profile, timeline)

        # ── Raw event index (parser audit) ─────────────────────────────────
        # Surfaces every valueType / actionType / attachment kind the parser
        # saw in the source dialog so the user can verify "did the parser
        # actually see knowledge events?" instead of trusting empty panels.
        if timeline is not None:
            self.mcs_raw_event_index = self._flatten_raw_event_index(timeline.raw_event_index)  # type: ignore[attr-defined]
        else:
            self.mcs_raw_event_index = []  # type: ignore[attr-defined]

        # Set default tab based on profile presence
        if profile is not None:
            self.mcs_analyse_tab = "profile"  # type: ignore[attr-defined]
        else:
            self.mcs_analyse_tab = "conversation"  # type: ignore[attr-defined]

    def _populate_coverage_summary(self, profile, timeline) -> None:
        """Populate `mcs_coverage_skipped` based on which panels are empty.

        Reasons describe what the parser *looked for* and didn't match —
        they avoid claiming the conversation didn't perform an action,
        because the parser can only report what its current signatures
        recognise (see Raw Events for the full event-type audit).
        """
        skipped: list[dict] = []

        def _add(tab: str, panel: str, reason: str) -> None:
            skipped.append({"tab": tab, "panel": panel, "reason": reason})

        if not self.mcs_routing_plan_evolution and not self.mcs_ins_plan_diffs:  # type: ignore[attr-defined]
            _add("Routing", "Plan Evolution", "fewer than 2 plans received — need ≥2 to compare")
        if not self.mcs_routing_lifecycles:  # type: ignore[attr-defined]
            _add("Routing", "Topic Lifecycles", "no STEP_TRIGGERED events extracted (see Raw Events)")
        if not self.mcs_knowledge_searches:  # type: ignore[attr-defined]
            _add(
                "Knowledge",
                "Search Results",
                "parser matched no UniversalSearchToolTraceData / KnowledgeSearchQuery events (see Raw Events)",
            )
        if not self.mcs_generative_traces:  # type: ignore[attr-defined]
            _add(
                "Knowledge",
                "Topic-Level Generative Answers",
                "parser matched no GenerativeAnswersSupportData events (see Raw Events)",
            )
        if not self.mcs_knowledge_citation_panel:  # type: ignore[attr-defined]
            _add(
                "Knowledge",
                "Citation Verification",
                "no generative-answer traces with citations were extracted",
            )
        if not self.mcs_ins_deleg_kpis:  # type: ignore[attr-defined]
            _add("Tools", "Multi-Agent Delegation", "no ChildAgent / ConnectedAgent / A2AAgent calls extracted")
        if not self.mcs_ins_turn_kpis:  # type: ignore[attr-defined]
            _add("Conversation", "Turn Efficiency", "fewer user turns than required for the per-turn KPIs")
        if not self.mcs_ins_latency_kpis:  # type: ignore[attr-defined]
            _add("Conversation", "Latency Bottlenecks", "not enough timed events to flag a bottleneck")

        self.mcs_coverage_skipped = skipped  # type: ignore[attr-defined]

    @staticmethod
    def _flatten_raw_event_index(idx: dict) -> list[dict]:
        """Flatten the nested {value_types, action_types, attachment_kinds}
        dict into one list of rows for `rx.foreach`.

        Each row gets a `category` field so the table can group/colour the
        rows in the UI.
        """
        out: list[dict] = []
        if not idx:
            return out
        labels = {
            "value_types": "valueType",
            "action_types": "actionType",
            "attachment_kinds": "attachmentType",
        }
        for key, label in labels.items():
            for r in idx.get(key, []) or []:
                out.append(
                    {
                        "category": label,
                        "name": r.get("name", ""),
                        "count": str(r.get("count", 0)),
                        "recognised": "yes" if r.get("recognised") else "no",
                        "mapped_to": r.get("mapped_to", "") or "—",
                    }
                )
        return out

    # ── Profile tab data extraction ──────────────────────────────────────────

    def _populate_profile_data(self, profile) -> None:
        """Extract structured data for the Profile tab."""
        # Classify components
        by_cat: dict[str, list] = {}
        for comp in profile.components:
            cat = _classify_component(comp)
            if cat:
                by_cat.setdefault(cat, []).append(comp)

        # Quick wins
        quick_wins: list[dict] = []
        for comp in profile.components:
            if comp.kind == "DialogComponent" and comp.state != "Active":
                quick_wins.append(
                    {
                        "severity": "warn",
                        "icon": "alert-triangle",
                        "text": f'Disabled topic: "{comp.display_name}"',
                        "detail": "Topic is inactive. Enable or remove to reduce clutter.",
                    }
                )
        for comp in profile.components:
            if (
                comp.kind == "DialogComponent"
                and not comp.trigger_queries
                and comp.trigger_kind
                and comp.trigger_kind not in _SYSTEM_TRIGGERS
                and comp.trigger_kind not in _AUTOMATION_TRIGGERS
            ):
                quick_wins.append(
                    {
                        "severity": "warn",
                        "icon": "alert-triangle",
                        "text": f'No trigger queries: "{comp.display_name}"',
                        "detail": "User topic has no trigger phrases. It may never be matched by the recognizer.",
                    }
                )
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
                    quick_wins.append(
                        {
                            "severity": "info",
                            "icon": "info",
                            "text": f'Weak description: "{comp.display_name}" — {_reason}',
                            "detail": "A clear model description helps the orchestrator choose the right topic. Aim for 20+ chars that explain what the topic handles.",
                        }
                    )
        trigger_kinds = {c.trigger_kind for c in profile.components if c.trigger_kind}
        for trigger in ("OnError", "OnUnknownIntent", "OnEscalate"):
            if trigger not in trigger_kinds:
                quick_wins.append(
                    {
                        "severity": "warn",
                        "icon": "alert-triangle",
                        "text": f"Missing system topic: {trigger}",
                        "detail": "No handler for this lifecycle event. The bot may fail silently when this event occurs.",
                    }
                )
        conn_issues = validate_connections(profile)
        for issue in conn_issues:
            sev = "warn" if issue["severity"] == "warning" else "info"
            quick_wins.append(
                {
                    "severity": sev,
                    "icon": "alert-triangle" if sev == "warn" else "info",
                    "text": issue["message"],
                    "detail": issue.get("detail", ""),
                }
            )

        # Unused global variables (heuristic)
        global_vars = [c for c in profile.components if c.kind == "GlobalVariableComponent"]
        if global_vars:
            other_schemas = set()
            for c in profile.components:
                if c.kind != "GlobalVariableComponent":
                    if c.description:
                        other_schemas.add(c.description)
                    if c.schema_name:
                        other_schemas.add(c.schema_name)
            all_text = " ".join(other_schemas)
            for gv in global_vars:
                if gv.schema_name and gv.schema_name not in all_text:
                    quick_wins.append(
                        {
                            "severity": "info",
                            "icon": "info",
                            "text": f'Possibly unused variable: "{gv.display_name}"',
                            "detail": "Schema name not found in other component references (heuristic). May be safe to remove.",
                        }
                    )

        # KPIs — Profile tab is the agent-level lens; per-capability
        # counts (User Topics, Tools, Knowledge) live on their own tabs
        # to avoid duplicating numbers across multiple grids.
        total_comps = sum(len(v) for k, v in by_cat.items() if k in _CATEGORY_ORDER)
        instructions_chars = (
            len(profile.gpt_info.instructions) if profile.gpt_info and profile.gpt_info.instructions else 0
        )
        starter_count = (
            len(profile.gpt_info.conversation_starters)
            if profile.gpt_info and profile.gpt_info.conversation_starters
            else 0
        )
        self.mcs_profile_kpis = [  # type: ignore[attr-defined]
            {"label": "Components", "value": str(total_comps), "hint": "Total config items", "tone": "neutral"},
            {
                "label": "Instructions",
                "value": f"{instructions_chars:,}",
                "hint": "characters" if instructions_chars else "not configured",
                "tone": "warn" if instructions_chars == 0 else "neutral",
            },
            {
                "label": "Conversation Starters",
                "value": str(starter_count),
                "hint": "Suggested prompts" if starter_count else "not configured",
                "tone": "warn" if starter_count == 0 else "neutral",
            },
            {
                "label": "Quick Wins",
                "value": str(len(quick_wins)),
                "hint": "Actionable issues",
                "tone": "warn" if quick_wins else "neutral",
            },
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
            if gpt.description:
                ai_config.append({"property": "Description", "value": gpt.description[:500]})
            if gpt.instructions:
                instructions_len = f"{len(gpt.instructions):,} chars"
                ai_config.append({"property": "Instructions", "value": instructions_len})
                self.mcs_profile_instructions_text = gpt.instructions  # type: ignore[attr-defined]
            else:
                self.mcs_profile_instructions_text = ""  # type: ignore[attr-defined]
            starters = [
                {"title": s.get("title", "—"), "message": s.get("message", "—")} for s in gpt.conversation_starters
            ]
        else:
            self.mcs_profile_instructions_text = ""  # type: ignore[attr-defined]
        self.mcs_profile_ai_config = ai_config  # type: ignore[attr-defined]
        self.mcs_profile_instructions_len = instructions_len  # type: ignore[attr-defined]
        self.mcs_profile_starters = starters  # type: ignore[attr-defined]

        # Static prompt assets (SearchAndSummarizeContent.additionalInstructions
        # + AI Builder model stubs from `aIModelDefinitions`).
        inline_rows: list[dict] = []
        for ip in profile.inline_prompts:
            meta_chips: list[str] = []
            if ip.user_input:
                meta_chips.append(f"userInput={ip.user_input}")
            if ip.output_variable:
                meta_chips.append(f"output={ip.output_variable}")
            if ip.response_capture_type:
                meta_chips.append(f"capture={ip.response_capture_type}")
            if ip.knowledge_sources_mode:
                meta_chips.append(f"ks={ip.knowledge_sources_mode}")
            if ip.auto_send is not None:
                meta_chips.append(f"autoSend={ip.auto_send}")
            inline_rows.append(
                {
                    "host": ip.host_topic_display,
                    "kind": ip.kind,
                    "text": ip.text,
                    "len_label": f"{len(ip.text):,} chars",
                    "meta_summary": " · ".join(meta_chips),
                }
            )
        self.mcs_profile_inline_prompts = inline_rows  # type: ignore[attr-defined]

        from collections import Counter
        call_counts = Counter(cs.model_id for cs in profile.ai_builder_call_sites)
        sites_by_model: dict[str, list] = {}
        for cs in profile.ai_builder_call_sites:
            sites_by_model.setdefault(cs.model_id, []).append(cs)
        model_rows: list[dict] = []
        for m in profile.ai_builder_models:
            input_fields = ", ".join(_describe_ai_model_fields(m.input_type)) or "—"
            output_fields = ", ".join(_describe_ai_model_fields(m.output_type)) or "—"
            # Pre-format call-sites as a single newline-joined string so the UI
            # can render with a flat `rx.text` instead of nested `rx.foreach`,
            # which Reflex can't typecheck through `list[dict]` state vars.
            site_lines: list[str] = []
            for cs in sites_by_model.get(m.id, []):
                in_summary = ", ".join(f"{k}={v}" for k, v in cs.input_bindings.items()) or "—"
                out_summary = ", ".join(f"{k}→{v}" for k, v in cs.output_bindings.items()) or "—"
                site_lines.append(f"  • {cs.host_topic_display}   in: {in_summary}   out: {out_summary}")
            model_rows.append(
                {
                    "name": m.name,
                    "id": m.id,
                    "input_fields": input_fields,
                    "output_fields": output_fields,
                    "call_count": str(call_counts.get(m.id, 0)),
                    "call_sites_text": "\n".join(site_lines) if site_lines else "No call-sites detected.",
                }
            )
        self.mcs_profile_ai_builder_models = model_rows  # type: ignore[attr-defined]

        # Security chips
        auth_display = profile.authentication_mode
        if profile.authentication_trigger != "Unknown":
            auth_display += f" ({profile.authentication_trigger})"
        self.mcs_profile_security_chips = [  # type: ignore[attr-defined]
            {
                "title": "Auth Mode",
                "value": auth_display,
                "tone": "good" if profile.authentication_mode != "Unknown" else "info",
            },
            {
                "title": "Access Control",
                "value": profile.access_control_policy,
                "tone": "good" if profile.access_control_policy != "Unknown" else "info",
            },
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
            {
                "property": "Generative Actions",
                "value": "Enabled" if profile.generative_actions_enabled else "Disabled",
            },
        ]
        meta.append({"property": "Access Control", "value": profile.access_control_policy})
        meta.append(
            {"property": "Lightweight Bot", "value": "Yes" if getattr(profile, "is_lightweight_bot", False) else "No"}
        )
        if profile.app_insights:
            ai_obj = profile.app_insights
            flags = []
            if ai_obj.log_activities:
                flags.append("log activities")
            if ai_obj.log_sensitive_properties:
                flags.append("log sensitive")
            detail = f"Configured ({', '.join(flags)})" if flags else "Configured"
            meta.append({"property": "Application Insights", "value": detail})
        if profile.ai_settings:
            meta.append({"property": "Use Model Knowledge", "value": str(profile.ai_settings.use_model_knowledge)})
            meta.append({"property": "File Analysis", "value": str(profile.ai_settings.file_analysis)})
            meta.append({"property": "Semantic Search", "value": str(profile.ai_settings.semantic_search)})
            meta.append({"property": "Content Moderation", "value": str(profile.ai_settings.content_moderation)})
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
            conn_refs.append(
                {
                    "name": ref.get("displayName", ref.get("connectionReferenceLogicalName", "—")),
                    "connector": connector,
                    "custom": "Yes" if ref.get("customConnectorId") else "No",
                }
            )
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

    def _populate_tools_data(self, profile, timeline=None) -> None:
        """Extract structured data for the Tools tab."""
        from renderer.topic_explainer import load_kb, settings_rows_for_dialog_component

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

        # Load explainer KB once. Failure is non-fatal — tools render without
        # the settings panel rather than crashing the whole tab.
        try:
            explainer_kb: dict | None = load_kb()
        except Exception as e:
            logger.warning(f"Tool explainer KB load failed: {e}")
            explainer_kb = None

        def _tool_settings_rows(comp) -> list[dict]:
            if not explainer_kb or not comp.raw_dialog:
                return []
            try:
                rows = settings_rows_for_dialog_component(comp, explainer_kb)
            except Exception as e:
                logger.warning(f"Explainer flatten failed for {comp.schema_name}: {e}")
                return []
            # Pre-compute UI fields server-side. Reflex can't do f-string concat
            # or compute labels off dict-indexed Vars at the component layer.
            for r in rows:
                r["indent_px"] = f"{int(r['depth']) * 16}px"
                r["label"] = r["kind"] if r["row_type"] == "kind" else r["path"]
                r["display_value"] = "" if r["row_type"] == "kind" else (r["value"] or "—")
            return rows

        _type_colors = {
            "ConnectorTool": "blue",
            "ChildAgent": "green",
            "ConnectedAgent": "teal",
            "A2AAgent": "cyan",
            "MCPServer": "purple",
            "FlowTool": "amber",
        }

        # (Tool Inventory card removed — tools live in the inline
        # Component Explorer. The standalone `mcs_tools_rows` table is
        # gone.)

        # External calls detail (per-action rows from action_details, deduplicated)
        from collections import Counter

        raw_ext: list[tuple[str, str, str, str]] = []
        for c in profile.components:
            if c.kind == "DialogComponent" and c.has_external_calls and c.action_details:
                for detail in c.action_details:
                    raw_ext.append(
                        (
                            c.display_name,
                            detail.get("kind", "—"),
                            detail.get("connector_display_name") or detail.get("connection_reference") or "—",
                            detail.get("operation_id") or "—",
                        )
                    )
        ext_rows: list[dict] = []
        for (topic, kind, connector, operation), count in Counter(raw_ext).items():
            op_display = f"{operation} (×{count})" if count > 1 else operation
            ext_rows.append(
                {
                    "topic": topic,
                    "kind": kind,
                    "connector": connector,
                    "operation": op_display,
                }
            )
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

        # Runtime tool call analysis
        if timeline is not None and timeline.tool_calls:
            from renderer.tools import build_tool_call_analysis_data
            from timeline import resolve_tool_types

            resolve_tool_types(timeline, profile)
            tool_data = build_tool_call_analysis_data(timeline, profile)
            self.mcs_tools_call_count = len(timeline.tool_calls)  # type: ignore[attr-defined]
            self.mcs_tools_stats_rows = tool_data["stats_rows"]  # type: ignore[attr-defined]
            self.mcs_tools_flow_mermaid = tool_data["flow_mermaid"]  # type: ignore[attr-defined]
            # Extend KPIs with runtime data
            self.mcs_tools_kpis.extend(tool_data["kpis"])  # type: ignore[attr-defined]
        else:
            self.mcs_tools_call_count = 0  # type: ignore[attr-defined]
            self.mcs_tools_stats_rows = []  # type: ignore[attr-defined]
            self.mcs_tools_flow_mermaid = ""  # type: ignore[attr-defined]

    # ── Knowledge tab data extraction ────────────────────────────────────────

    def _populate_knowledge_data(self, profile, timeline) -> None:
        """Extract structured data for the Knowledge tab."""
        from models import EventType

        ks_comps = [c for c in profile.components if c.kind == "KnowledgeSourceComponent"]
        file_comps = [c for c in profile.components if c.kind == "FileAttachmentComponent"]
        searches = timeline.knowledge_searches if timeline is not None else []
        attributions = getattr(timeline, "knowledge_attributions", []) if timeline is not None else []
        custom_steps = getattr(timeline, "custom_search_steps", []) if timeline is not None else []
        citations = getattr(timeline, "citation_sources", []) if timeline is not None else []
        metrics = getattr(timeline, "turn_prompt_metrics", []) if timeline is not None else []
        answered_turns = sum(1 for a in attributions if (a.completion_state or "").lower() == "answered")

        # --- Build per-turn bot-reply text map (Phase 1c) ---
        # Walk timeline events in order, attributing each BOT_MESSAGE to the
        # most recent USER_MESSAGE turn. Cap reply text per turn at 800 chars
        # for the inline preview; the full body still lives in the
        # Conversation tab. Reflex state-var size matters for hot paths.
        import re as _re
        bot_reply_by_turn: dict[str, str] = {}
        current_turn: str | None = None
        user_re = _re.compile(r'^User: "(.*)"$')
        for ev in getattr(timeline, "events", []) or []:
            if ev.event_type == EventType.USER_MESSAGE:
                m = user_re.match(ev.summary or "")
                current_turn = m.group(1) if m else (ev.summary or "").removeprefix("User: ").strip().strip('"')
            elif ev.event_type == EventType.BOT_MESSAGE and current_turn is not None:
                text = (ev.summary or "").removeprefix("Bot: ").strip()
                if text:
                    existing = bot_reply_by_turn.get(current_turn, "")
                    combined = (existing + "\n\n" + text) if existing else text
                    bot_reply_by_turn[current_turn] = combined[:1500]

        # --- Build per-turn aggregated prompt metrics (Phase 2a) ---
        # Group `TurnPromptMetrics` by triggering_user_message and pre-format
        # the strip-string the UI will render (model · tokens-in · tokens-out
        # · credits). Pre-formatting in the populator avoids any str+Var
        # arithmetic in Reflex foreach bodies.
        metrics_by_turn: dict[str, dict] = {}
        for m_obj in metrics:
            key = m_obj.triggering_user_message or ""
            if not key:
                continue
            slot = metrics_by_turn.setdefault(
                key,
                {"prompt_in": 0, "completion_out": 0, "credits": 0.0, "models": set()},
            )
            slot["prompt_in"] += m_obj.prompt_tokens or 0
            slot["completion_out"] += m_obj.completion_tokens or 0
            slot["credits"] += m_obj.copilot_credits or 0.0
            if m_obj.model_name:
                slot["models"].add(m_obj.model_name)

        def _metrics_strip_for(turn: str) -> str:
            slot = metrics_by_turn.get(turn)
            if not slot:
                return ""
            bits: list[str] = []
            if slot["models"]:
                bits.append(" · ".join(sorted(slot["models"])))
            if slot["prompt_in"]:
                bits.append(f"{slot['prompt_in']:,} in")
            if slot["completion_out"]:
                bits.append(f"{slot['completion_out']:,} out")
            if slot["credits"]:
                bits.append(f"{slot['credits']:.1f} credits")
            return " · ".join(bits)

        # --- Outcome tone per turn (Phase 1d) ---
        # Drives the colored left border on each search card and the
        # turn-strip chips above. Computed once and reused.
        _tone_to_color = {
            "good": "var(--green-9)",
            "info": "var(--blue-9)",
            "warn": "var(--amber-9)",
            "bad": "var(--red-9)",
            "neutral": "var(--gray-a4)",
        }
        def _outcome_border_css(tone: str) -> str:
            return f"4px solid {_tone_to_color.get(tone, _tone_to_color['neutral'])}"

        def _outcome_tone(ks) -> str:
            state_low = ""
            for a in attributions:
                if a.triggering_user_message == ks.triggering_user_message:
                    state_low = (a.completion_state or "").lower()
                    break
            if "notfound" in state_low.replace(" ", ""):
                return "bad"
            if any(r.result_type == "citation" for r in ks.search_results):
                return "good"
            if any(r.result_type == "kt_attribution" for r in ks.search_results):
                return "warn"
            if any(r.result_type == "bot_reply_link" for r in ks.search_results):
                return "info"
            return "neutral"

        self.mcs_knowledge_kpis = [  # type: ignore[attr-defined]
            {
                "label": "Knowledge Sources",
                "value": str(len(ks_comps)),
                "hint": "Configured sources",
                "tone": "neutral",
            },
            {"label": "File Attachments", "value": str(len(file_comps)), "hint": "Uploaded files", "tone": "neutral"},
            {
                "label": "Turns w/ Knowledge",
                "value": str(len(attributions)),
                "hint": f"{answered_turns} answered" if attributions else "in this session",
                "tone": "good" if attributions and answered_turns == len(attributions) else "neutral",
            },
            {
                "label": "Orchestrator Searches",
                "value": str(len(searches)),
                "hint": "In this session",
                "tone": "neutral",
            },
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
            coverage.append(
                {
                    "name": comp.display_name,
                    "source_type": source_type,
                    "state": comp.state,
                    "trigger": trigger,
                    "notes": "; ".join(notes_parts) if notes_parts else "—",
                }
            )
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

        # Search results — grouped by user message
        search_rows: list[dict] = []
        current_user_msg: str | None = None
        for i, ks in enumerate(searches, 1):
            msg = ks.triggering_user_message or ""
            if msg != current_user_msg:
                current_user_msg = msg
                search_rows.append(
                    {
                        "kind": "header",
                        "user_message": msg if msg else "System-initiated",
                        # Pad remaining fields for type consistency
                        "index": "",
                        "query": "",
                        "keywords": "",
                        "sources": "",
                        "duration": "",
                        "grounding_label": "",
                        "grounding_tone": "",
                        "thought": "",
                        "output_sources": "",
                        "efficiency": "",
                        "errors": "",
                        "result_count": "",
                        "results_text": "",
                        "has_urls": "",
                    }
                )
            badge, label = _grounding_score(ks)
            grounding_tone = "good" if label == "Strong" else ("info" if label == "Moderate" else "bad")
            dur_ms = _parse_execution_time_ms(ks.execution_time)
            dur = _format_duration(dur_ms) if dur_ms is not None else (ks.execution_time or "—")
            eff = _source_efficiency(ks)
            # Flatten results into a displayable summary string. Each row
            # gets a *tier* prefix indicating the provenance of the
            # evidence:
            #   📎  Tier 1 — full snippet body from CBResponse.CitationSources
            #   📚  Tier 2 — source-name attribution from KTD, URL resolved
            #              against profile.components (no snippet body)
            #   🔗  Tier 3 — markdown link extracted from the bot's reply
            #              text (no snippet body, inferred citation)
            # plus the existing quality icon (🟢/🟡/🔴) for snippet length.
            #
            # Each row is built as an HTML string with `title=` attributes
            # on the tier + quality icons so the browser shows a native
            # tooltip when the user hovers over them. This works around
            # Reflex's nested-foreach typing trap — we can't put a list of
            # per-result dicts inside the search-row dict, but we can
            # pre-render the section as raw HTML and render with rx.html.
            import html as _html
            result_count = len(ks.search_results)
            result_lines: list[str] = []
            url_parts: list[str] = []
            html_rows: list[str] = []
            tier_prefix_for = {
                "citation": "📎",
                "kt_attribution": "📚",
                "bot_reply_link": "🔗",
            }
            tier_tooltip_for = {
                "citation": (
                    "Tier 1 — full snippet body from CBResponse.CitationSources. "
                    "Gold-standard grounded evidence; you're seeing the actual "
                    "source text the bot consumed."
                ),
                "kt_attribution": (
                    "Tier 2 — source name from KnowledgeTraceData. The URL is "
                    "the SharePoint root from botContent.yml, not the specific "
                    "document. No snippet body — AI Builder consumed it internally "
                    "and didn't write it back to the trace."
                ),
                "bot_reply_link": (
                    "Tier 3 — URL extracted from the bot's reply text via a "
                    "markdown-link regex. Inferred citation; treat with caution. "
                    "Bot hallucinations (e.g. home.htmld vs home.html) appear here "
                    "verbatim."
                ),
            }
            quality_tooltip_for = {
                "🟢": "Snippet ≥200 chars — substantial grounded passage.",
                "🟡": "Snippet 50–199 chars — fragmentary, treat with caution.",
                "🔴": "Snippet <50 chars — near-empty result.",
                "⚫": (
                    "No snippet body. Common for Tier 2/3 rows where only "
                    "the source URL was recoverable from the export."
                ),
            }
            for j, r in enumerate(ks.search_results[:5], 1):
                title = r.name or r.url or f"Result {j}"
                snippet_len = len(r.text or "")
                if snippet_len >= 200:
                    quality_icon = "🟢"
                elif snippet_len >= 50:
                    quality_icon = "🟡"
                elif snippet_len > 0:
                    quality_icon = "🔴"
                else:
                    quality_icon = "⚫"
                tier_badge = tier_prefix_for.get(r.result_type or "", "")
                tier_tt = tier_tooltip_for.get(r.result_type or "", "")
                quality_tt = quality_tooltip_for.get(quality_icon, "")
                snippet = (r.text or "").replace("\n", " ")
                # Plain-text version kept for legacy callers / exports that
                # don't render HTML.
                result_lines.append(
                    f"{tier_badge} {quality_icon} {j}. {title}"
                    + (f" — {snippet}" if snippet else "")
                )
                # HTML version: tier + quality icons wrapped in <span title="…">
                # for native browser tooltips. Title attributes appear on any
                # element so they're robust to Reflex's component constraints.
                title_html = _html.escape(title)
                if r.url:
                    title_html = (
                        f'<a href="{_html.escape(r.url)}" target="_blank" '
                        f'style="color:inherit;text-decoration:underline">'
                        f"{title_html}</a>"
                    )
                snippet_html = ""
                if snippet:
                    snippet_html = " — " + _html.escape(
                        snippet[:200] + ("…" if len(snippet) > 200 else "")
                    )
                html_rows.append(
                    f'<div style="font-family:monospace;font-size:11px;'
                    f"color:var(--gray-11);line-height:1.6;margin:2px 0;"
                    f'word-break:break-word">'
                    f'<span title="{_html.escape(tier_tt)}" '
                    f'style="cursor:help">{tier_badge}</span>'
                    f' <span title="{_html.escape(quality_tt)}" '
                    f'style="cursor:help">{quality_icon}</span>'
                    f" {j}. {title_html}{snippet_html}"
                    f"</div>"
                )
                if r.url:
                    url_parts.append(r.url)
            results_text = "\n".join(result_lines) if result_lines else ""
            results_html = "".join(html_rows) if html_rows else ""
            # Clean up efficiency string (strip markdown)
            eff_clean = ""
            if eff:
                eff_clean = (
                    eff.replace("**", "")
                    .replace("`", "")
                    .replace("🟢 ", "")
                    .replace("🟡 ", "")
                    .replace("🔴 ", "")
                    .replace("⚫ ", "")
                )
            search_rows.append(
                {
                    "kind": "search",
                    "user_message": "",
                    "index": str(i),
                    # `anchor_id` lets attribution-row click-throughs scroll
                    # straight to the matching search card.
                    "anchor_id": f"search-{i}",
                    "query": ks.search_query or "—",
                    "keywords": ks.search_keywords or "—",
                    "sources": ", ".join(ks.knowledge_sources) if ks.knowledge_sources else "—",
                    "source_count": str(len(ks.knowledge_sources)) if ks.knowledge_sources else "0",
                    "duration": dur,
                    "grounding_label": f"{badge} {label}",
                    "grounding_tone": grounding_tone,
                    "thought": ks.thought or "",
                    "output_sources": ", ".join(ks.output_knowledge_sources) if ks.output_knowledge_sources else "",
                    "efficiency": eff_clean,
                    "errors": "; ".join(ks.search_errors) if ks.search_errors else "",
                    "result_count": str(result_count),
                    "results_text": results_text,
                    "results_html": results_html,
                    "has_urls": ", ".join(url_parts) if url_parts else "",
                    # Phase 1c: inline the matching bot-reply text so the
                    # user sees what the bot actually said next to the
                    # evidence that grounded it.
                    "bot_reply_text": bot_reply_by_turn.get(ks.triggering_user_message or "", ""),
                    # Phase 1d: tone keyword + pre-rendered CSS string for
                    # the card's coloured left border. Pre-rendering here
                    # keeps the Reflex render function free of Var-keyed
                    # `rx.match` (which can't be composed with style
                    # dicts).
                    "outcome_tone": _outcome_tone(ks),
                    "border_left_css": _outcome_border_css(_outcome_tone(ks)),
                    # Phase 2a: pre-formatted token/cost strip.
                    "metrics_strip": _metrics_strip_for(ks.triggering_user_message or ""),
                }
            )
        self.mcs_knowledge_searches = search_rows  # type: ignore[attr-defined]

        # Per-turn knowledge attribution rows. One row per answered turn that
        # touched knowledge — distinct from orchestrator search traces above.
        # Each row carries the matching anchor id so the dashboard can scroll
        # to the corresponding search card on click.
        anchor_by_turn: dict[str, str] = {}
        for row in search_rows:
            if row["kind"] == "search":
                # The matching turn is the most recent group header.
                pass
        # Re-derive anchor map by walking searches list (cheaper than walking
        # search_rows which has interleaved headers).
        for i, ks in enumerate(searches, 1):
            anchor_by_turn.setdefault(ks.triggering_user_message or "", f"search-{i}")

        attribution_rows: list[dict] = []
        for a in attributions:
            state_lower = (a.completion_state or "").lower()
            cited_str = ", ".join(a.cited_source_names) if a.cited_source_names else "—"
            turn = a.triggering_user_message or "(system-initiated)"
            attribution_rows.append(
                {
                    "turn_message": turn,
                    "completion_state": a.completion_state or "Unknown",
                    "completion_tone": "good" if state_lower == "answered" else "bad",
                    "is_searched": "Yes" if a.is_searched else "No",
                    "cited_count": str(len(a.cited_source_names)),
                    "cited_sources_str": cited_str,
                    "failed_types_str": ", ".join(a.failed_source_types) if a.failed_source_types else "",
                    "bot_reply_text": bot_reply_by_turn.get(a.triggering_user_message or "", ""),
                    "metrics_strip": _metrics_strip_for(a.triggering_user_message or ""),
                    "anchor_href": "#" + anchor_by_turn.get(a.triggering_user_message or "", ""),
                    "has_anchor": "yes" if anchor_by_turn.get(a.triggering_user_message or "") else "",
                }
            )
        self.mcs_knowledge_attributions = attribution_rows  # type: ignore[attr-defined]

        # Citation rows — Phase 1e: deduplicate by (name, url) so FAQ-Parking-
        # EN.pdf appearing in turns 15+18 collapses to one card with a
        # "cited in N turns" badge. Snippet body is preserved verbatim; the
        # UI handles preview truncation. Pre-formatting the "cited in" string
        # keeps the rx.foreach body free of str+Var arithmetic.
        citation_rows: list[dict] = []
        seen_key_to_row: dict[tuple[str, str], dict] = {}
        for c in citations:
            key = (c.name or "", c.url or "")
            snippet = (c.text or "").strip()
            preview = snippet[:400].replace("\n", " ")
            if len(snippet) > 400:
                preview += " …"
            turn = c.triggering_user_message or "(system-initiated)"
            existing = seen_key_to_row.get(key)
            if existing is not None:
                # Same source name + URL cited again on another turn: append
                # the turn message to the badge text.
                if turn not in existing["_turn_set"]:
                    existing["_turn_set"].append(turn)
                    existing["cited_turns_text"] = "; ".join(existing["_turn_set"])
                    existing["cited_turn_count"] = str(len(existing["_turn_set"]))
                continue
            row = {
                "turn_message": turn,
                "name": c.name or c.url or "Citation",
                "url": c.url or "",
                "snippet_preview": preview,
                "snippet_full": snippet,
                "char_count": str(len(snippet)),
                "cited_turn_count": "1",
                "cited_turns_text": turn,
                "_turn_set": [turn],
            }
            seen_key_to_row[key] = row
            citation_rows.append(row)
        # Strip the internal `_turn_set` accumulator — Reflex state must be
        # JSON-serialisable + lists of dicts.
        for row in citation_rows:
            row.pop("_turn_set", None)
        self.mcs_knowledge_citations = citation_rows  # type: ignore[attr-defined]

        if attributions:
            citation_suffix = (
                f" · {len(citations)} citation{'s' if len(citations) != 1 else ''}" if citations else ""
            )
            self.mcs_knowledge_attribution_summary = (  # type: ignore[attr-defined]
                f"{len(attributions)} turns used knowledge · {answered_turns} answered · "
                f"{len(searches)} orchestrator search{'es' if len(searches) != 1 else ''}"
                f"{citation_suffix}"
            )
        else:
            self.mcs_knowledge_attribution_summary = ""  # type: ignore[attr-defined]

        # --- Turn-strip header (Phase 2c) ---
        # Horizontal status chip per turn at the very top of the Knowledge
        # tab. Reuses the same outcome-tone vocabulary as the search-card
        # left border so the user sees a visual TOC of the conversation.
        turn_strip: list[dict] = []
        seen_turns: list[str] = []
        for ks in searches:
            t = ks.triggering_user_message or ""
            if t and t not in seen_turns:
                seen_turns.append(t)
                tone = _outcome_tone(ks)
                # Short label: index + first 24 chars of the turn text.
                short = (t[:24] + "…") if len(t) > 24 else t
                turn_strip.append(
                    {
                        "index": str(len(turn_strip) + 1),
                        "short_label": short,
                        "full_label": t,
                        "tone": tone,
                        "anchor_href": "#" + anchor_by_turn.get(t, ""),
                    }
                )
        self.mcs_knowledge_turn_strip = turn_strip  # type: ignore[attr-defined]

        # --- Cross-turn comparison clusters (Phase 3a) ---
        # Group searches by *normalized* user message so multiple-attempt
        # turns ("What parking rules apply at ING?" × 7) collapse into a
        # cluster card. Normalization: strip whitespace + punctuation + lowercase.
        import re as _re2
        def _norm(s: str) -> str:
            return _re2.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
        cluster_map: dict[str, dict] = {}
        for ks in searches:
            key = _norm(ks.triggering_user_message or "")
            if not key:
                continue
            slot = cluster_map.setdefault(key, {
                "representative_turn": ks.triggering_user_message or "",
                "turn_messages": [],
                "search_count": 0,
                "with_citation_count": 0,
            })
            if ks.triggering_user_message and ks.triggering_user_message not in slot["turn_messages"]:
                slot["turn_messages"].append(ks.triggering_user_message)
            slot["search_count"] += 1
            if any(r.result_type == "citation" for r in ks.search_results):
                slot["with_citation_count"] += 1
        cluster_rows: list[dict] = []
        for key, slot in cluster_map.items():
            if slot["search_count"] < 2:
                continue  # not a cluster — single-search turns are uninteresting.
            cluster_rows.append({
                "representative_turn": slot["representative_turn"],
                "occurrences": str(slot["search_count"]),
                "with_citation": str(slot["with_citation_count"]),
                "turn_list_text": "; ".join(slot["turn_messages"][:5])
                                  + ("…" if len(slot["turn_messages"]) > 5 else ""),
            })
        # Sort by frequency descending so the most-repeated question is first.
        cluster_rows.sort(key=lambda r: int(r["occurrences"]), reverse=True)
        self.mcs_knowledge_clusters = cluster_rows  # type: ignore[attr-defined]

        # --- Source-coverage heatmap (Phase 3b) ---
        # Matrix of (source × turn) with cell tone: cited (good) / searched
        # but not cited (warn) / not searched (neutral). Pre-formatted as a
        # flat list[dict], one row per source, with `cells` as a list of
        # turn-keyed dicts the UI iterates.
        source_names = [c.display_name for c in ks_comps]
        # Pre-render each row's cells as a single emoji string. Avoids
        # the nested-foreach trap (`list[dict]` inside `list[dict]` —
        # Reflex can't typecheck through it).
        heatmap_rows: list[dict] = []
        for src_name in source_names:
            clean_src = src_name.replace(" ", "").replace("-", "")
            cells_chars: list[str] = []
            cited_count = 0
            searched_count = 0
            for ks in searches:
                cited = any(
                    (r.name or "").lower() == src_name.lower()
                    or clean_src.lower() in (r.name or "").lower()
                    for r in ks.search_results
                    if r.result_type in ("kt_attribution", "citation")
                )
                searched_here = any(
                    src_name.lower() in s.lower() or clean_src.lower() in s.lower()
                    for s in (ks.knowledge_sources or [])
                )
                if cited:
                    cells_chars.append("🟩")
                    cited_count += 1
                elif searched_here:
                    cells_chars.append("🟨")
                    searched_count += 1
                else:
                    cells_chars.append("⬜")
            heatmap_rows.append({
                "source_name": src_name,
                "cells_str": "".join(cells_chars),
                "summary": f"cited {cited_count}x · searched only {searched_count}x",
            })
        self.mcs_knowledge_heatmap = heatmap_rows  # type: ignore[attr-defined]

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

        # Topic-level Search & Summarize diagnostic traces
        traces = getattr(timeline, "generative_answer_traces", []) if timeline is not None else []
        gen_rows: list[dict] = []
        gen_topics: set[str] = set()
        for idx, trace in enumerate(traces, 1):
            if trace.topic_name:
                gen_topics.add(trace.topic_name)
            # Outcome verdict — single source of truth shared with markdown report.
            # Profile is passed so the classifier can detect "Trigger Gated Off" when
            # every endpoint maps to a KnowledgeSourceComponent with triggerCondition=false.
            outcome_icon, outcome_label_text, outcome_explanation = _classify_trace_outcome(trace, profile)
            status_label = f"{outcome_icon} {outcome_label_text}"
            if outcome_icon == "🟢":
                status_tone = "good"
            elif outcome_icon == "🔴":
                status_tone = "bad"
            elif outcome_icon == "🟡":
                status_tone = "info"
            else:
                status_tone = "neutral"

            # Token totals
            total_prompt = (trace.rewrite_prompt_tokens or 0) + (trace.summarize_prompt_tokens or 0)
            total_completion = (trace.rewrite_completion_tokens or 0) + (trace.summarize_completion_tokens or 0)
            tokens_label = f"{total_prompt} / {total_completion}" if (total_prompt or total_completion) else "—"

            # Result rows — now include the full snippet so users can audit grounding
            result_rows: list[dict] = []
            for j, r in enumerate(trace.search_results, 1):
                rank = r.rank_score
                if rank is None:
                    rank_label = "—"
                elif rank >= 0.75:
                    rank_label = f"🟢 {rank:.2f}"
                elif rank >= 0.5:
                    rank_label = f"🟡 {rank:.2f}"
                else:
                    rank_label = f"🟠 {rank:.2f}"
                if r.verified_rank_score is not None and r.rank_score is not None:
                    delta = r.verified_rank_score - r.rank_score
                    delta_label = f"{'+' if delta >= 0 else ''}{delta:.3f}"
                else:
                    delta_label = "—"
                snippet = (r.text or "").replace("\r", "")
                result_rows.append(
                    {
                        "index": str(j),
                        "title": r.name or r.url or f"Result {j}",
                        "url": r.url or "",
                        "rank": rank_label,
                        "delta": delta_label,
                        "snippet": snippet,
                        "snippet_len": str(len(snippet)),
                    }
                )

            # Detect "all zero rank" anomaly — strong signal that the search ranker
            # is disabled or misconfigured against this tenant's backend.
            ranks = [r.rank_score for r in trace.search_results if r.rank_score is not None]
            all_zero_rank = bool(ranks) and all(s == 0 for s in ranks)
            shadow_count = len(trace.shadow_search_results)
            live_count = len(trace.search_results)
            shadow_anomaly = shadow_count > live_count
            shadow_label = (
                f"🟠 live={live_count} · shadow={shadow_count} (parallel backend retrieved more)"
                if shadow_anomaly
                else f"🟢 live={live_count} · shadow={shadow_count}"
                if shadow_count
                else ""
            )

            # Citation rows — keep the full snippet; the UI wraps + scrolls
            citation_rows: list[dict] = []
            for j, c in enumerate(trace.citations, 1):
                snippet = (c.snippet or "").replace("\r", "")
                citation_rows.append(
                    {
                        "index": str(j),
                        "title": c.title or c.url or f"Citation {j}",
                        "url": c.url or "",
                        "snippet": snippet,
                    }
                )

            # Safety chips
            safety_chips = [
                {
                    "label": "Moderation",
                    "icon": "🟢" if trace.performed_content_moderation else "⚫",
                    "tone": "good" if trace.performed_content_moderation else "neutral",
                },
                {
                    "label": "Provenance",
                    "icon": "🟢" if trace.performed_content_provenance else "⚫",
                    "tone": "good" if trace.performed_content_provenance else "neutral",
                },
                {
                    "label": "Confidential data",
                    "icon": "🔴" if trace.contains_confidential else "🟢",
                    "tone": "bad" if trace.contains_confidential else "good",
                },
                {
                    "label": "GPT default fallback" if trace.triggered_fallback else "No fallback",
                    "icon": "🔴" if trace.triggered_fallback else "🟢",
                    "tone": "bad" if trace.triggered_fallback else "good",
                },
            ]

            attempt_label = f"↻ Retry #{trace.attempt_index}" if trace.is_retry else f"#{trace.attempt_index}"
            # Sanitize topic_name → DOM id for the deep-link anchor.
            # Variable Tracker generative_answer cards use the raw
            # topic_name; the click handler in `jump_to_knowledge_topic`
            # applies the same sanitizer.
            _topic_for_anchor = trace.topic_name or ""
            gen_anchor_id = (
                "row-gen-" + "".join(c if c.isalnum() else "-" for c in _topic_for_anchor) if _topic_for_anchor else ""
            )
            gen_rows.append(
                {
                    "index": str(idx),
                    "attempt_label": attempt_label,
                    "is_retry": "true" if trace.is_retry else "",
                    "retry_reason": trace.previous_attempt_state or "",
                    "topic": trace.topic_name or "—",
                    "gen_anchor_id": gen_anchor_id,
                    "status_label": status_label,
                    "status_tone": status_tone,
                    "outcome_icon": outcome_icon,
                    "outcome_label_text": outcome_label_text,
                    "outcome_explanation": outcome_explanation,
                    "answer_state": trace.gpt_answer_state or "—",
                    "completion_state": trace.completion_state or "—",
                    "fallback_flag": "true" if trace.triggered_fallback else "false",
                    "search_log_count": str(len(trace.search_logs)),
                    "search_term_count": str(len(trace.search_terms_used)),
                    "shadow_result_count": str(len(trace.shadow_search_results)),
                    "shadow_error_count": str(len(trace.shadow_search_errors)),
                    "shadow_log_count": str(len(trace.shadow_search_logs)),
                    "shadow_errors": "; ".join(trace.shadow_search_errors) if trace.shadow_search_errors else "",
                    "search_logs_text": "\n".join(trace.search_logs) if trace.search_logs else "",
                    "shadow_logs_text": "\n".join(trace.shadow_search_logs) if trace.shadow_search_logs else "",
                    "search_terms_used_text": ", ".join(trace.search_terms_used) if trace.search_terms_used else "",
                    "user_msg": trace.original_message or trace.triggering_user_message or "—",
                    "screened": trace.screened_message or "",
                    "rewritten": trace.rewritten_message or "",
                    "keywords": trace.rewritten_keywords or "",
                    "rewrite_model": trace.rewrite_model or "—",
                    "summarize_model": trace.summarize_model or "—",
                    "tokens_label": tokens_label,
                    "rewrite_tokens": (
                        f"{trace.rewrite_prompt_tokens or 0} / {trace.rewrite_completion_tokens or 0}"
                        if trace.rewrite_prompt_tokens or trace.rewrite_completion_tokens
                        else "—"
                    ),
                    "summarize_tokens": (
                        f"{trace.summarize_prompt_tokens or 0} / {trace.summarize_completion_tokens or 0}"
                        if trace.summarize_prompt_tokens or trace.summarize_completion_tokens
                        else "—"
                    ),
                    "search_type": trace.search_type or "—",
                    "result_count": str(len(trace.search_results)),
                    "citation_count": str(len(trace.citations)),
                    "endpoint_count": str(len(trace.endpoints)),
                    "endpoints": trace.endpoints,
                    "results": result_rows,
                    "citations": citation_rows,
                    "safety_chips": safety_chips,
                    "summary_text": trace.summary_text or "",
                    "search_errors": "; ".join(trace.search_errors) if trace.search_errors else "",
                    "rewrite_total_tokens": str(trace.rewrite_total_tokens) if trace.rewrite_total_tokens else "",
                    "summarize_total_tokens": str(trace.summarize_total_tokens) if trace.summarize_total_tokens else "",
                    "rewrite_cached_tokens": str(trace.rewrite_cached_tokens) if trace.rewrite_cached_tokens else "",
                    "summarize_cached_tokens": str(trace.summarize_cached_tokens)
                    if trace.summarize_cached_tokens
                    else "",
                    "all_zero_rank": "true" if all_zero_rank else "",
                    "shadow_label": shadow_label,
                    "shadow_anomaly": "true" if shadow_anomaly else "",
                    "rewrite_system_prompt": trace.rewrite_system_prompt or "",
                    "summarize_system_prompt": trace.summarize_system_prompt or "",
                    "rewrite_raw_response": trace.rewrite_raw_response or "",
                    "hypothetical_snippet": trace.hypothetical_snippet_query or "",
                }
            )

        self.mcs_generative_traces = gen_rows  # type: ignore[attr-defined]
        self.mcs_generative_topics = sorted(gen_topics)  # type: ignore[attr-defined]

        # Citation Verification panel — see `build_citation_panel_rows`
        # for the row schema.
        self.mcs_knowledge_citation_panel = build_citation_panel_rows(traces)  # type: ignore[attr-defined]

    # ── Tools tab data extraction (formerly Topics tab) ──────────────────────

    def _populate_topics_data(self, profile, timeline) -> None:
        """Extract structured data for the Tools tab — Component Explorer
        topics list, KPIs, category summary, anomalies, topic graph,
        and the per-tool-type breakdown. Function name kept for backward
        compatibility; the Topics tab itself was consolidated into
        Tools in PR #18."""
        from models import EventType
        from renderer.topic_explainer import load_kb, settings_rows_for_dialog_component

        # Load explainer KB once and reuse across topic rows. If the KB file is
        # missing or malformed, fall back to empty rows rather than crash.
        try:
            explainer_kb: dict | None = load_kb()
        except Exception as e:
            logger.warning(f"Topic explainer KB load failed: {e}")
            explainer_kb = None

        def _settings_rows(comp) -> list[dict]:
            if not explainer_kb or not comp.raw_dialog:
                return []
            try:
                rows = settings_rows_for_dialog_component(comp, explainer_kb)
            except Exception as e:
                logger.warning(f"Explainer flatten failed for {comp.schema_name}: {e}")
                return []
            # Pre-compute UI fields. Reflex can't do f-string concat on State Vars,
            # so we materialise these server-side when the rows are built.
            for r in rows:
                r["indent_px"] = f"{int(r['depth']) * 16}px"
                # A label that's safe to render unconditionally — kind rows use the
                # action name, prop rows use the property path.
                r["label"] = r["kind"] if r["row_type"] == "kind" else r["path"]
                # Display value: blank for kind rows, raw value for prop rows.
                r["display_value"] = "" if r["row_type"] == "kind" else (r["value"] or "—")
            return rows

        by_cat: dict[str, list] = {}
        for comp in profile.components:
            cat = _classify_component(comp)
            if cat:
                by_cat.setdefault(cat, []).append(comp)

        user_topics = by_cat.get("user_topics", [])
        system_topics = by_cat.get("system_topics", []) + by_cat.get("automation_topics", [])
        orch_topics = by_cat.get("orchestrator_topics", [])

        # KPIs
        external_calls_total = sum(
            1 for c in profile.components if c.kind == "DialogComponent" and c.has_external_calls
        )
        self.mcs_topics_kpis = [  # type: ignore[attr-defined]
            {"label": "User Topics", "value": str(len(user_topics)), "hint": "Trigger-based", "tone": "neutral"},
            {
                "label": "System Topics",
                "value": str(len(system_topics)),
                "hint": "System + Automation",
                "tone": "neutral",
            },
            {"label": "Orchestrator", "value": str(len(orch_topics)), "hint": "Task/Agent dialogs", "tone": "neutral"},
            {
                "label": "External Calls",
                "value": str(external_calls_total),
                "hint": "Topics with actions",
                "tone": "neutral",
            },
        ]

        # Category summary — `orchestrator_topics` is split by
        # `tool_type` so each tool kind (MCP servers, connector tools,
        # flow tools, child/connected agents) gets its own row instead
        # of being lumped under the internal "Orchestrator Topics"
        # bucket.
        agent_tool_types = {"ChildAgent", "ConnectedAgent", "A2AAgent"}
        # Friendly label + icon per tool_type. Anything we haven't
        # explicitly mapped falls back to a generic "Tools" row.
        tool_type_display: dict[str, tuple[str, str]] = {
            "MCPServer": ("MCP Servers", "server"),
            "ConnectorTool": ("Connector Tools", "plug"),
            "FlowTool": ("Power Automate Flows", "workflow"),
            "ChildAgent": ("Child Agents", "users"),
            "ConnectedAgent": ("Connected Agents", "network"),
            "A2AAgent": ("A2A Agents", "share-2"),
        }
        topic_cat_order = [
            "user_topics",
            "system_topics",
            "automation_topics",
        ]
        misc_cat_order = [
            "skills",
            "custom_entities",
            "variables",
            "settings",
        ]
        cat_display = {
            "user_topics": ("User Topics", "user-round"),
            "system_topics": ("System Topics", "settings"),
            "automation_topics": ("Automation Topics", "bot"),
            "skills": ("Skills & Connectors", "puzzle"),
            "custom_entities": ("Custom Entities", "database"),
            "variables": ("Variables", "variable"),
            "settings": ("Settings", "sliders"),
        }
        summary_rows: list[dict] = []
        # Topic categories first
        for cat in topic_cat_order:
            comps = by_cat.get(cat, [])
            if not comps:
                continue
            display, icon = cat_display.get(cat, (cat, "list"))
            active = sum(1 for c in comps if c.state == "Active")
            summary_rows.append(
                {
                    "category": display,
                    "count": str(len(comps)),
                    "active": str(active),
                    "inactive": str(len(comps) - active),
                    "icon": icon,
                }
            )
        # Per-tool-type rows from orchestrator_topics, sorted: tools
        # first (alphabetical by display), agents next.
        orch_comps = by_cat.get("orchestrator_topics", [])
        by_tool_type: dict[str, list] = {}
        for c in orch_comps:
            key = c.tool_type or "Other"
            by_tool_type.setdefault(key, []).append(c)
        # Order: known tool types in declared order, then any unknown
        # types alphabetically. Agents grouped after non-agent tools.
        non_agent_keys = [k for k in by_tool_type if k not in agent_tool_types]
        agent_keys = [k for k in by_tool_type if k in agent_tool_types]

        def _tool_row(key: str) -> dict | None:
            comps = by_tool_type.get(key, [])
            if not comps:
                return None
            display, icon = tool_type_display.get(key, (key or "Tools", "wrench"))
            active = sum(1 for c in comps if c.state == "Active")
            return {
                "category": display,
                "count": str(len(comps)),
                "active": str(active),
                "inactive": str(len(comps) - active),
                "icon": icon,
            }

        for key in sorted(non_agent_keys, key=lambda k: tool_type_display.get(k, (k, ""))[0].lower()):
            row = _tool_row(key)
            if row:
                summary_rows.append(row)
        for key in sorted(agent_keys, key=lambda k: tool_type_display.get(k, (k, ""))[0].lower()):
            row = _tool_row(key)
            if row:
                summary_rows.append(row)
        # Misc (skills, entities, variables, settings) at the bottom
        for cat in misc_cat_order:
            comps = by_cat.get(cat, [])
            if not comps:
                continue
            display, icon = cat_display.get(cat, (cat, "list"))
            active = sum(1 for c in comps if c.state == "Active")
            summary_rows.append(
                {
                    "category": display,
                    "count": str(len(comps)),
                    "active": str(active),
                    "inactive": str(len(comps) - active),
                    "icon": icon,
                }
            )
        self.mcs_topics_summary = summary_rows  # type: ignore[attr-defined]

        # Cache the explainer rows per component so we compute once per topic.
        # Each row dict includes a `has_settings` flag (string-typed for Reflex
        # rx.cond compatibility) so the UI can branch without calling .length()
        # on an untyped Var.
        explainer_cache: dict[str, list[dict]] = {}

        def _cached_settings_rows(comp) -> list[dict]:
            key = comp.schema_name or id(comp)
            if key not in explainer_cache:
                explainer_cache[key] = _settings_rows(comp)
            return explainer_cache[key]

        def _settings_fields(comp) -> dict:
            rows = _cached_settings_rows(comp)
            return {
                "settings_rows": rows,
                "has_settings": "true" if rows else "",
            }

        # (Per-category topic detail tables — User / Orchestrator /
        # System / Automation — were removed when the Topics tab was
        # consolidated into the Tools tab. All topic browsing now goes
        # through the inline Component Explorer
        # (`mcs_topic_explorer_topics`).)

        # External calls (moved to Tools tab — just clear this legacy var)
        self.mcs_topics_external_calls = []  # type: ignore[attr-defined]

        # Coverage
        dialog_comps = [
            c
            for c in profile.components
            if c.kind == "DialogComponent"
            and c.trigger_kind not in (_SYSTEM_TRIGGERS | _AUTOMATION_TRIGGERS | {None})
            and c.dialog_kind not in ("TaskDialog", "AgentDialog")
        ]
        if timeline is not None:
            triggered_names = {
                ev.topic_name for ev in timeline.events if ev.event_type == EventType.STEP_TRIGGERED and ev.topic_name
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
            {
                "title": "Orphaned Topics",
                "value": str(anomalies["orphaned"]),
                "tone": "bad" if anomalies["orphaned"] > 0 else "good",
            },
            {
                "title": "Dead Ends",
                "value": str(anomalies["dead_ends"]),
                "tone": "bad" if anomalies["dead_ends"] > 0 else "good",
            },
            {
                "title": "Cycles",
                "value": str(anomalies["cycles"]),
                "tone": "bad" if anomalies["cycles"] > 0 else "good",
            },
        ]

        # Component Explorer — flat list across every category so the
        # inline picker can browse a single unified surface. Each entry
        # carries the pre-flattened `settings_rows` so the right pane
        # only has to render the picked component's rows. Includes both
        # DialogComponent topics AND tools (TaskDialog / AgentDialog) —
        # the picker is the canonical browse surface for the bot's
        # static design.
        # Sort buckets: topics first (alpha-grouped), then tools by
        # tool_type (MCP / Connector / Flow / generic), then agents by
        # their specific kind, then misc (skills).
        category_order: dict[str, tuple[int, str]] = {
            "user_topics": (0, "User Topic"),
            "system_topics": (1, "System Topic"),
            "automation_topics": (2, "Automation Topic"),
            "skills": (8, "Skill"),
        }
        # Per-tool-type badge for components in `orchestrator_topics`
        # (which contains all TaskDialog + AgentDialog components).
        tool_type_label: dict[str, tuple[int, str]] = {
            "MCPServer": (3, "MCP"),
            "ConnectorTool": (4, "Connector"),
            "FlowTool": (5, "Flow"),
            "ChildAgent": (6, "Child Agent"),
            "ConnectedAgent": (6, "Connected Agent"),
            "A2AAgent": (6, "A2A Agent"),
        }
        explorer_entries: list[tuple[int, str, dict]] = []
        for cat, comps in by_cat.items():
            for c in comps:
                if c.kind != "DialogComponent":
                    continue
                # Resolve the picker badge:
                #   - orchestrator_topics → tool_type-specific label
                #   - everything else → category-derived label
                if cat == "orchestrator_topics":
                    sort_key, cat_label = tool_type_label.get(
                        c.tool_type or "",
                        (7, "Tool"),
                    )
                else:
                    sort_key, cat_label = category_order.get(
                        cat,
                        (9, cat.replace("_", " ").title()),
                    )
                rows = _cached_settings_rows(c)
                action_count = sum(1 for r in rows if r.get("row_type") == "kind")
                explorer_entries.append(
                    (
                        sort_key,
                        c.display_name.lower(),
                        {
                            "display_name": c.display_name,
                            "schema_name": c.schema_name,
                            "category": cat_label,
                            "action_count": str(action_count),
                            "settings_rows": rows,
                        },
                    )
                )
        explorer_entries.sort(key=lambda x: (x[0], x[1]))
        self.mcs_topic_explorer_topics = [e[2] for e in explorer_entries]  # type: ignore[attr-defined]

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
            catalogue.append(
                {
                    "model": info["display"],
                    "tier": info["tier"],
                    "context": info["context_window"],
                    "cost": info["cost_tier"],
                    "is_current": "yes" if key == cat_key else "no",
                }
            )
        self.mcs_model_catalogue = catalogue  # type: ignore[attr-defined]

    # ── Conversation tab data extraction ────────────────────────────────────

    def _populate_conversation_data(self, timeline, profile=None) -> None:
        """Extract structured data for the Conversation detail panel."""
        from models import EventType

        # Metadata + page-header surface
        self.mcs_conversation_id = timeline.conversation_id or ""  # type: ignore[attr-defined]
        self.mcs_conv_metadata = [  # type: ignore[attr-defined]
            {"property": "Bot Name", "value": timeline.bot_name or "—"},
            {"property": "Conversation ID", "value": timeline.conversation_id or "—"},
            {"property": "User Query", "value": timeline.user_query or "—"},
            {
                "property": "Total Elapsed",
                "value": _format_duration(timeline.total_elapsed_ms) if timeline.total_elapsed_ms else "—",
            },
        ]

        # Phase breakdown — annotate each row with a deep-link target so
        # the user can jump from a slow phase to its component
        # definition. Knowledge phases jump to the Knowledge tab;
        # everything else jumps to the Tools tab Component Explorer.
        from renderer.dynamic_data import _build_component_lookup, _resolve_component_schema

        total_ms = timeline.total_elapsed_ms or 0.0
        _phase_status_tone = {"completed": "good", "failed": "bad"}
        _phase_lookup = _build_component_lookup(profile)
        phases: list[dict] = []
        for p in timeline.phases:
            if p.phase_type == "KnowledgeSource":
                link_kind = "knowledge"
                link_id = p.label or ""
            else:
                schema = _resolve_component_schema(p.label or "", _phase_lookup)
                link_kind = "component" if schema else ""
                link_id = schema
            phases.append(
                {
                    "label": p.label,
                    "phase_type": p.phase_type,
                    "duration": _format_duration(p.duration_ms),
                    "pct": _pct(p.duration_ms, total_ms),
                    "status": p.state,
                    "status_tone": _phase_status_tone.get(p.state, "info"),
                    "link_target_kind": link_kind,
                    "link_target_id": link_id,
                }
            )
        self.mcs_conv_phases = phases  # type: ignore[attr-defined]

        # Variable Tracker — unified canvas covering tool calls, Topic/Global
        # variable assignments, and topic-level Generative Answer traces. See
        # `build_variable_tracker_rows` for the row schema.
        self.mcs_conv_variables = build_variable_tracker_rows(timeline, profile)  # type: ignore[attr-defined]

        # Performance Waterfall — see `build_performance_waterfall` for
        # the row schema. One row per timed event with the gap from the
        # previous activity (idle gaps suppressed). Profile is passed so
        # rows naming a component carry a Tools-tab link target.
        self.mcs_conv_waterfall = build_performance_waterfall(timeline, profile)  # type: ignore[attr-defined]

        # Errors
        self.mcs_conv_errors = list(timeline.errors)  # type: ignore[attr-defined]

        # Error/exception banner — error-toned flow items with their
        # `flow_id` deep-link target. Reads from the flow items already
        # built in `_populate_dynamic_sections` so the banner row's
        # target_id matches the rendered flow row's DOM id.
        self.mcs_conv_error_banner = [  # type: ignore[attr-defined]
            {
                "flow_id": item.get("flow_id", ""),
                "title": item.get("title", "") or "Error",
                "summary": item.get("summary", ""),
                "timestamp": item.get("timestamp", ""),
                "topic_name": item.get("topic_name", ""),
            }
            for item in self.mcs_conversation_flow  # type: ignore[attr-defined]
            if item.get("tone") == "error"
        ]

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

                # Resolve the topic to a Component Explorer schema_name
                # so the row can hyperlink into the Tools tab.
                schema = _resolve_component_schema(ev.topic_name or "", _phase_lookup)
                reasoning.append(
                    {
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
                        "link_target_kind": "component" if schema else "",
                        "link_target_id": schema,
                    }
                )
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

    # ── Insights tab data extraction (conversation analysis features) ────────

    def _populate_insights_data(self, profile, timeline) -> None:
        """Populate the Insights tab with structured data for native components."""
        from conversation_analysis import (
            analyze_delegations,
            analyze_instruction_alignment,
            analyze_knowledge_effectiveness,
            analyze_latency_bottlenecks,
            analyze_plan_diffs,
            analyze_response_quality,
            analyze_turn_efficiency,
            detect_dead_code,
        )

        if timeline is not None:
            # Turn Efficiency
            tr = analyze_turn_efficiency(timeline)
            self.mcs_ins_turn_kpis = [  # type: ignore[attr-defined]
                {"label": "Total Turns", "value": str(len(tr.turns))},
                {"label": "Avg Plans/Turn", "value": f"{tr.avg_plans_per_turn:.1f}"},
                {"label": "Avg Tools/Turn", "value": f"{tr.avg_tools_per_turn:.1f}"},
                {"label": "Thinking Ratio", "value": f"{tr.avg_thinking_ratio:.0%}"},
                {
                    "label": "Inefficient",
                    "value": str(tr.inefficient_turn_count),
                    "tone": "warn" if tr.inefficient_turn_count > 0 else "",
                },
            ]
            self.mcs_ins_turn_rows = [  # type: ignore[attr-defined]
                {
                    "turn": str(t.turn_index),
                    "message": t.user_message[:60] or "—",
                    "plans": str(t.plan_count),
                    "tools": str(t.tool_call_count),
                    "searches": str(t.knowledge_search_count),
                    "thinking": f"{t.thinking_ms:.0f}ms",
                    "total": f"{t.total_ms:.0f}ms",
                    "flags": ", ".join(t.flags) if t.flags else "",
                }
                for t in tr.turns
            ]

            # Response Quality
            qr = analyze_response_quality(timeline)
            total_resp = qr.grounded_count + qr.ungrounded_count
            self.mcs_ins_quality_kpis = [  # type: ignore[attr-defined]
                {"label": "Responses", "value": str(total_resp)},
                {"label": "Grounded", "value": str(qr.grounded_count)},
                {
                    "label": "Ungrounded",
                    "value": str(qr.ungrounded_count),
                    "tone": "warn" if qr.ungrounded_count > 0 else "",
                },
                {
                    "label": "High Risk",
                    "value": str(qr.high_risk_count),
                    "tone": "danger" if qr.high_risk_count > 0 else "",
                },
                {
                    "label": "Swallowed Errors",
                    "value": str(qr.swallowed_error_count),
                    "tone": "warn" if qr.swallowed_error_count > 0 else "",
                },
            ]
            self.mcs_ins_quality_rows = [  # type: ignore[attr-defined]
                {
                    "turn": str(item.turn_index),
                    "risk": item.hallucination_risk,
                    "source": item.grounding_source,
                    "flags": "; ".join(item.flags),
                }
                for item in qr.items
                if item.flags
            ]

            # Plan Diff
            pr = analyze_plan_diffs(timeline)
            self.mcs_ins_plan_kpis = (
                [  # type: ignore[attr-defined]
                    {"label": "Re-plans", "value": str(pr.total_replans)},
                    {
                        "label": "Thrashing",
                        "value": str(pr.thrashing_count),
                        "tone": "danger" if pr.thrashing_count > 0 else "",
                    },
                    {
                        "label": "Scope Creep",
                        "value": str(pr.scope_creep_count),
                        "tone": "warn" if pr.scope_creep_count > 0 else "",
                    },
                ]
                if pr.total_replans > 0
                else []
            )
            self.mcs_ins_plan_diffs = [  # type: ignore[attr-defined]
                {
                    "turn": str(d.turn_index),
                    "ask": d.orchestrator_ask or "",
                    "added": ", ".join(d.added_steps),
                    "removed": ", ".join(d.removed_steps),
                    "is_thrashing": "yes" if d.is_thrashing else "no",
                }
                for d in pr.diffs
            ]

            # Knowledge Effectiveness
            ke = analyze_knowledge_effectiveness([timeline])
            self.mcs_ins_ke_kpis = (
                [  # type: ignore[attr-defined]
                    {"label": "Searches", "value": str(ke.total_searches)},
                    {"label": "Avg Sources/Search", "value": f"{ke.avg_sources_per_search:.1f}"},
                    {
                        "label": "Zero Results",
                        "value": str(ke.zero_result_searches),
                        "tone": "warn" if ke.zero_result_searches > 0 else "",
                    },
                ]
                if ke.total_searches > 0
                else []
            )
            self.mcs_ins_ke_rows = [  # type: ignore[attr-defined]
                {
                    "source": s.source_name,
                    "queries": str(s.query_count),
                    "contributions": str(s.contribution_count),
                    "hit_rate": f"{s.hit_rate:.0%}",
                    "hit_tone": "good" if s.hit_rate >= 0.6 else ("warn" if s.hit_rate >= 0.3 else "danger"),
                    "errors": str(s.error_count),
                    "avg_results": f"{s.avg_result_count:.1f}",
                }
                for s in ke.sources
            ]
            self.mcs_ins_ke_warnings = [  # type: ignore[attr-defined]
                f"{s.source_name} — queried {s.query_count}x, contributed {s.contribution_count}x"
                for s in ke.sources
                if s.hit_rate < 0.1 and s.query_count >= 3
            ]

            # Latency
            lr = analyze_latency_bottlenecks(timeline)
            self.mcs_ins_latency_kpis = (
                [  # type: ignore[attr-defined]
                    {"label": "Turns", "value": str(len(lr.turns))},
                    {
                        "label": "Bottlenecks",
                        "value": str(lr.bottleneck_turn_count),
                        "tone": "warn" if lr.bottleneck_turn_count > 0 else "",
                    },
                    {"label": "Avg Thinking", "value": f"{lr.avg_thinking_pct:.0f}%"},
                    {"label": "Avg Tools", "value": f"{lr.avg_tool_pct:.0f}%"},
                ]
                if lr.turns
                else []
            )
            latency_rows = []
            for t in lr.turns:
                seg_map = {s.category: s for s in t.segments}
                th = seg_map.get("thinking")
                to = seg_map.get("tool")
                kn = seg_map.get("knowledge")
                latency_rows.append(
                    {
                        "turn": str(t.turn_index),
                        "message": t.user_message[:40] or "—",
                        "total": f"{t.total_ms:.0f}ms",
                        "thinking": f"{th.duration_ms:.0f}ms ({th.percentage:.0f}%)" if th else "—",
                        "tools": f"{to.duration_ms:.0f}ms ({to.percentage:.0f}%)" if to else "—",
                        "knowledge": f"{kn.duration_ms:.0f}ms ({kn.percentage:.0f}%)" if kn else "—",
                        "bottleneck": t.bottleneck or "—",
                        "bottleneck_tone": "warn" if t.bottleneck else "",
                    }
                )
            self.mcs_ins_latency_rows = latency_rows  # type: ignore[attr-defined]
            # Mermaid Gantt for latency
            if len(lr.turns) <= 10 and lr.turns:
                gantt_lines = ["gantt", "    title Time Breakdown per Turn", "    dateFormat X", "    axisFormat %s ms"]
                for t in lr.turns:
                    gantt_lines.append(f"    section Turn {t.turn_index}")
                    offset = 0
                    for seg in t.segments:
                        dur = max(1, int(seg.duration_ms))
                        gantt_lines.append(f"    {seg.label} :{offset}, {offset + dur}")
                        offset += dur
                self.mcs_ins_latency_mermaid = "\n".join(gantt_lines)  # type: ignore[attr-defined]
            else:
                self.mcs_ins_latency_mermaid = ""  # type: ignore[attr-defined]
        else:
            self.mcs_ins_turn_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_turn_rows = []  # type: ignore[attr-defined]
            self.mcs_ins_quality_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_quality_rows = []  # type: ignore[attr-defined]
            self.mcs_ins_plan_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_plan_diffs = []  # type: ignore[attr-defined]
            self.mcs_ins_ke_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_ke_rows = []  # type: ignore[attr-defined]
            self.mcs_ins_ke_warnings = []  # type: ignore[attr-defined]
            self.mcs_ins_latency_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_latency_rows = []  # type: ignore[attr-defined]
            self.mcs_ins_latency_mermaid = ""  # type: ignore[attr-defined]

        # Features that need both profile + timeline
        if profile is not None and timeline is not None:
            # Dead Code
            dc = detect_dead_code(profile, [timeline])
            if dc.dead_items:
                self.mcs_ins_dead_summary = (  # type: ignore[attr-defined]
                    f"{len(dc.dead_items)} of {dc.total_components} components ({dc.dead_ratio:.0%}) "
                    f"have no runtime evidence of usage"
                )
                self.mcs_ins_dead_rows = [  # type: ignore[attr-defined]
                    {"kind": item.component_kind, "name": item.display_name, "schema": item.schema_name}
                    for item in dc.dead_items
                ]
            else:
                self.mcs_ins_dead_summary = "All components have runtime evidence of being used."  # type: ignore[attr-defined]
                self.mcs_ins_dead_rows = []  # type: ignore[attr-defined]

            # Delegation
            dl = analyze_delegations(timeline, profile)
            self.mcs_ins_deleg_kpis = (
                [  # type: ignore[attr-defined]
                    {"label": "Configured", "value": str(len(dl.configured_agents))},
                    {"label": "Delegations", "value": str(len(dl.delegations))},
                    {
                        "label": "Dead Agents",
                        "value": str(len(dl.dead_agents)),
                        "tone": "warn" if dl.dead_agents else "",
                    },
                    {
                        "label": "Always Failing",
                        "value": str(len(dl.failing_agents)),
                        "tone": "danger" if dl.failing_agents else "",
                    },
                ]
                if dl.configured_agents or dl.delegations
                else []
            )
            self.mcs_ins_deleg_rows = [  # type: ignore[attr-defined]
                {
                    "agent": d.agent_name,
                    "type": d.tool_type or "—",
                    "state": d.state,
                    "duration": f"{d.duration_ms:.0f}ms",
                    "thought": (d.thought or "—")[:80],
                }
                for d in dl.delegations
            ]
            self.mcs_ins_deleg_warnings = [  # type: ignore[attr-defined]
                *(f"Dead agent: {a}" for a in dl.dead_agents),
                *(f"Always failing: {a}" for a in dl.failing_agents),
            ]

            # Alignment
            al = analyze_instruction_alignment(timeline, profile)
            if al.directives_found > 0:
                score_tone = "good" if al.coverage_score >= 0.8 else ("warn" if al.coverage_score >= 0.5 else "danger")
                self.mcs_ins_align_kpis = [  # type: ignore[attr-defined]
                    {"label": "Directives", "value": str(al.directives_found)},
                    {
                        "label": "Violations",
                        "value": str(len(al.violations)),
                        "tone": "danger" if al.violations else "",
                    },
                    {"label": "Compliance", "value": f"{al.coverage_score:.0%}", "tone": score_tone},
                ]
                self.mcs_ins_align_rows = [  # type: ignore[attr-defined]
                    {"directive": v.directive, "type": v.violation_type, "evidence": v.evidence[:80]}
                    for v in al.violations
                ]
            else:
                self.mcs_ins_align_kpis = []  # type: ignore[attr-defined]
                self.mcs_ins_align_rows = []  # type: ignore[attr-defined]
        else:
            self.mcs_ins_dead_summary = ""  # type: ignore[attr-defined]
            self.mcs_ins_dead_rows = []  # type: ignore[attr-defined]
            self.mcs_ins_deleg_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_deleg_rows = []  # type: ignore[attr-defined]
            self.mcs_ins_deleg_warnings = []  # type: ignore[attr-defined]
            self.mcs_ins_align_kpis = []  # type: ignore[attr-defined]
            self.mcs_ins_align_rows = []  # type: ignore[attr-defined]

    def _clear_panel_data(self) -> None:
        """Reset all structured panel state vars."""
        self.mcs_profile_kpis = []  # type: ignore[attr-defined]
        self.mcs_profile_ai_config = []  # type: ignore[attr-defined]
        self.mcs_profile_instructions_len = ""  # type: ignore[attr-defined]
        self.mcs_profile_instructions_text = ""  # type: ignore[attr-defined]
        self.mcs_profile_instruction_drift = {}  # type: ignore[attr-defined]
        self.mcs_profile_starters = []  # type: ignore[attr-defined]
        self.mcs_profile_security_chips = []  # type: ignore[attr-defined]
        self.mcs_profile_bot_meta = []  # type: ignore[attr-defined]
        self.mcs_profile_env_vars = []  # type: ignore[attr-defined]
        self.mcs_profile_connectors = []  # type: ignore[attr-defined]
        self.mcs_profile_conn_refs = []  # type: ignore[attr-defined]
        self.mcs_profile_conn_defs = []  # type: ignore[attr-defined]
        self.mcs_profile_quick_wins = []  # type: ignore[attr-defined]
        self.mcs_profile_trigger_overlaps = []  # type: ignore[attr-defined]
        self.mcs_profile_inline_prompts = []  # type: ignore[attr-defined]
        self.mcs_profile_ai_builder_models = []  # type: ignore[attr-defined]
        self.mcs_tools_kpis = []  # type: ignore[attr-defined]
        self.mcs_tools_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_tools_external_calls = []  # type: ignore[attr-defined]
        self.mcs_tools_call_count = 0  # type: ignore[attr-defined]
        self.mcs_tools_stats_rows = []  # type: ignore[attr-defined]
        self.mcs_tools_flow_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_knowledge_kpis = []  # type: ignore[attr-defined]
        self.mcs_knowledge_sources = []  # type: ignore[attr-defined]
        self.mcs_knowledge_files = []  # type: ignore[attr-defined]
        self.mcs_knowledge_coverage = []  # type: ignore[attr-defined]
        self.mcs_knowledge_source_details = []  # type: ignore[attr-defined]
        self.mcs_knowledge_searches = []  # type: ignore[attr-defined]
        self.mcs_knowledge_attributions = []  # type: ignore[attr-defined]
        self.mcs_knowledge_attribution_summary = ""  # type: ignore[attr-defined]
        self.mcs_knowledge_citations = []  # type: ignore[attr-defined]
        self.mcs_knowledge_turn_strip = []  # type: ignore[attr-defined]
        self.mcs_knowledge_clusters = []  # type: ignore[attr-defined]
        self.mcs_knowledge_heatmap = []  # type: ignore[attr-defined]
        self.mcs_knowledge_custom_steps = []  # type: ignore[attr-defined]
        self.mcs_knowledge_general_enabled = False  # type: ignore[attr-defined]
        self.mcs_knowledge_citation_panel = []  # type: ignore[attr-defined]
        self.mcs_generative_traces = []  # type: ignore[attr-defined]
        self.mcs_generative_topics = []  # type: ignore[attr-defined]
        self.mcs_topics_kpis = []  # type: ignore[attr-defined]
        self.mcs_topics_summary = []  # type: ignore[attr-defined]
        self.mcs_topics_external_calls = []  # type: ignore[attr-defined]
        self.mcs_topics_coverage = []  # type: ignore[attr-defined]
        self.mcs_topics_coverage_summary = ""  # type: ignore[attr-defined]
        self.mcs_topics_anomalies = []  # type: ignore[attr-defined]
        self.mcs_topics_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_topics_trigger_matches = []  # type: ignore[attr-defined]
        self.mcs_topic_explorer_topics = []  # type: ignore[attr-defined]
        self.mcs_topic_explorer_selected = ""  # type: ignore[attr-defined]
        self.mcs_topic_explorer_search = ""  # type: ignore[attr-defined]
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
        self.mcs_conversation_id = ""  # type: ignore[attr-defined]
        self.mcs_highlight_target_id = ""  # type: ignore[attr-defined]
        self.mcs_conv_variables = []  # type: ignore[attr-defined]
        self.mcs_conv_phases = []  # type: ignore[attr-defined]
        self.mcs_conv_errors = []  # type: ignore[attr-defined]
        self.mcs_conv_error_banner = []  # type: ignore[attr-defined]
        self.mcs_conv_waterfall = []  # type: ignore[attr-defined]
        self.mcs_conv_reasoning = []  # type: ignore[attr-defined]
        self.mcs_conv_sequence_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_conv_gantt_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_credit_step_rows = []  # type: ignore[attr-defined]
        self.mcs_credit_mermaid = ""  # type: ignore[attr-defined]
        # Insights
        self.mcs_ins_turn_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_turn_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_quality_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_quality_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_dead_summary = ""  # type: ignore[attr-defined]
        self.mcs_ins_dead_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_plan_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_plan_diffs = []  # type: ignore[attr-defined]
        self.mcs_ins_ke_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_ke_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_ke_warnings = []  # type: ignore[attr-defined]
        self.mcs_ins_deleg_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_deleg_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_deleg_warnings = []  # type: ignore[attr-defined]
        self.mcs_ins_latency_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_latency_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_latency_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_ins_align_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_align_rows = []  # type: ignore[attr-defined]

    @rx.event
    def download_citations_csv(self):
        timeline_json: str = self.timeline_json  # type: ignore[attr-defined]
        if not timeline_json:
            self.upload_error = "No analysis loaded — upload a bot export first."
            return

        try:
            timeline = ConversationTimeline.model_validate_json(timeline_json)
        except Exception as e:
            logger.warning("Citations CSV: failed to rehydrate timeline: {}", e)
            self.upload_error = "Could not load citations from the current analysis."
            return

        csv_str = render_citations_csv(timeline)

        # Slug the visible bot/report title for the filename so the download
        # is recognisable when the user analyses several bots in one session.
        title = (self.report_title or "report").strip()  # type: ignore[attr-defined]
        slug = "".join(c if (c.isalnum() or c in ("-", "_")) else "-" for c in title) or "report"
        filename = f"citations-{slug}.csv"

        yield rx.download(data=csv_str, filename=filename)

    def new_upload(self):
        self.report_markdown = ""  # type: ignore[attr-defined]
        self.report_title = ""  # type: ignore[attr-defined]
        self.report_source = ""  # type: ignore[attr-defined]
        self.upload_error = ""
        self.paste_json = ""
        self.bot_profile_json = ""  # type: ignore[attr-defined]
        self.timeline_json = ""  # type: ignore[attr-defined]
        self.report_custom_findings = []  # type: ignore[attr-defined]
        _clear_bot_profile()
        self.lint_report_markdown = ""  # type: ignore[attr-defined]
        self.is_linting = False  # type: ignore[attr-defined]
        self.lint_error = ""  # type: ignore[attr-defined]
        # Clear AgentRX diagnosis state (mirrors DiagnosisMixin._clear_result)
        self.diagnosis_has_result = False  # type: ignore[attr-defined]
        self.diagnosis_kpis = []  # type: ignore[attr-defined]
        self.diagnosis_summary = ""  # type: ignore[attr-defined]
        self.diagnosis_reason_for_index = ""  # type: ignore[attr-defined]
        self.diagnosis_evidence_rows = []  # type: ignore[attr-defined]
        self.diagnosis_category_chips = []  # type: ignore[attr-defined]
        self.diagnosis_secondary_rows = []  # type: ignore[attr-defined]
        self.diagnosis_canned_recs = []  # type: ignore[attr-defined]
        self.diagnosis_llm_recs = []  # type: ignore[attr-defined]
        self.diagnosis_redaction_chips = []  # type: ignore[attr-defined]
        self.diagnosis_judge_model_used = ""  # type: ignore[attr-defined]
        self.diagnosis_generated_at = ""  # type: ignore[attr-defined]
        self.diagnosis_succeeded = False  # type: ignore[attr-defined]
        self.diagnosis_error_state = False  # type: ignore[attr-defined]
        self.diagnosis_error_message = ""  # type: ignore[attr-defined]
        self.diagnosis_error = ""  # type: ignore[attr-defined]
        self.is_diagnosing = False  # type: ignore[attr-defined]
        self._diagnosis_cache = {}  # type: ignore[attr-defined]
        # Chat with the judge (Issue B) — clear so a fresh upload doesn't
        # surface the old conversation under a stale verdict.
        self.diagnosis_active_cache_key = ""  # type: ignore[attr-defined]
        self.diagnosis_active_verdict_raw = {}  # type: ignore[attr-defined]
        self.diagnosis_chat_history_json = "[]"  # type: ignore[attr-defined]
        self.diagnosis_chat_input = ""  # type: ignore[attr-defined]
        self.diagnosis_chat_streaming_buffer = ""  # type: ignore[attr-defined]
        self.is_chatting = False  # type: ignore[attr-defined]
        self.diagnosis_chat_error = ""  # type: ignore[attr-defined]
        # Clear dynamic analysis state
        self.mcs_section_profile = ""  # type: ignore[attr-defined]
        self.mcs_section_knowledge = ""  # type: ignore[attr-defined]
        self.mcs_section_tools = ""  # type: ignore[attr-defined]
        self.mcs_section_conversation = ""  # type: ignore[attr-defined]
        self.mcs_section_credits = ""  # type: ignore[attr-defined]
        self.mcs_conversation_flow = []  # type: ignore[attr-defined]
        self.mcs_conversation_flow_groups = []  # type: ignore[attr-defined]
        self.mcs_conversation_flow_source = ""  # type: ignore[attr-defined]
        self.mcs_conv_kpis = []  # type: ignore[attr-defined]
        self.mcs_conv_event_mix = []  # type: ignore[attr-defined]
        self.mcs_conv_latency_bands = []  # type: ignore[attr-defined]
        self.mcs_conv_highlights = []  # type: ignore[attr-defined]
        self.mcs_credit_rows = []  # type: ignore[attr-defined]
        self.mcs_credit_total = 0.0  # type: ignore[attr-defined]
        self.mcs_credit_assumptions = []  # type: ignore[attr-defined]
        self.mcs_credit_step_rows = []  # type: ignore[attr-defined]
        self.mcs_credit_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_custom_findings = []  # type: ignore[attr-defined]
        self.mcs_coverage_skipped = []  # type: ignore[attr-defined]
        self.mcs_raw_event_index = []  # type: ignore[attr-defined]
        self.mcs_conv_metadata = []  # type: ignore[attr-defined]
        self.mcs_conversation_id = ""  # type: ignore[attr-defined]
        self.mcs_highlight_target_id = ""  # type: ignore[attr-defined]
        self.mcs_conv_variables = []  # type: ignore[attr-defined]
        self.mcs_conv_phases = []  # type: ignore[attr-defined]
        self.mcs_conv_errors = []  # type: ignore[attr-defined]
        self.mcs_conv_error_banner = []  # type: ignore[attr-defined]
        self.mcs_conv_waterfall = []  # type: ignore[attr-defined]
        self.mcs_conv_reasoning = []  # type: ignore[attr-defined]
        self.mcs_conv_sequence_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_conv_gantt_mermaid = ""  # type: ignore[attr-defined]
        # Insights
        self.mcs_ins_turn_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_turn_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_quality_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_quality_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_dead_summary = ""  # type: ignore[attr-defined]
        self.mcs_ins_dead_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_plan_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_plan_diffs = []  # type: ignore[attr-defined]
        self.mcs_ins_ke_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_ke_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_ke_warnings = []  # type: ignore[attr-defined]
        self.mcs_ins_deleg_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_deleg_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_deleg_warnings = []  # type: ignore[attr-defined]
        self.mcs_ins_latency_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_latency_rows = []  # type: ignore[attr-defined]
        self.mcs_ins_latency_mermaid = ""  # type: ignore[attr-defined]
        self.mcs_ins_align_kpis = []  # type: ignore[attr-defined]
        self.mcs_ins_align_rows = []  # type: ignore[attr-defined]
        self._clear_panel_data()
        return rx.redirect("/dashboard")

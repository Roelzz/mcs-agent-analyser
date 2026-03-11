import asyncio
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import reflex as rx
from loguru import logger

from instruction_store import save_snapshot  # noqa: E402
from models import BotProfile  # noqa: E402
from parser import build_bot_dict, parse_bot_data  # noqa: E402
from batch_analytics import aggregate_timelines, render_batch_report  # noqa: E402
from renderer import render_instruction_drift, render_report, render_transcript_report  # noqa: E402
from timeline import build_timeline  # noqa: E402
from transcript import parse_transcript_json  # noqa: E402

from web.state._base import _load_bot_profile, _save_bot_profile


class DataverseMixin(rx.State, mixin=True):
    """Dataverse import vars and handlers."""

    # Dataverse Import — connection config (session-only, user enters each time)
    dv_org_url: str = ""
    dv_tenant_id: str = ""
    dv_client_id: str = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
    dv_bot_identifier: str = ""
    dv_since_date: str = ""
    dv_top_n: int = 50

    # Dataverse Import — session state
    dv_device_code: str = ""
    dv_device_code_url: str = ""
    dv_is_authenticating: bool = False
    dv_auth_error: str = ""
    dv_is_connected: bool = False
    dv_token: str = ""
    dv_is_fetching: bool = False
    dv_fetch_error: str = ""
    dv_transcripts: list[dict] = []
    dv_transcript_contents: dict = {}
    dv_import_processing: bool = False
    dv_import_error: str = ""

    # Dataverse Import — session details autofill
    dv_session_details_paste: str = ""
    dv_autofill_error: str = ""

    # Dataverse Import — bot analysis
    dv_bot_analysing: bool = False
    dv_bot_analyse_error: str = ""
    dv_schema_lookup: dict = {}

    # Dataverse Import — single conversation lookup
    dv_conversation_id: str = ""
    dv_single_fetch_error: str = ""
    dv_single_fetching: bool = False

    # Dataverse Import — batch analysis
    dv_batch_processing: bool = False
    dv_batch_error: str = ""

    # Setters
    @rx.event
    def set_dv_org_url(self, value: str):
        self.dv_org_url = value

    @rx.event
    def set_dv_tenant_id(self, value: str):
        self.dv_tenant_id = value

    @rx.event
    def set_dv_client_id(self, value: str):
        self.dv_client_id = value

    @rx.event
    def set_dv_bot_identifier(self, value: str):
        self.dv_bot_identifier = value

    @rx.event
    def set_dv_since_date(self, value: str):
        self.dv_since_date = value

    @rx.event
    def set_dv_top_n(self, value: str):
        try:
            self.dv_top_n = int(value)
        except (ValueError, TypeError):
            pass

    @rx.event
    def set_dv_session_details_paste(self, value: str):
        self.dv_session_details_paste = value

    @rx.event
    def set_dv_conversation_id(self, value: str):
        self.dv_conversation_id = value

    @rx.var
    def dv_has_transcripts(self) -> bool:
        return len(self.dv_transcripts) > 0

    @rx.var
    def dv_show_device_code(self) -> bool:
        return bool(self.dv_device_code) and self.dv_is_authenticating

    @rx.var
    def dv_selected_count(self) -> int:
        return sum(1 for t in self.dv_transcripts if t.get("selected"))

    @rx.var
    def dv_has_selection(self) -> bool:
        return any(t.get("selected") for t in self.dv_transcripts)

    @rx.var
    def dv_all_selected(self) -> bool:
        return bool(self.dv_transcripts) and all(t.get("selected") for t in self.dv_transcripts)

    # --- Dataverse Import handlers ---

    @rx.event
    def dv_toggle_select(self, transcript_id: str):
        self.dv_transcripts = [
            {**t, "selected": not t["selected"]} if t["id"] == transcript_id else t for t in self.dv_transcripts
        ]

    @rx.event
    def dv_toggle_select_all(self):
        all_selected = all(t.get("selected") for t in self.dv_transcripts)
        self.dv_transcripts = [{**t, "selected": not all_selected} for t in self.dv_transcripts]

    @rx.event
    def dv_autofill_from_session_details(self):
        """Parse pasted Copilot Studio session details and auto-fill connection fields."""
        text = self.dv_session_details_paste.strip()
        if not text:
            self.dv_autofill_error = "Paste field is empty."
            return

        filled: list[str] = []
        missing: list[str] = []

        # Parse Tenant ID
        tenant_match = re.search(r"Tenant\s+ID\s*:\s*([0-9a-f-]{36})", text, re.IGNORECASE)
        if tenant_match:
            self.dv_tenant_id = tenant_match.group(1)
            filled.append("Tenant ID")
        else:
            missing.append("Tenant ID")

        # Parse Instance url
        url_match = re.search(r"Instance\s+url\s*:\s*(https?://\S+)", text, re.IGNORECASE)
        if url_match:
            self.dv_org_url = url_match.group(1).rstrip("/")
            filled.append("Instance url")
        else:
            missing.append("Instance url")

        # Parse Copilot Id
        copilot_match = re.search(r"Copilot\s+Id\s*:\s*([0-9a-f-]{36})", text, re.IGNORECASE)
        if copilot_match:
            self.dv_bot_identifier = copilot_match.group(1)
            filled.append("Copilot Id")
        else:
            missing.append("Copilot Id")

        if not filled:
            self.dv_autofill_error = (
                "Could not find any session details in the pasted text. "
                "Expected format: 'Tenant ID: <uuid>', 'Instance url: <url>', 'Copilot Id: <uuid>'."
            )
            return

        self.dv_session_details_paste = ""
        if missing:
            self.dv_autofill_error = (
                f"Filled {', '.join(filled)}. Could not find: {', '.join(missing)}. Fill the remaining fields manually."
            )
        else:
            self.dv_autofill_error = ""

    async def init_import_page(self):
        if not self.is_authenticated:  # type: ignore[attr-defined]
            return rx.redirect("/")
        await self._refresh_community_count()  # type: ignore[attr-defined]
        if not self.dv_since_date:
            default_since = datetime.now(timezone.utc) - timedelta(days=30)
            self.dv_since_date = default_since.strftime("%Y-%m-%d")

    @rx.event
    async def start_device_flow(self):
        org_url = self.dv_org_url.strip()
        tenant_id = self.dv_tenant_id.strip()

        if not org_url:
            self.dv_auth_error = (
                "Enter your Dataverse environment URL. Find it in "
                "Copilot Studio \u2192 Settings (gear icon) \u2192 Session details \u2192 Instance url."
            )
            return
        if not tenant_id:
            self.dv_auth_error = (
                "Enter your Azure AD tenant ID. Find it in "
                "Copilot Studio \u2192 Settings (gear icon) \u2192 Session details \u2192 Tenant ID."
            )
            return

        self.dv_auth_error = ""
        self.dv_is_authenticating = True
        self.dv_device_code = ""
        self.dv_device_code_url = ""
        yield

        try:
            import msal

            authority = f"https://login.microsoftonline.com/{tenant_id}"
            client_id = self.dv_client_id.strip() or "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
            app = msal.PublicClientApplication(client_id, authority=authority)

            scope = f"{org_url.rstrip('/')}/.default"
            flow = await asyncio.to_thread(app.initiate_device_flow, scopes=[scope])

            if "user_code" not in flow:
                error = flow.get("error_description", flow.get("error", "Unknown error"))
                self.dv_auth_error = f"Device flow initiation failed: {error}"
                self.dv_is_authenticating = False
                return

            self.dv_device_code = flow["user_code"]
            self.dv_device_code_url = flow.get("verification_uri", "https://microsoft.com/devicelogin")
            yield

            result = await asyncio.to_thread(app.acquire_token_by_device_flow, flow)

            if "access_token" in result:
                self.dv_token = result["access_token"]
                self.dv_is_connected = True
                self.dv_device_code = ""
                self.dv_device_code_url = ""
                logger.info("Dataverse device code auth succeeded")
                yield  # push connected UI to client
                if self.dv_bot_identifier.strip():
                    self.dv_bot_analysing = True
                    yield  # show spinner on Analyse Bot button
                    await self._run_bot_analysis()
                    self.dv_bot_analysing = False
                    if self.report_markdown:  # type: ignore[attr-defined]
                        yield
                        await self._refresh_community_count()  # type: ignore[attr-defined]
                        yield rx.redirect("/analysis")
            else:
                error = result.get("error_description", result.get("error", "Unknown error"))
                self.dv_auth_error = (
                    f"Authentication failed: {error}. "
                    "Check that your Tenant ID is correct and you have access to this environment."
                )
        except Exception as e:
            logger.error(f"Device flow error: {e}")
            self.dv_auth_error = (
                f"Authentication failed: {e}. "
                "Check that your Tenant ID is correct and you have access to this environment."
            )
        finally:
            self.dv_is_authenticating = False
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]

    @rx.event
    async def dv_fetch_transcripts(self):
        bot_id = self.dv_bot_identifier.strip()
        if not bot_id:
            self.dv_fetch_error = (
                "Enter the bot Copilot Id (GUID). Find it in "
                "Copilot Studio \u2192 Settings (gear icon) \u2192 Session details \u2192 Copilot Id."
            )
            return

        self.dv_fetch_error = ""
        self.dv_is_fetching = True
        yield

        try:
            from dataverse_client import DataverseClient

            client = DataverseClient(
                org_url=self.dv_org_url.strip(),
                tenant_id=self.dv_tenant_id.strip(),
                client_id=self.dv_client_id.strip(),
                _prefetched_token=self.dv_token,
            )

            since_dt = datetime.strptime(self.dv_since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            records = await client.fetch_transcripts(bot_id, since_dt, top=self.dv_top_n)

            if not records:
                self.dv_fetch_error = (
                    f"No transcripts found for this bot since {self.dv_since_date}. "
                    "Transcripts can take ~30 minutes to appear after a conversation ends."
                )
                self.dv_is_fetching = False
                return

            summaries = []
            contents = {}

            for record in records:
                tid = record.get("conversationtranscriptid", "")
                created = record.get("createdon", "")
                content_raw = record.get("content", "")

                # Parse content to get preview and activity count
                activities = []
                if content_raw:
                    try:
                        parsed = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                        if isinstance(parsed, list):
                            activities = parsed
                        elif isinstance(parsed, dict):
                            activities = parsed.get("activities", [])
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Find first user message for preview
                preview = ""
                for act in activities:
                    if act.get("type") == "message":
                        from_info = act.get("from", {}) or {}
                        role = from_info.get("role", "")
                        if role in ("user", 1):
                            text = act.get("text", "")
                            if text:
                                preview = text[:120] + ("..." if len(text) > 120 else "")
                                break

                if not preview:
                    preview = "(no user message found)"

                summaries.append(
                    {
                        "id": tid,
                        "short_id": tid[:8] + "..." if len(tid) > 8 else tid,
                        "created_on": created[:10] if len(created) >= 10 else created,
                        "preview": preview,
                        "activity_count": len(activities),
                        "selected": False,
                    }
                )
                contents[tid] = content_raw

            self.dv_transcripts = summaries
            self.dv_transcript_contents = contents
            logger.info(f"Loaded {len(summaries)} transcript summaries")

        except RuntimeError as e:
            error_msg = str(e)
            if "No bot found" in error_msg:
                self.dv_fetch_error = (
                    f"No bot found with identifier '{bot_id}'. "
                    "Check the Copilot Id in Copilot Studio \u2192 Settings (gear icon) \u2192 Session details."
                )
            else:
                self.dv_fetch_error = str(e)
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                self.dv_fetch_error = "Session expired. Click Disconnect, then Connect again to re-authenticate."
            elif "403" in error_str:
                self.dv_fetch_error = (
                    "Access denied. Your account needs read access to the conversationtranscripts table in Dataverse."
                )
            else:
                logger.error(f"Fetch transcripts failed: {e}")
                self.dv_fetch_error = f"Fetch failed: {e}"
        finally:
            self.dv_is_fetching = False
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]

    @rx.event
    async def dv_analyse_transcript(self, transcript_id: str):
        self.dv_import_processing = True
        self.dv_import_error = ""
        yield

        try:
            content_raw = self.dv_transcript_contents.get(transcript_id, "")
            if not content_raw:
                self.dv_import_error = "Transcript content not found."
                self.dv_import_processing = False
                return

            # Parse content, handle flat list vs wrapped format
            parsed = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            if isinstance(parsed, list):
                parsed = {"activities": parsed}

            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = Path(tmpdir) / "dataverse_transcript.json"
                json_path.write_text(json.dumps(parsed))

                activities, metadata = parse_transcript_json(json_path)
                timeline = build_timeline(activities, self.dv_schema_lookup)

                # Find a title from the preview
                title = "Dataverse Transcript"
                for t in self.dv_transcripts:
                    if t.get("id") == transcript_id:
                        preview = t.get("preview", "")
                        if preview and preview != "(no user message found)":
                            title = preview[:60] + ("..." if len(preview) > 60 else "")
                        break

                if not self.bot_profile_json:  # type: ignore[attr-defined]
                    self.bot_profile_json = _load_bot_profile()  # type: ignore[attr-defined]
                logger.debug(
                    "bot_profile_json present: {} (len={})",
                    bool(self.bot_profile_json),
                    len(self.bot_profile_json),  # type: ignore[attr-defined]
                )
                custom = self.get_custom_rules() or None  # type: ignore[attr-defined]
                if self.bot_profile_json:  # type: ignore[attr-defined]
                    profile = BotProfile.model_validate_json(self.bot_profile_json)  # type: ignore[attr-defined]
                    self.report_markdown = render_report(profile, timeline, custom_rules=custom)  # type: ignore[attr-defined]
                    self.report_title = profile.display_name  # type: ignore[attr-defined]
                    instruction_diff = save_snapshot(profile)
                    if instruction_diff and instruction_diff.is_significant:
                        self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]
                else:
                    self.report_markdown = render_transcript_report(title, timeline, metadata)  # type: ignore[attr-defined]
                    self.report_title = title  # type: ignore[attr-defined]
                self.report_source = "import"  # type: ignore[attr-defined]
                self.lint_report_markdown = ""  # type: ignore[attr-defined]

        except Exception as e:
            logger.error(f"Dataverse transcript analysis failed: {e}")
            self.dv_import_error = f"Analysis failed: {e}"
        finally:
            self.dv_import_processing = False
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]
            if self.report_markdown:  # type: ignore[attr-defined]
                yield rx.redirect("/analysis")

    @rx.event
    async def dv_fetch_and_analyse_by_id(self):
        """Fetch a single transcript by conversation ID and analyse it."""
        conversation_id = self.dv_conversation_id.strip()
        if not conversation_id:
            self.dv_single_fetch_error = "Enter a conversation ID."
            return

        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        if not uuid_pattern.match(conversation_id):
            self.dv_single_fetch_error = (
                "Invalid format. Conversation ID must be a UUID (e.g. 12345678-abcd-1234-abcd-1234567890ab)."
            )
            return

        self.dv_single_fetch_error = ""
        self.dv_single_fetching = True
        yield

        try:
            from dataverse_client import DataverseClient

            client = DataverseClient(
                org_url=self.dv_org_url.strip(),
                tenant_id=self.dv_tenant_id.strip(),
                client_id=self.dv_client_id.strip(),
                _prefetched_token=self.dv_token,
            )

            record = await client.fetch_transcript_by_id(conversation_id)
            content_raw = record.get("content", "")

            if not content_raw:
                self.dv_single_fetch_error = "Transcript found but content is empty."
                self.dv_single_fetching = False
                return

            parsed = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            if isinstance(parsed, list):
                parsed = {"activities": parsed}

            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = Path(tmpdir) / "conversation_transcript.json"
                json_path.write_text(json.dumps(parsed))

                activities, metadata = parse_transcript_json(json_path)
                timeline = build_timeline(activities, self.dv_schema_lookup)

                title = f"Conversation {conversation_id[:8]}..."
                if not self.bot_profile_json:  # type: ignore[attr-defined]
                    self.bot_profile_json = _load_bot_profile()  # type: ignore[attr-defined]
                logger.debug(
                    "bot_profile_json present: {} (len={})",
                    bool(self.bot_profile_json),
                    len(self.bot_profile_json),  # type: ignore[attr-defined]
                )
                custom = self.get_custom_rules() or None  # type: ignore[attr-defined]
                if self.bot_profile_json:  # type: ignore[attr-defined]
                    profile = BotProfile.model_validate_json(self.bot_profile_json)  # type: ignore[attr-defined]
                    self.report_markdown = render_report(profile, timeline, custom_rules=custom)  # type: ignore[attr-defined]
                    self.report_title = profile.display_name  # type: ignore[attr-defined]
                    instruction_diff = save_snapshot(profile)
                    if instruction_diff and instruction_diff.is_significant:
                        self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]
                else:
                    self.report_markdown = render_transcript_report(title, timeline, metadata)  # type: ignore[attr-defined]
                    self.report_title = title  # type: ignore[attr-defined]
                self.report_source = "import"  # type: ignore[attr-defined]
                self.lint_report_markdown = ""  # type: ignore[attr-defined]

        except RuntimeError as e:
            self.dv_single_fetch_error = str(e)
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                self.dv_single_fetch_error = "Session expired. Disconnect and reconnect to re-authenticate."
            elif "403" in error_str:
                self.dv_single_fetch_error = (
                    "Access denied. Your account needs read access to conversationtranscripts in Dataverse."
                )
            else:
                logger.error(f"Single transcript fetch failed: {e}")
                self.dv_single_fetch_error = f"Fetch failed: {e}"
        finally:
            self.dv_single_fetching = False
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]
            if self.report_markdown:  # type: ignore[attr-defined]
                yield rx.redirect("/analysis")

    async def _run_bot_analysis(self):
        """Core bot analysis logic — fetch config + components, generate report.

        Callers manage dv_bot_analysing flag. Sets dv_bot_analyse_error on failure.
        """
        try:
            from dataverse_client import DataverseClient

            client = DataverseClient(
                org_url=self.dv_org_url.strip(),
                tenant_id=self.dv_tenant_id.strip(),
                client_id=self.dv_client_id.strip(),
                _prefetched_token=self.dv_token,
            )

            bot_guid = await client.resolve_bot_guid(self.dv_bot_identifier.strip())
            bot_record = await client.fetch_bot_config(bot_guid)
            authoritative_id = bot_record.get("botid", bot_guid)
            logger.debug("Bot GUID for component fetch: {} (input was {})", authoritative_id, bot_guid)
            component_records = await client.fetch_bot_components(authoritative_id)

            bot_dict = build_bot_dict(bot_record, component_records)
            profile, schema_lookup = parse_bot_data(bot_dict)
            self.dv_schema_lookup = schema_lookup
            logger.info(
                "Analyse Bot result: {} \u2014 {} components",
                profile.display_name,
                len(profile.components),
            )

            custom = self.get_custom_rules() or None  # type: ignore[attr-defined]
            self.report_markdown = render_report(profile, custom_rules=custom)  # type: ignore[attr-defined]
            self.report_title = profile.display_name  # type: ignore[attr-defined]
            self.report_source = "import"  # type: ignore[attr-defined]
            self.bot_profile_json = profile.model_dump_json()  # type: ignore[attr-defined]
            _save_bot_profile(self.bot_profile_json)  # type: ignore[attr-defined]
            logger.debug("Stored bot_profile_json (len={})", len(self.bot_profile_json))  # type: ignore[attr-defined]
            self.lint_report_markdown = ""  # type: ignore[attr-defined]

            instruction_diff = save_snapshot(profile)
            if instruction_diff and instruction_diff.is_significant:
                self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]

        except RuntimeError as e:
            self.dv_bot_analyse_error = str(e)
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                self.dv_bot_analyse_error = "Session expired. Disconnect and reconnect to re-authenticate."
            elif "403" in error_str:
                self.dv_bot_analyse_error = (
                    "Access denied. Your account needs read access to the bots and botcomponents tables in Dataverse."
                )
            else:
                logger.error(f"Bot analysis failed: {e}")
                self.dv_bot_analyse_error = f"Analysis failed: {e}"

    @rx.event
    async def dv_analyse_bot(self):
        """Fetch bot config + components from Dataverse and generate full analysis report."""
        bot_id = self.dv_bot_identifier.strip()
        if not bot_id:
            self.dv_bot_analyse_error = (
                "Enter the bot Copilot Id (GUID). Find it in "
                "Copilot Studio \u2192 Settings (gear icon) \u2192 Session details \u2192 Copilot Id."
            )
            return

        self.dv_bot_analyse_error = ""
        self.dv_bot_analysing = True
        yield

        await self._run_bot_analysis()
        self.dv_bot_analysing = False
        yield
        await self._refresh_community_count()  # type: ignore[attr-defined]
        if self.report_markdown:  # type: ignore[attr-defined]
            yield rx.redirect("/analysis")

    @rx.event
    async def dv_run_batch_analysis(self):
        """Run batch analytics on selected Dataverse transcripts."""
        selected = [t for t in self.dv_transcripts if t.get("selected")]
        if not selected:
            self.dv_batch_error = "No transcripts selected."
            return

        self.dv_batch_processing = True
        self.dv_batch_error = ""
        yield

        try:
            timelines = []
            metadata_list = []

            for t in selected:
                content_raw = self.dv_transcript_contents.get(t["id"], "")
                if not content_raw:
                    continue

                parsed = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                if isinstance(parsed, list):
                    parsed = {"activities": parsed}

                with tempfile.TemporaryDirectory() as tmpdir:
                    json_path = Path(tmpdir) / "transcript.json"
                    json_path.write_text(json.dumps(parsed))

                    try:
                        activities, metadata = parse_transcript_json(json_path)
                        timeline = build_timeline(activities, self.dv_schema_lookup)
                        timelines.append(timeline)
                        metadata_list.append(metadata)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(f"Skipping transcript {t['id']}: {e}")

            if not timelines:
                self.dv_batch_error = "No valid transcripts found in selection."
                return

            summary = aggregate_timelines(timelines, metadata_list)
            self.batch_report_md = render_batch_report(summary)  # type: ignore[attr-defined]
            self.batch_count = len(timelines)  # type: ignore[attr-defined]
            logger.info(f"Dataverse batch analysis complete: {len(timelines)} transcripts")

        except Exception as e:
            logger.error(f"Dataverse batch analysis failed: {e}")
            self.dv_batch_error = f"Batch analysis failed: {e}"
        finally:
            self.dv_batch_processing = False
            yield
            if self.batch_report_md:  # type: ignore[attr-defined]
                yield rx.redirect("/batch")

    @rx.event
    def dv_disconnect(self):
        self.dv_token = ""
        self.dv_is_connected = False
        self.dv_transcripts = []
        self.dv_transcript_contents = {}
        self.dv_device_code = ""
        self.dv_device_code_url = ""
        self.dv_fetch_error = ""
        self.dv_auth_error = ""
        self.dv_session_details_paste = ""
        self.dv_autofill_error = ""
        self.dv_conversation_id = ""
        self.dv_single_fetch_error = ""
        self.dv_single_fetching = False
        self.dv_bot_analysing = False
        self.dv_bot_analyse_error = ""
        self.dv_batch_error = ""

    @rx.event
    def dv_back_to_list(self):
        """Clear report view but preserve bot profile and Dataverse connection."""
        self.report_markdown = ""  # type: ignore[attr-defined]
        self.report_title = ""  # type: ignore[attr-defined]
        self.report_source = ""  # type: ignore[attr-defined]
        self.lint_report_markdown = ""  # type: ignore[attr-defined]
        self.is_linting = False  # type: ignore[attr-defined]
        self.lint_error = ""  # type: ignore[attr-defined]
        return rx.redirect("/import")

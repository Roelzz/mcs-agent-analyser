import asyncio
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import reflex as rx
from dotenv import load_dotenv
from loguru import logger

# Ensure project root is importable (Reflex runs from project root)
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from parser import build_bot_dict, parse_bot_data, parse_dialog_json, parse_yaml  # noqa: E402
from renderer import render_report, render_transcript_report  # noqa: E402
from timeline import build_timeline  # noqa: E402
from transcript import parse_transcript_json  # noqa: E402

from web.mermaid import split_markdown_mermaid  # noqa: E402

from linter import run_lint as _run_lint  # noqa: E402
from models import BotProfile  # noqa: E402

load_dotenv()

# --- Community counter (komarev badge) ---

_KOMAREV_URL = (
    "https://komarev.com/ghpvc/?username=Roelzz"
    "&label=Community%20Views&color=0e75b6&style=flat"
)

_community_count_cache: dict[str, float | int] = {"count": 0, "fetched_at": 0.0}


def _fetch_community_count() -> int:
    """Fetch community view count from komarev badge SVG (cached 30s)."""
    now = time.time()
    if now - _community_count_cache["fetched_at"] < 30:
        return int(_community_count_cache["count"])
    try:
        req = urllib.request.Request(
            _KOMAREV_URL, headers={"User-Agent": "AgentAnalyser/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            svg = resp.read().decode()
            numbers = re.findall(r">(\d+)</", svg)
            if numbers:
                count = int(numbers[-1])
                _community_count_cache["count"] = count
                _community_count_cache["fetched_at"] = now
                return count
    except Exception as e:
        logger.warning(f"Failed to fetch community count: {e}")
    return int(_community_count_cache["count"])


_CAT_MILESTONES: list[tuple[int, str, str]] = [
    (1000, "\U0001f406", "Legendary Leopard"),
    (500, "\U0001f42f", "Tiger Analyst"),
    (250, "\U0001f981", "Lion Mode"),
    (100, "\U0001f408\u200d\u2b1b", "Shadow Cat"),
    (50, "\U0001f408", "Prowling Cat"),
    (25, "\U0001f638", "Grinning Cat"),
    (10, "\U0001f63a", "Happy Cat"),
    (0, "\U0001f431", "Curious Kitten"),
]

_MILESTONE_THRESHOLDS: set[int] = {t for t, _, _ in _CAT_MILESTONES if t > 0}

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_BOT_PROFILE_FILE = _DATA_DIR / "bot_profile.json"


def _save_bot_profile(json_str: str) -> None:
    _BOT_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _BOT_PROFILE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json_str)
        tmp.replace(_BOT_PROFILE_FILE)
    except OSError as e:
        logger.error(f"Failed to save bot profile: {e}")


def _load_bot_profile() -> str:
    try:
        if _BOT_PROFILE_FILE.exists():
            return _BOT_PROFILE_FILE.read_text()
    except OSError as e:
        logger.warning(f"Failed to load bot profile: {e}")
    return ""


def _clear_bot_profile() -> None:
    try:
        _BOT_PROFILE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _load_users() -> dict[str, str]:
    """Parse USERS env var into username:password dict.

    Format: "admin:pass1,analyst:pass2"
    """
    raw = os.getenv("USERS", "")
    if not raw.strip():
        return {}
    users: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            username, password = pair.split(":", 1)
            username = username.strip()
            password = password.strip()
            if username:
                users[username] = password
    return users


class State(rx.State):
    """Combined auth, upload, and report state."""

    # Auth
    username: str = ""
    password: str = ""
    is_authenticated: bool = False
    auth_error: str = ""

    # Upload
    is_processing: bool = False
    upload_error: str = ""
    paste_json: str = ""

    # Report
    report_markdown: str = ""
    report_title: str = ""

    # Lint
    bot_profile_json: str = ""
    lint_report_markdown: str = ""
    is_linting: bool = False
    lint_error: str = ""

    # Counter
    analyses_count: int = 0
    counter_animating: bool = False
    milestone_reached: bool = False

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

    # Explicit setters (auto-setters deprecated in 0.8.9)
    @rx.event
    def set_username(self, value: str):
        self.username = value

    @rx.event
    def set_password(self, value: str):
        self.password = value

    @rx.event
    def set_paste_json(self, value: str):
        self.paste_json = value

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
    def has_report(self) -> bool:
        return bool(self.report_markdown)

    @rx.var
    def report_segments(self) -> list[dict[str, str]]:
        if not self.report_markdown:
            return []
        segments = split_markdown_mermaid(self.report_markdown)
        return [{"type": t, "content": c} for t, c in segments]

    @rx.var
    def can_lint(self) -> bool:
        return bool(self.bot_profile_json) and bool(self.report_markdown)

    @rx.var
    def dv_has_transcripts(self) -> bool:
        return len(self.dv_transcripts) > 0

    @rx.var
    def dv_show_device_code(self) -> bool:
        return bool(self.dv_device_code) and self.dv_is_authenticating

    @rx.var
    def cat_emoji(self) -> str:
        for threshold, emoji, _ in _CAT_MILESTONES:
            if self.analyses_count >= threshold:
                return emoji
        return "\U0001f431"

    @rx.var
    def cat_title(self) -> str:
        for threshold, _, title in _CAT_MILESTONES:
            if self.analyses_count >= threshold:
                return title
        return "Curious Kitten"

    @rx.var
    def has_lint_report(self) -> bool:
        return bool(self.lint_report_markdown)

    @rx.var
    def lint_report_segments(self) -> list[dict[str, str]]:
        if not self.lint_report_markdown:
            return []
        segments = split_markdown_mermaid(self.lint_report_markdown)
        return [{"type": t, "content": c} for t, c in segments]

    # --- Auth handlers ---

    @rx.event
    def login(self):
        users = _load_users()
        if not users:
            self.auth_error = "No users configured. Set USERS env var."
            return
        if users.get(self.username) == self.password:
            self.is_authenticated = True
            self.auth_error = ""
            return rx.redirect("/upload")
        self.auth_error = "Invalid username or password."

    @rx.event
    def logout(self):
        self.username = ""
        self.password = ""
        self.is_authenticated = False
        self.auth_error = ""
        self.report_markdown = ""
        self.report_title = ""
        self.upload_error = ""
        self.is_processing = False
        self.bot_profile_json = ""
        _clear_bot_profile()
        self.lint_report_markdown = ""
        self.is_linting = False
        self.lint_error = ""
        # Clear Dataverse state
        self.dv_org_url = ""
        self.dv_tenant_id = ""
        self.dv_client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
        self.dv_bot_identifier = ""
        self.dv_since_date = ""
        self.dv_top_n = 50
        self.dv_device_code = ""
        self.dv_device_code_url = ""
        self.dv_is_authenticating = False
        self.dv_auth_error = ""
        self.dv_is_connected = False
        self.dv_token = ""
        self.dv_is_fetching = False
        self.dv_fetch_error = ""
        self.dv_transcripts = []
        self.dv_transcript_contents = {}
        self.dv_import_processing = False
        self.dv_import_error = ""
        self.dv_session_details_paste = ""
        self.dv_autofill_error = ""
        self.dv_conversation_id = ""
        self.dv_single_fetch_error = ""
        self.dv_single_fetching = False
        self.dv_bot_analysing = False
        self.dv_bot_analyse_error = ""
        return rx.redirect("/")

    async def check_auth(self):
        if not self.is_authenticated:
            return rx.redirect("/")
        await self._refresh_community_count()

    def check_already_authed(self):
        if self.is_authenticated:
            return rx.redirect("/upload")

    # --- Upload handlers ---

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        if not files:
            self.upload_error = "No files selected."
            return

        self.is_processing = True
        self.upload_error = ""
        yield

        try:
            names = [f.filename for f in files]
            exts = [Path(n).suffix.lower() for n in names]

            if len(files) == 1 and exts[0] == ".zip":
                await self._process_bot_zip(files)
            elif len(files) == 2:
                has_yaml = any(e in (".yml", ".yaml") for e in exts)
                has_json = any(e == ".json" for e in exts)
                if has_yaml and has_json:
                    await self._process_bot_files(files)
                else:
                    self.upload_error = (
                        "Two files uploaded but expected botContent.yml + dialog.json. "
                        f"Got: {', '.join(names)}"
                    )
            elif len(files) == 1 and exts[0] == ".json":
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
        yield

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                json_path = Path(tmpdir) / "pasted_transcript.json"
                json_path.write_text(text)

                activities, metadata = parse_transcript_json(json_path)
                timeline = build_timeline(activities, {})
                title = "Pasted Transcript"
                self.report_markdown = render_transcript_report(title, timeline, metadata)
                self.report_title = title
                self.bot_profile_json = ""
                _clear_bot_profile()

                self.paste_json = ""
        except Exception as e:
            logger.error(f"Paste processing failed: {e}")
            self.upload_error = f"Processing failed: {e}"
        finally:
            self.is_processing = False

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
                zf.extractall(extract_dir)

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
            self.report_markdown = render_report(profile, timeline)
            self.report_title = profile.display_name
            self.bot_profile_json = profile.model_dump_json()
            _save_bot_profile(self.bot_profile_json)


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
            self.report_markdown = render_report(profile, timeline)
            self.report_title = profile.display_name
            self.bot_profile_json = profile.model_dump_json()
            _save_bot_profile(self.bot_profile_json)


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
            self.report_markdown = render_transcript_report(title, timeline, metadata)
            self.report_title = title
            self.bot_profile_json = ""
            _clear_bot_profile()


    async def _refresh_community_count(self):
        """Fetch community count from komarev and trigger animation if it changed."""
        prev = self.analyses_count
        self.analyses_count = await asyncio.to_thread(_fetch_community_count)
        if self.analyses_count > prev and prev > 0:
            self.counter_animating = True
            self.milestone_reached = any(
                prev < t <= self.analyses_count for t in _MILESTONE_THRESHOLDS
            )

    @rx.event
    def reset_counter_animation(self):
        self.counter_animating = False
        self.milestone_reached = False

    # --- Dataverse Import handlers ---

    @rx.event
    def dv_autofill_from_session_details(self):
        """Parse pasted Copilot Studio session details and auto-fill connection fields."""
        import re

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
                f"Filled {', '.join(filled)}. Could not find: {', '.join(missing)}. "
                "Fill the remaining fields manually."
            )
        else:
            self.dv_autofill_error = ""

    async def init_import_page(self):
        if not self.is_authenticated:
            return rx.redirect("/")
        await self._refresh_community_count()
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
                "Copilot Studio → Settings (gear icon) → Session details → Instance url."
            )
            return
        if not tenant_id:
            self.dv_auth_error = (
                "Enter your Azure AD tenant ID. Find it in "
                "Copilot Studio → Settings (gear icon) → Session details → Tenant ID."
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

    @rx.event
    async def dv_fetch_transcripts(self):
        bot_id = self.dv_bot_identifier.strip()
        if not bot_id:
            self.dv_fetch_error = (
                "Enter the bot Copilot Id (GUID). Find it in "
                "Copilot Studio → Settings (gear icon) → Session details → Copilot Id."
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

                summaries.append({
                    "id": tid,
                    "created_on": created[:10] if len(created) >= 10 else created,
                    "preview": preview,
                    "activity_count": len(activities),
                })
                contents[tid] = content_raw

            self.dv_transcripts = summaries
            self.dv_transcript_contents = contents
            logger.info(f"Loaded {len(summaries)} transcript summaries")

        except RuntimeError as e:
            error_msg = str(e)
            if "No bot found" in error_msg:
                self.dv_fetch_error = (
                    f"No bot found with identifier '{bot_id}'. "
                    "Check the Copilot Id in Copilot Studio → Settings (gear icon) → Session details."
                )
            else:
                self.dv_fetch_error = str(e)
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                self.dv_fetch_error = "Session expired. Click Disconnect, then Connect again to re-authenticate."
            elif "403" in error_str:
                self.dv_fetch_error = (
                    "Access denied. Your account needs read access to the "
                    "conversationtranscripts table in Dataverse."
                )
            else:
                logger.error(f"Fetch transcripts failed: {e}")
                self.dv_fetch_error = f"Fetch failed: {e}"
        finally:
            self.dv_is_fetching = False

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

                if not self.bot_profile_json:
                    self.bot_profile_json = _load_bot_profile()
                logger.debug("bot_profile_json present: {} (len={})", bool(self.bot_profile_json), len(self.bot_profile_json))
                if self.bot_profile_json:
                    profile = BotProfile.model_validate_json(self.bot_profile_json)
                    self.report_markdown = render_report(profile, timeline)
                    self.report_title = profile.display_name
                else:
                    self.report_markdown = render_transcript_report(title, timeline, metadata)
                    self.report_title = title
                self.lint_report_markdown = ""


        except Exception as e:
            logger.error(f"Dataverse transcript analysis failed: {e}")
            self.dv_import_error = f"Analysis failed: {e}"
        finally:
            self.dv_import_processing = False

    @rx.event
    async def dv_fetch_and_analyse_by_id(self):
        """Fetch a single transcript by conversation ID and analyse it."""
        import re

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
                "Invalid format. Conversation ID must be a UUID "
                "(e.g. 12345678-abcd-1234-abcd-1234567890ab)."
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
                if not self.bot_profile_json:
                    self.bot_profile_json = _load_bot_profile()
                logger.debug("bot_profile_json present: {} (len={})", bool(self.bot_profile_json), len(self.bot_profile_json))
                if self.bot_profile_json:
                    profile = BotProfile.model_validate_json(self.bot_profile_json)
                    self.report_markdown = render_report(profile, timeline)
                    self.report_title = profile.display_name
                else:
                    self.report_markdown = render_transcript_report(title, timeline, metadata)
                    self.report_title = title
                self.lint_report_markdown = ""


        except RuntimeError as e:
            self.dv_single_fetch_error = str(e)
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                self.dv_single_fetch_error = "Session expired. Disconnect and reconnect to re-authenticate."
            elif "403" in error_str:
                self.dv_single_fetch_error = (
                    "Access denied. Your account needs read access to "
                    "conversationtranscripts in Dataverse."
                )
            else:
                logger.error(f"Single transcript fetch failed: {e}")
                self.dv_single_fetch_error = f"Fetch failed: {e}"
        finally:
            self.dv_single_fetching = False

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
                "Analyse Bot result: {} — {} components",
                profile.display_name, len(profile.components),
            )

            self.report_markdown = render_report(profile)
            self.report_title = profile.display_name
            self.bot_profile_json = profile.model_dump_json()
            _save_bot_profile(self.bot_profile_json)
            logger.debug("Stored bot_profile_json (len={})", len(self.bot_profile_json))
            self.lint_report_markdown = ""


        except RuntimeError as e:
            self.dv_bot_analyse_error = str(e)
        except Exception as e:
            error_str = str(e)
            if "401" in error_str:
                self.dv_bot_analyse_error = "Session expired. Disconnect and reconnect to re-authenticate."
            elif "403" in error_str:
                self.dv_bot_analyse_error = (
                    "Access denied. Your account needs read access to the "
                    "bots and botcomponents tables in Dataverse."
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
                "Copilot Studio → Settings (gear icon) → Session details → Copilot Id."
            )
            return

        self.dv_bot_analyse_error = ""
        self.dv_bot_analysing = True
        yield

        await self._run_bot_analysis()
        self.dv_bot_analysing = False

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

    @rx.event
    def dv_back_to_list(self):
        """Clear report view but preserve bot profile and Dataverse connection."""
        self.report_markdown = ""
        self.report_title = ""
        self.lint_report_markdown = ""
        self.is_linting = False
        self.lint_error = ""

    # --- Report handlers ---

    def download_report(self):
        filename = f"{self.report_title}.md" if self.report_title else "report.md"
        return rx.download(data=self.report_markdown, filename=filename)

    def new_upload(self):
        self.report_markdown = ""
        self.report_title = ""
        self.upload_error = ""
        self.paste_json = ""
        self.bot_profile_json = ""
        _clear_bot_profile()
        self.lint_report_markdown = ""
        self.is_linting = False
        self.lint_error = ""

    # --- Lint handlers ---

    @rx.event
    async def run_lint(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            self.lint_error = "OPENAI_API_KEY not set. Add it to your .env file."
            return

        if not self.bot_profile_json:
            self.lint_error = "No bot profile available for linting."
            return

        self.is_linting = True
        self.lint_error = ""
        self.lint_report_markdown = ""
        yield

        try:
            profile = BotProfile.model_validate_json(self.bot_profile_json)
            report, model_used = await _run_lint(profile, api_key)
            self.lint_report_markdown = report
            logger.info(f"Lint complete using {model_used}")
        except Exception as e:
            logger.error(f"Lint failed: {e}")
            self.lint_error = f"Lint failed: {e}"
        finally:
            self.is_linting = False

    def download_lint_report(self):
        title = self.report_title if self.report_title else "report"
        filename = f"{title}_lint.md"
        return rx.download(data=self.lint_report_markdown, filename=filename)

    def clear_lint(self):
        self.lint_report_markdown = ""
        self.lint_error = ""

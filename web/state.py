import os
import sys
import tempfile
import zipfile
from pathlib import Path

import reflex as rx
from dotenv import load_dotenv
from loguru import logger

# Ensure project root is importable (Reflex runs from project root)
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from parser import parse_dialog_json, parse_yaml  # noqa: E402
from renderer import render_report, render_transcript_report  # noqa: E402
from timeline import build_timeline  # noqa: E402
from transcript import parse_transcript_json  # noqa: E402

from web.mermaid import split_markdown_mermaid  # noqa: E402

load_dotenv()


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
    upload_type: str = "bot_zip"
    is_processing: bool = False
    upload_error: str = ""

    # Report
    report_markdown: str = ""
    report_title: str = ""

    # Explicit setters (auto-setters deprecated in 0.8.9)
    @rx.event
    def set_username(self, value: str):
        self.username = value

    @rx.event
    def set_password(self, value: str):
        self.password = value

    @rx.event
    def set_upload_type(self, display_value: str):
        upload_type_map: dict[str, str] = {
            "Bot Export (.zip)": "bot_zip",
            "Bot Export (individual files)": "bot_files",
            "Transcript (.json)": "transcript",
        }
        self.upload_type = upload_type_map.get(display_value, "bot_zip")

    @rx.var
    def has_report(self) -> bool:
        return bool(self.report_markdown)

    @rx.var
    def report_segments(self) -> list[dict[str, str]]:
        if not self.report_markdown:
            return []
        segments = split_markdown_mermaid(self.report_markdown)
        return [{"type": t, "content": c} for t, c in segments]

    # --- Auth handlers ---

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

    def logout(self):
        self.username = ""
        self.password = ""
        self.is_authenticated = False
        self.auth_error = ""
        self.report_markdown = ""
        self.report_title = ""
        self.upload_error = ""
        self.is_processing = False
        return rx.redirect("/")

    def check_auth(self):
        if not self.is_authenticated:
            return rx.redirect("/")

    def check_already_authed(self):
        if self.is_authenticated:
            return rx.redirect("/upload")

    # --- Upload handlers ---

    async def handle_upload(self, files: list[rx.UploadFile]):
        if not files:
            self.upload_error = "No files selected."
            return

        self.is_processing = True
        self.upload_error = ""
        yield

        try:
            if self.upload_type == "bot_zip":
                await self._process_bot_zip(files)
            elif self.upload_type == "bot_files":
                await self._process_bot_files(files)
            elif self.upload_type == "transcript":
                await self._process_transcript(files)
            else:
                self.upload_error = f"Unknown upload type: {self.upload_type}"
        except Exception as e:
            logger.error(f"Upload processing failed: {e}")
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

    # --- Report handlers ---

    def download_report(self):
        filename = f"{self.report_title}.md" if self.report_title else "report.md"
        return rx.download(data=self.report_markdown, filename=filename)

    def new_upload(self):
        self.report_markdown = ""
        self.report_title = ""
        self.upload_error = ""

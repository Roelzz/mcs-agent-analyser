import json
import tempfile
import zipfile
from pathlib import Path

import reflex as rx
from loguru import logger

from instruction_store import save_snapshot  # noqa: E402
from parser import parse_dialog_json, parse_yaml  # noqa: E402
from renderer import render_instruction_drift, render_report, render_transcript_report  # noqa: E402
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
                yield rx.redirect("/analysis")

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
                _clear_bot_profile()

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
                yield rx.redirect("/analysis")

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
            custom = self.get_custom_rules() or None  # type: ignore[attr-defined]
            self.report_markdown = render_report(profile, timeline, custom_rules=custom)  # type: ignore[attr-defined]
            self.report_title = profile.display_name  # type: ignore[attr-defined]
            self.report_source = "upload"  # type: ignore[attr-defined]
            self.bot_profile_json = profile.model_dump_json()  # type: ignore[attr-defined]
            _save_bot_profile(self.bot_profile_json)  # type: ignore[attr-defined]

            instruction_diff = save_snapshot(profile)
            if instruction_diff and instruction_diff.is_significant:
                self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]

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
            custom = self.get_custom_rules() or None  # type: ignore[attr-defined]
            self.report_markdown = render_report(profile, timeline, custom_rules=custom)  # type: ignore[attr-defined]
            self.report_title = profile.display_name  # type: ignore[attr-defined]
            self.report_source = "upload"  # type: ignore[attr-defined]
            self.bot_profile_json = profile.model_dump_json()  # type: ignore[attr-defined]
            _save_bot_profile(self.bot_profile_json)  # type: ignore[attr-defined]

            instruction_diff = save_snapshot(profile)
            if instruction_diff and instruction_diff.is_significant:
                self.report_markdown = render_instruction_drift(instruction_diff) + "\n" + self.report_markdown  # type: ignore[attr-defined]

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
            _clear_bot_profile()

    def new_upload(self):
        self.report_markdown = ""  # type: ignore[attr-defined]
        self.report_title = ""  # type: ignore[attr-defined]
        self.report_source = ""  # type: ignore[attr-defined]
        self.upload_error = ""
        self.paste_json = ""
        self.bot_profile_json = ""  # type: ignore[attr-defined]
        _clear_bot_profile()
        self.lint_report_markdown = ""  # type: ignore[attr-defined]
        self.is_linting = False  # type: ignore[attr-defined]
        self.lint_error = ""  # type: ignore[attr-defined]
        return rx.redirect("/dashboard")

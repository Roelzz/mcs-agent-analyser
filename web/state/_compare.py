"""Comparison state mixin for bot diff feature."""

import tempfile
import zipfile
from pathlib import Path

import reflex as rx
from loguru import logger

from models import BotProfile
from parser import parse_yaml
from utils import safe_extractall

from diff import compare_bots, render_diff_report
from web.mermaid import split_markdown_mermaid

COMPARE_A_ID = "compare_a"
COMPARE_B_ID = "compare_b"


class ComparisonMixin(rx.State, mixin=True):
    """Bot comparison state."""

    compare_a_name: str = ""
    compare_b_name: str = ""
    compare_result_md: str = ""
    compare_error: str = ""
    is_comparing: bool = False
    _compare_a_json: str = ""
    _compare_b_json: str = ""

    @rx.var
    def compare_segments(self) -> list[dict[str, str]]:
        if not self.compare_result_md:
            return []
        segments = split_markdown_mermaid(self.compare_result_md)
        return [{"type": t, "content": c} for t, c in segments]

    @rx.event
    async def handle_compare_a_upload(self, files: list[rx.UploadFile]):
        self.compare_error = ""
        try:
            profile = await self._parse_compare_zip(files)
            if profile:
                self.compare_a_name = profile.display_name or profile.schema_name
                self._compare_a_json = profile.model_dump_json()
        except Exception as e:
            logger.error(f"Compare A upload failed: {e}")
            self.compare_error = f"Bot A upload failed: {e}"

    @rx.event
    async def handle_compare_b_upload(self, files: list[rx.UploadFile]):
        self.compare_error = ""
        try:
            profile = await self._parse_compare_zip(files)
            if profile:
                self.compare_b_name = profile.display_name or profile.schema_name
                self._compare_b_json = profile.model_dump_json()
        except Exception as e:
            logger.error(f"Compare B upload failed: {e}")
            self.compare_error = f"Bot B upload failed: {e}"

    async def _parse_compare_zip(self, files: list[rx.UploadFile]) -> BotProfile | None:
        if not files:
            self.compare_error = "No file selected."
            return None

        upload_file = files[0]
        data = await upload_file.read()

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / upload_file.filename
            zip_path.write_bytes(data)

            if not zipfile.is_zipfile(zip_path):
                self.compare_error = "File is not a valid zip archive."
                return None

            extract_dir = Path(tmpdir) / "extracted"
            with zipfile.ZipFile(zip_path) as zf:
                safe_extractall(zf, extract_dir)

            yaml_files = list(extract_dir.rglob("botContent.yml"))
            if not yaml_files:
                self.compare_error = "No botContent.yml found in zip."
                return None

            profile, _ = parse_yaml(yaml_files[0])
            return profile

    @rx.event
    def run_comparison(self):
        self.compare_error = ""
        if not self._compare_a_json or not self._compare_b_json:
            self.compare_error = "Upload both bot exports before comparing."
            return

        self.is_comparing = True
        yield

        try:
            profile_a = BotProfile.model_validate_json(self._compare_a_json)
            profile_b = BotProfile.model_validate_json(self._compare_b_json)
            diff = compare_bots(profile_a, profile_b)
            self.compare_result_md = render_diff_report(diff)
        except Exception as e:
            logger.error(f"Comparison failed: {e}")
            self.compare_error = f"Comparison failed: {e}"
        finally:
            self.is_comparing = False

    @rx.event
    def clear_comparison(self):
        self.compare_a_name = ""
        self.compare_b_name = ""
        self.compare_result_md = ""
        self.compare_error = ""
        self.is_comparing = False
        self._compare_a_json = ""
        self._compare_b_json = ""

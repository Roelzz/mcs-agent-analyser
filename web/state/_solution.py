import asyncio
import tempfile
from pathlib import Path

import reflex as rx
from loguru import logger

from renamer import inspect_zip, rename_solution_from_bytes  # noqa: E402
from solution_checker import check_solution_zip  # noqa: E402
from validator import validate_zip_bytes  # noqa: E402
from deps_analyzer import analyze_deps_zip_bytes  # noqa: E402

from web.mermaid import split_markdown_mermaid


class SolutionMixin(rx.State, mixin=True):
    """Solution tools vars and handlers."""

    # Solution Tools — shared
    sol_zip_bytes: bytes = b""
    sol_zip_name: str = ""
    sol_active_tab: str = "check"

    # Solution Checker
    sol_check_results: list[dict] = []
    sol_check_error: str = ""
    sol_is_checking: bool = False
    sol_check_agent_name: str = ""
    sol_check_solution_name: str = ""
    sol_check_pass: int = 0
    sol_check_warn: int = 0
    sol_check_fail: int = 0
    sol_check_info: int = 0
    sol_check_active_category: str = "All"

    # Validator
    sol_validate_results: list[dict] = []
    sol_validate_error: str = ""
    sol_is_validating: bool = False
    sol_validate_model_display: str = ""
    sol_validate_best_practices_md: str = ""

    # Dependencies
    sol_deps_segments: list[dict] = []
    sol_deps_error: str = ""
    sol_is_deps_analyzing: bool = False

    # Renamer
    sol_rename_new_agent: str = ""
    sol_rename_new_solution: str = ""
    sol_rename_result_bytes: bytes = b""
    sol_rename_result: dict = {}
    sol_rename_error: str = ""
    sol_is_renaming: bool = False
    sol_detected_info: dict = {}

    # Setters
    @rx.event
    def set_sol_active_tab(self, value: str):
        self.sol_active_tab = value

    @rx.event
    def set_sol_check_active_category(self, value: str):
        self.sol_check_active_category = value

    @rx.event
    def set_sol_rename_new_agent(self, value: str):
        self.sol_rename_new_agent = value

    @rx.event
    def set_sol_rename_new_solution(self, value: str):
        self.sol_rename_new_solution = value

    @rx.var
    def sol_has_zip(self) -> bool:
        return len(self.sol_zip_bytes) > 0

    @rx.var
    def sol_filtered_results(self) -> list[dict]:
        if self.sol_check_active_category == "All":
            return self.sol_check_results
        return [r for r in self.sol_check_results if r.get("category") == self.sol_check_active_category]

    @rx.var
    def sol_validate_bp_segments(self) -> list[dict[str, str]]:
        if not self.sol_validate_best_practices_md:
            return []
        segments = split_markdown_mermaid(self.sol_validate_best_practices_md)
        return [{"type": t, "content": c} for t, c in segments]

    # --- Solution Tools handlers ---

    @rx.event
    async def handle_solution_upload(self, files: list[rx.UploadFile]):
        if not files:
            return
        upload_file = files[0]
        data = await upload_file.read()
        if not data:
            return

        self.sol_zip_bytes = data
        self.sol_zip_name = upload_file.filename or "solution.zip"
        # Reset all results
        self.sol_check_results = []
        self.sol_check_error = ""
        self.sol_check_agent_name = ""
        self.sol_check_solution_name = ""
        self.sol_check_pass = 0
        self.sol_check_warn = 0
        self.sol_check_fail = 0
        self.sol_check_info = 0
        self.sol_check_active_category = "All"
        self.sol_validate_results = []
        self.sol_validate_error = ""
        self.sol_validate_model_display = ""
        self.sol_validate_best_practices_md = ""
        self.sol_deps_segments = []
        self.sol_deps_error = ""
        self.sol_rename_result_bytes = b""
        self.sol_rename_result = {}
        self.sol_rename_error = ""
        self.sol_detected_info = {}
        yield

        # Auto-detect solution info for renamer
        try:
            info = await asyncio.to_thread(self._detect_solution_info)
            self.sol_detected_info = info
            self.sol_rename_new_agent = info.get("bot_display_name", "")
            self.sol_rename_new_solution = info.get("solution_unique_name", "")
        except Exception:
            pass

        # Auto-trigger read-only analyses
        self.sol_is_checking = True
        self.sol_is_validating = True
        self.sol_is_deps_analyzing = True
        yield

        await self._run_solution_check()
        yield
        await self._run_solution_validate()
        yield
        await self._run_deps_analysis()
        yield
        await self._refresh_community_count()  # type: ignore[attr-defined]

    def _detect_solution_info(self) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            zip_path = tmp / "input.zip"
            zip_path.write_bytes(self.sol_zip_bytes)
            info = inspect_zip(zip_path)
            return {
                "bot_schema_name": info.bot_schema_name,
                "bot_display_name": info.bot_display_name,
                "solution_unique_name": info.solution_unique_name,
                "solution_display_name": info.solution_display_name,
            }

    async def _run_solution_check(self):
        self.sol_is_checking = True
        self.sol_check_error = ""
        try:
            custom = self.get_custom_rules() or None  # type: ignore[attr-defined]
            result = await asyncio.to_thread(check_solution_zip, self.sol_zip_bytes, custom_rules=custom)
            self.sol_check_results = result.get("results", [])
            self.sol_check_agent_name = result.get("agent_name", "")
            self.sol_check_solution_name = result.get("solution_name", "")
            self.sol_check_pass = result.get("pass_count", 0)
            self.sol_check_warn = result.get("warn_count", 0)
            self.sol_check_fail = result.get("fail_count", 0)
            self.sol_check_info = result.get("info_count", 0)
            error = result.get("error", "")
            if error:
                self.sol_check_error = error
        except Exception as e:
            logger.error(f"Solution check failed: {e}")
            self.sol_check_error = f"Check failed: {e}"
        finally:
            self.sol_is_checking = False

    @rx.event
    async def run_solution_check(self):
        if not self.sol_zip_bytes:
            self.sol_check_error = "No solution ZIP uploaded."
            return
        self.sol_is_checking = True
        yield
        await self._run_solution_check()

    async def _run_solution_validate(self):
        self.sol_is_validating = True
        self.sol_validate_error = ""
        try:
            result = await asyncio.to_thread(validate_zip_bytes, self.sol_zip_bytes)
            self.sol_validate_results = result.get("results", [])
            self.sol_validate_model_display = result.get("model_display", "")
            self.sol_validate_best_practices_md = result.get("best_practices_md", "")
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            self.sol_validate_error = f"Validation failed: {e}"
        finally:
            self.sol_is_validating = False

    @rx.event
    async def run_solution_validate(self):
        if not self.sol_zip_bytes:
            self.sol_validate_error = "No solution ZIP uploaded."
            return
        self.sol_is_validating = True
        yield
        await self._run_solution_validate()

    async def _run_deps_analysis(self):
        self.sol_is_deps_analyzing = True
        self.sol_deps_error = ""
        try:
            segments = await asyncio.to_thread(analyze_deps_zip_bytes, self.sol_zip_bytes)
            self.sol_deps_segments = segments
        except (ValueError, RuntimeError) as e:
            self.sol_deps_error = str(e)
        except Exception as e:
            logger.error(f"Deps analysis failed: {e}")
            self.sol_deps_error = f"Analysis failed: {e}"
        finally:
            self.sol_is_deps_analyzing = False

    @rx.event
    async def run_deps_analysis(self):
        if not self.sol_zip_bytes:
            self.sol_deps_error = "No solution ZIP uploaded."
            return
        self.sol_is_deps_analyzing = True
        yield
        await self._run_deps_analysis()

    @rx.event
    async def run_rename(self):
        if not self.sol_zip_bytes:
            self.sol_rename_error = "No solution ZIP uploaded."
            return
        if not self.sol_rename_new_agent.strip():
            self.sol_rename_error = "Enter a new agent name."
            return
        if not self.sol_rename_new_solution.strip():
            self.sol_rename_error = "Enter a new solution name."
            return

        self.sol_is_renaming = True
        self.sol_rename_error = ""
        self.sol_rename_result_bytes = b""
        self.sol_rename_result = {}
        yield

        try:
            result_bytes, result = await asyncio.to_thread(
                rename_solution_from_bytes,
                self.sol_zip_bytes,
                self.sol_rename_new_agent.strip(),
                self.sol_rename_new_solution.strip(),
            )
            self.sol_rename_result_bytes = result_bytes
            self.sol_rename_result = {
                "old_agent_name": result.old_agent_name,
                "new_agent_name": result.new_agent_name,
                "old_solution_name": result.old_solution_name,
                "new_solution_name": result.new_solution_name,
                "files_modified": result.files_modified,
                "folders_renamed": result.folders_renamed,
                "warnings": result.warnings,
            }
        except Exception as e:
            logger.error(f"Rename failed: {e}")
            self.sol_rename_error = f"Rename failed: {e}"
        finally:
            self.sol_is_renaming = False
            yield
            await self._refresh_community_count()  # type: ignore[attr-defined]

    @rx.event
    def download_renamed_zip(self):
        if not self.sol_rename_result_bytes:
            return
        new_name = self.sol_rename_new_solution.strip() or "renamed_solution"
        filename = f"{new_name}.zip"
        yield rx.download(data=self.sol_rename_result_bytes, filename=filename)
        yield rx.toast(f"Downloaded {filename}", duration=3000)

    @rx.event
    def sol_clear(self):
        """Reset all solution tools state."""
        self.sol_zip_bytes = b""
        self.sol_zip_name = ""
        self.sol_active_tab = "check"
        self.sol_check_results = []
        self.sol_check_error = ""
        self.sol_check_agent_name = ""
        self.sol_check_solution_name = ""
        self.sol_check_pass = 0
        self.sol_check_warn = 0
        self.sol_check_fail = 0
        self.sol_check_info = 0
        self.sol_check_active_category = "All"
        self.sol_validate_results = []
        self.sol_validate_error = ""
        self.sol_validate_model_display = ""
        self.sol_validate_best_practices_md = ""
        self.sol_deps_segments = []
        self.sol_deps_error = ""
        self.sol_rename_new_agent = ""
        self.sol_rename_new_solution = ""
        self.sol_rename_result_bytes = b""
        self.sol_rename_result = {}
        self.sol_rename_error = ""
        self.sol_detected_info = {}

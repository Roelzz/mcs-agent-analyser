"""Multi-mode audit runner state.

Drives the Instruction Lint UI on the report page. Today's
"Instruction Lint" button keeps working with the same one-click
behaviour (it runs only `static_config`); the audit-options popover
exposes the rest of the modes (summary, sentiment, PII, accuracy,
routing) plus a custom-prompt textarea — all opt-in.
"""

import os

import reflex as rx
from loguru import logger

from linter import (  # noqa: E402
    AuditResult,
    load_audit_modes,
    run_audits as _run_audits,
)
from models import BotProfile, ConversationTimeline  # noqa: E402

from web.mermaid import split_markdown_mermaid


def _segments_from_markdown(markdown: str) -> list[dict[str, str]]:
    """Mermaid-aware split — re-used per audit section so the existing
    `render_segment` machinery still renders code-fenced mermaid blocks
    correctly."""
    if not markdown:
        return []
    return [{"type": t, "content": c} for t, c in split_markdown_mermaid(markdown)]


def _result_to_section(result: AuditResult) -> dict:
    """Reflex state stores plain dicts. Project an `AuditResult` into a
    UI-friendly shape so per-section rendering doesn't need to know
    about the Pydantic model."""
    return {
        "mode_id": result.mode_id,
        "name": result.mode_name,
        "model_used": result.model_used,
        "error": result.error,
        "segments": _segments_from_markdown(result.markdown),
        "markdown": result.markdown,
    }


class LintMixin(rx.State, mixin=True):
    """Lint vars and handlers."""

    # ── Persisted source data (set by UploadMixin) ──────────────────────
    bot_profile_json: str = ""
    # Conversation transcript (serialized ConversationTimeline). Required
    # for transcript-based audits; empty when the user uploaded a
    # profile-only bot.
    timeline_json: str = ""

    # ── Audit run state ────────────────────────────────────────────────
    is_linting: bool = False
    lint_error: str = ""

    # Catalogue + user selection. The catalogue loads lazily on first
    # access (see `lint_audit_modes` computed var) so a missing /
    # malformed YAML file produces a friendly UI error rather than a
    # boot failure.
    lint_selected_audit_ids: list[str] = ["static_config"]
    lint_custom_prompt: str = ""
    # Per-audit result rows — the canonical multi-section output.
    # Each entry: `{mode_id, name, model_used, error, segments, markdown}`.
    lint_audit_results: list[dict] = []
    # Legacy single-string field — preserved as a plain attribute (not a
    # computed var) so external code can still clear it via
    # `self.lint_report_markdown = ""`. Populated alongside
    # `lint_audit_results` on a successful run with the static_config
    # section's markdown.
    lint_report_markdown: str = ""

    @rx.var
    def lint_audit_modes(self) -> list[dict]:
        """The full audit-mode catalogue from
        `data/default_lint_modes.yaml`. Each entry exposes the fields
        the UI needs (id, name, description, inputs_required,
        default_enabled). Errors fall back to an empty list and surface
        in `lint_error`."""
        try:
            modes = load_audit_modes()
        except Exception as e:
            logger.error(f"Failed to load audit modes: {e}")
            return []
        return [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
                "inputs_required": list(m.inputs_required),
                "default_enabled": m.default_enabled,
            }
            for m in modes
        ]

    @rx.var
    def lint_mode_availability(self) -> list[dict]:
        """Per-mode availability with disabled-state reason for the UI.
        A mode is `enabled` only when every input it requires is
        currently in state."""
        out: list[dict] = []
        has_profile = bool(self.bot_profile_json)
        has_transcript = bool(self.timeline_json)
        for mode in self.lint_audit_modes:
            inputs = mode["inputs_required"]
            missing: list[str] = []
            if "profile" in inputs and not has_profile:
                missing.append("bot profile")
            if "transcript" in inputs and not has_transcript:
                missing.append("conversation transcript")
            if missing:
                reason = f"requires {' + '.join(missing)}"
                enabled = False
            else:
                reason = ""
                enabled = True
            out.append(
                {
                    "id": mode["id"],
                    "name": mode["name"],
                    "description": mode["description"],
                    "default_enabled": mode["default_enabled"],
                    "enabled": enabled,
                    "reason": reason,
                    "selected": mode["id"] in self.lint_selected_audit_ids,
                }
            )
        return out

    # ── Computed flags driving the UI ──────────────────────────────────

    @rx.var
    def can_lint(self) -> bool:
        """The original "ready to run" check — preserved for the
        existing single-button flow. True when a profile + report exist
        in state."""
        return bool(self.bot_profile_json) and bool(self.report_markdown)  # type: ignore[attr-defined]

    @rx.var
    def has_lint_report(self) -> bool:
        return bool(self.lint_audit_results)

    @rx.var
    def lint_report_segments(self) -> list[dict[str, str]]:
        """Legacy field — flattens all audit sections into a single
        segment list for any caller that hasn't migrated to
        `lint_audit_results` yet."""
        out: list[dict[str, str]] = []
        for section in self.lint_audit_results:
            segs = section.get("segments")
            if isinstance(segs, list):
                out.extend(segs)
        return out

    @rx.var
    def lint_selected_count(self) -> int:
        """How many audits will fire on the next run, counting the
        custom prompt when present."""
        n = len(self.lint_selected_audit_ids)
        if self.lint_custom_prompt.strip():
            n += 1
        return n

    # ── Selection events ───────────────────────────────────────────────

    @rx.event
    def toggle_lint_audit(self, mode_id: str):
        """Toggle a mode in/out of the selection set."""
        current = list(self.lint_selected_audit_ids)
        if mode_id in current:
            current.remove(mode_id)
        else:
            current.append(mode_id)
        self.lint_selected_audit_ids = current

    @rx.event
    def set_lint_custom_prompt(self, value: str):
        self.lint_custom_prompt = value

    @rx.event
    def reset_lint_selection(self):
        """Restore the default audit selection (static_config only,
        custom prompt empty)."""
        self.lint_selected_audit_ids = ["static_config"]
        self.lint_custom_prompt = ""

    # ── Run handlers ───────────────────────────────────────────────────

    async def _execute_audits(self, mode_ids: list[str]):
        """Shared body for `run_lint` and `run_lint_audits` so both
        entry points use identical key-resolution + error-handling."""
        openai_key = os.getenv("OPENAI_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        if not openai_key and not anthropic_key:
            self.lint_error = "No API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env."
            return

        if not self.bot_profile_json and not self.timeline_json:
            self.lint_error = "Nothing to audit — upload a bot profile or transcript first."
            return

        # If the user runs with nothing selected and no custom prompt,
        # there's nothing to do. (The button is disabled in this state
        # but defend at the handler too.)
        if not mode_ids and not self.lint_custom_prompt.strip():
            self.lint_error = "Select at least one audit (or supply a custom prompt)."
            return

        self.is_linting = True
        self.lint_error = ""
        self.lint_audit_results = []
        self.lint_report_markdown = ""
        yield

        try:
            profile = BotProfile.model_validate_json(self.bot_profile_json) if self.bot_profile_json else None
            timeline = ConversationTimeline.model_validate_json(self.timeline_json) if self.timeline_json else None
            results = await _run_audits(
                profile=profile,
                timeline=timeline,
                mode_ids=mode_ids,
                custom_prompt=self.lint_custom_prompt,
                openai_api_key=openai_key,
                anthropic_api_key=anthropic_key,
            )
            sections = [_result_to_section(r) for r in results]
            self.lint_audit_results = sections
            # Populate the legacy single-blob field with the static_config
            # section's markdown so external readers (report download,
            # dataverse clears) keep working without changes.
            for section in sections:
                if section["mode_id"] == "static_config" and not section["error"]:
                    self.lint_report_markdown = section["markdown"]
                    break
            else:
                # No static_config in this run — use the first
                # successful audit so the legacy field still has *some*
                # content when external code reads it.
                for section in sections:
                    if not section["error"]:
                        self.lint_report_markdown = section["markdown"]
                        break
            ok = sum(1 for r in results if not r.error)
            failed = sum(1 for r in results if r.error)
            logger.info(f"Audit run complete: {ok} succeeded, {failed} failed")
        except Exception as e:
            logger.error(f"Audit run failed: {e}")
            self.lint_error = f"Audit run failed: {e}"
        finally:
            self.is_linting = False

    @rx.event
    async def run_lint(self):
        """Legacy entry point — preserves the one-click "Instruction
        Lint" flow. Runs only the static-config audit."""
        async for _ in self._execute_audits(["static_config"]):
            yield

    @rx.event
    async def run_lint_audits(self):
        """Run every currently-selected audit + the custom prompt (if
        non-empty) in parallel."""
        async for _ in self._execute_audits(list(self.lint_selected_audit_ids)):
            yield

    # ── Output handlers ────────────────────────────────────────────────

    @rx.event
    def download_lint_report(self):
        """Concat every audit's markdown — separated by a clear divider
        — and serve the combined report as a single file."""
        title = self.report_title if self.report_title else "report"  # type: ignore[attr-defined]
        filename = f"{title}_audit.md"
        if not self.lint_audit_results:
            return
        parts: list[str] = []
        for section in self.lint_audit_results:
            parts.append(f"# {section['name']}\n")
            if section.get("error"):
                parts.append(f"_Audit failed:_ {section['error']}\n")
            else:
                parts.append(section.get("markdown", ""))
            parts.append("\n\n---\n\n")
        yield rx.download(data="".join(parts).strip(), filename=filename)
        yield rx.toast(f"Audit report saved as {filename}", duration=3000)

    def clear_lint(self):
        self.lint_audit_results = []
        self.lint_report_markdown = ""
        self.lint_error = ""


"""Failure-Diagnosis (AgentRx) state machine.

Drives the Diagnose button and tab. Pattern mirrors `_lint.py`:

- Source data (`bot_profile_json`, `timeline_json`) populated by `UploadMixin`.
- An async `run_diagnose` event handler invokes `diagnosis.diagnose_async`.
- Results projected into typed top-level state vars (Reflex's `rx.foreach`
  needs explicit list/dict types — a generic `dict` is too loose).
- In-memory cache keyed by (transcript_hash, profile_hash, judge_model,
  offline, redaction_enabled) so re-clicking with the same inputs returns
  instantly.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

import reflex as rx
from loguru import logger

from diagnosis import DiagnosisReport, diagnose_async
from diagnosis.judge import DEFAULT_JUDGE_MODEL
from diagnosis.labels import badge_for, label_for
from models import BotProfile, ConversationTimeline


_JUDGE_MODEL_CHOICES = [
    DEFAULT_JUDGE_MODEL,
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _project_report(report: DiagnosisReport) -> dict:
    """Project a DiagnosisReport into a flat dict whose keys map 1:1 onto
    the typed state vars below. Cached and applied via `_apply_snapshot`."""
    source_label = "LLM judge" if report.judge_model else "Heuristic"
    if report.error_state:
        kpis: list[dict] = [
            {"label": "Status", "value": "Error", "tone": "danger"},
            {"label": "Source", "value": source_label},
        ]
    elif report.succeeded:
        kpis = [
            {"label": "Status", "value": "Succeeded", "tone": "good"},
            {"label": "Violations", "value": str(len(report.violations))},
            {"label": "Recovered", "value": "Yes", "tone": "good"},
            {"label": "Confidence", "value": report.confidence.title()},
            {"label": "Source", "value": source_label},
        ]
    else:
        kpis = [
            {"label": "Status", "value": "Failed", "tone": "danger"},
            {"label": "Category", "value": label_for(report.category), "tone": "danger"},
            {
                "label": "Critical step",
                "value": str(report.critical_step_index) if report.critical_step_index is not None else "—",
            },
            {"label": "Confidence", "value": report.confidence.title()},
            {"label": "Source", "value": source_label},
        ]

    # Per-violation category surfacing (Tier 1).
    evidence_rows: list[dict] = [
        {
            "step_label": f"step {v.step_index}",
            "rule": v.rule_id,
            "severity": v.severity,
            "description": (v.description or "")[:200],
            "category_label": label_for(v.default_category_seed),
            "category_badge": badge_for(v.default_category_seed),
            # Flattened to a string — Reflex can't foreach over a list nested
            # inside a list[dict] without explicit type annotation.
            "component_refs_label": ", ".join(f"{ref.kind}:{ref.display_name}" for ref in (v.component_refs or [])),
        }
        for v in report.violations
    ]

    # Category breakdown chips. Only useful when ≥ 2 categories appeared.
    counter = Counter(v.default_category_seed for v in report.violations if v.default_category_seed)
    if len(counter) >= 2:
        category_chips: list[dict] = [
            {"chip_label": f"{badge_for(cat)} {count}× {label_for(cat)}"} for cat, count in counter.most_common()
        ]
    else:
        category_chips = []

    # Secondary findings from the LLM judge (Tier 2).
    secondary_rows: list[dict] = [
        {
            "step_label": f"step {sf.step_index}",
            "category_label": label_for(sf.category),
            "category_badge": badge_for(sf.category),
            "severity": sf.severity,
            "reason": sf.reason,
        }
        for sf in report.secondary_failures
    ]

    canned: list[dict] = [{"title": rec.title, "body": rec.body_md} for rec in report.canned_recommendations]
    llm_recs: list[dict] = [{"title": rec.title, "body": rec.body_md} for rec in report.llm_recommendations]
    redaction_chips: list[dict] = [
        {"chip_label": f"{k.lower()}: {v}"} for k, v in sorted(report.redaction_summary.items())
    ]
    return {
        "has_result": True,
        "kpis": kpis,
        "summary": report.summary,
        "reason_for_index": report.reason_for_index,
        "evidence_rows": evidence_rows,
        "category_chips": category_chips,
        "secondary_rows": secondary_rows,
        "canned_recs": canned,
        "llm_recs": llm_recs,
        "redaction_chips": redaction_chips,
        "judge_model_used": report.judge_model,
        "generated_at": report.generated_at.isoformat(),
        "succeeded": report.succeeded,
        "error_state": report.error_state,
        "error_message": report.error_message,
        # Snapshot the raw verdict so the chat handler can rebuild context
        # without paying for a second judge call.
        "judge_verdict_raw": report.judge_verdict_raw or {},
    }


class DiagnosisMixin(rx.State, mixin=True):
    """Diagnose button + tab state."""

    # ── User-controlled run options ──────────────────────────────────────
    diagnosis_judge_model: str = DEFAULT_JUDGE_MODEL
    diagnosis_offline: bool = False
    diagnosis_redact_pii: bool = True

    # ── Run state ────────────────────────────────────────────────────────
    is_diagnosing: bool = False
    diagnosis_error: str = ""

    # ── Result vars (typed; Reflex's rx.foreach needs explicit types) ────
    diagnosis_has_result: bool = False
    diagnosis_kpis: list[dict] = []
    diagnosis_summary: str = ""
    diagnosis_reason_for_index: str = ""
    diagnosis_evidence_rows: list[dict] = []
    diagnosis_category_chips: list[dict] = []
    diagnosis_secondary_rows: list[dict] = []
    diagnosis_canned_recs: list[dict] = []
    diagnosis_llm_recs: list[dict] = []
    diagnosis_redaction_chips: list[dict] = []
    diagnosis_judge_model_used: str = ""
    diagnosis_generated_at: str = ""
    diagnosis_succeeded: bool = False
    diagnosis_error_state: bool = False
    diagnosis_error_message: str = ""

    # Cache: maps key -> snapshot dict so re-running with the same inputs
    # returns instantly. Cleared on `new_upload`.
    _diagnosis_cache: dict[str, dict] = {}

    # ── Chat with the judge (Issue B) ────────────────────────────────────
    # Active cache key — set on every diagnose run (cache hit or miss) so
    # the chat panel knows which verdict it's tied to.
    diagnosis_active_cache_key: str = ""
    # Verdict raw JSON for the active diagnosis (mirrored from the active
    # snapshot). Used by the chat handler to rebuild the same context the
    # judge originally saw.
    diagnosis_active_verdict_raw: dict = {}
    # Persisted chat history. Each entry: `{role, content, ts, cache_key}`.
    # `rx.LocalStorage` is string-backed in Reflex — we JSON-encode the list
    # ourselves so it survives reloads. The `chat_history_*` properties below
    # decode it on read and `_set_chat_history` encodes on write.
    diagnosis_chat_history_json: str = rx.LocalStorage("[]", name="agentrx_chat_v1")
    # Composer + streaming bookkeeping.
    diagnosis_chat_input: str = ""
    diagnosis_chat_streaming_buffer: str = ""
    is_chatting: bool = False
    diagnosis_chat_error: str = ""

    # ── Computed ─────────────────────────────────────────────────────────

    @rx.var
    def diagnosis_judge_model_choices(self) -> list[str]:
        return list(_JUDGE_MODEL_CHOICES)

    @rx.var
    def can_diagnose(self) -> bool:
        return bool(self.bot_profile_json) and bool(self.timeline_json) and not self.is_diagnosing  # type: ignore[attr-defined]

    # ── Snapshot apply / clear helpers ───────────────────────────────────

    def _apply_snapshot(self, snap: dict) -> None:
        """Splat a projected report dict onto the typed state vars."""
        self.diagnosis_has_result = snap.get("has_result", False)
        self.diagnosis_kpis = list(snap.get("kpis", []))
        self.diagnosis_summary = snap.get("summary", "")
        self.diagnosis_reason_for_index = snap.get("reason_for_index", "")
        self.diagnosis_evidence_rows = list(snap.get("evidence_rows", []))
        self.diagnosis_category_chips = list(snap.get("category_chips", []))
        self.diagnosis_secondary_rows = list(snap.get("secondary_rows", []))
        self.diagnosis_canned_recs = list(snap.get("canned_recs", []))
        self.diagnosis_llm_recs = list(snap.get("llm_recs", []))
        self.diagnosis_redaction_chips = list(snap.get("redaction_chips", []))
        self.diagnosis_judge_model_used = snap.get("judge_model_used", "")
        self.diagnosis_generated_at = snap.get("generated_at", "")
        self.diagnosis_succeeded = snap.get("succeeded", False)
        self.diagnosis_error_state = snap.get("error_state", False)
        self.diagnosis_error_message = snap.get("error_message", "")
        self.diagnosis_active_verdict_raw = dict(snap.get("judge_verdict_raw", {}) or {})

    def _clear_result(self) -> None:
        self.diagnosis_has_result = False
        self.diagnosis_kpis = []
        self.diagnosis_summary = ""
        self.diagnosis_reason_for_index = ""
        self.diagnosis_evidence_rows = []
        self.diagnosis_category_chips = []
        self.diagnosis_secondary_rows = []
        self.diagnosis_canned_recs = []
        self.diagnosis_llm_recs = []
        self.diagnosis_redaction_chips = []
        self.diagnosis_judge_model_used = ""
        self.diagnosis_generated_at = ""
        self.diagnosis_succeeded = False
        self.diagnosis_error_state = False
        self.diagnosis_error_message = ""
        self.diagnosis_active_verdict_raw = {}
        self.diagnosis_active_cache_key = ""
        self.diagnosis_chat_input = ""
        self.diagnosis_chat_streaming_buffer = ""
        self.diagnosis_chat_error = ""

    # ── Chat history persistence (string-backed LocalStorage) ────────────

    def _read_chat_history_all(self) -> list[dict]:
        """Decode the JSON-stringified persistent chat history."""
        try:
            data = json.loads(self.diagnosis_chat_history_json or "[]")
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)]

    def _write_chat_history_all(self, entries: list[dict]) -> None:
        """JSON-encode and persist the chat history."""
        try:
            self.diagnosis_chat_history_json = json.dumps(entries, default=str)
        except (TypeError, ValueError):
            self.diagnosis_chat_history_json = "[]"

    # ── Chat computed views + handlers ───────────────────────────────────

    @rx.var
    def diagnosis_chat_history_active(self) -> list[dict]:
        """Filter the persisted history to the current verdict only."""
        key = self.diagnosis_active_cache_key
        if not key:
            return []
        return [entry for entry in self._read_chat_history_all() if entry.get("cache_key") == key]

    @rx.var
    def has_chat_history(self) -> bool:
        return len(self.diagnosis_chat_history_active) > 0

    @rx.var
    def can_chat(self) -> bool:
        # Chat is only meaningful when a judge actually ran on the active
        # diagnosis (the heuristic-only path has no verdict to interrogate).
        return (
            self.diagnosis_has_result
            and bool(self.diagnosis_active_verdict_raw)
            and not self.is_chatting
            and bool(self.diagnosis_chat_input.strip())
        )

    # ── Event handlers ───────────────────────────────────────────────────

    @rx.event
    def set_diagnosis_judge_model(self, value: str):
        if value in _JUDGE_MODEL_CHOICES:
            self.diagnosis_judge_model = value

    @rx.event
    def toggle_diagnosis_offline(self):
        self.diagnosis_offline = not self.diagnosis_offline

    @rx.event
    def toggle_diagnosis_redact(self):
        self.diagnosis_redact_pii = not self.diagnosis_redact_pii

    @rx.event
    async def run_diagnose(self):
        """Build the cache key, return cached result if hit, otherwise run
        the full pipeline. Async so it can call `diagnose_async`."""
        profile_json: str = self.bot_profile_json  # type: ignore[attr-defined]
        timeline_json: str = self.timeline_json  # type: ignore[attr-defined]
        if not profile_json or not timeline_json:
            self.diagnosis_error = "Diagnosis needs both bot export and transcript."
            return

        cache_key = "|".join(
            [
                _digest(timeline_json),
                _digest(profile_json),
                self.diagnosis_judge_model,
                "offline" if self.diagnosis_offline else "online",
                "redact" if self.diagnosis_redact_pii else "raw",
            ]
        )
        cached = self._diagnosis_cache.get(cache_key)
        if cached is not None:
            self._apply_snapshot(cached)
            self.diagnosis_active_cache_key = cache_key
            self.diagnosis_error = ""
            return

        self.is_diagnosing = True
        self.diagnosis_error = ""
        yield

        try:
            profile = BotProfile.model_validate_json(profile_json)
            timeline = ConversationTimeline.model_validate_json(timeline_json)
            report = await diagnose_async(
                profile,
                timeline,
                llm=not self.diagnosis_offline,
                judge_model=self.diagnosis_judge_model,
                redact_pii=self.diagnosis_redact_pii,
            )
            snap = _project_report(report)
            self._apply_snapshot(snap)
            self.diagnosis_active_cache_key = cache_key
            new_cache = dict(self._diagnosis_cache)
            new_cache[cache_key] = snap
            self._diagnosis_cache = new_cache
        except Exception as exc:  # noqa: BLE001 — surface to the user
            logger.exception("Diagnosis failed")
            self.diagnosis_error = f"Diagnosis failed: {exc}"
        finally:
            self.is_diagnosing = False

    @rx.event
    def clear_diagnosis(self):
        """Clear the displayed result (without dumping the cache)."""
        self._clear_result()
        self.diagnosis_error = ""

    @rx.event
    def reset_diagnosis_state(self):
        """Hard reset — used by `new_upload` so a fresh upload starts clean."""
        self._clear_result()
        self.diagnosis_error = ""
        self.is_diagnosing = False
        self._diagnosis_cache = {}
        self.diagnosis_judge_model = DEFAULT_JUDGE_MODEL
        self.diagnosis_offline = False
        self.diagnosis_redact_pii = True
        # Wipe persisted chat too — different bot, different conversation.
        self.diagnosis_chat_history_json = "[]"

    # ── Chat handlers ────────────────────────────────────────────────────

    @rx.event
    def set_diagnosis_chat_input(self, value: str):
        self.diagnosis_chat_input = value

    @rx.event
    def clear_chat(self):
        """Drop chat entries tied to the active verdict only. Other
        verdicts in localStorage stay; switching back to one of them
        resurfaces its thread."""
        key = self.diagnosis_active_cache_key
        if not key:
            self._write_chat_history_all([])
        else:
            kept = [e for e in self._read_chat_history_all() if e.get("cache_key") != key]
            self._write_chat_history_all(kept)
        self.diagnosis_chat_input = ""
        self.diagnosis_chat_error = ""
        self.diagnosis_chat_streaming_buffer = ""

    @rx.event
    async def send_chat_message(self):
        """Stream a reply from the judge for `diagnosis_chat_input`. Updates
        `diagnosis_chat_streaming_buffer` after every chunk so the UI shows
        a token-by-token bubble; pushes the final reply into
        `diagnosis_chat_history_all` once the stream completes."""
        from diagnosis.chat import ChatChunk, ChatTurn, chat_with_judge_stream
        from diagnosis.models import ConstraintViolation as _CV

        message = (self.diagnosis_chat_input or "").strip()
        if not message:
            return
        if not self.diagnosis_active_verdict_raw:
            self.diagnosis_chat_error = (
                "Chat is only available when the LLM judge produced the verdict (not in heuristic-only mode)."
            )
            return

        active_key = self.diagnosis_active_cache_key
        ts = datetime.now(tz=timezone.utc).isoformat()
        # Push the user's bubble immediately so the UI shows it before we
        # start the streaming call.
        history_all = self._read_chat_history_all()
        history_all.append({"role": "user", "content": message, "ts": ts, "cache_key": active_key})
        self._write_chat_history_all(history_all)
        self.diagnosis_chat_input = ""
        self.diagnosis_chat_error = ""
        self.diagnosis_chat_streaming_buffer = ""
        self.is_chatting = True
        yield

        # Rebuild the same context the judge originally saw. We re-use the
        # current bot_profile_json + timeline_json from UploadMixin (no need
        # to persist them again — they're stable while the active diagnosis
        # holds).
        try:
            profile = BotProfile.model_validate_json(self.bot_profile_json)  # type: ignore[attr-defined]
            timeline = ConversationTimeline.model_validate_json(self.timeline_json)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — fail visibly
            self.diagnosis_chat_error = f"Couldn't reload diagnosis context: {exc}"
            self.is_chatting = False
            return

        # Re-run heuristics so the chat sees the same violation log as the
        # judge did. Cheap (no LLM); deterministic given the same timeline.
        from diagnosis.constraints import run_constraints

        violations = run_constraints(profile, timeline)

        # Filter the chat history to the active verdict's turns BEFORE this
        # one, formatted as ChatTurn for the streaming function.
        prior_turns = [
            ChatTurn(role=e["role"], content=e["content"])
            for e in self._read_chat_history_all()
            if e.get("cache_key") == active_key
            and e.get("role") in ("user", "assistant")
            and e.get("content") != message  # exclude the message we just added
        ]
        # Drop trailing duplicate of `message` if it slipped through.
        if prior_turns and prior_turns[-1].role == "user" and prior_turns[-1].content == message:
            prior_turns = prior_turns[:-1]

        try:
            buf = ""
            async for chunk in chat_with_judge_stream(
                profile,
                timeline,
                [_CV.model_validate(v.model_dump()) if hasattr(v, "model_dump") else v for v in violations],
                self.diagnosis_active_verdict_raw or None,
                prior_turns,
                message,
                judge_model=self.diagnosis_judge_model,
                redact_pii=self.diagnosis_redact_pii,
            ):
                if not isinstance(chunk, ChatChunk):
                    continue
                if chunk.error:
                    self.diagnosis_chat_error = chunk.error
                    self.is_chatting = False
                    self.diagnosis_chat_streaming_buffer = ""
                    yield
                    return
                if chunk.delta:
                    buf += chunk.delta
                    self.diagnosis_chat_streaming_buffer = buf
                    yield
                if chunk.done:
                    break
        except Exception as exc:  # noqa: BLE001 — surface to the user
            logger.exception("Chat call failed")
            self.diagnosis_chat_error = f"Chat call failed: {exc}"
            self.is_chatting = False
            return

        # Freeze the buffered reply into the persisted history.
        history_all = self._read_chat_history_all()
        history_all.append(
            {
                "role": "assistant",
                "content": buf,
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "cache_key": active_key,
            }
        )
        self._write_chat_history_all(history_all)
        self.diagnosis_chat_streaming_buffer = ""
        self.is_chatting = False

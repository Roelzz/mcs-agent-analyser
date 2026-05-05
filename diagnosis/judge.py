"""LLM judge for failure diagnosis.

Single-pass call: timeline + violations + bot profile → JSON verdict
following AgentRx's `failure_case` integer schema, plus our additions
(`confidence`, `summary`).

Retry policy: one retry on JSON-parse failure with a stricter "JSON ONLY"
reminder. Second failure surfaces as `error_state=True` on the report —
not a fake Inconclusive verdict.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from diagnosis.models import (
    ConstraintViolation,
    FailureCategory,
    SecondaryFailure,
    category_from_index,
)
from diagnosis.redaction import redact_dict
from linter import build_transcript_payload, build_component_payload
from models import BotProfile, ConversationTimeline


_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "judge.md"
DEFAULT_JUDGE_MODEL = "gpt-5"
_MAX_SECONDARY_FAILURES = 5
_VALID_SECONDARY_SEVERITIES = {"low", "medium", "high"}


@dataclass
class JudgeVerdict:
    category: FailureCategory
    critical_step_index: int | None
    confidence: str  # "low" | "medium" | "high"
    summary: str
    taxonomy_checklist_reasoning: str
    reason_for_failure: str
    reason_for_index: str
    raw: dict
    secondary_failures: list[SecondaryFailure] = field(default_factory=list)


@dataclass
class JudgeResult:
    verdict: JudgeVerdict | None
    error: str = ""
    redaction_summary: dict[str, int] | None = None
    model_used: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict is not None and not self.error


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _parse_judge_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[: -len("```")]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Judge response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def _parse_secondary_failures(raw: object, primary_step: int | None) -> list[SecondaryFailure]:
    """Tolerantly parse the optional `secondary_failures` field.

    Skips malformed rows individually (one bad entry must not nuke the whole
    verdict). Caps at `_MAX_SECONDARY_FAILURES`. Drops any row whose step
    matches the primary critical step.
    """
    if not isinstance(raw, list):
        return []
    seen_steps: set[int] = set()
    out: list[SecondaryFailure] = []
    for entry in raw:
        if not isinstance(entry, dict):
            logger.debug(f"secondary_failures: skipped non-dict entry: {entry!r}")
            continue
        step = entry.get("step")
        fc = entry.get("failure_case")
        if not isinstance(step, int) or not isinstance(fc, int):
            logger.debug(f"secondary_failures: skipped entry missing step/failure_case: {entry!r}")
            continue
        if primary_step is not None and step == primary_step:
            continue
        if step in seen_steps:
            continue
        try:
            category = category_from_index(fc)
        except ValueError:
            logger.debug(f"secondary_failures: skipped entry with bad failure_case={fc}")
            continue
        severity = entry.get("severity", "medium")
        if severity not in _VALID_SECONDARY_SEVERITIES:
            severity = "medium"
        reason = str(entry.get("reason", "")).strip()
        try:
            out.append(
                SecondaryFailure(
                    step_index=step,
                    category=category,
                    reason=reason,
                    severity=severity,  # type: ignore[arg-type]
                )
            )
            seen_steps.add(step)
        except Exception as exc:  # noqa: BLE001 — defensive, pydantic validation
            logger.debug(f"secondary_failures: pydantic rejected entry {entry!r}: {exc}")
        if len(out) >= _MAX_SECONDARY_FAILURES:
            break
    return out


def _verdict_from_json(parsed: dict) -> JudgeVerdict:
    failure_case = parsed.get("failure_case")
    if not isinstance(failure_case, int):
        raise ValueError("failure_case must be an integer 1..10")
    category = category_from_index(failure_case)
    confidence = parsed.get("confidence", "low")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    index = parsed.get("index")
    crit = int(index) if isinstance(index, int) and index >= 0 else None
    secondaries = _parse_secondary_failures(parsed.get("secondary_failures"), crit)
    return JudgeVerdict(
        category=category,
        critical_step_index=crit,
        confidence=confidence,
        summary=str(parsed.get("summary", "")).strip(),
        taxonomy_checklist_reasoning=str(parsed.get("taxonomy_checklist_reasoning", "")).strip(),
        reason_for_failure=str(parsed.get("reason_for_failure", "")).strip(),
        reason_for_index=str(parsed.get("reason_for_index", "")).strip(),
        raw=parsed,
        secondary_failures=secondaries,
    )


def _build_payload(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
    *,
    redact_pii: bool,
) -> tuple[dict, dict[str, int]]:
    profile_payload = build_component_payload(profile)
    transcript_payload = build_transcript_payload(timeline)
    violations_payload = [
        {
            "rule_id": v.rule_id,
            "step_index": v.step_index,
            "severity": v.severity,
            "description": v.description,
            "evidence": v.evidence,
            "suggested_category": v.default_category_seed.value if v.default_category_seed else None,
        }
        for v in violations
    ]
    payload = {
        "profile": profile_payload,
        "transcript": transcript_payload,
        "violations": violations_payload,
    }
    summary: dict[str, int] = {}
    if redact_pii:
        # Redact only the user-content surfaces — events, errors, instructions —
        # not structural metadata (positions, ids).
        for ev in payload["transcript"].get("events", []):
            if isinstance(ev, dict):
                redacted, s = redact_dict(ev)
                ev.update(redacted)
                for k, v in s.items():
                    summary[k] = summary.get(k, 0) + v
        if isinstance(payload["profile"].get("instructions"), str):
            from diagnosis.redaction import redact_text

            r = redact_text(payload["profile"]["instructions"])
            payload["profile"]["instructions"] = r.text
            for k, v in r.summary.items():
                summary[k] = summary.get(k, 0) + v
    return payload, summary


async def _call_openai(model: str, system_prompt: str, user_content: str) -> str:
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = AsyncOpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        response = await client.chat.completions.create(model=model, temperature=0.2, messages=messages)
    except Exception as exc:  # noqa: BLE001 — narrow check by message
        msg = str(exc).lower()
        if "temperature" in msg and "unsupported" in msg:
            logger.info(f"Judge model '{model}' rejected custom temperature; retrying without it")
            response = await client.chat.completions.create(model=model, messages=messages)
        else:
            raise
    return response.choices[0].message.content or ""


async def run_judge_async(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
    *,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    redact_pii: bool = True,
) -> JudgeResult:
    """Single-pass judge call with one retry on JSON-parse failure."""
    payload, redaction_summary = _build_payload(profile, timeline, violations, redact_pii=redact_pii)
    user_content = json.dumps(payload, indent=2, default=str)
    system_prompt = _load_prompt()

    for attempt in (1, 2):
        try:
            raw = await _call_openai(judge_model, system_prompt, user_content)
        except Exception as exc:  # noqa: BLE001 — surface judge errors to UI
            logger.warning(f"Judge call failed: {exc}")
            return JudgeResult(
                verdict=None,
                error=f"Judge call failed: {exc}",
                redaction_summary=redaction_summary,
                model_used=judge_model,
            )
        try:
            parsed = _parse_judge_json(raw)
            verdict = _verdict_from_json(parsed)
        except (ValueError, json.JSONDecodeError) as exc:
            if attempt == 1:
                logger.info(f"Judge returned non-JSON, retrying with stricter reminder: {exc}")
                system_prompt = _load_prompt() + (
                    "\n\nREMINDER: Return ONLY a JSON object with the exact keys listed. "
                    "No fences, no commentary, no prose around the JSON."
                )
                continue
            logger.warning(f"Judge JSON parse failed twice: {exc}")
            return JudgeResult(
                verdict=None,
                error=f"Judge response was not valid JSON: {exc}",
                redaction_summary=redaction_summary,
                model_used=judge_model,
            )
        return JudgeResult(verdict=verdict, redaction_summary=redaction_summary, model_used=judge_model)
    # Unreachable — both attempts return inside the loop.
    raise RuntimeError("judge loop fell through")


def run_judge(
    profile: BotProfile,
    timeline: ConversationTimeline,
    violations: list[ConstraintViolation],
    *,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    redact_pii: bool = True,
) -> JudgeResult:
    """Sync wrapper for CLI / tests. Use `run_judge_async` from inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            run_judge_async(profile, timeline, violations, judge_model=judge_model, redact_pii=redact_pii)
        )
    raise RuntimeError("run_judge called from inside an event loop; use run_judge_async() instead")

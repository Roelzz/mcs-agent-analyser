"""SEC001–SEC003: Security and injection risk checks."""

from __future__ import annotations

from pathlib import Path

from ._helpers import (
    _INJECTION_PATTERNS,
    _SECRET_PATTERNS,
    _fail,
    _pass,
    _read_xml,
    _warn,
)


def _check_security(work_dir: Path, schema: str) -> list[dict]:  # noqa: C901
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    # SEC001 — Prompt injection patterns in topic data files
    injection_hits: list[tuple[str, str]] = []  # (topic_name, matched_pattern)
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            if folder.startswith("mspva_"):
                continue
            parts = folder.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            data_path = comp_dir / "data"
            if not data_path.exists():
                continue
            try:
                text = data_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in _INJECTION_PATTERNS:
                m = pat.search(text)
                if m:
                    xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
                    name = xml_fields.get("name") or folder
                    injection_hits.append((name, m.group(0)[:60]))
                    break  # one hit per component is enough

    if injection_hits:
        details = "; ".join(f"'{n}' (matched: \"{s}\")" for n, s in injection_hits[:3])
        suffix = f" and {len(injection_hits) - 3} more" if len(injection_hits) > 3 else ""
        results.append(
            _fail(
                "SEC001",
                "Security",
                f"Prompt injection patterns detected in {len(injection_hits)} topic(s)",
                f"Potential prompt injection or instruction-override language found in: {details}{suffix}. "
                "System instructions and topic content must not contain language that could override "
                "the agent's safety constraints. Review and sanitise the affected topics before "
                "deploying to production.",
            )
        )
    else:
        results.append(
            _pass(
                "SEC001",
                "Security",
                "No prompt injection patterns detected in topic content",
                "None of the topic data files contain common prompt injection or instruction-override patterns.",
            )
        )

    # SEC002 — Hardcoded secrets / credentials in topic data
    secret_hits: list[tuple[str, str]] = []
    if botcomponents_dir.exists():
        for comp_dir in sorted(botcomponents_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            if folder.startswith("mspva_"):
                continue
            parts = folder.split(".", 2)
            if len(parts) < 2 or parts[0] != schema:
                continue
            data_path = comp_dir / "data"
            if not data_path.exists():
                continue
            try:
                text = data_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in _SECRET_PATTERNS:
                m = pat.search(text)
                if m:
                    xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
                    name = xml_fields.get("name") or folder
                    # Only flag high-confidence patterns (skip long base64 if it's in known-safe contexts)
                    matched = m.group(0)
                    # Skip base64 blobs that appear inside filedata (legitimate binary encoding)
                    if len(matched) > 100 and "filedata" in str(comp_dir):
                        continue
                    secret_hits.append((name, matched[:40]))
                    break

    if secret_hits:
        names = ", ".join(f"'{n}'" for n, _ in secret_hits[:3])
        suffix = f" and {len(secret_hits) - 3} more" if len(secret_hits) > 3 else ""
        results.append(
            _warn(
                "SEC002",
                "Security",
                f"Possible hardcoded credential patterns in {len(secret_hits)} component(s)",
                f"Patterns resembling hardcoded secrets were found in: {names}{suffix}. "
                "Credentials must not be embedded in topic data or bot configuration. "
                "Use Power Platform Environment Variables or Azure Key Vault references instead. "
                "Review the flagged components and remove or replace any embedded secrets.",
            )
        )
    else:
        results.append(
            _pass(
                "SEC002",
                "Security",
                "No hardcoded credential patterns detected",
                "No patterns resembling hardcoded API keys, passwords, or tokens were found in "
                "the botcomponent data files.",
            )
        )

    # SEC003 — File analysis enabled (can process uploaded files from users)
    config_path = work_dir / "bots" / schema / "configuration.json"
    file_analysis_enabled = False
    if config_path.exists():
        try:
            import json

            config = json.loads(config_path.read_text(encoding="utf-8"))
            ai_settings = config.get("aISettings", {}) or {}
            file_analysis_enabled = bool(ai_settings.get("isFileAnalysisEnabled", False))
        except Exception:
            pass

    if file_analysis_enabled:
        results.append(
            _warn(
                "SEC003",
                "Security",
                "File analysis (user file uploads) is enabled",
                "isFileAnalysisEnabled is true, allowing end users to upload files directly to "
                "the agent for analysis. This expands the attack surface: users could upload "
                "malicious documents or attempt prompt injection through file content. Ensure "
                "this capability is required for the agent's use case, and that uploaded content "
                "is processed safely.",
            )
        )
    else:
        results.append(
            _pass(
                "SEC003",
                "Security",
                "File upload analysis is disabled",
                "isFileAnalysisEnabled is false. End users cannot upload files to this agent.",
            )
        )

    return results

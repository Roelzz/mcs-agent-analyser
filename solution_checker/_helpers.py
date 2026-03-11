"""Shared helpers, constants, and result constructors for solution checker modules."""

from __future__ import annotations

import re
from pathlib import Path

import defusedxml.ElementTree as ET

try:
    import yaml as _yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False


# ── Category labels ────────────────────────────────────────────────────────────

CATEGORIES: list[str] = ["Solution", "Agent", "Topics", "Knowledge", "Security", "Orchestrator"]

_CAT_ICONS: dict[str, str] = {
    "Solution": "file-text",
    "Agent": "bot",
    "Topics": "list",
    "Knowledge": "database",
    "Security": "shield-alert",
    "Orchestrator": "network",
}

# System topics that every production agent should have
_REQUIRED_SYSTEM_TOPICS: dict[str, tuple[str, str]] = {
    # trigger → (display label, severity if absent)
    "OnError": ("On Error", "fail"),
    "OnUnknownIntent": ("Fallback (Unknown Intent)", "warning"),
    "OnConversationStart": ("Conversation Start", "warning"),
    "OnEscalate": ("Escalate", "warning"),
    "OnSignIn": ("Sign-In", "warning"),
}

# Patterns that look like hardcoded secrets / credentials
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|apikey|api[_-]?secret)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(client[_-]?secret|clientsecret)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(bearer\s+[A-Za-z0-9\-._~+/]+=*)"),
    re.compile(r"(?i)(access[_-]?token)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(connection[_-]?string)\s*[=:]\s*.{10,}"),
    # Typical Azure SAS / storage keys length
    re.compile(r"[A-Za-z0-9+/]{64,}={0,2}"),
]

# Prompt injection patterns (same set as validator.py rule 11)
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore (all |previous |above |prior |system |original )?instructions", re.I),
    re.compile(r"disregard (all |previous |above |prior )?instructions", re.I),
    re.compile(r"override (all |previous |above |prior )?instructions", re.I),
    re.compile(r"forget (all |your |previous )?instructions", re.I),
    re.compile(r"new (role|persona|objective):", re.I),
    re.compile(r"you are now (a |an )?(?!legal|financial|hr|support)", re.I),
    re.compile(r"pretend (you are|to be)", re.I),
    re.compile(r"act as (?!a |an |the )", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"DAN mode", re.I),
]


# ── Internal helpers ───────────────────────────────────────────────────────────


def _read_xml(path: Path, *tags: str) -> dict[str, str]:
    """Return {tag: text} from an XML file; empty string on any parse failure."""
    try:
        root = ET.parse(path).getroot()
        return {tag: root.findtext(tag) or "" for tag in tags}
    except Exception:
        return {tag: "" for tag in tags}


def _load_yaml(path: Path) -> dict:
    """Load a YAML file (Power Platform 'data'); return {} on any failure."""
    if not _YAML_AVAILABLE or not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        # Fix common PP YAML quirks
        raw = raw.replace("\t", "    ")
        raw = re.sub(r"^(\s*)(@[a-zA-Z0-9_.]+)(\s*:)", r'\1"\2"\3', raw, flags=re.MULTILINE)
        raw = re.sub(
            r"(:\s+)(@[^\n]+)$",
            lambda m: m.group(1) + '"' + m.group(2) + '"',
            raw,
            flags=re.MULTILINE,
        )
        result = _yaml.safe_load(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _pass(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "pass", "detail": detail}


def _warn(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "warning", "detail": detail}


def _fail(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "fail", "detail": detail}


def _info(rule_id: str, category: str, title: str, detail: str) -> dict:
    return {"rule_id": rule_id, "category": category, "title": title, "severity": "info", "detail": detail}

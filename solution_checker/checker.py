"""Main entry point — check_solution_zip orchestrates all check modules."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import defusedxml.ElementTree as ET

from utils import safe_extractall

from ._helpers import _YAML_AVAILABLE, _fail, _load_yaml, _read_xml
from .agent_config import _check_agent_config
from .knowledge import _check_knowledge
from .orchestrator import _check_orchestrator
from .security import _check_security
from .solution_xml import _check_solution_xml
from .topics import _check_topics


def check_solution_zip(zip_bytes: bytes, *, custom_rules: list[dict] | None = None) -> dict:
    """Run all solution checks against a Power Platform solution ZIP.

    Args:
        zip_bytes: Raw bytes of the solution ZIP file.

    Returns:
        A dict with keys:
          - ``results``: list of check result dicts (rule_id, category, title, severity, detail)
          - ``agent_name``: detected agent display name
          - ``solution_name``: detected solution unique name
          - ``pass_count``, ``warn_count``, ``fail_count``, ``info_count``: summary counts
          - ``error``: non-empty string if the ZIP could not be parsed at all
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        return {
            "results": [],
            "agent_name": "",
            "solution_name": "",
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "info_count": 0,
            "error": f"Invalid ZIP file: {exc}",
        }

    # Ensure it looks like a solution ZIP
    has_solution = any(n == "bots" or n.startswith("bots/") for n in names)
    if not has_solution:
        return {
            "results": [],
            "agent_name": "",
            "solution_name": "",
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": 0,
            "info_count": 0,
            "error": (
                "Uploaded file does not appear to be a Power Platform solution ZIP "
                "(no bots/ directory found). Solution check requires a solution export."
            ),
        }

    results: list[dict] = []
    agent_name = ""
    solution_name = ""
    bot_config: dict = {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            safe_extractall(zf, work_dir)

        # Detect bot schema
        bots_dir = work_dir / "bots"
        bot_folders = [d for d in bots_dir.iterdir() if d.is_dir()] if bots_dir.exists() else []
        schema = bot_folders[0].name if bot_folders else ""

        # Detect agent / solution names for the summary header
        if schema:
            gpt_xml = work_dir / "botcomponents" / f"{schema}.gpt.default" / "botcomponent.xml"
            if gpt_xml.exists():
                agent_name = _read_xml(gpt_xml, "name").get("name", schema)
            else:
                agent_name = schema

            config_path = work_dir / "bots" / schema / "configuration.json"
            if config_path.exists():
                try:
                    import json

                    bot_config = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        sol_xml = work_dir / "solution.xml"
        if sol_xml.exists():
            try:
                root = ET.parse(sol_xml).getroot()
                manifest = root.find("SolutionManifest")
                if manifest is not None:
                    solution_name = manifest.findtext("UniqueName") or ""
            except Exception:
                pass

        # ── Run all check groups ────────────────────────────────────────
        results.extend(_check_solution_xml(work_dir))
        if schema:
            results.extend(_check_agent_config(work_dir, schema))
            results.extend(_check_topics(work_dir, schema))
            results.extend(_check_knowledge(work_dir, schema, bot_config))
            results.extend(_check_security(work_dir, schema))
            # Orchestrator checks (only if agent has TaskDialog/AgentDialog)
            botcomponents_dir = work_dir / "botcomponents"
            is_orchestrator = False
            if botcomponents_dir.exists():
                for comp_dir in botcomponents_dir.iterdir():
                    if not comp_dir.is_dir():
                        continue
                    folder = comp_dir.name
                    parts = folder.split(".", 2)
                    if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
                        continue
                    data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
                    if data.get("kind") in ("TaskDialog", "AgentDialog"):
                        is_orchestrator = True
                        break
            if is_orchestrator:
                results.extend(_check_orchestrator(work_dir, schema))
        else:
            results.append(
                _fail(
                    "AGT000",
                    "Agent",
                    "No bot schema detected",
                    "Could not detect a bot schema name from the bots/ directory. "
                    "Agent, topic, knowledge, and security checks are skipped.",
                )
            )

        # ── Custom rules ────────────────────────────────────────────────
        if custom_rules and schema and _YAML_AVAILABLE:
            try:
                from custom_rules import evaluate_rules
                from models import CustomRule
                from parser import parse_yaml

                # Find botContent YAML files and parse into a BotProfile
                bot_content_files = list((work_dir / "bots" / schema).glob("**/botContent.yml"))
                if not bot_content_files:
                    bot_content_files = list((work_dir / "bots" / schema).glob("**/*.yml"))
                if bot_content_files:
                    profile, _ = parse_yaml(bot_content_files[0])
                    parsed_rules = [CustomRule(**r) for r in custom_rules]
                    results.extend(evaluate_rules(parsed_rules, profile))
            except Exception as e:
                results.append(
                    {
                        "rule_id": "CUSTOM_ERR",
                        "category": "Custom",
                        "title": "Custom rule evaluation error",
                        "severity": "warning",
                        "detail": str(e),
                    }
                )

    pass_count = sum(1 for r in results if r["severity"] == "pass")
    warn_count = sum(1 for r in results if r["severity"] == "warning")
    fail_count = sum(1 for r in results if r["severity"] == "fail")
    info_count = sum(1 for r in results if r["severity"] == "info")

    return {
        "results": results,
        "agent_name": agent_name,
        "solution_name": solution_name,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "info_count": info_count,
        "error": "",
    }

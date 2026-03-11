"""KNO001–KNO004: Knowledge sources and capabilities checks."""

from __future__ import annotations

from pathlib import Path

from ._helpers import _info, _pass, _warn


def _check_knowledge(work_dir: Path, schema: str, config: dict) -> list[dict]:
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    # KNO001 — Has at least one knowledge source
    knowledge_dirs: list[Path] = []
    if botcomponents_dir.exists():
        for comp_dir in botcomponents_dir.iterdir():
            if not comp_dir.is_dir():
                continue
            folder = comp_dir.name
            parts = folder.split(".", 2)
            if len(parts) >= 2 and parts[0] == schema and parts[1] in ("file", "knowledge", "entity"):
                knowledge_dirs.append(comp_dir)

    if knowledge_dirs:
        results.append(
            _pass(
                "KNO001",
                "Knowledge",
                f"{len(knowledge_dirs)} knowledge source(s) / entity component(s) present",
                f"The solution includes {len(knowledge_dirs)} file/knowledge/entity component(s), "
                "providing grounding data for the agent.",
            )
        )
    else:
        results.append(
            _info(
                "KNO001",
                "Knowledge",
                "No knowledge sources found",
                "No file or knowledge source components were found. If this agent is expected to "
                "answer domain-specific questions, add knowledge sources in Copilot Studio under "
                "Knowledge → Add Knowledge.",
            )
        )

    # KNO002 — Oversized file attachments (> 20 MB)
    MAX_FILE_BYTES = 20 * 1024 * 1024
    large_files: list[tuple[str, int]] = []
    if botcomponents_dir.exists():
        for fdir in knowledge_dirs:
            filedata_dir = fdir / "filedata"
            if filedata_dir.exists():
                for f in filedata_dir.iterdir():
                    if f.is_file():
                        size = f.stat().st_size
                        if size > MAX_FILE_BYTES:
                            large_files.append((f.name, size))

    if large_files:
        details = "; ".join(f"{name} ({sz // 1024 // 1024} MB)" for name, sz in large_files[:5])
        results.append(
            _warn(
                "KNO002",
                "Knowledge",
                f"{len(large_files)} oversized knowledge file(s) detected",
                f"The following knowledge files exceed 20 MB: {details}. Very large files increase "
                "ZIP extraction time, solution import time, and may hit platform size limits. "
                "Consider chunking large documents or hosting them externally and referencing via "
                "SharePoint or URL knowledge sources.",
            )
        )
    else:
        results.append(
            _pass(
                "KNO002",
                "Knowledge",
                "No oversized knowledge files detected",
                "All knowledge source files are within the 20 MB recommended size limit.",
            )
        )

    # KNO003 — Semantic search enabled
    ai_settings = config.get("aISettings", {}) or {}
    semantic_search = bool(ai_settings.get("isSemanticSearchEnabled", False))
    if semantic_search:
        results.append(
            _pass(
                "KNO003",
                "Knowledge",
                "Semantic search is enabled",
                "isSemanticSearchEnabled is true. The agent will use vector-based semantic search "
                "over knowledge sources, improving recall for natural language queries compared to "
                "keyword matching.",
            )
        )
    else:
        results.append(
            _warn(
                "KNO003",
                "Knowledge",
                "Semantic search is disabled",
                "isSemanticSearchEnabled is false. The agent falls back to keyword-based search "
                "over knowledge sources, which may miss relevant documents when user phrasing "
                "differs from document text. Enable semantic search in Copilot Studio Settings → "
                "AI Capabilities for better knowledge retrieval.",
            )
        )

    # KNO004 — Web browsing enabled
    web_browsing = False
    settings = config.get("settings", {}) or {}
    for _key, sv in settings.items():
        if isinstance(sv, dict):
            caps = (sv.get("content") or {}).get("capabilities") or {}
            if caps.get("webBrowsing"):
                web_browsing = True
                break

    if web_browsing:
        results.append(
            _warn(
                "KNO004",
                "Knowledge",
                "Web browsing capability is enabled",
                "The agent has web browsing enabled, allowing it to retrieve information from the "
                "public internet in real time. This can lead to responses based on unverified "
                "sources. Ensure your system instructions explicitly scope what the agent may "
                "or may not retrieve via browsing, or disable web browsing if not required.",
            )
        )
    else:
        results.append(
            _pass(
                "KNO004",
                "Knowledge",
                "Web browsing is not enabled",
                "Web browsing is disabled. The agent relies solely on provided knowledge sources "
                "and model knowledge (if enabled), keeping responses grounded in controlled data.",
            )
        )

    return results

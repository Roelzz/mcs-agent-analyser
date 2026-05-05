"""Canned recommendations loader.

Reads `data/recommendations.yaml` and resolves a `FailureCategory` to a list
of `Recommendation(source="canned")`. Pure data; no LLM calls.

Phase 2 will add an `ai_recommendations.py` companion that calls a model
with full component context. That layer renders alongside this one in the
UI; it does not replace it (canned is the liability shield).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from diagnosis.models import FailureCategory, Recommendation


_RECS_PATH = Path(__file__).resolve().parent.parent / "data" / "recommendations.yaml"


@lru_cache(maxsize=1)
def _load() -> dict[str, list[dict]]:
    text = _RECS_PATH.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or "recommendations" not in raw:
        raise ValueError(f"{_RECS_PATH} must contain a top-level 'recommendations' key")
    recs = raw["recommendations"]
    if not isinstance(recs, dict):
        raise ValueError("'recommendations' must be a mapping of category -> list[entry]")
    return recs


def canned_for(category: FailureCategory) -> list[Recommendation]:
    """Return canned recommendations for a category. Empty list if the
    category has no entries (treated as non-fatal — the renderer just
    omits the section)."""
    entries = _load().get(category.value, [])
    return [
        Recommendation(
            source="canned",
            title=str(entry.get("title", "")).strip(),
            body_md=str(entry.get("body", "")).strip(),
        )
        for entry in entries
        if isinstance(entry, dict)
    ]

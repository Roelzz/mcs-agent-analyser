import os
from pathlib import Path
from unittest.mock import patch

import pytest

from parser import parse_dialog_json, parse_yaml
from renderer import render_report
from timeline import build_timeline
from web.mermaid import split_markdown_mermaid
from web.state import _load_users

BASE_DIR = Path(__file__).parent.parent


# --- Auth tests ---


def test_load_users_parses_env():
    with patch.dict(os.environ, {"USERS": "admin:pass1,analyst:pass2"}):
        users = _load_users()
    assert users == {"admin": "pass1", "analyst": "pass2"}


def test_load_users_empty():
    with patch.dict(os.environ, {"USERS": ""}):
        users = _load_users()
    assert users == {}


def test_load_users_single():
    with patch.dict(os.environ, {"USERS": "admin:secret"}):
        users = _load_users()
    assert users == {"admin": "secret"}


def test_load_users_whitespace():
    with patch.dict(os.environ, {"USERS": " admin : pass1 , analyst : pass2 "}):
        users = _load_users()
    assert users == {"admin": "pass1", "analyst": "pass2"}


def test_load_users_missing_env():
    with patch.dict(os.environ, {}, clear=True):
        # Remove USERS if it exists
        os.environ.pop("USERS", None)
        users = _load_users()
    assert users == {}


# --- Mermaid splitting tests ---


def test_split_no_mermaid():
    md = "# Hello\n\nSome text here."
    segments = split_markdown_mermaid(md)
    assert len(segments) == 1
    assert segments[0] == ("markdown", "# Hello\n\nSome text here.")


def test_split_single_mermaid():
    md = "# Title\n\n```mermaid\ngraph TD\n    A-->B\n```\n\nAfter text."
    segments = split_markdown_mermaid(md)
    assert len(segments) == 3
    assert segments[0] == ("markdown", "# Title")
    assert segments[1] == ("mermaid", "graph TD\n    A-->B")
    assert segments[2] == ("markdown", "After text.")


def test_split_multiple_mermaid():
    md = (
        "# Title\n\n"
        "```mermaid\ngraph TD\n    A-->B\n```\n\n"
        "Middle text.\n\n"
        "```mermaid\nsequenceDiagram\n    A->>B: msg\n```\n\n"
        "End text."
    )
    segments = split_markdown_mermaid(md)
    assert len(segments) == 5
    assert segments[0][0] == "markdown"
    assert segments[1][0] == "mermaid"
    assert segments[2][0] == "markdown"
    assert segments[3][0] == "mermaid"
    assert segments[4][0] == "markdown"
    assert "graph TD" in segments[1][1]
    assert "sequenceDiagram" in segments[3][1]


def test_split_real_report():
    """Generate actual report from pipeline and verify mermaid segments extracted."""
    yaml_path = BASE_DIR / "botContent" / "botContent.yml"
    json_path = BASE_DIR / "botContent" / "dialog.json"

    if not yaml_path.exists() or not json_path.exists():
        pytest.skip("Test data not available")

    profile, schema_lookup = parse_yaml(yaml_path)
    activities = parse_dialog_json(json_path)
    timeline = build_timeline(activities, schema_lookup)
    report = render_report(profile, timeline)

    segments = split_markdown_mermaid(report)
    types = [s[0] for s in segments]

    # Report should have at least one mermaid diagram
    assert "mermaid" in types
    # Should have markdown segments too
    assert "markdown" in types
    # Mermaid segments should contain valid mermaid syntax keywords
    for seg_type, content in segments:
        if seg_type == "mermaid":
            assert any(kw in content for kw in ["sequenceDiagram", "graph", "gantt"])


def test_split_mermaid_only():
    md = "```mermaid\ngraph TD\n    A-->B\n```"
    segments = split_markdown_mermaid(md)
    assert len(segments) == 1
    assert segments[0] == ("mermaid", "graph TD\n    A-->B")


def test_split_empty_string():
    segments = split_markdown_mermaid("")
    assert segments == []

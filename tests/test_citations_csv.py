"""Tests for `exports.citations_csv.render_citations_csv`."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from exports.citations_csv import CSV_HEADER, render_citations_csv
from parser import parse_dialog_json, parse_yaml
from timeline import build_timeline


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "employee_hr_uat"


@pytest.fixture(scope="module")
def timeline():
    profile, lookup = parse_yaml(FIXTURE_DIR / "botContent.yml")
    activities = parse_dialog_json(FIXTURE_DIR / "dialog.json")
    return build_timeline(activities, lookup, profile=profile)


def test_render_returns_non_empty_string(timeline) -> None:
    csv_str = render_citations_csv(timeline)
    assert isinstance(csv_str, str)
    assert csv_str.strip() != ""


def test_csv_starts_with_expected_header(timeline) -> None:
    csv_str = render_citations_csv(timeline)
    expected_header_line = ",".join(CSV_HEADER)
    assert csv_str.splitlines()[0] == expected_header_line
    assert expected_header_line == "turn_message,completion_state,source_name,source_url,snippet_chars,snippet_text"


def test_faq_parking_row_has_url_and_large_snippet(timeline) -> None:
    csv_str = render_citations_csv(timeline)
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    faq_rows = [r for r in rows if r["source_name"] == "FAQ-Parking-EN.pdf"]
    assert faq_rows, "expected at least one row for FAQ-Parking-EN.pdf"
    sample = faq_rows[0]
    assert sample["source_url"] == "https://ing.sharepoint.com/sites/intranet-001-hr/INGDocuments/FAQ-Parking-EN.pdf"
    assert int(sample["snippet_chars"]) >= 1000
    assert len(sample["snippet_text"]) >= 1000


def test_employee_hr_uat_yields_six_data_rows(timeline) -> None:
    csv_str = render_citations_csv(timeline)
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert len(rows) == len(timeline.citation_sources)
    assert len(rows) >= 6

"""Tests for the judge JSON parser and verdict construction."""

from __future__ import annotations

import json

import pytest

from diagnosis.judge import _parse_judge_json, _verdict_from_json
from diagnosis.models import FailureCategory


_VALID = {
    "taxonomy_checklist_reasoning": "rules out PlanAdherence and Invention; tool call returned valid data...",
    "reason_for_failure": "Bot ignored ORDER_NOT_FOUND error and claimed shipped",
    "failure_case": 4,
    "reason_for_index": "Step 23 is where the bot replied without referencing the error",
    "index": 23,
    "confidence": "high",
    "summary": "Tool returned ORDER_NOT_FOUND, bot misinterpreted as shipped.",
}


class TestParseJudgeJson:
    def test_plain_json(self):
        parsed = _parse_judge_json(json.dumps(_VALID))
        assert parsed["failure_case"] == 4

    def test_strips_markdown_fences(self):
        wrapped = "```json\n" + json.dumps(_VALID) + "\n```"
        assert _parse_judge_json(wrapped)["failure_case"] == 4

    def test_strips_prose_around_json(self):
        wrapped = "Here is the answer:\n\n" + json.dumps(_VALID) + "\n\nThanks."
        assert _parse_judge_json(wrapped)["failure_case"] == 4

    def test_missing_braces_raises(self):
        with pytest.raises(ValueError):
            _parse_judge_json("just some prose, no JSON object here")


class TestVerdictFromJson:
    def test_happy_path(self):
        v = _verdict_from_json(_VALID)
        assert v.category == FailureCategory.TOOL_MISINTERPRETATION
        assert v.critical_step_index == 23
        assert v.confidence == "high"
        assert v.summary.startswith("Tool")

    def test_index_minus_one_means_no_critical_step(self):
        d = dict(_VALID, index=-1)
        v = _verdict_from_json(d)
        assert v.critical_step_index is None

    def test_invalid_failure_case_raises(self):
        with pytest.raises(ValueError):
            _verdict_from_json(dict(_VALID, failure_case=11))

    def test_missing_failure_case_raises(self):
        d = dict(_VALID)
        d.pop("failure_case")
        with pytest.raises(ValueError):
            _verdict_from_json(d)

    def test_unknown_confidence_falls_back_to_low(self):
        v = _verdict_from_json(dict(_VALID, confidence="???"))
        assert v.confidence == "low"

    def test_inconclusive_returns_inconclusive(self):
        v = _verdict_from_json(dict(_VALID, failure_case=10, index=-1))
        assert v.category == FailureCategory.INCONCLUSIVE
        assert v.critical_step_index is None

    def test_secondary_failures_missing_defaults_to_empty(self):
        v = _verdict_from_json(_VALID)
        assert v.secondary_failures == []


class TestSecondaryFailures:
    def _verdict_with_secondaries(self, secondaries: list) -> object:
        return _verdict_from_json(dict(_VALID, secondary_failures=secondaries))

    def test_well_formed_secondary_parsed(self):
        v = self._verdict_with_secondaries(
            [{"step": 19, "failure_case": 6, "reason": "user input was ambiguous", "severity": "medium"}]
        )
        assert len(v.secondary_failures) == 1
        sf = v.secondary_failures[0]
        assert sf.step_index == 19
        assert sf.category == FailureCategory.UNDERSPECIFIED_INTENT
        assert sf.severity == "medium"
        assert "ambiguous" in sf.reason

    def test_malformed_entry_skipped_individually(self):
        v = self._verdict_with_secondaries(
            [
                {"step": 19, "failure_case": 6, "reason": "ok"},
                {"step": "not-an-int", "failure_case": 4},  # malformed: bad type
                {"step": 25, "failure_case": 99},  # malformed: bad failure_case
                {"step": 30, "failure_case": 5, "reason": "second valid"},
            ]
        )
        steps = [sf.step_index for sf in v.secondary_failures]
        assert steps == [19, 30]

    def test_dedupes_against_primary_step(self):
        v = self._verdict_with_secondaries([{"step": 23, "failure_case": 4, "reason": "duplicate of primary"}])
        assert v.secondary_failures == []

    def test_dedupes_internally_by_step(self):
        v = self._verdict_with_secondaries(
            [
                {"step": 19, "failure_case": 6, "reason": "first"},
                {"step": 19, "failure_case": 4, "reason": "dup"},
            ]
        )
        assert len(v.secondary_failures) == 1
        assert v.secondary_failures[0].category == FailureCategory.UNDERSPECIFIED_INTENT

    def test_caps_at_five(self):
        many = [{"step": 100 + i, "failure_case": 1, "reason": f"r{i}"} for i in range(10)]
        v = self._verdict_with_secondaries(many)
        assert len(v.secondary_failures) == 5

    def test_unknown_severity_falls_back_to_medium(self):
        v = self._verdict_with_secondaries([{"step": 19, "failure_case": 6, "reason": "x", "severity": "???"}])
        assert v.secondary_failures[0].severity == "medium"

    def test_non_list_input_returns_empty(self):
        v = _verdict_from_json(dict(_VALID, secondary_failures="not a list"))
        assert v.secondary_failures == []

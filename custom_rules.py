"""Custom rule engine — evaluate YAML-based rules against BotProfile models."""

from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import BaseModel

from models import CustomRule


def load_rules_yaml(yaml_text: str) -> list[CustomRule]:
    """Parse YAML text into a list of CustomRule models.

    Raises ValueError on invalid YAML or invalid rule definitions.
    """
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError("YAML must contain a top-level 'rules' key")

    raw_rules = data["rules"]
    if not isinstance(raw_rules, list):
        raise ValueError("'rules' must be a list")

    rules: list[CustomRule] = []
    for i, raw in enumerate(raw_rules):
        try:
            rules.append(CustomRule(**raw))
        except Exception as exc:
            raise ValueError(f"Rule #{i + 1}: {exc}") from exc
    return rules


def evaluate_rules(rules: list[CustomRule], profile: BaseModel) -> list[dict]:
    """Evaluate custom rules against a profile and return solution_checker-format results."""
    results: list[dict] = []
    for rule in rules:
        values = _resolve_field(profile, rule.condition.field)
        triggered = False
        for val in values:
            if _apply_operator(val, rule.condition.operator, rule.condition.value):
                triggered = True
                break
        # For exists/not_exists on empty resolution, check the empty list itself
        if not values and rule.condition.operator in ("not_exists", "exists"):
            triggered = _apply_operator(None, rule.condition.operator, rule.condition.value)
        if triggered:
            results.append(
                {
                    "rule_id": rule.rule_id,
                    "category": rule.category,
                    "title": rule.rule_id,
                    "severity": rule.severity,
                    "detail": rule.message,
                }
            )
    return results


def _resolve_field(obj: BaseModel, path: str) -> list[Any]:
    """Resolve a dotted field path on a Pydantic model.

    Supports array iteration with ``[]`` syntax, e.g. ``components[].tool_type``.
    Returns a list of resolved values.
    """
    parts = path.replace("[]", ".[].").strip(".").split(".")
    current: list[Any] = [obj]

    for part in parts:
        if not part:
            continue
        if part == "[]":
            # Flatten iterables
            expanded: list[Any] = []
            for item in current:
                if isinstance(item, (list, tuple)):
                    expanded.extend(item)
                else:
                    expanded.append(item)
            current = expanded
            continue

        next_values: list[Any] = []
        for item in current:
            if item is None:
                continue
            if isinstance(item, BaseModel):
                val = getattr(item, part, None)
                next_values.append(val)
            elif isinstance(item, dict):
                next_values.append(item.get(part))
            elif isinstance(item, (list, tuple)):
                for sub in item:
                    if isinstance(sub, BaseModel):
                        next_values.append(getattr(sub, part, None))
                    elif isinstance(sub, dict):
                        next_values.append(sub.get(part))
        current = next_values

    return current


def _apply_operator(actual: Any, op: str, expected: Any) -> bool:
    """Apply a comparison operator. Returns False on type mismatches rather than raising."""
    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, (list, tuple)):
            return expected in actual
        return False
    if op == "not_contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected not in actual
        if isinstance(actual, (list, tuple)):
            return expected not in actual
        return True
    if op == "matches":
        if isinstance(actual, str) and isinstance(expected, str):
            if len(expected) > 500:
                return False
            if re.search(r"\(.+[*+]\)[*+]", expected):
                return False
            try:
                return re.search(expected, actual) is not None
            except re.error:
                return False
        return False
    # Numeric comparisons
    try:
        a, b = float(actual), float(expected)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return a > b
    if op == "lt":
        return a < b
    if op == "gte":
        return a >= b
    if op == "lte":
        return a <= b
    return False

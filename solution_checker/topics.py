"""TOP001–TOP005: Topic coverage and quality checks."""

from __future__ import annotations

from pathlib import Path

from ._helpers import (
    _REQUIRED_SYSTEM_TOPICS,
    _YAML_AVAILABLE,
    _fail,
    _load_yaml,
    _pass,
    _read_xml,
    _warn,
)


def _check_topics(work_dir: Path, schema: str) -> list[dict]:
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    if not botcomponents_dir.exists():
        results.append(
            _warn(
                "TOP000",
                "Topics",
                "No botcomponents/ directory found",
                "The solution does not contain a botcomponents/ directory. Topic checks are skipped.",
            )
        )
        return results

    # Collect all topic components for this bot schema
    topics: list[dict] = []  # list of {folder, display_name, trigger_kind, state, has_actions}
    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        if folder.startswith("mspva_"):
            continue
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue

        xml_path = comp_dir / "botcomponent.xml"
        if not xml_path.exists():
            continue
        fields = _read_xml(xml_path, "name", "statecode")
        name = fields.get("name") or folder
        state = "active" if fields.get("statecode", "0") == "0" else "inactive"

        data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
        begin = data.get("beginDialog") or {}
        trigger_kind = begin.get("kind") or ""
        has_actions = bool(begin.get("actions"))
        topics.append(
            {
                "folder": folder,
                "display_name": name,
                "trigger_kind": trigger_kind,
                "state": state,
                "has_actions": has_actions,
            }
        )

    # TOP001–TOP005 — Required system topics
    found_triggers = {t["trigger_kind"] for t in topics}
    for trigger, (label, severity) in _REQUIRED_SYSTEM_TOPICS.items():
        if trigger in found_triggers:
            results.append(
                _pass(
                    "TOP001" if trigger == "OnError" else "TOP002",
                    "Topics",
                    f"'{label}' system topic is present",
                    f"The '{label}' topic (trigger: {trigger}) is included in the solution.",
                )
            )
        else:
            entry = _fail if severity == "fail" else _warn
            results.append(
                entry(
                    "TOP001" if trigger == "OnError" else "TOP002",
                    "Topics",
                    f"'{label}' system topic is missing",
                    f"No topic with a '{trigger}' trigger was found. This system topic is important "
                    f"for handling the corresponding lifecycle event. Consider adding it in Copilot "
                    f"Studio to ensure robust conversational flow.",
                )
            )

    # TOP003 — Inactive topics
    inactive = [t for t in topics if t["state"] == "inactive"]
    if inactive:
        names = ", ".join(t["display_name"] for t in inactive[:5])
        suffix = f" and {len(inactive) - 5} more" if len(inactive) > 5 else ""
        results.append(
            _warn(
                "TOP003",
                "Topics",
                f"{len(inactive)} inactive topic(s) detected",
                f"The following topic(s) are inactive and will not be triggered: {names}{suffix}. "
                "Inactive topics clutter the solution and may cause confusion during maintenance. "
                "Consider removing unused topics before promoting to production.",
            )
        )
    else:
        results.append(
            _pass(
                "TOP003",
                "Topics",
                "No inactive topics detected",
                "All topics in the solution are active.",
            )
        )

    # TOP004 — Empty topics (no actions in beginDialog)
    empty = [t for t in topics if not t["has_actions"] and t["trigger_kind"]]
    if empty:
        names = ", ".join(t["display_name"] for t in empty[:5])
        suffix = f" and {len(empty) - 5} more" if len(empty) > 5 else ""
        results.append(
            _warn(
                "TOP004",
                "Topics",
                f"{len(empty)} topic(s) have empty dialog (no actions)",
                f"The following topic(s) define a trigger but have no actions: {names}{suffix}. "
                "Empty topics will be triggered but do nothing, resulting in silent failures or "
                "confusing user experiences. Add at least one action (e.g., a message or redirect) "
                "or disable the topic.",
            )
        )
    else:
        results.append(
            _pass(
                "TOP004",
                "Topics",
                "All topics have dialog actions defined",
                "No topics were found with triggers but empty dialog action lists.",
            )
        )

    # TOP005 — Large topic count
    user_topics = [
        t
        for t in topics
        if t["trigger_kind"]
        and t["trigger_kind"]
        not in (
            "OnError",
            "OnUnknownIntent",
            "OnConversationStart",
            "OnEscalate",
            "OnSignIn",
            "OnRedirect",
            "OnActivity",
            "OnInactivity",
            "OnSystemRedirect",
            "OnSelectIntent",
        )
    ]
    user_count = len(user_topics)
    if user_count > 100:
        results.append(
            _warn(
                "TOP005",
                "Topics",
                f"Very large number of user topics ({user_count})",
                f"The solution contains {user_count} user-triggered topics. Agents with more than "
                "100 user topics can be difficult to maintain and may experience slower topic "
                "disambiguation at runtime. Consider consolidating related topics or off-loading "
                "logic to Power Automate flows.",
            )
        )
    elif user_count > 50:
        results.append(
            _warn(
                "TOP005",
                "Topics",
                f"High number of user topics ({user_count})",
                f"The solution contains {user_count} user-triggered topics. This is manageable but "
                "consider grouping topics into logical sections and using redirect chains to keep "
                "the topic list navigable.",
            )
        )
    else:
        results.append(
            _pass(
                "TOP005",
                "Topics",
                f"Topic count is within a manageable range ({user_count} user topics)",
                f"The solution contains {user_count} user-triggered topics, which is within the "
                "recommended range for maintainability.",
            )
        )

    return results

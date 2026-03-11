"""ORCH001–ORCH005: Orchestrator-specific health checks."""

from __future__ import annotations

from pathlib import Path

from ._helpers import (
    _YAML_AVAILABLE,
    _info,
    _load_yaml,
    _pass,
    _read_xml,
    _warn,
)


def _check_orchestrator(work_dir: Path, schema: str) -> list[dict]:
    """ORCH001-ORCH005: Orchestrator-specific health checks."""
    results: list[dict] = []
    botcomponents_dir = work_dir / "botcomponents"

    if not botcomponents_dir.exists():
        return results

    # Collect TaskDialog / AgentDialog components
    agent_topics: list[dict] = []  # {folder, display_name, dialog_kind, connection_ref, model_desc}
    all_topics: list[dict] = []

    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        if folder.startswith("mspva_"):
            continue
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue

        data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
        dialog_kind = data.get("kind", "")
        xml_fields = _read_xml(comp_dir / "botcomponent.xml", "name")
        display_name = xml_fields.get("name") or folder

        topic_info = {
            "folder": folder,
            "display_name": display_name,
            "dialog_kind": dialog_kind,
        }
        all_topics.append(topic_info)

        if dialog_kind in ("TaskDialog", "AgentDialog"):
            action = data.get("action", {}) or {}
            conn_ref = action.get("connectionReference", "")
            settings = data.get("settings", {}) or {}
            model_desc = (data.get("modelDescription") or "").strip().lower()

            topic_info["connection_reference"] = conn_ref
            topic_info["model_description"] = model_desc
            topic_info["instructions"] = (settings.get("instructions") or "").strip()
            agent_topics.append(topic_info)

    if not agent_topics:
        return results

    # ORCH001: Child agents have connection references
    missing_conn = [t for t in agent_topics if not t.get("connection_reference")]
    if missing_conn:
        names = ", ".join(t["display_name"] for t in missing_conn[:5])
        suffix = f" and {len(missing_conn) - 5} more" if len(missing_conn) > 5 else ""
        results.append(
            _warn(
                "ORCH001",
                "Orchestrator",
                f"{len(missing_conn)} agent tool(s) missing connection references",
                f"The following TaskDialog/AgentDialog components have no connectionReference: "
                f"{names}{suffix}. Without a connection reference, the orchestrator cannot invoke "
                "the agent at runtime.",
            )
        )
    else:
        results.append(
            _pass(
                "ORCH001",
                "Orchestrator",
                "All agent tools have connection references",
                "Every TaskDialog/AgentDialog component has a connectionReference configured.",
            )
        )

    # ORCH002: Fallback handler exists (OnUnknownIntent)
    has_fallback = False
    for comp_dir in sorted(botcomponents_dir.iterdir()):
        if not comp_dir.is_dir():
            continue
        folder = comp_dir.name
        parts = folder.split(".", 2)
        if len(parts) < 2 or parts[0] != schema or parts[1] != "topic":
            continue
        data = _load_yaml(comp_dir / "data") if _YAML_AVAILABLE else {}
        begin = data.get("beginDialog") or {}
        if begin.get("kind") == "OnUnknownIntent":
            has_fallback = True
            break

    if has_fallback:
        results.append(
            _pass(
                "ORCH002",
                "Orchestrator",
                "Fallback handler (OnUnknownIntent) is present",
                "The orchestrator has a topic with OnUnknownIntent trigger to handle unmatched user input.",
            )
        )
    else:
        results.append(
            _warn(
                "ORCH002",
                "Orchestrator",
                "No fallback handler (OnUnknownIntent) found",
                "The orchestrator has no topic with OnUnknownIntent trigger. Without a fallback, "
                "unmatched user input will produce no response. Add a fallback topic.",
            )
        )

    # ORCH003: No single agent >70% of routed topics
    ref_counts: dict[str, int] = {}
    for t in agent_topics:
        ref = t.get("connection_reference", "") or "unset"
        ref_counts[ref] = ref_counts.get(ref, 0) + 1

    total_agent = len(agent_topics)
    if total_agent > 1:
        for ref, count in ref_counts.items():
            ratio = count / total_agent
            if ratio > 0.7:
                results.append(
                    _warn(
                        "ORCH003",
                        "Orchestrator",
                        f"Single agent handles {ratio:.0%} of routed topics",
                        f"Connection reference '{ref}' handles {count}/{total_agent} agent topics. "
                        "If one agent dominates, the orchestrator adds latency without meaningful "
                        "routing. Consider simplifying or rebalancing.",
                    )
                )
                break
        else:
            results.append(
                _pass(
                    "ORCH003",
                    "Orchestrator",
                    "Agent workload is distributed across connections",
                    f"{len(ref_counts)} distinct connection references handle {total_agent} agent topics.",
                )
            )

    # ORCH004: Distinct agent descriptions
    seen_descs: dict[str, list[str]] = {}
    for t in agent_topics:
        md = t.get("model_description", "")
        if md:
            seen_descs.setdefault(md, []).append(t["display_name"])
    duplicates = {desc: names for desc, names in seen_descs.items() if len(names) > 1}
    if duplicates:
        dup_detail = "; ".join(
            f"'{names[0]}' and '{names[1]}'" + (f" (+{len(names) - 2} more)" if len(names) > 2 else "")
            for names in duplicates.values()
        )
        results.append(
            _warn(
                "ORCH004",
                "Orchestrator",
                f"{len(duplicates)} set(s) of agents share identical descriptions",
                f"Agents with duplicate modelDescription: {dup_detail}. "
                "The orchestrator uses descriptions to route — duplicates cause ambiguous routing.",
            )
        )
    else:
        results.append(
            _pass(
                "ORCH004",
                "Orchestrator",
                "All agent descriptions are distinct",
                "Each agent tool has a unique modelDescription, enabling clear routing decisions.",
            )
        )

    # ORCH005: External agent ratio (mostly-router check)
    if total_agent > 0 and len(all_topics) > 0:
        agent_ratio = total_agent / max(len(all_topics), 1)
        if agent_ratio > 0.8:
            results.append(
                _info(
                    "ORCH005",
                    "Orchestrator",
                    f"High agent-to-topic ratio ({agent_ratio:.0%})",
                    f"{total_agent} of {len(all_topics)} topics are agent tools. "
                    "This orchestrator is primarily a router with minimal native logic.",
                )
            )
        else:
            results.append(
                _pass(
                    "ORCH005",
                    "Orchestrator",
                    f"Balanced topic mix ({total_agent} agent tools / {len(all_topics)} total topics)",
                    "The orchestrator has a mix of native topics and delegated agent tools.",
                )
            )

    return results

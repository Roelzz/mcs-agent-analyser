"""SOL001–SOL005: solution.xml metadata health checks."""

from __future__ import annotations

from pathlib import Path

import defusedxml.ElementTree as ET

from ._helpers import _fail, _info, _pass, _warn


def _check_solution_xml(work_dir: Path) -> list[dict]:
    results: list[dict] = []
    sol_path = work_dir / "solution.xml"

    if not sol_path.exists():
        results.append(
            _fail(
                "SOL001",
                "Solution",
                "solution.xml is missing",
                "The ZIP does not contain a solution.xml at the root level. This is required for "
                "all Power Platform solution imports.",
            )
        )
        # No point running further solution checks
        return results

    try:
        root = ET.parse(sol_path).getroot()
    except Exception as exc:
        results.append(
            _fail(
                "SOL001",
                "Solution",
                "solution.xml could not be parsed",
                f"The solution.xml could not be parsed as XML: {exc}. The file may be corrupt.",
            )
        )
        return results

    results.append(
        _pass(
            "SOL001",
            "Solution",
            "solution.xml is present and valid",
            "solution.xml exists and is well-formed XML.",
        )
    )

    # SOL002 — Publisher prefix not "new" (default publisher)
    manifest = root.find("SolutionManifest")
    if manifest is not None:
        prefix = (manifest.findtext("Publisher/CustomizationPrefix") or "").strip().lower()
        if prefix in ("new", "default", ""):
            results.append(
                _warn(
                    "SOL002",
                    "Solution",
                    f"Default publisher prefix detected ('{prefix or 'empty'}')",
                    "The solution uses the default publisher prefix. This is acceptable for development "
                    "but for production solutions you should create a dedicated publisher with a unique "
                    "prefix (e.g., your organisation abbreviation). Clashing prefixes cause import "
                    "conflicts when multiple solutions share the default publisher.",
                )
            )
        else:
            results.append(
                _pass(
                    "SOL002",
                    "Solution",
                    f"Custom publisher prefix in use ('{prefix}')",
                    f"The solution uses the publisher prefix '{prefix}', which is not the default. "
                    "This reduces the risk of naming conflicts with other solutions.",
                )
            )

    # SOL003 — Version is still 1.0.0.0
    version = (manifest.findtext("Version") if manifest is not None else None) or ""
    if version == "1.0.0.0":
        results.append(
            _warn(
                "SOL003",
                "Solution",
                "Solution version is the default (1.0.0.0)",
                "The solution version has not been incremented from the initial default. Before "
                "promoting to a Test or Production environment, update the version to reflect the "
                "release state (e.g., 1.1.0.0 or 2.0.0.0).",
            )
        )
    elif version:
        results.append(
            _pass(
                "SOL003",
                "Solution",
                f"Solution version is set ({version})",
                f"The solution carries version {version}, indicating it has been versioned for promotion.",
            )
        )

    # SOL004 — Solution description
    if manifest is not None:
        desc_node = manifest.find("Descriptions/Description")
        desc = (desc_node.get("description") or "").strip() if desc_node is not None else ""
        if not desc:
            results.append(
                _warn(
                    "SOL004",
                    "Solution",
                    "Solution has no description",
                    "Adding a description to the solution helps administrators understand its purpose "
                    "without opening each component. Edit this in your Power Platform environment under "
                    "Solutions → Properties.",
                )
            )
        else:
            results.append(
                _pass(
                    "SOL004",
                    "Solution",
                    "Solution description is present",
                    f'Solution description: "{desc}"',
                )
            )

    # SOL005 — Managed vs unmanaged
    managed = (manifest.findtext("Managed") if manifest is not None else None) or "0"
    if managed == "1":
        results.append(
            _info(
                "SOL005",
                "Solution",
                "Solution is managed",
                "This is a managed solution. Components cannot be edited directly in the target "
                "environment. This is the expected state for production deployments.",
            )
        )
    else:
        results.append(
            _info(
                "SOL005",
                "Solution",
                "Solution is unmanaged",
                "This is an unmanaged solution, which allows components to be edited after import. "
                "Consider exporting as managed for production environments to prevent accidental changes.",
            )
        )

    return results

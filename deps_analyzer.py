"""Dependency Analyzer — parse a Power Platform solution ZIP and generate
a visual dependency map from solution.xml component metadata.

Inspects:
  - RootComponents in solution.xml (all component types / counts)
  - MissingDependencies in solution.xml (external components required but absent)
  - Component artefact files for display-name enrichment

Returns segments compatible with ``viz_segments`` (list[dict]) so they can be
rendered by the existing Mermaid / Markdown frontend pipeline.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

import defusedxml.ElementTree as ET

from renamer import safe_extractall

# ── Component type registry ────────────────────────────────────────────────────

# (display_name, group)
_COMP_TYPES: dict[int, tuple[str, str]] = {
    1: ("Table", "data"),
    2: ("Column", "data"),
    3: ("Relationship", "data"),
    4: ("Attribute Picklist Map", "data"),
    9: ("Option Set", "data"),
    10: ("Entity Relationship", "data"),
    14: ("Table Key", "data"),
    26: ("Web Resource", "ui"),
    29: ("Canvas App", "app"),
    30: ("Cloud Flow", "automation"),
    33: ("Dialog (Legacy)", "ui"),
    34: ("Security Role", "security"),
    38: ("Form", "ui"),
    40: ("View", "ui"),
    44: ("Environment Variable", "config"),
    45: ("Env Variable Value", "config"),
    50: ("Plugin Assembly", "code"),
    51: ("SDK Step", "code"),
    52: ("SDK Step Image", "code"),
    60: ("System Form", "ui"),
    61: ("Security Role", "security"),
    64: ("Report", "reporting"),
    65: ("Report Entity", "reporting"),
    70: ("Report", "reporting"),
    80: ("Site Map", "ui"),
    300: ("Canvas App", "app"),
    380: ("PCF Control", "ui"),
    400: ("Custom Connector", "integration"),
    408: ("AI Builder Model", "ai"),
    430: ("Copilot Studio Agent", "agent"),
    431: ("Bot Component", "agent"),
    432: ("Bot Component Collection", "agent"),
    10066: ("Connection Reference", "integration"),
    10067: ("AI Builder Model", "ai"),
    10068: ("Dataflow", "data"),
}

_GROUP_LABELS: dict[str, tuple[str, str]] = {
    # group → (icon, tab label)
    "agent": ("🤖", "Agent"),
    "automation": ("⚡", "Cloud Flows"),
    "integration": ("🔗", "Connections"),
    "config": ("⚙️", "Environment Variables"),
    "data": ("🗃", "Data Components"),
    "app": ("📱", "Canvas Apps"),
    "ui": ("🖥", "UI Components"),
    "code": ("🔌", "Code Components"),
    "ai": ("🧠", "AI Components"),
    "security": ("🔒", "Security"),
    "reporting": ("📊", "Reporting"),
    "other": ("📦", "Other"),
}

# Maximum individual nodes before collapsing to a summary node
_MAX_INDIVIDUAL = 5


def _type_info(code: int) -> tuple[str, str]:
    return _COMP_TYPES.get(code, (f"Component ({code})", "other"))


def _safe_node_id(text: str, prefix: str = "N") -> str:
    """Return a globally-unique, Mermaid-safe node ID."""
    clean = re.sub(r"[^A-Za-z0-9_]", "_", text).strip("_")
    base = clean[:28] if clean else "X"
    return f"{prefix}_{base}"


# ── Internal data classes ─────────────────────────────────────────────────────


class _Component:
    __slots__ = ("type_code", "comp_id", "schema_name", "display_name")

    def __init__(self, type_code: int, comp_id: str, schema_name: str = "", display_name: str = "") -> None:
        self.type_code = type_code
        self.comp_id = comp_id
        self.schema_name = schema_name
        self.display_name = display_name

    @property
    def label(self) -> str:
        return self.display_name or self.schema_name or self.comp_id[:12] or "?"

    @property
    def stripped_id(self) -> str:
        return self.comp_id.strip("{}").lower()


class _MissingDep:
    __slots__ = ("req_type", "req_name", "req_schema", "dep_id")

    def __init__(self, req_type: int, req_name: str, req_schema: str, dep_id: str) -> None:
        self.req_type = req_type
        self.req_name = req_name or req_schema or "Unknown"
        self.req_schema = req_schema
        self.dep_id = dep_id.strip("{}")

    @property
    def dedup_key(self) -> str:
        return f"{self.req_type}:{(self.req_schema or self.req_name).lower()}"


# ── solution.xml parser ───────────────────────────────────────────────────────


def _parse_solution_xml(sol_path: Path) -> tuple[dict, list[_Component], list[_MissingDep]]:
    """Parse solution.xml. Returns (metadata_dict, components, missing_deps)."""
    metadata: dict = {
        "solution_name": "",
        "solution_display": "",
        "version": "1.0.0.0",
        "managed": False,
        "publisher": "",
    }
    components: list[_Component] = []
    missing: list[_MissingDep] = []

    try:
        root = ET.parse(sol_path).getroot()
    except Exception:
        return metadata, components, missing
    if root is None:
        return metadata, components, missing

    manifest = root.find("SolutionManifest")
    if manifest is None:
        return metadata, components, missing

    metadata["solution_name"] = manifest.findtext("UniqueName") or ""
    desc_node = manifest.find("Descriptions/Description")
    metadata["solution_display"] = (desc_node.get("description") or "") if desc_node is not None else ""
    if not metadata["solution_display"]:
        metadata["solution_display"] = metadata["solution_name"]

    metadata["version"] = manifest.findtext("Version") or "1.0.0.0"
    metadata["managed"] = (manifest.findtext("Managed") or "0") == "1"
    metadata["publisher"] = manifest.findtext("Publisher/UniqueName") or ""

    # Root components (the actual solution contents)
    rc_el = manifest.find("RootComponents")
    if rc_el is not None:
        for rc in rc_el.findall("RootComponent"):
            try:
                tc = int(rc.get("type") or "0")
            except ValueError:
                continue
            if tc == 0:
                continue
            components.append(
                _Component(
                    type_code=tc,
                    comp_id=rc.get("id") or "",
                    schema_name=rc.get("schemaName") or "",
                )
            )

    # Missing dependencies (required but not present in this ZIP)
    miss_el = manifest.find("MissingDependencies")
    if miss_el is not None:
        for md in miss_el.findall("MissingDependency"):
            req = md.find("Required")
            dep = md.find("Dependent")
            if req is None:
                continue
            try:
                rt = int(req.get("type") or "0")
            except ValueError:
                rt = 0
            rname = req.get("displayName") or req.get("parentDisplayName") or ""
            rschema = req.get("schemaName") or ""
            dep_id = (dep.get("id") or "") if dep is not None else ""
            missing.append(_MissingDep(rt, rname, rschema, dep_id))

    return metadata, components, missing


# ── Display-name enrichment from component files ──────────────────────────────


def _enrich_from_files(components: list[_Component], work_dir: Path) -> None:
    """Fill in missing display names from artefact files where possible."""
    by_schema: dict[str, _Component] = {c.schema_name.lower(): c for c in components if c.schema_name}

    def _set(comp: _Component, name: str) -> None:
        if name and not comp.display_name:
            comp.display_name = name.strip()

    # Bots → configuration.json
    bots_dir = work_dir / "bots"
    if bots_dir.is_dir():
        for bot_dir in bots_dir.iterdir():
            if not bot_dir.is_dir():
                continue
            cfg = bot_dir / "configuration.json"
            if cfg.exists():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
                    name = data.get("DisplayName") or data.get("displayName") or ""
                    schema = bot_dir.name.lower()
                    if schema in by_schema:
                        _set(by_schema[schema], name)
                    else:
                        for c in components:
                            if c.type_code == 430 and not c.display_name:
                                _set(c, name)
                                break
                except Exception:
                    pass

    # Botcomponents → botcomponent.xml
    botcomp_dir = work_dir / "botcomponents"
    if botcomp_dir.is_dir():
        for comp_dir in botcomp_dir.iterdir():
            if not comp_dir.is_dir():
                continue
            xml_path = comp_dir / "botcomponent.xml"
            if xml_path.exists():
                try:
                    xroot = ET.parse(xml_path).getroot()
                    if xroot is None:
                        continue
                    name = xroot.findtext("name") or xroot.findtext("displayname") or ""
                    schema = comp_dir.name.lower()
                    if schema in by_schema:
                        _set(by_schema[schema], name)
                except Exception:
                    pass

    # Connection references → folder name as label
    cr_dir = work_dir / "connectionreferences"
    if cr_dir.is_dir():
        for item in cr_dir.iterdir():
            if not item.is_dir():
                continue
            schema = item.name.lower()
            if schema in by_schema:
                _set(by_schema[schema], item.name)

    # Environment variable definitions → folder name
    ev_dir = work_dir / "environmentvariabledefinitions"
    if ev_dir.is_dir():
        for item in ev_dir.iterdir():
            if not item.is_dir():
                continue
            schema = item.name.lower()
            if schema in by_schema:
                _set(by_schema[schema], item.name)

    # Workflows → try JSON displayName
    wf_dir = work_dir / "Workflows"
    if wf_dir.is_dir():
        for wf_file in wf_dir.iterdir():
            if not wf_file.is_file():
                continue
            schema = wf_file.stem.lower()
            if schema in by_schema:
                try:
                    data = json.loads(wf_file.read_text(encoding="utf-8", errors="replace"))
                    name = (data.get("properties") or {}).get("displayName") or data.get("name") or ""
                    _set(by_schema[schema], name)
                except Exception:
                    pass


# ── Mermaid helpers ───────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Sanitise a string for use inside a Mermaid double-quoted label."""
    if not text:
        return ""
    return text.replace('"', "'").replace("\n", " ").replace("\r", "").strip()[:60]


def _node(nid: str, label: str, shape: str = "rect") -> str:
    """Return a Mermaid node definition line (indented 4 spaces)."""
    esc_label = _esc(label)
    if shape == "stadium":
        return f'    {nid}(["{esc_label}"])'
    if shape == "diamond":
        return f'    {nid}{{"{esc_label}"}}'
    return f'    {nid}["{esc_label}"]'


# ── Mermaid diagram builder ───────────────────────────────────────────────────


def _build_mermaid(
    metadata: dict,
    components: list[_Component],
    missing: list[_MissingDep],
) -> str:
    lines: list[str] = ["flowchart TD"]

    # ── Classify components ────────────────────────────────────────────────────
    agents = [c for c in components if c.type_code == 430]
    bot_comps = [c for c in components if c.type_code in (431, 432)]
    flows = [c for c in components if c.type_code == 30]
    conn_refs = [c for c in components if c.type_code in (10066, 400)]
    env_vars = [c for c in components if c.type_code == 44]
    canvas_apps = [c for c in components if c.type_code in (29, 300)]
    tables = [c for c in components if c.type_code == 1]
    known_types = {430, 431, 432, 30, 10066, 400, 44, 29, 300, 1}
    others = [c for c in components if c.type_code not in known_types]

    sol_label = _esc(metadata.get("solution_display") or metadata.get("solution_name") or "Solution")
    sol_version = _esc(metadata.get("version") or "")
    managed_str = "Managed" if metadata.get("managed") else "Unmanaged"

    # Map comp stripped_id → mermaid node ID (for missing dep edge lookup)
    id_to_nid: dict[str, str] = {}

    # ── Solution subgraph ──────────────────────────────────────────────────────
    lines.append(f'    subgraph SOL["{sol_label}  ·  v{sol_version}  ({managed_str})"]')

    # Agent node(s)
    agent_nids: list[str] = []
    for i, ag in enumerate(agents):
        nid = f"AGT{i}"
        agent_nids.append(nid)
        if ag.stripped_id:
            id_to_nid[ag.stripped_id] = nid
        lbl = f"🤖 {_esc(ag.label)}"
        lines.append(f'        {nid}["{lbl}"]')

    # Bot components collapsed into one summary node
    bc_nid: str | None = None
    if bot_comps:
        bc_nid = "BCTOPICS"
        cnt = len(bot_comps)
        lines.append(f'        {bc_nid}["💬 {cnt} Bot Component{"s" if cnt != 1 else ""}"]')

    # Cloud flows — show individually up to _MAX_INDIVIDUAL, else summarise
    flow_nids: list[str] = []
    if flows:
        if len(flows) <= _MAX_INDIVIDUAL:
            for i, f in enumerate(flows):
                nid = f"FLW{i}"
                flow_nids.append(nid)
                if f.stripped_id:
                    id_to_nid[f.stripped_id] = nid
                lbl = f"⚡ {_esc(f.label)}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "FLWS"
            flow_nids.append(nid)
            for f in flows:
                if f.stripped_id:
                    id_to_nid[f.stripped_id] = nid
            lines.append(f'        {nid}["⚡ {len(flows)} Cloud Flows"]')

    # Connection references
    cr_nids: list[str] = []
    if conn_refs:
        if len(conn_refs) <= _MAX_INDIVIDUAL:
            for i, cr in enumerate(conn_refs):
                nid = f"CR{i}"
                cr_nids.append(nid)
                if cr.stripped_id:
                    id_to_nid[cr.stripped_id] = nid
                lbl = f"🔗 {_esc(cr.label)}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "CRS"
            cr_nids.append(nid)
            for cr in conn_refs:
                if cr.stripped_id:
                    id_to_nid[cr.stripped_id] = nid
            lines.append(f'        {nid}["🔗 {len(conn_refs)} Connection References"]')

    # Environment variables
    ev_nids: list[str] = []
    if env_vars:
        if len(env_vars) <= _MAX_INDIVIDUAL:
            for i, ev in enumerate(env_vars):
                nid = f"EV{i}"
                ev_nids.append(nid)
                if ev.stripped_id:
                    id_to_nid[ev.stripped_id] = nid
                lbl = f"⚙️ {_esc(ev.label)}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "EVS"
            ev_nids.append(nid)
            lines.append(f'        {nid}["⚙️ {len(env_vars)} Environment Variables"]')

    # Canvas apps
    ca_nids: list[str] = []
    if canvas_apps:
        if len(canvas_apps) <= _MAX_INDIVIDUAL:
            for i, ca in enumerate(canvas_apps):
                nid = f"CA{i}"
                ca_nids.append(nid)
                if ca.stripped_id:
                    id_to_nid[ca.stripped_id] = nid
                lbl = f"📱 {_esc(ca.label)}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "CAS"
            ca_nids.append(nid)
            lines.append(f'        {nid}["📱 {len(canvas_apps)} Canvas Apps"]')

    # Tables
    tbl_nids: list[str] = []
    if tables:
        if len(tables) <= _MAX_INDIVIDUAL:
            for i, t in enumerate(tables):
                nid = f"TBL{i}"
                tbl_nids.append(nid)
                if t.stripped_id:
                    id_to_nid[t.stripped_id] = nid
                lbl = f"🗃 {_esc(t.label)}"
                lines.append(f'        {nid}["{lbl}"]')
        else:
            nid = "TBLS"
            tbl_nids.append(nid)
            lines.append(f'        {nid}["🗃 {len(tables)} Tables"]')

    # All other component types — one summary node per type group
    if others:
        type_buckets: dict[int, list[_Component]] = defaultdict(list)
        for o in others:
            type_buckets[o.type_code].append(o)
        for ti, (tc, items) in enumerate(sorted(type_buckets.items())):
            type_name, _ = _type_info(tc)
            nid = f"OTH{ti}"
            if len(items) == 1:
                lbl = f"📦 {_esc(items[0].label)} ({type_name})"
            else:
                lbl = f"📦 {len(items)} {type_name}s"
            lines.append(f'        {nid}["{lbl}"]')

    lines.append("    end")  # close SOL subgraph

    # ── Missing dependencies subgraph ──────────────────────────────────────────
    seen_keys: set[str] = set()
    deduped: list[_MissingDep] = []
    for m in missing:
        if m.dedup_key not in seen_keys:
            seen_keys.add(m.dedup_key)
            deduped.append(m)

    miss_key_to_nid: dict[str, str] = {}
    if deduped:
        lines.append('    subgraph MISS["⚠️ Missing Dependencies  (must be installed in target env)"]')
        for i, m in enumerate(deduped):
            nid = f"MDEP{i}"
            miss_key_to_nid[m.dedup_key] = nid
            type_name, _ = _type_info(m.req_type)
            lbl = f"❌ {_esc(m.req_name or m.req_schema)}  ({type_name})"
            lines.append(f'        {nid}["{lbl}"]')
        lines.append("    end")

    # ── Edges ──────────────────────────────────────────────────────────────────
    for aid in agent_nids:
        if bc_nid:
            lines.append(f"    {aid} --> {bc_nid}")
        for fid in flow_nids:
            lines.append(f"    {aid} --> {fid}")
        for evid in ev_nids:
            lines.append(f"    {aid} --> {evid}")
        for caid in ca_nids:
            lines.append(f"    {aid} --> {caid}")

    # Flows → connection references
    for fid in flow_nids:
        for crid in cr_nids:
            lines.append(f"    {fid} --> {crid}")

    # Missing dep edges: dep_id → required missing component
    for m in deduped:
        mnid = miss_key_to_nid.get(m.dedup_key)
        if not mnid:
            continue
        dep_id_clean = m.dep_id.lower()
        source = id_to_nid.get(dep_id_clean)
        if source is None and agent_nids:
            source = agent_nids[0]  # fall back to first agent node
        if source:
            lines.append(f"    {source} -.->|missing| {mnid}")

    # ── Node styles ────────────────────────────────────────────────────────────
    for i in range(len(agents)):
        lines.append(f"    style AGT{i} fill:#0078d4,color:white,stroke:#005a9e,stroke-width:2px")
    if bc_nid:
        lines.append(f"    style {bc_nid} fill:#deecf9,color:#201f1e,stroke:#0078d4")
    if len(flows) <= _MAX_INDIVIDUAL:
        for i in range(len(flows)):
            lines.append(f"    style FLW{i} fill:#e8f4e8,color:#0a5c0a,stroke:#107c10")
    elif flows:
        lines.append("    style FLWS fill:#e8f4e8,color:#0a5c0a,stroke:#107c10")
    if len(conn_refs) <= _MAX_INDIVIDUAL:
        for i in range(len(conn_refs)):
            lines.append(f"    style CR{i} fill:#f3e5f5,color:#4a108a,stroke:#8764b8")
    elif conn_refs:
        lines.append("    style CRS fill:#f3e5f5,color:#4a108a,stroke:#8764b8")
    if len(env_vars) <= _MAX_INDIVIDUAL:
        for i in range(len(env_vars)):
            lines.append(f"    style EV{i} fill:#fff4ce,color:#4d3800,stroke:#d29200")
    elif env_vars:
        lines.append("    style EVS fill:#fff4ce,color:#4d3800,stroke:#d29200")
    if len(canvas_apps) <= _MAX_INDIVIDUAL:
        for i in range(len(canvas_apps)):
            lines.append(f"    style CA{i} fill:#fce8e8,color:#601010,stroke:#d13438")
    elif canvas_apps:
        lines.append("    style CAS fill:#fce8e8,color:#601010,stroke:#d13438")
    for nid in miss_key_to_nid.values():
        lines.append(f"    style {nid} fill:#fde7e9,color:#a4262c,stroke:#a4262c,stroke-dasharray:5 5")

    return "\n".join(lines)


# ── Markdown summary builder ──────────────────────────────────────────────────


def _build_summary_md(
    metadata: dict,
    components: list[_Component],
    missing: list[_MissingDep],
) -> str:
    sol_name = metadata.get("solution_display") or metadata.get("solution_name") or "Unknown"
    version = metadata.get("version") or "1.0.0.0"
    managed = "**Managed** ✔" if metadata.get("managed") else "Unmanaged"
    publisher = metadata.get("publisher") or "—"

    # De-duplicate missing deps
    seen: set[str] = set()
    unique_missing: list[_MissingDep] = []
    for m in missing:
        if m.dedup_key not in seen:
            seen.add(m.dedup_key)
            unique_missing.append(m)

    # Tally by type
    type_counts: dict[int, int] = defaultdict(int)
    for c in components:
        type_counts[c.type_code] += 1

    lines: list[str] = [
        f"## Solution: {sol_name}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Version | `{version}` |",
        f"| State | {managed} |",
        f"| Publisher | `{publisher}` |",
        f"| Total Components | **{len(components)}** |",
        f"| Missing Dependencies | **{len(unique_missing)}** |",
        "",
        "### Component Breakdown",
        "",
        "| Type | Count |",
        "|---|---|",
    ]

    for tc, cnt in sorted(type_counts.items(), key=lambda x: (-x[1], x[0])):
        type_name, _ = _type_info(tc)
        lines.append(f"| {type_name} | {cnt} |")

    if unique_missing:
        lines += [
            "",
            "### Missing Dependencies",
            "",
            "> ⚠️ These components are **required** by this solution but are **not included** in the "
            "ZIP. They must be present in the target environment before import will succeed.",
            "",
            "| Required Component | Type | Dep ID (first 8 chars) |",
            "|---|---|---|",
        ]
        for m in unique_missing:
            type_name, _ = _type_info(m.req_type)
            dep_ref = f"`{m.dep_id[:8]}…`" if m.dep_id else "—"
            lines.append(f"| `{m.req_name or m.req_schema}` | {type_name} | {dep_ref} |")
    else:
        lines += [
            "",
            "> ✅ **No missing dependencies detected** — all required components appear to be "
            "included in this solution or have no external dependencies.",
        ]

    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────


def analyze_deps_zip_bytes(zip_bytes: bytes) -> list[dict]:
    """Analyze a Power Platform solution ZIP and return dependency segments.

    Returns a list of render segments compatible with ``viz_segments``:
    ``[{"type": "text", "content": markdown}, {"type": "mermaid", "content": mermaid}]``

    Raises ``ValueError`` for clearly invalid input (not a ZIP, no solution.xml).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                safe_extractall(zf, work_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError("Uploaded file is not a valid ZIP archive.") from exc

        sol_path = work_dir / "solution.xml"
        if not sol_path.exists():
            raise ValueError("No solution.xml found — this does not appear to be a Power Platform solution export.")

        metadata, components, missing = _parse_solution_xml(sol_path)
        _enrich_from_files(components, work_dir)

        if not components:
            raise ValueError(
                "solution.xml contains no RootComponents — the solution may be empty "
                "or the XML format is not recognised."
            )

        summary_md = _build_summary_md(metadata, components, missing)
        mermaid = _build_mermaid(metadata, components, missing)

        return [
            {"type": "text", "content": summary_md},
            {"type": "mermaid", "content": mermaid},
        ]

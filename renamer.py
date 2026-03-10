"""Core renaming logic for Power Platform agent solution exports.

Handles:
- Detecting the current bot schema name, solution name, and display names
- Replacing all references to the old names in file contents
- Renaming bot and botcomponent folders
- Packaging the result back to a ZIP file
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import defusedxml.ElementTree as ET
from loguru import logger

from models import RenameConfig, RenameResult, SolutionInfo

# ── Text file extensions to process (binary files are skipped) ─────────────
TEXT_EXTENSIONS = {".xml", ".json", ".yaml", ".yml", ".txt", ".md", ""}
# "" covers extensionless files like the 'data' botcomponent dialog files
EXTENSIONLESS_NAMES = {"data"}  # only rename known extensionless text files


# ── Name helpers ─────────────────────────────────────────────────────────────


def sanitize_schema_name(display_name: str) -> str:
    """Convert a display name to a valid Power Platform schema name component.

    Rules:
        - lowercase only
        - non-alphanumeric sequences replaced with single underscore
        - leading/trailing underscores stripped
        - max 50 characters (leave room for prefix)
    """
    sanitized = re.sub(r"[^a-z0-9]+", "_", display_name.lower())
    return sanitized.strip("_")[:50]


def derive_solution_unique_name(display_name: str) -> str:
    """Derive a valid Power Platform solution unique name from a display name.

    Converts to PascalCase stripping special characters.
    Example: "My New Bot (Copy)" -> "MyNewBotCopy"
    """
    words = re.sub(r"[^a-zA-Z0-9\s]", "", display_name).split()
    if not words:
        return ""
    result = "".join(w.capitalize() for w in words)
    # Ensure starts with a letter (PP requirement)
    if result and not result[0].isalpha():
        result = "S" + result
    return result[:100]


def derive_schema_name(old_schema: str, new_agent_name: str) -> str:
    """Derive a new bot schema name from the old one, preserving the prefix.

    Power Platform bot schema names typically follow the pattern::

        copilots_{publisher_prefix}_{logical_name}

    We extract everything up to and including the second underscore-separated
    element as the prefix (e.g. ``copilots_new_``) and append the sanitized
    new logical name.
    """
    parts = old_schema.split("_")
    # Take first two parts as prefix: e.g. ["copilots", "new"] -> "copilots_new_"
    if len(parts) >= 2:
        prefix = "_".join(parts[:2]) + "_"
    else:
        prefix = parts[0] + "_"
    return prefix + sanitize_schema_name(new_agent_name)


# ── ZIP utilities ───────────────────────────────────────────────────────────


def safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a ZIP, rejecting any entries that would escape *dest* via path traversal."""
    dest_resolved = dest.resolve()
    for info in zf.infolist():
        target = (dest_resolved / info.filename).resolve()
        if not target.is_relative_to(dest_resolved):
            raise ValueError(f"Rejected unsafe ZIP entry: {info.filename!r}")
    zf.extractall(dest)


# ── Solution inspection ───────────────────────────────────────────────────────


def inspect_solution(solution_dir: Path) -> SolutionInfo:
    """Auto-detect all relevant names from an extracted solution folder."""

    # --- Bot schema name from bots/ directory ---
    bots_dir = solution_dir / "bots"
    if not bots_dir.exists():
        raise ValueError("No 'bots/' directory found -- is this a valid solution export?")
    bot_folders = [d for d in bots_dir.iterdir() if d.is_dir()]
    if not bot_folders:
        raise ValueError("No bot folder found inside 'bots/'.")
    if len(bot_folders) > 1:
        logger.warning(
            f"Multiple bot folders found; using '{bot_folders[0].name}'. Others: {[d.name for d in bot_folders[1:]]}"
        )
    old_bot_schema = bot_folders[0].name

    # --- Bot display name from bot.xml ---
    bot_xml_path = bots_dir / old_bot_schema / "bot.xml"
    bot_display_name = old_bot_schema  # fallback
    if bot_xml_path.exists():
        try:
            tree = ET.parse(str(bot_xml_path))
            el = tree.getroot().find(".//name")
            if el is not None and el.text:
                bot_display_name = el.text.strip()
        except ET.ParseError as exc:
            logger.warning(f"Could not parse bot.xml: {exc}")

    # --- Solution unique name and display name from solution.xml ---
    solution_xml_path = solution_dir / "solution.xml"
    if not solution_xml_path.exists():
        raise ValueError("No 'solution.xml' found -- is this a valid solution export?")
    try:
        tree = ET.parse(str(solution_xml_path))
        root = tree.getroot()
        # Handle optional namespace
        unique_el = root.find(".//{*}UniqueName") or root.find(".//UniqueName")
        if unique_el is None or not unique_el.text:
            raise ValueError("Could not find <UniqueName> in solution.xml.")
        solution_unique_name = unique_el.text.strip()

        disp_el = root.find(".//{*}LocalizedName[@languagecode='1033']") or root.find(
            ".//LocalizedName[@languagecode='1033']"
        )
        solution_display_name = (
            disp_el.get("description", solution_unique_name) if disp_el is not None else solution_unique_name
        )
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse solution.xml: {exc}") from exc

    # --- Botcomponent folder list ---
    bc_dir = solution_dir / "botcomponents"
    bc_folders = []
    if bc_dir.exists():
        bc_folders = [d.name for d in bc_dir.iterdir() if d.is_dir() and d.name.startswith(old_bot_schema)]

    return SolutionInfo(
        bot_schema_name=old_bot_schema,
        bot_display_name=bot_display_name,
        solution_unique_name=solution_unique_name,
        solution_display_name=solution_display_name,
        botcomponent_folders=bc_folders,
    )


def inspect_zip(zip_path: Path) -> SolutionInfo:
    """Inspect a solution ZIP without fully extracting it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / "src"
        tmp.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            safe_extractall(zf, tmp)
        return inspect_solution(tmp)


# ── Content replacement ───────────────────────────────────────────────────────


def _is_text_file(path: Path) -> bool:
    """Return True if the file should be treated as text."""
    if path.suffix.lower() in TEXT_EXTENSIONS:
        if path.suffix == "":  # extensionless -- only known names
            return path.name in EXTENSIONLESS_NAMES
        return True
    return False


def _replace_content(
    work_dir: Path,
    replacements: list[tuple[str, str]],
) -> int:
    """Walk all text files under *work_dir* and apply string replacements.

    Returns the number of files that were modified.
    """
    modified = 0
    for file_path in sorted(work_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if not _is_text_file(file_path):
            continue
        try:
            raw = file_path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.debug(f"Skipping {file_path.name}: {exc}")
            continue

        original = text
        for old, new in replacements:
            text = text.replace(old, new)

        if text != original:
            file_path.write_text(text, encoding="utf-8")
            modified += 1
            logger.debug(f"Updated: {file_path.relative_to(work_dir)}")

    return modified


# ── XML-level attribute updates ───────────────────────────────────────────────


def _update_solution_xml(
    solution_xml_path: Path,
    old_unique_name: str,
    new_unique_name: str,
    old_display_name: str,
    new_display_name: str,
) -> None:
    """Update UniqueName and LocalizedName in solution.xml using XML parsing."""
    tree = ET.parse(str(solution_xml_path))
    root = tree.getroot()

    for tag in ("UniqueName", "{*}UniqueName"):
        el = root.find(f".//{tag}")
        if el is not None and el.text and el.text.strip() == old_unique_name:
            el.text = new_unique_name

    for el in root.iter():
        tag_local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag_local == "LocalizedName" and el.get("description") == old_display_name:
            el.set("description", new_display_name)

    # Preserve XML declaration and write back
    ET.indent(tree, space="  ")
    tree.write(str(solution_xml_path), encoding="unicode", xml_declaration=False)


def _update_bot_xml_name(bot_xml_path: Path, new_display_name: str) -> None:
    """Update the <name> element in bot.xml."""
    if not bot_xml_path.exists():
        return
    try:
        tree = ET.parse(str(bot_xml_path))
        el = tree.getroot().find(".//name")
        if el is not None:
            el.text = new_display_name
        ET.indent(tree, space="  ")
        tree.write(str(bot_xml_path), encoding="unicode", xml_declaration=False)
    except ET.ParseError as exc:
        logger.warning(f"Could not update bot.xml display name: {exc}")


# ── Folder renaming ───────────────────────────────────────────────────────────


def _rename_folders(
    work_dir: Path,
    old_bot_schema: str,
    new_bot_schema: str,
) -> int:
    """Rename the bot folder and all prefixed botcomponent folders.

    Returns the number of directories renamed.
    """
    renamed = 0

    # Rename bots/{old_schema}/ -> bots/{new_schema}/
    old_bot_dir = work_dir / "bots" / old_bot_schema
    new_bot_dir = work_dir / "bots" / new_bot_schema
    if old_bot_dir.exists() and old_bot_dir != new_bot_dir:
        old_bot_dir.rename(new_bot_dir)
        renamed += 1
        logger.debug(f"Renamed folder: bots/{old_bot_schema} -> bots/{new_bot_schema}")

    # Rename botcomponents/{old_schema}*/ -> botcomponents/{new_schema}*/
    bc_dir = work_dir / "botcomponents"
    if bc_dir.exists():
        # Collect first so we're not iterating while renaming
        to_rename = [d for d in bc_dir.iterdir() if d.is_dir() and d.name.startswith(old_bot_schema)]
        for old_dir in sorted(to_rename):
            suffix = old_dir.name[len(old_bot_schema) :]
            new_name = new_bot_schema + suffix
            new_dir = bc_dir / new_name
            old_dir.rename(new_dir)
            renamed += 1
            logger.debug(f"Renamed: botcomponents/{old_dir.name} -> botcomponents/{new_name}")

    return renamed


# ── Main entry point ──────────────────────────────────────────────────────────


def rename_solution(config: RenameConfig) -> RenameResult:
    """Process a Power Platform solution ZIP/folder and produce a renamed copy.

    Steps
    -----
    1. Extract ZIP (or use the folder directly).
    2. Detect current names (bot schema, solution name, display names).
    3. Derive/validate the new bot schema name.
    4. Replace all textual references to old names in file contents.
    5. Update XML display names in solution.xml and bot.xml.
    6. Rename bot and botcomponent folders.
    7. Package everything back to an output ZIP.

    Returns a :class:`RenameResult` with statistics and the output path.
    """
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ── 1. Extract or reference source ──────────────────────────────────
        if config.source_path.suffix.lower() == ".zip":
            src_dir = tmp / "src"
            src_dir.mkdir()
            with zipfile.ZipFile(config.source_path) as zf:
                safe_extractall(zf, src_dir)
            logger.info(f"Extracted ZIP: {config.source_path.name}")
        else:
            src_dir = config.source_path
            logger.info(f"Using folder: {src_dir}")

        # ── 2. Detect current names ──────────────────────────────────────────
        info = inspect_solution(src_dir)

        # Apply user-provided overrides for current names when supplied.
        if config.old_agent_name_override:
            info = info.model_copy(update={"bot_display_name": config.old_agent_name_override})
        if config.old_solution_name_override:
            info = info.model_copy(update={"solution_unique_name": config.old_solution_name_override})

        logger.info(
            f"Detected -> bot schema: '{info.bot_schema_name}', "
            f"solution: '{info.solution_unique_name}', "
            f"display: '{info.bot_display_name}'"
        )

        # ── 3. Derive new bot schema name ────────────────────────────────────
        new_bot_schema = config.new_bot_schema_name or derive_schema_name(info.bot_schema_name, config.new_agent_name)
        logger.info(f"New bot schema: '{new_bot_schema}'")

        if new_bot_schema == info.bot_schema_name:
            warnings.append(
                "The derived new bot schema name is identical to the original. "
                "Consider providing a more distinct agent name."
            )

        # ── 4. Copy source to working directory ──────────────────────────────
        work_dir = tmp / "work"
        shutil.copytree(src_dir, work_dir, symlinks=False)

        # ── 5. Replace textual content ───────────────────────────────────────
        # Order matters: replace more-specific patterns first
        content_replacements: list[tuple[str, str]] = []

        if info.bot_schema_name != new_bot_schema:
            content_replacements.append((info.bot_schema_name, new_bot_schema))

        if info.solution_unique_name != config.new_solution_name:
            content_replacements.append((info.solution_unique_name, config.new_solution_name))

        files_modified = _replace_content(work_dir, content_replacements)
        logger.info(f"Modified content in {files_modified} files")

        # ── 6. Update display names via XML parsing ──────────────────────────
        # solution.xml -- unique name and display name
        _update_solution_xml(
            solution_xml_path=work_dir / "solution.xml",
            old_unique_name=info.solution_unique_name,
            new_unique_name=config.new_solution_name,
            old_display_name=info.solution_display_name,
            new_display_name=config.new_solution_display_name or config.new_agent_name,
        )

        # bot.xml -- display name (schema name already replaced in step 5)
        _update_bot_xml_name(
            bot_xml_path=work_dir / "bots" / info.bot_schema_name / "bot.xml",
            new_display_name=config.new_agent_name,
        )

        # gpt.default botcomponent -- update agent display name there too
        gpt_xml = work_dir / "botcomponents" / f"{info.bot_schema_name}.gpt.default" / "botcomponent.xml"
        if gpt_xml.exists():
            try:
                tree = ET.parse(str(gpt_xml))
                el = tree.getroot().find(".//name")
                if el is not None:
                    el.text = config.new_agent_name
                ET.indent(tree, space="  ")
                tree.write(str(gpt_xml), encoding="unicode", xml_declaration=False)
            except ET.ParseError as exc:
                logger.warning(f"Could not update gpt.default name: {exc}")

        # ── 7. Rename folders ────────────────────────────────────────────────
        folders_renamed = _rename_folders(work_dir, info.bot_schema_name, new_bot_schema)
        logger.info(f"Renamed {folders_renamed} folders")

        # ── 8. Package to output ZIP ─────────────────────────────────────────
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(config.output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            all_files = sorted(f for f in work_dir.rglob("*") if f.is_file())
            # Write [Content_Types].xml last: macOS Archive Utility treats a ZIP
            # as a broken OOXML package and rejects it when [Content_Types].xml
            # with the OPC namespace is the first entry.
            ct_files = [f for f in all_files if f.name == "[Content_Types].xml"]
            other_files = [f for f in all_files if f.name != "[Content_Types].xml"]
            for f in other_files + ct_files:
                zf.write(f, f.relative_to(work_dir))
        logger.info(f"Output ZIP: {config.output_path}")

        return RenameResult(
            old_bot_schema=info.bot_schema_name,
            new_bot_schema=new_bot_schema,
            old_solution_name=info.solution_unique_name,
            new_solution_name=config.new_solution_name,
            old_agent_name=info.bot_display_name,
            new_agent_name=config.new_agent_name,
            files_modified=files_modified,
            folders_renamed=folders_renamed,
            output_path=config.output_path,
            warnings=warnings,
        )


def rename_solution_from_bytes(
    zip_bytes: bytes,
    new_agent_name: str,
    new_solution_name: str,
    new_bot_schema_name: str | None = None,
    old_agent_name_override: str | None = None,
    old_solution_name_override: str | None = None,
    new_solution_display_name: str | None = None,
) -> tuple[bytes, RenameResult]:
    """Convenience wrapper that accepts and returns raw ZIP bytes.

    Used by the web UI state to process in-memory uploads.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_zip = tmp / "input.zip"
        input_zip.write_bytes(zip_bytes)
        output_zip = tmp / "output.zip"

        config = RenameConfig(
            source_path=input_zip,
            new_agent_name=new_agent_name,
            new_solution_name=new_solution_name,
            new_bot_schema_name=new_bot_schema_name,
            output_path=output_zip,
            old_agent_name_override=old_agent_name_override,
            old_solution_name_override=old_solution_name_override,
            new_solution_display_name=new_solution_display_name,
        )
        result = rename_solution(config)
        return output_zip.read_bytes(), result

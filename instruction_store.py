"""Instruction versioning store — tracks instruction changes across bot uploads."""

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from models import BotProfile, InstructionDiff, InstructionSnapshot

_DATA_DIR = Path(__file__).resolve().parent / "data"
_VERSIONS_FILE = _DATA_DIR / "instruction_versions.json"


def _atomic_write(filepath: Path, content: str) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp = filepath.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(filepath)
    except OSError as e:
        logger.error(f"Failed to write {filepath}: {e}")


def _load_versions() -> dict[str, list[dict]]:
    try:
        if _VERSIONS_FILE.exists():
            data = json.loads(_VERSIONS_FILE.read_text(encoding="utf-8"))
            return data.get("versions", {})
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load instruction versions: {e}")
    return {}


def _save_versions(versions: dict[str, list[dict]]) -> None:
    _atomic_write(_VERSIONS_FILE, json.dumps({"versions": versions}, indent=2))


def _hash_text(text: str | None) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode()).hexdigest()


def _diff_snapshots(a: InstructionSnapshot, b: InstructionSnapshot) -> InstructionDiff:
    instructions_changed = a.instructions_hash != b.instructions_hash
    description_changed = (a.gpt_description or "") != (b.gpt_description or "")

    unified_diff = ""
    change_ratio = 0.0

    if instructions_changed:
        old_lines = (a.instructions or "").splitlines(keepends=True)
        new_lines = (b.instructions or "").splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(old_lines, new_lines, fromfile="previous", tofile="current", lineterm="")
        )
        unified_diff = "\n".join(diff_lines)
        matcher = difflib.SequenceMatcher(None, a.instructions or "", b.instructions or "")
        change_ratio = round(1.0 - matcher.ratio(), 4)

    return InstructionDiff(
        bot_identity=b.bot_identity,
        from_timestamp=a.timestamp,
        to_timestamp=b.timestamp,
        instructions_changed=instructions_changed,
        description_changed=description_changed,
        unified_diff=unified_diff,
        change_ratio=change_ratio,
        is_significant=change_ratio > 0.2,
    )


def save_snapshot(profile: BotProfile) -> InstructionDiff | None:
    identity = profile.bot_id if profile.bot_id else profile.schema_name
    if not identity:
        return None

    instructions = profile.gpt_info.instructions if profile.gpt_info else None
    gpt_description = profile.gpt_info.description if profile.gpt_info else None

    snapshot = InstructionSnapshot(
        bot_identity=identity,
        bot_name=profile.display_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        instructions=instructions,
        instructions_hash=_hash_text(instructions),
        gpt_description=gpt_description,
    )

    versions = _load_versions()
    history = versions.get(identity, [])

    diff: InstructionDiff | None = None
    if history:
        previous = InstructionSnapshot.model_validate(history[-1])
        if previous.instructions_hash == snapshot.instructions_hash and (previous.gpt_description or "") == (
            snapshot.gpt_description or ""
        ):
            return None
        diff = _diff_snapshots(previous, snapshot)

    history.append(snapshot.model_dump())
    versions[identity] = history
    _save_versions(versions)
    logger.info(f"Saved instruction snapshot for {identity} ({profile.display_name})")

    return diff


def get_history(bot_identity: str) -> list[InstructionSnapshot]:
    versions = _load_versions()
    history = versions.get(bot_identity, [])
    return [InstructionSnapshot.model_validate(entry) for entry in history]

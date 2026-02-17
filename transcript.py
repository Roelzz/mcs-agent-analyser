from datetime import datetime, timezone
from pathlib import Path
import json

from loguru import logger


def parse_transcript_json(path: Path) -> tuple[list[dict], dict]:
    """Parse transcript JSON, normalize activities, return (activities, metadata).

    Normalization:
    1. Convert from.role from 0/1 to "bot"/"user"
    2. Convert timestamp from epoch seconds to ISO string
    3. Assign synthetic channelData position based on array index
    4. Set valueType from name field when valueType is missing
    5. Extract metadata from SessionInfo/ConversationInfo trace events
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_activities: list[dict] = raw.get("activities", [])

    metadata: dict = {}
    normalized: list[dict] = []

    for idx, activity in enumerate(raw_activities):
        # 1. Normalize role
        from_info = activity.get("from", {}) or {}
        role_raw = from_info.get("role")
        if role_raw == 0:
            from_info["role"] = "bot"
        elif role_raw == 1:
            from_info["role"] = "user"
        activity["from"] = from_info

        # 2. Convert epoch seconds to ISO string
        ts = activity.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                activity["timestamp"] = dt.isoformat()
            except (ValueError, OSError):
                pass

        # 3. Synthetic position
        channel_data = activity.get("channelData") or {}
        if "webchat:internal:position" not in channel_data:
            channel_data["webchat:internal:position"] = idx * 1000
            activity["channelData"] = channel_data

        # 4. Set valueType from name when missing
        value_type = activity.get("valueType", "")
        name = activity.get("name", "")
        if not value_type and name:
            activity["valueType"] = name

        # 5. Extract metadata from SessionInfo / ConversationInfo
        value_type = activity.get("valueType", "")
        value = activity.get("value", {}) or {}

        if value_type == "SessionInfo":
            metadata["session_info"] = value
            logger.debug(f"SessionInfo: outcome={value.get('outcome')}, turns={value.get('turnCount')}")

        if value_type == "ConversationInfo":
            metadata["conversation_info"] = value

        normalized.append(activity)

    logger.info(f"Transcript: {len(normalized)} activities from {path.name}")
    return normalized, metadata

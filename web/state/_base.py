import os
import re
import sys
import time
from pathlib import Path

import httpx
import reflex as rx
from dotenv import load_dotenv
from loguru import logger

# Ensure project root is importable (Reflex runs from project root)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

load_dotenv()

# --- Community counter (komarev badge) ---

_KOMAREV_URL = "https://komarev.com/ghpvc/?username=Roelzz&label=Community%20Views&color=0e75b6&style=flat"

_community_count_cache: dict[str, float | int] = {"count": 0, "fetched_at": 0.0}


def _fetch_community_count() -> int:
    """Fetch community view count from komarev badge SVG (cached 30s)."""
    now = time.time()
    if now - _community_count_cache["fetched_at"] < 30:
        return int(_community_count_cache["count"])
    try:
        resp = httpx.get(_KOMAREV_URL, headers={"User-Agent": "AgentAnalyser/1.0"}, timeout=5)
        svg = resp.text
        numbers = re.findall(r">(\d+)</", svg)
        if numbers:
            count = int(numbers[-1])
            _community_count_cache["count"] = count
            _community_count_cache["fetched_at"] = now
            return count
    except Exception as e:
        logger.warning(f"Failed to fetch community count: {e}")
    return int(_community_count_cache["count"])


_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_BOT_PROFILE_FILE = _DATA_DIR / "bot_profile.json"


def _save_bot_profile(json_str: str) -> None:
    _BOT_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _BOT_PROFILE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json_str)
        tmp.replace(_BOT_PROFILE_FILE)
    except OSError as e:
        logger.error(f"Failed to save bot profile: {e}")


def _load_bot_profile() -> str:
    try:
        if _BOT_PROFILE_FILE.exists():
            return _BOT_PROFILE_FILE.read_text()
    except OSError as e:
        logger.warning(f"Failed to load bot profile: {e}")
    return ""


def _clear_bot_profile() -> None:
    try:
        _BOT_PROFILE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _load_users() -> dict[str, str]:
    """Parse USERS env var into username:password dict.

    Format: "admin:pass1,analyst:pass2"
    """
    raw = os.getenv("USERS", "")
    if not raw.strip():
        return {}
    users: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            username, password = pair.split(":", 1)
            username = username.strip()
            password = password.strip()
            if username:
                users[username] = password
    return users


# Import mixins — must be after helpers are defined since mixins import from this module
from web.state._auth import AuthMixin  # noqa: E402
from web.state._upload import UploadMixin  # noqa: E402
from web.state._report import ReportMixin  # noqa: E402
from web.state._lint import LintMixin  # noqa: E402
from web.state._counter import CounterMixin  # noqa: E402
from web.state._dataverse import DataverseMixin  # noqa: E402
from web.state._solution import SolutionMixin  # noqa: E402
from web.state._rules import RulesMixin  # noqa: E402
from web.state._compare import ComparisonMixin  # noqa: E402
from web.state._batch import BatchMixin  # noqa: E402
from web.state._dynamic import DynamicMixin  # noqa: E402


class State(
    AuthMixin,
    UploadMixin,
    ReportMixin,
    LintMixin,
    CounterMixin,
    DataverseMixin,
    SolutionMixin,
    RulesMixin,
    ComparisonMixin,
    BatchMixin,
    DynamicMixin,
    rx.State,
):
    """Combined auth, upload, and report state."""

    pass

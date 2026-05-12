from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class LinkStatus:
    url: str
    ok: bool
    status_code: int | None
    error: str | None
    checked_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _do_request(url: str, method: str, timeout: float, extra_headers: dict[str, str] | None = None) -> int:
    headers = {"User-Agent": "agent-analyser-link-health/1.0"}
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, method=method, headers=headers)
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - stdlib-only, scheme validated upstream by caller intent
        return int(resp.status)


def check_url(url: str, timeout: float = 3.0) -> LinkStatus:
    """HEAD a URL with timeout. Falls back to ranged GET when HEAD is rejected.

    Some SharePoint / CDN endpoints reject HEAD with 405/501; a 1-byte ranged
    GET is the cheapest portable fallback.
    """
    try:
        status = _do_request(url, "HEAD", timeout)
        return LinkStatus(url=url, ok=200 <= status < 400, status_code=status, error=None, checked_at=_now_iso())
    except HTTPError as exc:
        if exc.code in (405, 501):
            try:
                status = _do_request(url, "GET", timeout, {"Range": "bytes=0-0"})
                return LinkStatus(
                    url=url,
                    ok=200 <= status < 400,
                    status_code=status,
                    error=None,
                    checked_at=_now_iso(),
                )
            except HTTPError as get_exc:
                return LinkStatus(
                    url=url,
                    ok=False,
                    status_code=int(get_exc.code),
                    error=f"HTTPError: {get_exc.code} {get_exc.reason}",
                    checked_at=_now_iso(),
                )
            except (URLError, socket.timeout, TimeoutError, ValueError, OSError) as get_exc:
                return LinkStatus(
                    url=url,
                    ok=False,
                    status_code=None,
                    error=f"{type(get_exc).__name__}: {get_exc}",
                    checked_at=_now_iso(),
                )
        return LinkStatus(
            url=url,
            ok=False,
            status_code=int(exc.code),
            error=f"HTTPError: {exc.code} {exc.reason}",
            checked_at=_now_iso(),
        )
    except (URLError, socket.timeout, TimeoutError, ValueError, OSError) as exc:
        return LinkStatus(
            url=url,
            ok=False,
            status_code=None,
            error=f"{type(exc).__name__}: {exc}",
            checked_at=_now_iso(),
        )


def check_urls(urls: list[str], timeout: float = 3.0, max_workers: int = 8) -> list[LinkStatus]:
    """Concurrent checker. Dedupes input, preserves first-seen order in output."""
    seen: dict[str, int] = {}
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen[url] = len(ordered)
            ordered.append(url)

    if not ordered:
        return []

    workers = max(1, min(max_workers, len(ordered)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda u: check_url(u, timeout=timeout), ordered))
    return results

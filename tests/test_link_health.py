from link_health import LinkStatus, check_url, check_urls


def test_check_url_unreachable():
    result = check_url("http://localhost:1/never", timeout=1.0)
    assert isinstance(result, LinkStatus)
    assert result.ok is False
    assert result.error is not None
    assert result.url == "http://localhost:1/never"
    assert result.checked_at  # ISO timestamp populated


def test_check_urls_dedupes():
    results = check_urls(["http://localhost:1/a", "http://localhost:1/a", "http://localhost:1/b"], timeout=1.0)
    assert len(results) == 2
    urls = [r.url for r in results]
    assert urls == ["http://localhost:1/a", "http://localhost:1/b"]


def test_check_url_handles_malformed():
    result = check_url("not a url", timeout=1.0)
    assert result.ok is False
    assert result.error is not None
    assert result.status_code is None


def test_check_urls_empty_input():
    assert check_urls([], timeout=1.0) == []

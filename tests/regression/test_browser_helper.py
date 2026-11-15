import gzip
import urllib.error
import zlib

import pytest

from selenium_to_html.core.helpers import browser_helper
from selenium_to_html.core.helpers.browser_helper import (
    _JS_FETCH,
    _block_browser_fetch,
    _build_headers,
    _cookie_header,
    _decode_body,
    _get_page_state,
    _http_get,
)
from selenium_to_html.core.types.fetch_config import FetchConfig
from selenium_to_html.core.types.internal import _AttemptError, _Context


def test_get_page_state_waits_and_collects_values(monkeypatch, fake_driver):
    sleeps = []
    monkeypatch.setattr(browser_helper.time, "sleep", lambda s: sleeps.append(s))
    # monotonic: start, loop check, loop check after sleep -> ready
    ticks = iter([0.0, 0.0, 0.2, 0.2, 0.2])
    monkeypatch.setattr(browser_helper.time, "monotonic", lambda: next(ticks))
    fake_driver.ready_states = ["loading", "complete"]
    state = _get_page_state(fake_driver, FetchConfig(page_ready_timeout=5.0))
    assert state["source"] == "<html><body>ok</body></html>"
    assert state["page_url"] == "https://example.test/page"
    assert state["browser_base"] == "https://example.test/page"
    assert state["user_agent"] == "TestAgent/1.0"
    assert state["cookies"] == []
    assert sleeps == [0.1]


def test_get_page_state_timeout_and_source_fallbacks(monkeypatch, fake_driver):
    monkeypatch.setattr(browser_helper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(browser_helper.time, "monotonic", lambda: 100.0)  # deadline immediately passed
    fake_driver.page_source = "   "
    fake_driver.outer_html = "<html>outer</html>"
    state = _get_page_state(fake_driver, FetchConfig(page_ready_timeout=0.0, page_source_attempts=2))
    assert state["source"] == "<html>outer</html>"


def test_get_page_state_raises_when_source_unavailable(monkeypatch, fake_driver):
    monkeypatch.setattr(browser_helper.time, "sleep", lambda *_: None)
    ticks = iter([0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    monkeypatch.setattr(browser_helper.time, "monotonic", lambda: next(ticks, 1.0))
    fake_driver.page_source = ""
    fake_driver.page_source_error = RuntimeError("ps")
    fake_driver.outer_html = ""
    fake_driver.outer_html_error = RuntimeError("oh")
    with pytest.raises(RuntimeError, match="Unable to retrieve the page source"):
        _get_page_state(fake_driver, FetchConfig(page_ready_timeout=0.0, page_source_attempts=2))


def test_get_page_state_getter_debug_path_bug_current_behavior(monkeypatch, fake_driver):
    # _get_or_default logs with undefined `f`; if getter fails, current impl raises NameError.
    monkeypatch.setattr(browser_helper.time, "sleep", lambda *_: None)
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(browser_helper.time, "monotonic", lambda: next(ticks, 1.0))

    class RaisingURLDriver(type(fake_driver)):
        @property
        def current_url(self):
            raise RuntimeError("boom")

    fake_driver.__class__ = RaisingURLDriver
    with pytest.raises(NameError):
        _get_page_state(fake_driver, FetchConfig(page_ready_timeout=0.0))


def test_block_browser_fetch_success_redirect_error_cases(fake_driver):
    cfg = FetchConfig()
    fake_driver.async_result = {
        "status": 200,
        "redirected": True,
        "url": "https://e.test/final",
        "type": "text/plain",
        "body": __import__("base64").b64encode(b"ok").decode(),
    }
    fetched = _block_browser_fetch(fake_driver, "https://e.test/a", cfg)
    assert fake_driver.script_timeout == cfg.browser_script_timeout
    assert fetched.status == 200
    assert fetched.final_url == "https://e.test/final"
    assert fetched.redirects == ("https://e.test/final",)
    assert fetched.body == b"ok"

    fake_driver.async_result = {"error": "CORS"}
    with pytest.raises(_AttemptError) as ei:
        _block_browser_fetch(fake_driver, "https://e.test/a", cfg)
    assert ei.value.retryable is False

    fake_driver.async_result = ["bad"]
    with pytest.raises(_AttemptError, match="unexpected payload"):
        _block_browser_fetch(fake_driver, "https://e.test/a", cfg)

    fake_driver.async_result = {"status": 503, "url": "https://e.test/a", "body": ""}
    with pytest.raises(_AttemptError) as ei:
        _block_browser_fetch(fake_driver, "https://e.test/a", cfg)
    assert ei.value.retryable is True

    fake_driver.async_result = {
        "status": 200,
        "url": "https://e.test/a",
        "body": __import__("base64").b64encode(b"12345").decode(),
    }
    with pytest.raises(_AttemptError, match="max_bytes"):
        _block_browser_fetch(fake_driver, "https://e.test/a", FetchConfig(max_bytes=4))

    fake_driver.async_result = None
    fake_driver.async_error = RuntimeError("boom")
    with pytest.raises(_AttemptError, match="browser fetch failed"):
        _block_browser_fetch(fake_driver, "https://e.test/a", cfg)


def test_cookie_and_header_building():
    ctx = _Context(
        driver=object(),
        cfg=FetchConfig(),
        page_url="https://example.test/page/path",
        user_agent="UA/1",
        cookies=[
            {"name": "a", "value": "1", "domain": "example.test", "path": "/"},
            {"name": "b", "value": "2", "domain": ".example.test", "path": "/page", "secure": True},
            {"name": "c", "value": "3", "domain": "other.test"},
            {"name": "d", "value": "4", "path": "/other"},
        ],
        opener=None,  # type: ignore[arg-type]
        driver_lock=None,  # type: ignore[arg-type]
    )
    cookie = _cookie_header(ctx, "https://example.test/page/path?q=1")
    assert "a=1" in cookie and "b=2" in cookie
    assert "c=3" not in cookie and "d=4" not in cookie

    h_browser = _build_headers("browser_headers", ctx, "https://example.test/x")
    assert h_browser["User-Agent"] == "UA/1"
    assert h_browser["Referer"] == "https://example.test/page/path"
    assert "Cookie" in h_browser

    h_origin = _build_headers("origin_referer", ctx, "https://example.test/x")
    assert h_origin["Referer"] == "https://example.test/"

    h_generic = _build_headers("generic_minimal", ctx, "https://example.test/x")
    assert h_generic["Accept-Encoding"] == "identity"
    assert "Cookie" not in h_generic


def test_decode_body_variants_and_errors():
    assert _decode_body(b"abc", "identity") == b"abc"
    assert _decode_body(gzip.compress(b"abc"), "gzip") == b"abc"
    assert _decode_body(zlib.compress(b"abc"), "deflate") == b"abc"
    raw_deflate = zlib.compress(b"abc")[2:-4]
    assert _decode_body(raw_deflate, "deflate") == b"abc"
    with pytest.raises(_AttemptError, match="decompression failed"):
        _decode_body(b"notgzip", "gzip")
    with pytest.raises(_AttemptError, match="unsupported Content-Encoding") as ei:
        _decode_body(b"x", "br")
    assert ei.value.retryable is False


def test_http_get_success_redirects_and_errors(monkeypatch, fake_opener, fake_http_response):
    monkeypatch.setattr(browser_helper.time, "monotonic", lambda: 0.0)
    cfg = FetchConfig()

    # success with gzip body
    opener = fake_opener(responses=[fake_http_response(status=200, headers={"Content-Type": "text/plain", "Content-Encoding": "gzip"}, body=gzip.compress(b"ok"))])
    fetched = _http_get("https://e.test/a", {}, cfg, opener)
    assert fetched.body == b"ok"
    assert fetched.status == 200

    # manual redirect 302 -> 200
    redirect_err = urllib.error.HTTPError(
        "https://e.test/a", 302, "Found", hdrs={"Location": "/b"}, fp=None
    )
    opener = fake_opener(side_effect=[redirect_err, fake_http_response(status=200, body=b"done")])
    fetched = _http_get("https://e.test/a", {}, cfg, opener)
    assert fetched.final_url == "https://e.test/b"
    assert fetched.redirects == ("https://e.test/b",)

    # redirect without location
    no_loc = urllib.error.HTTPError("https://e.test/a", 302, "Found", hdrs={}, fp=None)
    opener = fake_opener(side_effect=[no_loc])
    with pytest.raises(_AttemptError, match="without Location"):
        _http_get("https://e.test/a", {}, cfg, opener)

    # non-retryable http error
    err404 = urllib.error.HTTPError("https://e.test/a", 404, "NF", hdrs={}, fp=None)
    opener = fake_opener(side_effect=[err404])
    with pytest.raises(_AttemptError) as ei:
        _http_get("https://e.test/a", {}, FetchConfig(retryable_statuses=frozenset()), opener)
    assert ei.value.status == 404 and ei.value.retryable is False

    # network error
    opener = fake_opener(side_effect=[urllib.error.URLError("boom")])
    with pytest.raises(_AttemptError, match="network error"):
        _http_get("https://e.test/a", {}, cfg, opener)

    # max bytes
    opener = fake_opener(responses=[fake_http_response(status=200, chunks=[b"123", b"45"])])
    with pytest.raises(_AttemptError, match="max_bytes"):
        _http_get("https://e.test/a", {}, FetchConfig(max_bytes=4), opener)

    # total timeout
    ticks = iter([0.0, 0.0, 999.0, 999.0])
    monkeypatch.setattr(browser_helper.time, "monotonic", lambda: next(ticks))
    opener = fake_opener(responses=[fake_http_response(status=200, chunks=[b"a"])])
    with pytest.raises(_AttemptError, match="total timeout"):
        _http_get("https://e.test/a", {}, cfg, opener)

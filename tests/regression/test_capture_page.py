import asyncio

import pytest

from selenium_to_html.core import runner
from selenium_to_html.core.types.fetch_config import FetchConfig, ResourceRef
from selenium_to_html.core.types.result_types import FetchAttempt, PageSnapshot, ResourceResult


@pytest.mark.asyncio
async def test_capture_page_wires_state_refs_fetch_and_embedding(monkeypatch):
    state = {
        "source": '<html><img src="/a.png"></html>',
        "page_url": "https://e.test/page",
        "browser_base": "https://e.test/page",
        "user_agent": "UA",
        "cookies": [{"name": "c", "value": "1"}],
    }
    monkeypatch.setattr(runner, "_get_page_state", lambda driver, cfg: state)

    seen = {}

    def fake_extract(source, base_url, page_url, cfg, browser_base):
        seen["extract"] = (source, base_url, page_url, browser_base, cfg.embed_media)
        return [ResourceRef(url="https://e.test/a.png", tag="img", attr="src", kind="media", tag_texts=['<img src="/a.png">'])]

    monkeypatch.setattr(runner, "_extract_refs", fake_extract)

    captured_ctx = {}

    async def fake_fetch(ref, ctx, sem):
        captured_ctx["ctx"] = ctx
        return ResourceResult(ref=ref, ok=True, status=200, body=b"img", content_type="image/png", final_url=ref.url, approach="generic_minimal")

    monkeypatch.setattr(runner, "_fetch_resource", fake_fetch)

    def fake_embed(source, results, cfg):
        assert cfg.embed_media is True
        return ("<embedded>", 1)

    monkeypatch.setattr(runner, "_embed_media", fake_embed)

    class DummyOpener:
        pass

    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *a, **k: DummyOpener())

    ssl_calls = []
    import ssl

    class DummySSL:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

    def fake_ssl_ctx():
        ctx = DummySSL()
        ssl_calls.append(ctx)
        return ctx

    monkeypatch.setattr(runner.ssl, "create_default_context", fake_ssl_ctx)

    snap = await runner.capture_page(object(), FetchConfig(embed_media=True, verify_tls=False, max_concurrency=0))
    assert isinstance(snap, PageSnapshot)
    assert seen["extract"] == (state["source"], "https://e.test/page", "https://e.test/page", True, True)
    assert snap.page_url == "https://e.test/page"
    assert snap.base_url == "https://e.test/page"
    assert len(snap.succeeded) == 1
    assert snap.embedded_source == "<embedded>"
    assert snap.embedded_count == 1
    assert ssl_calls[0].check_hostname is False
    assert ssl_calls[0].verify_mode == ssl.CERT_NONE
    assert captured_ctx["ctx"].user_agent == "UA"
    assert captured_ctx["ctx"].cookies == [{"name": "c", "value": "1"}]


@pytest.mark.asyncio
async def test_capture_page_handles_gather_exception_and_embed_failure(monkeypatch):
    state = {"source": "<html></html>", "page_url": "https://e.test", "browser_base": "", "user_agent": "UA", "cookies": []}
    monkeypatch.setattr(runner, "_get_page_state", lambda d, c: state)
    ref = ResourceRef(url="https://e.test/a.js", tag="script", attr="src", kind="script")
    monkeypatch.setattr(runner, "_extract_refs", lambda *a, **k: [ref])
    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *a, **k: object())
    monkeypatch.setattr(runner.ssl, "create_default_context", lambda: type("S", (), {"check_hostname": True, "verify_mode": 2})())

    async def boom(ref, ctx, sem):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_fetch_resource", boom)

    def bad_embed(*a, **k):
        raise RuntimeError("embed fail")

    monkeypatch.setattr(runner, "_embed_media", bad_embed)

    snap = await runner.capture_page(object(), FetchConfig(embed_media=True))
    assert len(snap.failures) == 1
    assert snap.failures[0].attempts[0].approach == "internal"
    assert "RuntimeError" in (snap.failures[0].attempts[0].error or "")
    assert snap.embedded_source is None


def test_capture_page_sync_no_running_loop(monkeypatch):
    sentinel = object()
    import selenium_to_html.core.runner as rmod

    async def fake_capture(driver, config=None):
        return sentinel

    monkeypatch.setattr(rmod, "capture_page", fake_capture)
    assert rmod.capture_page_sync(object()) is sentinel


@pytest.mark.asyncio
async def test_capture_page_sync_with_running_loop(monkeypatch):
    sentinel = object()
    import selenium_to_html.core.runner as rmod

    async def fake_capture(driver, config=None):
        return sentinel

    monkeypatch.setattr(rmod, "capture_page", fake_capture)
    # call sync wrapper from async context -> should use threadpool path
    out = rmod.capture_page_sync(object())
    assert out is sentinel

import asyncio

import pytest

from selenium_to_html.core import runner
from selenium_to_html.core.types.fetch_config import FetchConfig, ResourceRef
from selenium_to_html.core.types.internal import _AttemptError, _Context, _Fetched
from selenium_to_html.core.types.result_types import ResourceResult


def _ctx(cfg=None):
    cfg = cfg or FetchConfig()
    return _Context(
        driver=object(),
        cfg=cfg,
        page_url="https://example.test/page",
        user_agent="UA",
        cookies=[],
        opener=object(),
        driver_lock=asyncio.Lock(),
    )


def test_standby_idle_bounds_and_jitter(monkeypatch):
    monkeypatch.setattr(runner.random, "random", lambda: 0.0)
    cfg = FetchConfig(standby_idle_base=0.5, standby_idle_max=3.0)
    # attempt 1 -> floor 0.5, raise_factor max(0.5,1.1)=1.1 => 0.55
    assert runner._standby_idle(cfg, 1) == pytest.approx(0.55)
    # large attempt capped
    assert runner._standby_idle(cfg, 10) == 3.0
    monkeypatch.setattr(runner.random, "random", lambda: 0.9)
    assert runner._standby_idle(cfg, 1) == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_fetch_resource_success_after_retry_and_recovery(monkeypatch):
    calls = []

    async def fake_try(approach, url, ctx):
        calls.append((approach, url))
        if len(calls) == 1:
            raise _AttemptError(503, "temporary", retryable=True)
        return _Fetched(200, "https://e.test/final", b"ok", "text/plain", ("https://e.test/r",))

    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(runner, "_try_approach", fake_try)
    monkeypatch.setattr(runner, "_standby_idle", lambda cfg, attempt: 0.25)
    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)

    ref = ResourceRef(url="https://e.test/a", tag="script", attr="src", kind="script")
    res = await runner._fetch_resource(ref, _ctx(FetchConfig(attempts_per_approach=2)), asyncio.Semaphore(1))
    assert res.ok is True
    assert res.status == 200
    assert res.final_url == "https://e.test/final"
    assert res.body == b"ok"
    assert res.approach == "generic_minimal"
    assert len(res.attempts) == 2
    assert res.attempts[0].ok is False and res.attempts[1].ok is True
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_fetch_resource_terminal_stops_and_nonretryable_moves_on(monkeypatch):
    calls = []

    async def fake_try(approach, url, ctx):
        calls.append(approach)
        if approach == "generic_minimal":
            raise _AttemptError(None, "bad", retryable=False)
        if approach == "browser_headers":
            raise _AttemptError(404, "gone", retryable=False)
        raise AssertionError("should stop on terminal")

    monkeypatch.setattr(runner, "_try_approach", fake_try)
    ref = ResourceRef(url="https://e.test/a", tag="script", attr="src", kind="script")
    res = await runner._fetch_resource(ref, _ctx(FetchConfig(attempts_per_approach=2)), asyncio.Semaphore(1))
    assert res.ok is False
    assert res.status == 404
    assert calls == ["generic_minimal", "browser_headers"]
    assert len(res.attempts) == 2


@pytest.mark.asyncio
async def test_fetch_resource_skips_browser_fetch_when_disabled(monkeypatch):
    calls = []

    async def fake_try(approach, url, ctx):
        calls.append(approach)
        raise _AttemptError(None, "no", retryable=False)

    monkeypatch.setattr(runner, "_try_approach", fake_try)
    ref = ResourceRef(url="https://e.test/a", tag="script", attr="src", kind="script")
    res = await runner._fetch_resource(ref, _ctx(FetchConfig(use_browser_fallback=False)), asyncio.Semaphore(1))
    assert res.ok is False
    assert "browser_fetch" not in calls
    assert calls == ["generic_minimal", "browser_headers", "origin_referer"]


@pytest.mark.asyncio
async def test_fetch_resource_exhaustion_sets_last_status(monkeypatch):
    async def fake_try(approach, url, ctx):
        raise _AttemptError(503, "temp", retryable=False)

    monkeypatch.setattr(runner, "_try_approach", fake_try)
    ref = ResourceRef(url="https://e.test/a", tag="script", attr="src", kind="script")
    res = await runner._fetch_resource(ref, _ctx(FetchConfig(attempts_per_approach=1)), asyncio.Semaphore(1))
    assert res.ok is False
    assert res.status == 503
    assert len(res.attempts) == 4


@pytest.mark.asyncio
async def test_fetch_resource_defensive_unexpected_exception(monkeypatch):
    async def fake_try(approach, url, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(runner, "_try_approach", fake_try)
    ref = ResourceRef(url="https://e.test/a", tag="script", attr="src", kind="script")
    res = await runner._fetch_resource(
        ref, _ctx(FetchConfig(attempts_per_approach=1, use_browser_fallback=False)), asyncio.Semaphore(1)
    )
    assert res.ok is False
    assert any("unexpected error" in (a.error or "") for a in res.attempts)


@pytest.mark.asyncio
async def test_try_approach_routes_browser_fetch_through_lock(monkeypatch):
    called = {"browser": 0, "http": 0}

    def browser_fetch(driver, url, cfg):
        called["browser"] += 1
        return _Fetched(200, url, b"x", "t", ())

    def http_get(url, headers, cfg, opener):
        called["http"] += 1
        return _Fetched(200, url, b"y", "t", ())

    monkeypatch.setattr(runner, "_block_browser_fetch", browser_fetch)
    monkeypatch.setattr(runner, "_http_get", http_get)
    ctx = _ctx()
    out = await runner._try_approach("browser_fetch", "https://e.test/a", ctx)
    assert out.body == b"x" and called["browser"] == 1
    out = await runner._try_approach("generic_minimal", "https://e.test/a", ctx)
    assert out.body == b"y" and called["http"] == 1

"""Async orchestration: per-resource fallback state machine and public entry points."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import random
import ssl
import time
import urllib.request
from typing import Any

from .helpers.browser_helper import (
    _block_browser_fetch,
    _build_headers,
    _get_page_state,
    _http_get,
)
from .helpers.resource_helper import _embed_media, _extract_refs
from .types.fetch_config import FetchConfig, ResourceRef
from .types.internal import _AttemptError, _Context, _Fetched, _NoRedirect
from .types.result_types import FetchAttempt, PageSnapshot, ResourceResult

logger = logging.getLogger("selenium_to_html.runner")

_APPROACHES: tuple[str, ...] = (
    "generic_minimal",
    "browser_headers",
    "origin_referer",
    "browser_fetch",
)


async def _try_approach(approach: str, url: str, ctx: _Context) -> _Fetched:

    # Selenium drivers are not thread-safe, the following serializes all driver access.
    if approach == "browser_fetch":
        async with ctx.driver_lock:
            return await asyncio.to_thread(_block_browser_fetch, ctx.driver, url, ctx.cfg)
    
    # All other requests are already thread-safe, as they are routed through urllib.request.
    headers = _build_headers(approach, ctx, url)
    return await asyncio.to_thread(_http_get, url, headers, ctx.cfg, ctx.opener)


def _standby_idle(cfg: FetchConfig, attempt: int) -> float:
    """Performs an idle standby operation that increases exponentially"""

    # cfg.standy_idle_base defaults to '0.5'.
    # 'N' is the attempt #
    # Computes to:
    # 0.5 * 2 = 1
    # 1 ^ (N - 1) = idle_min
    idle_floor = cfg.standby_idle_base * 2 ** (attempt - 1)
    
    raise_factor = 0.5 + random.random()
    
    # Ensuring the factor is raised by at least 1.1x
    if raise_factor < 1:
        raise_factor = 1.1

    # Raising idle_floor by >= 1.1
    raised_idle_floor = idle_floor * max(raise_factor, 1.1)

    return min(cfg.standby_idle_max, raised_idle_floor)


async def _fetch_resource(ref: ResourceRef, ctx: _Context, semaphore: asyncio.Semaphore) -> ResourceResult:
    cfg = ctx.cfg
    result = ResourceResult(ref=ref, ok=False)

    async with semaphore:
        for approach in _APPROACHES:

            # Skipping browser_fetch if the provided FetchConfig does not have use_browser_fallback enabled.
            if approach == "browser_fetch" and not cfg.use_browser_fallback:
                continue

            for attempt in range(1, cfg.attempts_per_approach + 1):
                t0 = time.perf_counter()
                try:
                    fetched = await _try_approach(approach, ref.url, ctx)
                
                except asyncio.CancelledError:
                    raise
                
                except _AttemptError as exc:
                    err = exc
                except Exception as exc:  # defensive: never let one resource kill the batch
                    err = _AttemptError(None, f"unexpected error: {exc!r}", retryable=False)
                
                else:
                    result.attempts.append(
                        FetchAttempt(
                            approach, 
                            attempt, 
                            True, 
                            fetched.status, 
                            fetched.final_url,
                            fetched.redirects, 
                            None, 
                            time.perf_counter() - t0
                        )
                    )

                    result.ok = True
                    result.status = fetched.status
                    result.final_url = fetched.final_url
                    result.content_type = fetched.content_type
                    result.body = fetched.body
                    result.approach = approach

                    if attempt > 1 or approach != _APPROACHES[0]:
                        logger.info("Recovered %s via %s (attempt %d)", ref.url, approach, attempt)
                    return result

                elapsed = time.perf_counter() - t0
                result.attempts.append(FetchAttempt(
                    approach, attempt, False, err.status, None,
                    err.redirects, str(err), elapsed))
                logger.warning(
                    "Fetch failure url=%s approach=%s attempt=%d/%d status=%s error=%s",
                    ref.url, approach, attempt, cfg.attempts_per_approach,
                    err.status, err)

                if err.status in cfg.terminal_statuses:
                    result.status = err.status
                    logger.error("Resource failed (terminal status %s): %s",
                                 err.status, ref.url)
                    return result
                if not err.retryable:
                    break
                if attempt < cfg.attempts_per_approach:
                    await asyncio.sleep(_standby_idle(cfg, attempt))

    last = result.attempts[-1] if result.attempts else None
    result.status = last.status if last else None
    logger.error("Resource failed after %d attempt(s) across all approaches: %s",
                 len(result.attempts), ref.url)
    return result


async def capture_page(driver: Any, config: FetchConfig | None = None) -> PageSnapshot:
    """
    Capture the driver's current page: rendered source plus all linked resources.

    The driver must already be on the target page. Do not use the driver from
    other threads while this coroutine is running.
    """
    cfg = config or FetchConfig()
    started = time.perf_counter()

    state = await asyncio.to_thread(_get_page_state, driver, cfg)
    source: str = state["source"]
    page_url: str = state["page_url"]
    browser_base: str = state["browser_base"]
    base_url = browser_base or page_url

    refs = _extract_refs(source, base_url, page_url or base_url, cfg, bool(browser_base))
    logger.info("Discovered %d unique external resource(s) on %s", len(refs), page_url)

    ssl_ctx = ssl.create_default_context()
    if not cfg.verify_tls:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=ssl_ctx))

    ctx = _Context(
        driver=driver,
        cfg=cfg,
        page_url=page_url or base_url,
        user_agent=state["user_agent"],
        cookies=state["cookies"],
        opener=opener,
        driver_lock=asyncio.Lock(),
    )

    sem = asyncio.Semaphore(max(1, cfg.max_concurrency))
    outcomes = await asyncio.gather(
        *(_fetch_resource(r, ctx, sem) for r in refs),
        return_exceptions=True,
    )

    results: list[ResourceResult] = []
    for ref, outcome in zip(refs, outcomes):
        if isinstance(outcome, BaseException):
            logger.error("Unhandled error fetching %s: %r", ref.url, outcome)
            results.append(ResourceResult(ref=ref, ok=False, attempts=[
                FetchAttempt("internal", 1, False, None, None, (), repr(outcome), 0.0)]))
        else:
            results.append(outcome)

    embedded_source: str | None = None
    embedded_count = 0
    if cfg.embed_media:
        try:
            embedded_source, embedded_count = await asyncio.to_thread(
                _embed_media, source, results, cfg)
            logger.info("Embedded %d media tag(s) as data: URIs", embedded_count)
        except Exception:
            logger.exception("Media embedding failed; embedded_source left unset")

    snapshot = PageSnapshot(
        page_url=page_url,
        base_url=base_url,
        page_source=source,
        resources=results,
        elapsed=time.perf_counter() - started,
        embedded_source=embedded_source,
        embedded_count=embedded_count,
    )
    logger.info("Capture complete: %d ok, %d failed, %.2fs",
                len(snapshot.succeeded), len(snapshot.failures), snapshot.elapsed)
    return snapshot


def capture_page_sync(driver: Any, config: FetchConfig | None = None) -> PageSnapshot:
    """
    Blocking wrapper. Safe to call whether or not an event loop is already
    running in the calling thread (e.g. when hosted inside another runtime).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(capture_page(driver, config))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(capture_page(driver, config))).result()

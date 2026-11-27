"""This file contains the core runner logic for selenium_to_html; It supports both asynchronous and synchronous operations."""

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
    block_browser_fetch,
    build_headers,
    get_page_source,
    make_get_request,
)
from .helpers.resource_helper import embed_media, extract_references
from .types.fetch_config import FetchConfig, ResourceRef
from .types.internal_types import AttemptError, Context, Response, NoRedirect
from .types.result_types import FetchAttempt, PageSnapshot, ResourceResult

logger = logging.getLogger("selenium_to_html.runner")

_APPROACHES: tuple[str, ...] = (
    "generic_minimal",
    "browser_headers",
    "origin_referer",
    "browser_fetch",
)


async def _try_approach(approach: str, url: str, ctx: Context) -> Response:
    """Attempts to fetch the resource from url in the context "ctx" using approach."""

    # Selenium drivers are not thread-safe, the following serializes all driver access.
    if approach == "browser_fetch":
        async with ctx.driver_lock:
            return await asyncio.to_thread(block_browser_fetch, ctx.driver, url, ctx.cfg)  # pyright: ignore[reportAny]
    
    # All other requests are already thread-safe, as they are routed through urllib.request.
    headers = build_headers(approach, ctx, url)
    return await asyncio.to_thread(make_get_request, url, headers, ctx.cfg, ctx.request_opener)


def _standby_idle(cfg: FetchConfig, attempt: int) -> float:
    """Performs an idle standby operation that increases exponentially"""

    # cfg.standy_idle_base defaults to '0.5'.
    # 'N' is the attempt #
    # Computes to:
    # 0.5 * 2 = 1
    # 1 ^ (N - 1) = idle_min
    idle_floor: float = cfg.standby_idle_base * 2 ** (attempt - 1)  # pyright: ignore[reportAny]
    
    raise_factor = 0.5 + random.random()
    
    # Ensuring the factor is raised by at least 1.1x
    if raise_factor < 1:
        raise_factor = 1.1

    # Raising idle_floor by >= 1.1
    raised_idle_floor: float = idle_floor * max(raise_factor, 1.1)

    return min(cfg.standby_idle_max, raised_idle_floor)


async def _fetch_resource(ref: ResourceRef, ctx: Context, semaphore: asyncio.Semaphore) -> ResourceResult:
    """Using the provided context and semaphore, an asynchronous attempt is made to fetch the requested ResourceRef."""
    cfg = ctx.cfg
    result = ResourceResult(ref=ref, ok=False)

    async with semaphore:
        for approach in _APPROACHES:

            # Skipping browser_fetch if the provided FetchConfig does not have use_browser_fallback enabled.
            if approach == "browser_fetch" and not cfg.use_browser_fallback:
                continue

            for attempt in range(1, cfg.attempts_per_approach + 1):
                start_time = time.perf_counter()
                try:
                    fetched = await _try_approach(approach, ref.url, ctx)
                
                except asyncio.CancelledError:
                    raise
                
                except AttemptError as exc:
                    err = exc

                except Exception as exc:  # Ensuring a single failed resource fetch doesn't kill a batch operation.
                    err = AttemptError(None, f"unexpected error: {exc!r}", retryable=False)
                
                # This else conditional serve as a guard clause.
                # If an attempt to fetch the provided resource throws an exception, the following is NOT executed.
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
                            time.perf_counter() - start_time
                        )
                    )

                    result.ok = True
                    result.status = fetched.status
                    result.final_url = fetched.final_url
                    result.content_type = fetched.content_type
                    result.body = fetched.body
                    result.approach = approach

                    if attempt > 1 or approach != _APPROACHES[0]:
                        logger.info("Retrieved %s via %s (attempt %d in fallback mode)", ref.url, approach, attempt)

                    return result

                elapsed = time.perf_counter() - start_time
                result.attempts.append(
                    FetchAttempt(
                        approach, attempt, False, err.status, None, err.redirects, str(err), elapsed
                    )
                )

                logger.warning(
                    "Fetch failure | url=%s | approach=%s | attempt=%d/%d | status=%s | error=%s",
                    ref.url, approach, attempt, cfg.attempts_per_approach, err.status, err
                )

                if err.status in cfg.fatal_statuses:
                    result.status = err.status
                    logger.error("Resource failed with status %s: %s", err.status, ref.url)
                    return result

                if not err.retryable:
                    break
                
                if attempt < cfg.attempts_per_approach:
                    await asyncio.sleep(_standby_idle(cfg, attempt))

    last = result.attempts[-1] if result.attempts else None
    result.status = last.status if last else None
    logger.error("Failed to fetch resource after %d attempt(s) from: %s", len(result.attempts), ref.url)

    return result


async def capture_page(
    driver: Any,  # pyright: ignore[reportExplicitAny, reportAny]
    config: FetchConfig | None = None
) -> PageSnapshot: 
    """
    Asynchronously captures the rendered page source for the active tab in the provided driver.
    
    The provided driver must not be accessed by another thread for the duration of this operation.

    For thread-safe requests, opt for capture_page_sync in an asyncio event loop.
    """

    cfg = config or FetchConfig()
    started = time.perf_counter_ns()

    thread_state: dict[str, Any] = await asyncio.to_thread(get_page_source, driver, cfg)  # pyright: ignore[reportExplicitAny]
    
    source: str = thread_state["source"]  # pyright: ignore[reportAny]
    page_url: str = thread_state["page_url"]  # pyright: ignore[reportAny]
    browser_base: str = thread_state["browser_base"]  # pyright: ignore[reportAny]
    base_url = browser_base or page_url

    references = extract_references(source, base_url, page_url or base_url, cfg, bool(browser_base))
    logger.info(" Discovered %d unique external resource(s) on '%s'", len(references), page_url)

    # This was flagged as a false positive in multiple security audits.

    # False positives:
    # Enable server hostname verification on this SSL/TLS connection.
    # Use a stronger protocol, or upgrade to Python 3.10+ which uses secure defaults.

    # If the config parameter is not provided in a call to capture_page, an instance is created with default values.
    ## Amongst these default values, is `verify_tls: bool = True`
    ## Therefore a developer must explicitly pass `FetchConfig(..., verify_tls=False)` to capture_page

    ssl_ctx = ssl.create_default_context()

    if not cfg.verify_tls:
        logger.warning("verify_tls=False disables TLS verification and should not be used in production.")
        logger.info("Set verify_tls=True in FetchConfig (the default) to re-enable TLS verification.")
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    request_opener = urllib.request.build_opener(
        NoRedirect, 
        urllib.request.HTTPSHandler(context=ssl_ctx)
    )

    ctx = Context(
        driver=driver,
        cfg=cfg,
        page_url=page_url or base_url,
        user_agent=thread_state["user_agent"],  # pyright: ignore[reportAny]
        cookies=thread_state["cookies"],  # pyright: ignore[reportAny]
        request_opener=request_opener,
        driver_lock=asyncio.Lock(),
    )

    semaphore = asyncio.Semaphore(max(1, cfg.max_concurrency))

    responses = await asyncio.gather(
        *(_fetch_resource(reference, ctx, semaphore) for reference in references),
        return_exceptions=True,
    )

    results: list[ResourceResult] = []
    for reference, response in zip(references, responses):
        
        if not isinstance(response, BaseException):
            results.append(response)
        
        else:
            logger.error(" Unhandled error fetching %s: %r", reference.url, response)
            results.append(
                ResourceResult(ref=reference, ok=False, attempts=[
                    FetchAttempt("internal_types", 1, False, None, None, (), repr(response), 0.0)
                ])
            )
        
    embedded_source: str | None = None
    embedded_count = 0

    if cfg.embed_media:
        try:
            embedded_source, embedded_count = await asyncio.to_thread(embed_media, source, results, cfg)
            logger.info(" Embedded %d media tag(s) as base64 'data:' URIs", embedded_count)
        except Exception:
            logger.exception(" Media embedding failed because 'embedded_source' was not set")

    snapshot = PageSnapshot(
        page_url=page_url,
        base_url=base_url,
        page_source=source,
        resources=results,
        elapsed=(time.perf_counter_ns() - started) / 1_000_000,
        embedded_source=embedded_source,
        embedded_count=embedded_count,
    )
    
    logger.info(
        " Capture complete!\n\nResults:\n%d succeeded | %d failed | Time spent: %.2fms", 
        len(snapshot.succeeded), len(snapshot.failures), snapshot.elapsed
    )

    return snapshot


def capture_page_sync(
    driver: Any, # pyright: ignore[reportAny, reportExplicitAny]
    config: FetchConfig | None = None
) -> PageSnapshot:  
    """
    Synchronously captures the rendered page source for the active tab in the provided driver.
    
    Unlike capture_page (which is non-blocking), executing in a synchronous context makes this operation thread-safe.
    """
    try:
        asyncio.get_running_loop()  # pyright: ignore[reportUnusedCallResult]
    except RuntimeError:
        return asyncio.run(capture_page(driver, config))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(capture_page(driver, config))).result()

"""
This file contains helpers that communicate with Selenium or urllib.request and manage synchronous blocking via asyncio.to_thread.
"""

from __future__ import annotations

import base64
import gzip
import logging
import time
import urllib.error
import urllib.request
import zlib
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..types.fetch_config import FetchConfig
from ..types.internal_types import AttemptError, Context, Response

logger = logging.getLogger("selenium_to_html.browser_helper")

_GENERIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# --------------------------------------------------------------------------- #
# Selenium related declarations.
# --------------------------------------------------------------------------- #

_JS_FETCH = """
const url = arguments[0];
const done = arguments[arguments.length - 1];
fetch(url, {
    credentials: 'include', 
    redirect: 'follow', 
    cache: 'no-store'
})
.then(async req => {

    const bytes = new Uint8Array(await req.arrayBuffer());
    let bin = '';
    const step = 32768; // 32768
    for (let i = 0; i < bytes.length; i += step) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    }
    done({
        status: req.status, 
        redirected: req.redirected, 
        url: req.url,
        type: req.headers.get('content-type') || '', body: btoa(bin)
    });
})
.catch(e => done({error: String(e)}));
"""

def _get_or_default(func, default) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportUnknownParameterType, reportMissingParameterType]
    """Executes and returns the value from the provided func; the default provided if the func returned no value."""
    try:
        value = func()  # pyright: ignore[reportUnknownVariableType]
        return value if value else default  # pyright: ignore[reportUnknownVariableType]
    except Exception as exc:
        logger.debug(f"Call to {func.__name__} failed: %r", exc)  # pyright: ignore[reportUnknownMemberType]
        return default  # pyright: ignore[reportUnknownVariableType]

def _wait_for_complete_page_load(driver: Any, cfg: FetchConfig) -> None:  # pyright: ignore[reportAny, reportExplicitAny]
    """
    Uses the provided page timeout (set via cfg.page_ready_timeout) to wait for the document to fully load.
    If an exception is thrown, execution haults with an exit code 1.
    """

    timeout = time.monotonic() + cfg.page_ready_timeout
    while time.monotonic() < timeout:
        try:
            if driver.execute_script("return document.readyState") == "complete":  # pyright: ignore[reportAny]
                break
        except Exception as exc:
            logger.debug("document.readyState was not resolved: %r", exc)

        time.sleep(0.1)
    else:
        logger.warning("Page did not reach readyState=complete within %.1fs", cfg.page_ready_timeout)


def get_page_source(driver: Any, cfg: FetchConfig) -> dict[str, Any]:  # pyright: ignore[reportAny, reportExplicitAny]
    """
    Attempts to retrieve the source of driver's currently loaded page using the provided FetchConfig.

    Args:
        driver: A selenium instance.
        cfg: A FetchConfig object for `page_source_attempts`, `standby_idle_base`, and `standby_idle_max`.

    Returns: A dictionary containing the following:
        `"source"`: The non-empty HTML source of the loaded page, stored as a string.
        `"page_url"`: The driver's current page url, or an empty string on failure.
        `"browser_base"`: The page's document base URI (`document.baseURI`), or an empty string on failure.
        `"user_agent"`: The driver's user-agent string (`navigator.userAgent`), or `_GENERIC_UA` on failure.
        `"cookies"`: A `list[dict[str, Any]` from `driver.get_cookies()` or `[]` on failure.

    Raises:
        RuntimeError: If the page source is empty after all invocation attempts.
    """

    _wait_for_complete_page_load(driver, cfg)

    # Attempts to retrieve the page's source with three different approaches. 
    source = ""
    last_exc: Exception | None = None
    for attempt in range(1, cfg.page_source_attempts + 1):
        
        # First with a direct invocation of 'driver.page_source'
        try:
            source = driver.page_source  # pyright: ignore[reportAny]
            if source and source.strip():  # pyright: ignore[reportAny]
                break
        except Exception as exc:
            last_exc = exc
            logger.warning("driver.page_source invocation attempt %d failed: %r", attempt, exc)
        
        # Secondly is an invocation to `document.documentElement`.
        # Lastly, if `document.documentElement` does not return a string, 'document.documentElement.outerHtml` is used.
        try:
            source = driver.execute_script(  # pyright: ignore[reportAny]
                "return document.documentElement ? document.documentElement.outerHTML : ''"
            ) or ""
            if source.strip():
                break

        except Exception as exc:
            last_exc = exc
            logger.warning("outerHTML fallback attempt %d failed: %r", attempt, exc)


        time.sleep(min(cfg.standby_idle_max, cfg.standby_idle_base * 2 ** (attempt - 1)))  # pyright: ignore[reportAny]

    if not source.strip():
        raise RuntimeError(f"Unable to retrieve the page source: {last_exc!r}")

    page_url = _get_or_default(lambda: driver.current_url, "")  # pyright: ignore[reportAny]
    
    return {
        "source": source,
        "page_url": page_url,
        "browser_base": _get_or_default(lambda: driver.execute_script("return document.baseURI"), ""),  # pyright: ignore[reportAny]
        "user_agent": _get_or_default(lambda: driver.execute_script("return navigator.userAgent"), _GENERIC_UA),  # pyright: ignore[reportAny]
        "cookies": _get_or_default(driver.get_cookies, []),  # pyright: ignore[reportAny]
    }


def block_browser_fetch(driver: Any, url: str, cfg: FetchConfig) -> Response:  # pyright: ignore[reportAny, reportExplicitAny]
    try:
        driver.set_script_timeout(cfg.browser_script_timeout)  # pyright: ignore[reportAny]
        result = driver.execute_async_script(_JS_FETCH, url)  # pyright: ignore[reportAny]
    except Exception as exc:
        raise AttemptError(None, f"browser fetch failed: {exc!r}") from exc

    if not isinstance(result, dict):
        raise AttemptError(None, f"browser fetch returned unexpected payload: {type(result)!r}")  # pyright: ignore[reportAny]


    # While not exclusive for CORS / general network failures, it also handles all failures inside the page context.
    if "error" in result:
        raise AttemptError(None, f"browser fetch error: {result['error']}", retryable=False)

    status = int(result.get("status") or 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    final_url = result.get("url") or url  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    
    redirect_count = (final_url,) if result.get("redirected") else ()  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

    
    if status not in cfg.success_statuses:
        raise AttemptError(
            status, f"HTTP {status}",
            retryable=status in cfg.retryable_statuses, redirects=redirect_count,  # pyright: ignore[reportUnknownArgumentType]
        )

    body = base64.b64decode(result.get("body") or "")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

    if len(body) > cfg.max_resource_bytes:
        raise AttemptError(status, "response exceeds max_resource_bytes", retryable=False)

    return Response(
        status, 
        final_url,   # pyright: ignore[reportUnknownArgumentType]
        body, 
        result.get("type") or "",   # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        redirect_count  # pyright: ignore[reportUnknownArgumentType]
    )


# --------------------------------------------------------------------------- #
# urllib helper function declarations.
# --------------------------------------------------------------------------- #

def _cookie_header(ctx: Context, url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    pairs: list[str] = []
    
    for cookie in ctx.cookies:
        name, value = cookie.get("name"), cookie.get("value")
        
        if not name or value is None:
            continue

        domain = (cookie.get("domain") or "").lstrip(".").lower()
        if domain and not (host == domain or host.endswith("." + domain)):
            continue
        
        if not path.startswith(cookie.get("path") or "/"):
            continue
        
        if cookie.get("secure") and parts.scheme != "https":
            continue
        
        pairs.append(f"{name}={value}")
    
    return "; ".join(pairs)


def build_headers(approach: str, ctx: Context, url: str) -> dict[str, str]:
    
    # Approach: browser_headers
    if approach == "browser_headers":
        headers = {
            "User-Agent": ctx.user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": ctx.page_url,
        }
        cookie = _cookie_header(ctx, url)

        if cookie:
            headers["Cookie"] = cookie
        return headers

    # Approach: origin_referer
    elif approach == "origin_referer":
        parts = urlsplit(ctx.page_url)
        headers = {
            "User-Agent": ctx.user_agent,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Referer": f"{parts.scheme}://{parts.netloc}/",
        }
        cookie = _cookie_header(ctx, url)
        if cookie:
            headers["Cookie"] = cookie
        return headers

    # Approach: generic_minimal
    return {
        "User-Agent": _GENERIC_UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }


def _decode_body(raw_bytes: bytes, encoding: str) -> bytes:
    encoding_string = encoding.strip().lower()
    try:
        if encoding_string in ("", "identity"):
            return raw_bytes
        
        if encoding_string in ("gzip", "x-gzip"):
            return gzip.decompress(raw_bytes)

        if encoding_string == "deflate":
            try:
                return zlib.decompress(raw_bytes)
            except zlib.error:
                return zlib.decompress(raw_bytes, -zlib.MAX_WBITS)

    except (OSError, EOFError, zlib.error) as exc:
        raise AttemptError(None, f"decompression failed ({encoding_string}): {exc!r}") from exc

    raise AttemptError(None, f"unsupported Content-Encoding: {encoding_string}", retryable=False)


def make_get_request(
    url: str, headers: dict[str, str], cfg: FetchConfig, request_opener: urllib.request.OpenerDirector
) -> Response:

    current_url: str = url
    timeout: float = time.monotonic() + cfg.total_timeout
    redirect_count: list[str] = []

    for _ in range(cfg.max_redirects + 1):

        req = urllib.request.Request(current_url, headers=headers, method="GET")
        
        try:
            with request_opener.open(req, timeout=cfg.request_timeout) as resp:   # pyright: ignore[reportAny]
                code: int = resp.status  # pyright: ignore[reportAny]

                if code not in cfg.success_statuses:
                    raise AttemptError(
                        status=code, 
                        message=f"HTTP {code}", 
                        retryable=False,
                        redirects=tuple(redirect_count)
                    )
                
                status, buffer = read_response(cfg, resp, timeout, redirect_count)

                if not status:
                    raise AttemptError(
                        status=code,
                        message=f"An empty buffer was returned.",
                        retryable=False,
                        redirects=tuple(redirect_count)
                    )
                content_encoding: str = resp.headers.get("Content-Encoding", "")  # pyright: ignore[reportAny]
                
                body = _decode_body(b"".join(buffer), content_encoding) 
                
                return Response(
                    status=code, 
                    final_url=current_url, 
                    body=body, 
                    content_type=resp.headers.get("Content-Type", ""),   # pyright: ignore[reportAny]
                    redirects=tuple(redirect_count)
                )

        except urllib.error.HTTPError as exc:
            # Defined here so the except
            code = exc.code

            # Retrieving the Location header from the thrown exception.
            location = exc.headers.get("Location") if exc.headers else None

            # Closing the exception stream.
            try:
                exc.close()

            except Exception:
                pass

            if code in cfg.redirect_statuses:
                if not location:
                    raise AttemptError(
                        status=code, 
                        message="redirected without a Location header",
                        retryable=False, 
                        redirects=tuple(redirect_count)
                    ) from exc
                
                current_url = urljoin(url, location)

                if urlsplit(current_url).scheme not in ("http", "https"):
                    raise AttemptError(
                        status=code, 
                        message=f"redirected to an unsupported scheme: {current_url}",
                        retryable=False, 
                        redirects=tuple(redirect_count)
                    ) from exc
                
                redirect_count.append(current_url)
                continue
            
            raise AttemptError(
                status=code, 
                message=f"HTTP {code}",
                retryable=code in cfg.retryable_statuses,
                redirects=tuple(redirect_count)
            ) from exc

        except AttemptError:
            raise
            
        except ValueError as exc:
            raise AttemptError(
                status=None, 
                message=f"invalid request: {exc!r}", 
                retryable=False
            ) from exc

    raise AttemptError(
        None, 
        f"too many redirects (exceeded {cfg.max_redirects})",
        retryable=False, 
        redirects=tuple(redirect_count)
    )

def read_response(
    cfg: FetchConfig, 
    resp: Any,  # pyright: ignore[reportExplicitAny, reportAny]
    timeout: float, 
    redirect_count: list[str]
) -> tuple[bool, list[bytes]]:  
    """
    Reads an HTTP response buffer in chunks while adhering to the provided timeout and max_resource_bytes set in cfg (FetchConfig).

    The response buffer is iterated through in chunks of 65536 bytes.
    Iterates over `resp.read(65536)` until EOF or an error is met.

    `timeout` is compared against `time.monotonic` on a per-chunk basis.

    `total_bytes` is compared against `cfg.max_resource_bytes` on a per-chunk basis.

    Args:
        cfg: A `FetchConfig` object defined on line 1 of runner.capture_page.
        resp: The `Response` object from `urllib.request.request_opener` (Not to be confused with `internal_types.Response`).
        timeout: Monotonic timestamp that serves as the timeout for a request.
        redirect_count: A collection of redirects raised in an `_AttemptError` if a timeout or resource size limit is met.

    Returns: A `tuple[bool, list[bytes]]`
        Item1: A boolean set to True if the returned buffer is non-empty, otherwise False.
        Item2: A list of the bytes read from the provided request buffer.

    Raises:
        _AttemptError: 
            Thrown if `timeout` is met or `total_bytes` exceeds `cfg.max_resource_bytes`.
    """
    
    buffer: list[bytes] = []
    chunk_size: int = 81920
    total_bytes = 0

    while True:
        if time.monotonic() > timeout:
            raise AttemptError(
                status=None, 
                message="total timeout exceeded", 
                redirects=tuple(redirect_count)
            )

        # Read abstracts the EOF parsing logic.
        # A chunk can be <= 81920 bytes.
        # As such, total_bytes is incremented by the length of the chunk, not chunk_size.
        chunk: bytes = resp.read(chunk_size)  # pyright: ignore[reportAny]
        
        if not chunk:
            break

        total_bytes += len(chunk)

        if total_bytes > cfg.max_resource_bytes:
            raise AttemptError(
                status=resp.status,    # pyright: ignore[reportAny]
                message="response exceeds max_resource_bytes",
                retryable=False, 
                redirects=tuple(redirect_count)
            )
        
        buffer.append(chunk)
    
    # This may be an empty buffer
    return (len(buffer) > 0, buffer)

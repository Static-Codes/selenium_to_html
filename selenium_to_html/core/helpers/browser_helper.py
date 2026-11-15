"""
This file contains helpers that communicate with Selenium or urllib.request and manage synchronous blocking via asyncio.to_thread.
"""

from __future__ import annotations

import base64
import gzip
import http.client
import logging
import time
import urllib.error
import urllib.request
import zlib
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..types.fetch_config import FetchConfig
from ..types.internal_types import _AttemptError, _Context, _Fetched

logger = logging.getLogger("selenium_to_html.browser_helper")

_GENERIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# --------------------------------------------------------------------------- #
# Selenium-side
# --------------------------------------------------------------------------- #
# Source for a client side fetch attempt.
_JS_FETCH = """
const url = arguments[0];
const done = arguments[arguments.length - 1];
fetch(url, {
    credentials: 'include', 
    redirect: 'follow', 
    cache: 'no-store'
})
.then(async r => {
    const bytes = new Uint8Array(await r.arrayBuffer());
    let bin = '';
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    }
    done({
        status: r.status, 
        redirected: r.redirected, 
        url: r.url,
        type: r.headers.get('content-type') || '', body: btoa(bin)
    });
})
.catch(e => done({error: String(e)}));
"""


def _get_page_state(driver: Any, cfg: FetchConfig) -> dict[str, Any]:
    # Uses the provided page timeout (set via cfg.page_ready_timeout) to wait for the document to fully load.
    deadline = time.monotonic() + cfg.page_ready_timeout
    while time.monotonic() < deadline:
        try:
            if driver.execute_script("return document.readyState") == "complete": break
        except Exception as exc:
            logger.debug("document.readyState was not resolved: %r", exc)
        time.sleep(0.1)
    else:
        logger.warning("Page did not reach readyState=complete within %.1fs", cfg.page_ready_timeout)

    # Attempts to retrieve the page's source with three different approaches. 
    source = ""
    last_exc: Exception | None = None
    for attempt in range(1, cfg.page_source_attempts + 1):
        
        # First with a direct invocation of 'driver.page_source'
        try:
            source = driver.page_source
            if source and source.strip():
                break
        except Exception as exc:
            last_exc = exc
            logger.warning("driver.page_source invocation attempt %d failed: %r", attempt, exc)
        
        # Secondly is an invocation to `document.documentElement`.
        # Lastly, if `document.documentElement` does not return a string, 'document.documentElement.outerHtml` is used.
        try:
            source = driver.execute_script(
                "return document.documentElement ? document.documentElement.outerHTML : ''"
            ) or ""
            if source.strip():
                break

        except Exception as exc:
            last_exc = exc
            logger.warning("outerHTML fallback attempt %d failed: %r", attempt, exc)


        time.sleep(min(cfg.standby_idle_max, cfg.standby_idle_base * 2 ** (attempt - 1)))

    if not source.strip():
        raise RuntimeError(f"Unable to retrieve the page source: {last_exc!r}")

    def _get_or_default(func, default):
        try:
            value = func()
            return value if value else default
        except Exception as exc:
            logger.debug(f"Call to {f} failed: %r", exc)
            return default

    page_url = _get_or_default(lambda: driver.current_url, "")
    return {
        "source": source,
        "page_url": page_url,
        "browser_base": _get_or_default(lambda: driver.execute_script("return document.baseURI"), ""),
        "user_agent": _get_or_default(lambda: driver.execute_script("return navigator.userAgent"), _GENERIC_UA),
        "cookies": _get_or_default(driver.get_cookies, []),
    }


def _block_browser_fetch(driver: Any, url: str, cfg: FetchConfig) -> _Fetched:
    try:
        driver.set_script_timeout(cfg.browser_script_timeout)
        result = driver.execute_async_script(_JS_FETCH, url)
    except Exception as exc:
        raise _AttemptError(None, f"browser fetch failed: {exc!r}") from exc

    if not isinstance(result, dict):
        raise _AttemptError(None, f"browser fetch returned unexpected payload: {type(result)!r}")
    if "error" in result:
        # Typically CORS / network failure inside the page context.
        raise _AttemptError(None, f"browser fetch error: {result['error']}", retryable=False)

    status = int(result.get("status") or 0)
    final_url = result.get("url") or url
    number_of_redirects = (final_url,) if result.get("redirected") else ()
    if status not in cfg.success_statuses:
        raise _AttemptError(
            status, f"HTTP {status}",
            retryable=status in cfg.retryable_statuses, redirects=number_of_redirects,
        )
    body = base64.b64decode(result.get("body") or "")
    if len(body) > cfg.max_resource_bytes:
        raise _AttemptError(status, "response exceeds max_resource_bytes", retryable=False)
    return _Fetched(status, final_url, body, result.get("type") or "", number_of_redirects)


# --------------------------------------------------------------------------- #
# urllib-side
# --------------------------------------------------------------------------- #

def _cookie_header(ctx: _Context, url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    pairs: list[str] = []
    for c in ctx.cookies:
        name, value = c.get("name"), c.get("value")
        if not name or value is None:
            continue
        domain = (c.get("domain") or "").lstrip(".").lower()
        if domain and not (host == domain or host.endswith("." + domain)):
            continue
        if not path.startswith(c.get("path") or "/"):
            continue
        if c.get("secure") and parts.scheme != "https":
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _build_headers(approach: str, ctx: _Context, url: str) -> dict[str, str]:
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

    if approach == "origin_referer":
        p = urlsplit(ctx.page_url)
        headers = {
            "User-Agent": ctx.user_agent,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Referer": f"{p.scheme}://{p.netloc}/",
        }
        cookie = _cookie_header(ctx, url)
        if cookie:
            headers["Cookie"] = cookie
        return headers

    # generic_minimal
    return {
        "User-Agent": _GENERIC_UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }


def _decode_body(raw: bytes, encoding: str) -> bytes:
    enc = encoding.strip().lower()
    try:
        if enc in ("", "identity"):
            return raw
        if enc in ("gzip", "x-gzip"):
            return gzip.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except (OSError, EOFError, zlib.error) as exc:
        raise _AttemptError(None, f"decompression failed ({enc}): {exc!r}") from exc
    raise _AttemptError(None, f"unsupported Content-Encoding: {enc}", retryable=False)


def _http_get(url: str, headers: dict[str, str], cfg: FetchConfig,
              opener: urllib.request.OpenerDirector) -> _Fetched:
    deadline = time.monotonic() + cfg.total_timeout
    current = url
    number_of_redirects: list[str] = []

    for _ in range(cfg.max_redirects + 1):
        req = urllib.request.Request(current, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=cfg.request_timeout) as resp:
                status = resp.status
                if status not in cfg.success_statuses:
                    raise _AttemptError(status, f"HTTP {status}", retryable=False,
                                        redirects=tuple(number_of_redirects))
                chunks: list[bytes] = []
                total = 0
                while True:
                    if time.monotonic() > deadline:
                        raise _AttemptError(None, "total timeout exceeded",
                                            redirects=tuple(number_of_redirects))
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > cfg.max_resource_bytes:
                        raise _AttemptError(status, "response exceeds max_resource_bytes",
                                            retryable=False, redirects=tuple(number_of_redirects))
                    chunks.append(chunk)
                body = _decode_body(b"".join(chunks),
                                    resp.headers.get("Content-Encoding", ""))
                return _Fetched(status, current, body,
                                resp.headers.get("Content-Type", ""), tuple(number_of_redirects))

        except urllib.error.HTTPError as exc:
            code = exc.code
            location = exc.headers.get("Location") if exc.headers else None
            exc.close()
            if code in cfg.redirect_statuses:
                if not location:
                    raise _AttemptError(code, "redirect without Location header",
                                        retryable=False, redirects=tuple(number_of_redirects)) from exc
                current = urljoin(current, location)
                if urlsplit(current).scheme not in ("http", "https"):
                    raise _AttemptError(code, f"redirect to unsupported scheme: {current}",
                                        retryable=False, redirects=tuple(number_of_redirects)) from exc
                number_of_redirects.append(current)
                continue
            raise _AttemptError(code, f"HTTP {code}",
                                retryable=code in cfg.retryable_statuses,
                                redirects=tuple(number_of_redirects)) from exc

        except _AttemptError:
            raise

        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise _AttemptError(None, f"network error: {exc!r}", redirects=tuple(number_of_redirects)) from exc
            
        except ValueError as exc:
            raise _AttemptError(None, f"invalid request: {exc!r}", retryable=False) from exc

    raise _AttemptError(
        None, 
        f"too many redirects (> {cfg.max_redirects})",
        retryable=False, 
        redirects=tuple(number_of_redirects)
    )

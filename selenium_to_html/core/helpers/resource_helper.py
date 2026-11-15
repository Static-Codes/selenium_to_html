"""Resource discovery (HTML -> refs) and media embedding (refs -> data: URIs)."""

from __future__ import annotations

import base64
import logging
import mimetypes
import re
from urllib.parse import urldefrag, urljoin, urlsplit

from ..types.fetch_config import FetchConfig, ResourceRef
from ..types.resource_parsing import _ResourceParser
from ..types.result_types import ResourceResult

logger = logging.getLogger("selenium_to_html.resource_helper")

_SKIP_SCHEMES = ("data:", "javascript:", "blob:", "about:", "mailto:", "tel:")

# Matches 'src=*' inside a raw start tag. 
# The leading '\s' keeps the patern from matching both 'data-src=*' and 'lazy-src=*'.
_SRC_ATTR_RE = re.compile(r"""(\ssrc\s*=\s*)("[^"]*"|'[^']*'|[^\s"'>]+)""", re.IGNORECASE)


def _extract_refs(
    html: str,
    base_url: str,
    page_url: str,
    cfg: FetchConfig,
    browser_base: bool,
) -> list[ResourceRef]:
    parser = _ResourceParser(cfg.include_media or cfg.embed_media)
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # HTMLParser is lenient, but never let it sink the run
        logger.exception("HTML parser raised; using partial results")

    # document.baseURI already accounts for <base>; only apply it manually
    # when we could not get the browser's own value.
    effective_base = base_url
    if not browser_base and parser.base_href:
        effective_base = urljoin(base_url, parser.base_href)

    page_origin = urlsplit(page_url)[:2]
    seen: dict[str, ResourceRef] = {}

    for tag, attr, raw, kind, tag_text in parser.found:
        if not raw or raw.lower().startswith(_SKIP_SCHEMES):
            continue
        try:
            url = urldefrag(urljoin(effective_base, raw))[0]
            parts = urlsplit(url)
        except ValueError:
            logger.warning("Unparseable resource URL skipped: %r", raw)
            continue
        if parts.scheme not in ("http", "https") or not parts.netloc:
            continue
        if cfg.same_origin_only and parts[:2] != page_origin:
            continue

        if url in seen:
            ref = seen[url]
            ref.occurrences += 1
        else:
            ref = seen[url] = ResourceRef(url=url, tag=tag, attr=attr, kind=kind)
        if tag_text and tag_text not in ref.tag_texts:
            ref.tag_texts.append(tag_text)

    return list(seen.values())


def _data_uri(res: ResourceResult) -> str:
    mime = res.content_type.split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(urlsplit(res.final_url or res.ref.url).path)
        mime = guessed or mime or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(res.body).decode('ascii')}"


def _embed_media(
    html: str, results: list[ResourceResult], cfg: FetchConfig
) -> tuple[str, int]:
    """
    Return (html, count) with the src attribute of every successfully fetched
    media tag replaced by a base64 data: URI. Failed or oversized resources
    are left pointing at their original URL.
    """
    out = html
    embedded = 0
    done: set[str] = set()

    for res in results:
        if res.ref.kind != "media" or not res.ok or not res.body:
            continue
        if len(res.body) > cfg.embed_max_bytes:
            logger.warning("Not embedding %s: %d bytes exceeds embed_max_bytes",
                           res.ref.url, len(res.body))
            continue

        uri = _data_uri(res)
        for tag_text in res.ref.tag_texts:
            if tag_text in done:
                continue
            done.add(tag_text)
            # Callable replacement avoids backslash/group-escape surprises.
            new_tag, n = _SRC_ATTR_RE.subn(
                lambda m, u=uri: f'{m.group(1)}"{u}"', tag_text, count=1)
            if n:
                out = out.replace(tag_text, new_tag)
                embedded += 1

    return out, embedded

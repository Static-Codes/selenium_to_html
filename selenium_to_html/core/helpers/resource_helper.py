"""
This file contains helper functions for selenium_to_html's resource discovery/extraction and media embedding operations.
""" 

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


def _extract_references(
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


def _get_mime_type(res: ResourceResult) -> str:
    """
    Attempts to resolve the mime type for the provided ResourceResult.
    Returns "application/octet-stream" as a fallback if resolution fails.
    """
    mime_type = res.content_type.split(";")[0].strip().lower()
    
    if not mime_type or mime_type == "application/octet-stream":
        guessed_type, path = mimetypes.guess_type(
            urlsplit(res.final_url or res.ref.url).path
        )
        
        mime_type = guessed_type or mime_type or "application/octet-stream"

def _res_to_data_uri(res: ResourceResult) -> str:
    return f"data:{_get_mime_type(res)};base64,{base64.b64encode(res.body).decode('ascii')}"


def _embed_media(html: str, results: list[ResourceResult], cfg: FetchConfig) -> tuple[str, int]:
    """
    Returns a tuple (html: str, count: int) where "html" contains the modified page source, with each resolved "src" attribute replaced with it's base64 data: URI representation.

    Note: 
    Attributes are not replaced in if:
    - A fetch operation for a given resource operation fails
    - The desired resource's size exceeds "cfg.max_resource_bytes".
    """
    output = html
    number_of_embedded_attributes = 0
    embedded_attributes: set[str] = set()

    for result in results:
        if result.ref.kind != "media" or not result.ok or not result.body:
            continue

        if len(result.body) > cfg.embed_max_bytes:
            logger.warning("Not embedding %s: %d bytes exceeds embed_max_bytes", result.ref.url, len(result.body))
            continue

        uri = _res_to_data_uri(result)
        for tag_text in result.ref.tag_texts:
            
            if tag_text in embedded_attributes:
                continue

            embedded_attributes.add(tag_text)

            # Escaping/sanitizing tags to avoid backslashes.
            # The lambda expression isn't necessary, but it helpful for formatting purposes.
            new_tag, number_of_replacements = _SRC_ATTR_RE.subn(
                lambda match, uri=uri: f'{match.group(1)}"{uri}"', tag_text, count=1
            )

            if number_of_replacements:
                output = output.replace(tag_text, new_tag)
                number_of_embedded_attributes += 1

    return output, number_of_embedded_attributes

"""
A hardened replacement for Selenium's driver.page_source inspired by zebbern's website-clone.

selenium_to_html follows the same initial principle of retrieving the raw page source as Selenium, but with added hardening. Every externally linked resource is fetched in parallel with socketed requests. Each requests goes through a layered fallback approach, which maintains a full stacktrace upon failure.

Media embedding is opt-in by default, as it will produce differing output when compared to Selenium's driver.page_source.

When enabled, all media (both local and remote resources) will be embedded as base64 'data:' URIs in the outputted HTML.

The public API exposes: FetchConfig, FetchAttempt, ResourceRef, ResourceResult, PageSnapshot, capture_page, and capture_page_sync.
"""

import logging

from .runner import capture_page, capture_page_sync
from .types.fetch_config import FetchConfig, ResourceRef
from .types.result_types import FetchAttempt, PageSnapshot, ResourceResult

# Throws a NullHandler if selenium_to_html is invoked without a logger instance configured.
logging.getLogger("selenium_to_html").addHandler(logging.NullHandler())

__all__ = [
    "FetchConfig",
    "FetchAttempt",
    "ResourceRef",
    "ResourceResult",
    "PageSnapshot",
    "capture_page",
    "capture_page_sync",
]

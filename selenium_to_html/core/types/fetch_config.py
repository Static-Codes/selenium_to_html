"""Configuration and resource-reference types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FetchConfig:
    
    # The number of concurrent workers.
    max_concurrency: int = 8

    # The number of seconds before a TimeoutException is thrown on each socket op.
    request_timeout: float = 15.0

    # The number of seconds a single attempt will be capped to before a TimeoutException is thrown.
    total_timeout: float = 60.0

    # The number of attempts each approach should receive.
    attempts_per_approach: int = 2

    # The base idle standby time that is exponentially increased.
    standby_idle_base: float = 0.5

    # The maximum idle standby time in seconds.
    standby_idle_max: float = standby_idle_base * 16

    # The maximum number of redirects allowed before an exception is thrown.
    max_redirects: int = 5

    # Handles 200 and 302 status codes that result in a 200 status code as the final result.
    success_statuses: frozenset[int] = frozenset({200})
    
    # Handles a 302 status redirect chains.
    redirect_statuses: frozenset[int] = frozenset({302})

    # Statuses that indicate a fatal failure.
    terminal_statuses: frozenset[int] = frozenset({404, 410})
    
    # Statuses that indicate another attempt should be made for this approach.
    retryable_statuses: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

    # If the request should only fetch resources from the same origin as defined by the 'origin' header.
    same_origin_only: bool = False
    
    # Handles <img>, <video>, <audio>, <source>, <track>, <embed>
    include_media: bool = False

    # Whether encountered media should be embedded as base64 into the resulting html artifact.
    embed_media: bool = False

    # The per resource cap for embedded artifacts, defaults to 2MiB.
    embed_max_bytes: int = 2 * 1024 * 1024

    # Whether or not selenium_to_html should step in to preform fallback operations.
    use_browser_fallback: bool = True
    
    # Whether or not selenium_to_html should verify the authenticity of the tls certificate served by the requested host.
    verify_tls: bool = True

    # The max number of 
    max_bytes: int = 25 * 1024 * 1024

    # The number of seconds selenium_to_html should wait for until throwing a TimeoutException.
    page_ready_timeout: float = 15.0

    # The number of attempts selenium_to_html should make to retrieve the page source for the provided Uri.
    page_source_attempts: int = 3

    # The number of seconds before a TimeoutException is thrown in:
    # selenium_to_html.core.helpers.browser_helper._JS_FETCH
    browser_script_timeout: float = 20.0


@dataclass(slots=True)
class ResourceRef:
    url: str # The absolute/relative url associated with the resource.
    tag: str  # The tag name associated with the current resource.
    attr: str # The attribute name associated with the current source.
    kind: str # A string repr of the resource kind, i.e: 'script', 'stylesheet', 'link', 'media', etc.
    occurrences: int = 1 # The number of times this resource has been located in the currently resolved page source.
    # A list of the raw start-tag text for each media tag that referenced this URL.
    # This is used to rewrite 'src' attributes when embedding any media. 
    # If this is empty, then kind is known to be a non-media type.
    tag_texts: list[str] = field(default_factory=list)

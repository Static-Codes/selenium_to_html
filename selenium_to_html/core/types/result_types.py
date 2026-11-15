"""This file contains result type declarations used during a capture operation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fetch_config import ResourceRef


@dataclass(slots=True)
class FetchAttempt:
    """Represents an attempt made to fetch a given resource."""
    approach: str
    attempt: int
    ok: bool
    status: int | None
    final_url: str | None
    redirects: tuple[str, ...]
    error: str | None
    elapsed: float


@dataclass(slots=True)
class ResourceResult:
    """Represents the result of the fetching operations for a given ResourceRef."""
    ref: ResourceRef
    ok: bool
    status: int | None = None
    final_url: str | None = None
    content_type: str = ""
    body: bytes = b""
    approach: str | None = None            # approach that produced success
    attempts: list[FetchAttempt] = field(default_factory=list)

    def text(self, errors: str = "replace") -> str:
        charset = "utf-8"
        for part in self.content_type.split(";")[1:]:
            k, _, v = part.strip().partition("=")
            if k.lower() == "charset" and v:
                charset = v.strip("\"' ")
        try:
            return self.body.decode(charset, errors)
        except LookupError:
            return self.body.decode("utf-8", errors)


@dataclass(slots=True)
class PageSnapshot:
    """Represents the captured snapshot of the active page in the provided driver instance."""
    page_url: str # The active page's full url.
    base_url: str # The base url from where the resource is served from.
    page_source: str # The raw page source of the active page.
    resources: list[ResourceResult] # A collection resolved resources from the raw page source.
    elapsed: float # The seconds that have elapsed in the current operation.
    
    embedded_source: str | None = None # The page's rendered source code; this is set when embed_media is enabled.
    embedded_count: int = 0 # The number of tags that had their resource embedded as 'data:' URIs.

    @property
    def succeeded(self) -> list[ResourceResult]:
        return [resource for resource in self.resources if resource.ok]

    @property
    def failures(self) -> list[ResourceResult]:
        return [resource for resource in self.resources if not resource.ok]

    def failure_report(self) -> list[dict[str, Any]]:
        """Generates a dictionary containing a log of the events leading up to a fatal failure."""
        return [
            {
                "url": failure.ref.url,
                "tag": failure.ref.tag,
                "kind": failure.ref.kind,
                "attempts": [
                    {
                        "approach": attempt.approach,
                        "attempt": attempt.attempt,
                        "status": attempt.status,
                        "error": attempt.error,
                        "redirects": list(attempt.redirects),
                        "elapsed": round(attempt.elapsed, 3),
                    }
                    for attempt in failure.attempts
                ],
            }
            for failure in self.failures
        ]

"""Result types returned by a capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fetch_config import ResourceRef


@dataclass(slots=True)
class FetchAttempt:
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
    page_url: str
    base_url: str
    page_source: str
    resources: list[ResourceResult]
    elapsed: float
    embedded_source: str | None = None     # set when embed_media=True
    embedded_count: int = 0                # media tags rewritten to data: URIs

    @property
    def succeeded(self) -> list[ResourceResult]:
        return [r for r in self.resources if r.ok]

    @property
    def failures(self) -> list[ResourceResult]:
        return [r for r in self.resources if not r.ok]

    def failure_report(self) -> list[dict[str, Any]]:
        """Plain-dict failure log, convenient for serialisation."""
        return [
            {
                "url": r.ref.url,
                "tag": r.ref.tag,
                "kind": r.ref.kind,
                "attempts": [
                    {
                        "approach": a.approach,
                        "attempt": a.attempt,
                        "status": a.status,
                        "error": a.error,
                        "redirects": list(a.redirects),
                        "elapsed": round(a.elapsed, 3),
                    }
                    for a in r.attempts
                ],
            }
            for r in self.failures
        ]

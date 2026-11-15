"""This file contains declarations for internal_types helper types shared between the helper modules and the runner."""

from __future__ import annotations

import asyncio
import urllib.request
from dataclasses import dataclass
from typing import Any

from .fetch_config import FetchConfig


class _AttemptError(Exception):
    def __init__(
        self,
        status: int | None,
        message: str,
        *,
        retryable: bool = True,
        redirects: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.redirects = redirects


@dataclass(slots=True)
class _Fetched:
    status: int
    final_url: str
    body: bytes
    content_type: str
    redirects: tuple[str, ...]


@dataclass(slots=True)
class _Context:
    driver: Any
    cfg: FetchConfig
    page_url: str
    user_agent: str
    cookies: list[dict[str, Any]]
    opener: urllib.request.OpenerDirector
    driver_lock: asyncio.Lock


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects as HTTPError so we can validate each hop ourselves."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None

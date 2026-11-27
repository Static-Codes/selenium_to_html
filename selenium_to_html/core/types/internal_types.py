"""This file contains declarations for internal_types helper types shared between the helper modules and the runner."""

from __future__ import annotations

import asyncio
import urllib.request
from dataclasses import dataclass
from typing import Any, override

from .fetch_config import FetchConfig


class AttemptError(Exception):
    def __init__(
        self,
        status: int | None,
        message: str,
        *,
        retryable: bool = True,
        redirects: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status: int | None = status
        self.retryable: bool = retryable
        self.redirects: tuple[str, ...] = redirects


@dataclass(slots=True)
class Response:
    status: int
    final_url: str
    body: bytes
    content_type: str
    redirects: tuple[str, ...]


@dataclass(slots=True)
class Context:
    driver: Any  # pyright: ignore[reportExplicitAny]
    cfg: FetchConfig
    page_url: str
    user_agent: str
    cookies: list[dict[str, Any]]  # pyright: ignore[reportExplicitAny]
    request_opener: urllib.request.OpenerDirector
    driver_lock: asyncio.Lock


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """
    Explicitly marks a redirect as an HTTPError.
    This allows a redirect to be validated prior to its execution.

    Marked as noqa: D401 so UV doesnt complain.
    """

    @override
    
    # noqa: D401
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pyright: ignore[reportMissingParameterType]
        return None

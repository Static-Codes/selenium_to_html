"""Regression-test fixtures: deterministic, no real network or browsers."""
from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest


class _BlockedSocket(socket.socket):
    def connect(self, *args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("Network access is disabled in regression tests")

    def connect_ex(self, *args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("Network access is disabled in regression tests")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Best-effort guard against accidental outbound sockets in regression tests."""

    def blocked(*_args, **_kwargs):
        raise AssertionError("Network access is disabled in regression tests")

    monkeypatch.setattr(socket, "socket", _BlockedSocket)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def fake_driver():
    """Configurable fake Selenium driver for helper/runner tests."""

    class Driver:
        def __init__(self):
            self.current_url = "https://example.test/page"
            self.ready_states = ["complete"]
            self.ready_index = 0
            self.page_source = "<html><body>ok</body></html>"
            self.cookies = []
            self.script_timeout = None
            self.execute_script_calls = []
            self.execute_async_script_calls = []
            self.outer_html = None
            self.base_uri = "https://example.test/page"
            self.user_agent = "TestAgent/1.0"
            self.ready_state_error = None
            self.page_source_error = None
            self.outer_html_error = None
            self.current_url_error = None
            self.base_uri_error = None
            self.user_agent_error = None
            self.cookies_error = None
            self.async_result = None
            self.async_error = None

        def execute_script(self, script, *args):
            self.execute_script_calls.append((script, args))
            if script == "return document.readyState":
                if self.ready_state_error:
                    raise self.ready_state_error
                idx = min(self.ready_index, len(self.ready_states) - 1)
                state = self.ready_states[idx]
                self.ready_index += 1
                return state
            if "document.documentElement" in script and "outerHTML" in script:
                if self.outer_html_error:
                    raise self.outer_html_error
                return self.outer_html
            if script == "return document.baseURI":
                if self.base_uri_error:
                    raise self.base_uri_error
                return self.base_uri
            if script == "return navigator.userAgent":
                if self.user_agent_error:
                    raise self.user_agent_error
                return self.user_agent
            raise AssertionError(f"Unexpected execute_script: {script}")

        def execute_async_script(self, script, *args):
            self.execute_async_script_calls.append((script, args))
            if self.async_error:
                raise self.async_error
            return self.async_result

        def set_script_timeout(self, timeout):
            self.script_timeout = timeout

        def get_cookies(self):
            if self.cookies_error:
                raise self.cookies_error
            return self.cookies

        @property
        def current_url_value(self):  # helper, not selenium API
            return self.current_url

    driver = Driver()
    # expose current_url as attribute that can raise via property-like behavior in tests
    return driver


class FakeHTTPResponse:
    """Minimal urllib response/context-manager for _http_get tests."""

    def __init__(self, status=200, headers=None, chunks=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self._chunks = list(chunks) if chunks is not None else ([body] if body is not None else [])
        self.closed = False

    def read(self, n=-1):
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if n < 0 or len(chunk) <= n:
            return chunk
        head, tail = chunk[:n], chunk[n:]
        self._chunks.insert(0, tail)
        return head

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False


class FakeOpener:
    def __init__(self, responses=None, side_effect=None):
        self.responses = list(responses or [])
        self.side_effect = list(side_effect or [])
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        if self.side_effect:
            effect = self.side_effect.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            if callable(effect):
                return effect(req, timeout)
            return effect
        if not self.responses:
            raise AssertionError("FakeOpener has no more responses")
        resp = self.responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return resp


@pytest.fixture
def fake_http_response():
    return FakeHTTPResponse


@pytest.fixture
def fake_opener():
    return FakeOpener

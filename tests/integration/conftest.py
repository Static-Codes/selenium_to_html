"""Integration fixtures: local HTTP server and real Selenium drivers."""
from __future__ import annotations

import functools
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class FixtureHandler(SimpleHTTPRequestHandler):
    """Serves static fixtures plus simple dynamic endpoints for status scenarios."""

    server_version = "FixtureHTTP/1.0"
    _retry_counts: dict[str, int] = {}
    _lock = threading.Lock()

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self):  # noqa: N802
        self._dispatch("HEAD")

    def log_message(self, fmt, *args):  # quieter test output
        return

    def _dispatch(self, method: str):
        parsed = urlsplit(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/__status__":
            code = int(qs.get("code", ["200"])[0])
            body = qs.get("body", [f"status-{code}"])[0].encode()
            self._send_bytes(code, body, "text/plain; charset=utf-8", head_only=(method == "HEAD"))
            return

        if path == "/__redirect__":
            to = qs.get("to", ["/"])[0]
            code = int(qs.get("code", ["302"])[0])
            self.send_response(code)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/__retry__":
            key = qs.get("key", ["default"])[0]
            fail = int(qs.get("fail", ["1"])[0])
            code = int(qs.get("code", ["429"])[0])
            with self._lock:
                count = self._retry_counts.get(key, 0) + 1
                self._retry_counts[key] = count
            if count <= fail:
                body = f"retry-{count}".encode()
                self._send_bytes(code, body, "text/plain; charset=utf-8", head_only=(method == "HEAD"))
            else:
                body = b"ok-after-retry"
                self._send_bytes(200, body, "text/plain; charset=utf-8", head_only=(method == "HEAD"))
            return

        if path == "/__slow__":
            delay = float(qs.get("delay", ["0"])[0])
            time.sleep(delay)
            body = b"slow-ok"
            self._send_bytes(200, body, "text/plain; charset=utf-8", head_only=(method == "HEAD"))
            return

        if path == "/__reset_retry__":
            key = qs.get("key", [None])[0]
            with self._lock:
                if key is None:
                    self._retry_counts.clear()
                else:
                    self._retry_counts.pop(key, None)
            self._send_bytes(200, b"reset", "text/plain", head_only=(method == "HEAD"))
            return

        # fall back to static file serving
        if method == "HEAD":
            # SimpleHTTPRequestHandler implements do_HEAD
            return super().do_GET() if False else self._do_head_static()
        return super().do_GET()

    def _do_head_static(self):
        # leverage SimpleHTTPRequestHandler logic by calling do_GET-like send_head path
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = urlsplit(self.path)
            if not parts.path.endswith('/'):
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                new_parts = (parts.scheme, parts.netloc, parts.path + '/', parts.query, parts.fragment)
                from urllib.parse import urlunsplit
                self.send_header("Location", urlunsplit(new_parts))
                self.end_headers()
                return
            for index in ("index.html", "index.htm"):
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.send_error(HTTPStatus.NOT_FOUND, "File not found")
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        try:
            fs = os.fstat(f.fileno())
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", ctype)
            self.send_header("Content-Length", str(fs.st_size))
            self.end_headers()
        finally:
            f.close()

    def _send_bytes(self, code: int, body: bytes, content_type: str, head_only: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


@pytest.fixture(scope="session")
def local_server():
    """Serve tests/fixtures over HTTP on 127.0.0.1 for real-browser tests."""
    handler = functools.partial(FixtureHandler, directory=str(FIXTURES_DIR))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def _selected_browsers():
    raw = os.getenv("SELENIUM_BROWSERS")
    if not raw:
        return {"chrome", "firefox", "safari"}
    return {b.strip().lower() for b in raw.split(",") if b.strip()}


@pytest.fixture
def browser_driver(request):
    """Create a real WebDriver for the requested browser or skip if unavailable."""
    selenium = pytest.importorskip("selenium")
    from selenium import webdriver

    browser = request.param
    selected = _selected_browsers()
    if browser not in selected:
        pytest.skip(f"{browser} not selected via SELENIUM_BROWSERS")

    driver = None
    try:
        if browser == "chrome":
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--allow-insecure-localhost")
            options.add_argument("--remote-allow-origins=*")
            driver = webdriver.Chrome(options=options)
        elif browser == "firefox":
            options = webdriver.FirefoxOptions()
            options.add_argument("-headless")
            driver = webdriver.Firefox(options=options)
        elif browser == "safari":
            if sys.platform != "darwin":
                pytest.skip("Safari integration tests require macOS")
            options = webdriver.SafariOptions()
            driver = webdriver.Safari(options=options)
        else:  # pragma: no cover
            pytest.skip(f"Unknown browser: {browser}")
    except Exception as exc:
        pytest.skip(f"{browser} WebDriver unavailable: {exc}")

    try:
        yield browser, driver
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

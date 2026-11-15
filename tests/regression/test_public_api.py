import inspect
import logging

import selenium_to_html.core as core
from selenium_to_html.core.types.fetch_config import FetchConfig, ResourceRef
from selenium_to_html.core.types.result_types import FetchAttempt, PageSnapshot, ResourceResult


def test_core_exports_and_all_match_documented_surface():
    expected = {
        "FetchConfig",
        "FetchAttempt",
        "ResourceRef",
        "ResourceResult",
        "PageSnapshot",
        "capture_page",
        "capture_page_sync",
    }
    assert expected.issubset(set(core.__all__))
    for name in core.__all__:
        assert hasattr(core, name)


def test_capture_functions_shapes():
    assert inspect.iscoroutinefunction(core.capture_page)
    assert callable(core.capture_page_sync)
    assert not inspect.iscoroutinefunction(core.capture_page_sync)


def test_resource_result_text_decodes_charset_and_falls_back():
    res = ResourceResult(
        ref=ResourceRef(url="https://e.test/a.txt", tag="script", attr="src", kind="script"),
        ok=True,
        content_type="text/plain; charset=utf-8",
        body="hé".encode("utf-8"),
    )
    assert res.text() == "hé"

    res.content_type = "text/plain; charset=unknown-charset"
    res.body = b"ok"
    assert res.text() == "ok"

    res.content_type = ""
    res.body = b"\xff\xfe"
    assert "�" in res.text()


def test_pagesnapshot_properties_and_failure_report_shape():
    ok_ref = ResourceRef(url="https://e.test/ok.js", tag="script", attr="src", kind="script")
    bad_ref = ResourceRef(url="https://e.test/bad.css", tag="link", attr="href", kind="stylesheet")
    ok = ResourceResult(ref=ok_ref, ok=True, status=200)
    bad = ResourceResult(
        ref=bad_ref,
        ok=False,
        attempts=[
            FetchAttempt(
                approach="generic_minimal",
                attempt=1,
                ok=False,
                status=404,
                final_url=None,
                redirects=("https://e.test/r",),
                error="HTTP 404",
                elapsed=0.1236,
            )
        ],
    )
    snap = PageSnapshot(
        page_url="https://e.test/page",
        base_url="https://e.test/page",
        page_source="<html></html>",
        resources=[ok, bad],
        elapsed=0.5,
    )
    assert snap.succeeded == [ok]
    assert snap.failures == [bad]
    report = snap.failure_report()
    assert report == [
        {
            "url": "https://e.test/bad.css",
            "tag": "link",
            "kind": "stylesheet",
            "attempts": [
                {
                    "approach": "generic_minimal",
                    "attempt": 1,
                    "status": 404,
                    "error": "HTTP 404",
                    "redirects": ["https://e.test/r"],
                    "elapsed": 0.124,
                }
            ],
        }
    ]


def test_readme_import_surface_mismatch_is_pinned():
    # README documents `from selenium_to_html import ...`, but current package root
    # has no __init__ exports and may resolve as an implicit namespace package.
    import importlib

    mod = importlib.import_module("selenium_to_html")
    assert not hasattr(mod, "capture_page")
    assert not hasattr(mod, "capture_page_sync")
    assert not hasattr(mod, "FetchConfig")


def test_core_registers_null_handler():
    logger = logging.getLogger("selenium_to_html")
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)

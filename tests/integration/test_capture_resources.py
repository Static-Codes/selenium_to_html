import pytest

from selenium_to_html.core import capture_page_sync
from selenium_to_html.core.types.fetch_config import FetchConfig

pytestmark = pytest.mark.integration

BROWSERS = [pytest.param("chrome", marks=pytest.mark.chrome),
            pytest.param("firefox", marks=pytest.mark.firefox),
            pytest.param("safari", marks=pytest.mark.safari)]


@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
def test_capture_local_resources_statuses_and_redirects(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/resources.html")
    snap = capture_page_sync(driver, FetchConfig(max_concurrency=4, include_media=True))

    by_url = {r.ref.url: r for r in snap.resources}

    # static assets ok
    ok_assets = [r for r in snap.resources if r.ok]
    assert any(u.endswith("/assets/app.js") for u in by_url)
    assert any(u.endswith("/assets/style.css") for u in by_url)
    assert any(u.endswith("/assets/icon.svg") for u in by_url)

    # redirecting script should resolve to success (final app.js)
    redirect_results = [r for r in snap.resources if "__redirect__" in r.ref.url or r.final_url and r.final_url.endswith("/assets/app.js")]
    assert redirect_results, f"expected redirect-handled resource in {[r.ref.url for r in snap.resources]}"
    assert any(r.ok for r in redirect_results)

    # terminal statuses become failures
    failed_urls = [r.ref.url for r in snap.failures]
    assert any("__status__?code=404" in u for u in failed_urls), snap.failure_report()
    assert any("__status__?code=410" in u for u in failed_urls), snap.failure_report()
    for r in snap.failures:
        if "__status__?code=404" in r.ref.url or "__status__?code=410" in r.ref.url:
            assert r.status in {404, 410}


@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
def test_capture_include_media_toggles_discovery(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/resources.html")

    snap_no = capture_page_sync(driver, FetchConfig(include_media=False))
    assert not any(r.ref.kind == "media" for r in snap_no.resources)
    assert not any(r.ref.url.endswith("/assets/media.svg") for r in snap_no.resources)

    snap_yes = capture_page_sync(driver, FetchConfig(include_media=True))
    assert any(r.ref.kind == "media" and r.ref.url.endswith("/assets/media.svg") for r in snap_yes.resources)


@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
def test_capture_no_browser_fallback_still_fetches_local(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/basic.html")
    snap = capture_page_sync(driver, FetchConfig(use_browser_fallback=False, max_concurrency=4))
    assert any(r.ok and r.ref.url.endswith("/assets/app.js") for r in snap.resources)
    assert all(a.approach != "browser_fetch" for a in [at for r in snap.resources for at in r.attempts] if a.ok)

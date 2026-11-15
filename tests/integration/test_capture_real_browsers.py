import pytest

from selenium_to_html.core import capture_page, capture_page_sync
from selenium_to_html.core.types.fetch_config import FetchConfig

pytestmark = pytest.mark.integration

BROWSERS = [pytest.param("chrome", marks=pytest.mark.chrome),
            pytest.param("firefox", marks=pytest.mark.firefox),
            pytest.param("safari", marks=pytest.mark.safari)]


@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
def test_capture_sync_happy_path_local_assets(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/basic.html")
    snap = capture_page_sync(driver, FetchConfig(max_concurrency=4))
    assert snap.page_url.rstrip("/").endswith("/pages/basic.html")
    assert "<h1" in snap.page_source and "basic-ok" in snap.page_source
    urls = [r.ref.url for r in snap.resources]
    assert any(u.endswith("/assets/app.js") for u in urls)
    assert any(u.endswith("/assets/style.css") for u in urls)
    assert all(r.ok for r in snap.resources), snap.failure_report()
    assert snap.elapsed >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
async def test_capture_async_happy_path(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/basic.html")
    snap = await capture_page(driver, FetchConfig(max_concurrency=4))
    assert any(r.ok and r.ref.url.endswith("/assets/app.js") for r in snap.resources)
    assert any(r.ok and r.ref.url.endswith("/assets/style.css") for r in snap.resources)

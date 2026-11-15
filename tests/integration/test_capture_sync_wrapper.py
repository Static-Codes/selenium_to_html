import pytest

from selenium_to_html.core import capture_page_sync
from selenium_to_html.core.types.fetch_config import FetchConfig

pytestmark = pytest.mark.integration

BROWSERS = [pytest.param("chrome", marks=pytest.mark.chrome),
            pytest.param("firefox", marks=pytest.mark.firefox),
            pytest.param("safari", marks=pytest.mark.safari)]


@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
def test_capture_page_sync_from_plain_context(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/basic.html")
    snap = capture_page_sync(driver, FetchConfig(max_concurrency=2))
    assert snap.page_source
    assert isinstance(snap.resources, list)
    assert any(r.ref.url.endswith("/assets/style.css") for r in snap.resources)

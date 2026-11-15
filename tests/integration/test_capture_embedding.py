import pytest

from selenium_to_html.core import capture_page_sync
from selenium_to_html.core.types.fetch_config import FetchConfig

pytestmark = pytest.mark.integration

BROWSERS = [pytest.param("chrome", marks=pytest.mark.chrome),
            pytest.param("firefox", marks=pytest.mark.firefox),
            pytest.param("safari", marks=pytest.mark.safari)]


@pytest.mark.parametrize("browser_driver", BROWSERS, indirect=True)
def test_capture_embeds_local_media_as_data_uris(browser_driver, local_server):
    browser, driver = browser_driver
    driver.get(f"{local_server}/pages/embed_local.html")
    snap = capture_page_sync(driver, FetchConfig(embed_media=True, max_concurrency=4))

    assert snap.embedded_source is not None
    assert "data:image/svg+xml;base64," in snap.embedded_source
    # two img tags reference same asset but are distinct tag texts
    assert snap.embedded_count >= 1
    # non-media script should remain a normal fetched resource, not rewritten as data URI in source by embedder
    assert any(r.ok and r.ref.kind == "script" and r.ref.url.endswith("/assets/app.js") for r in snap.resources)
    assert 'src="../assets/app.js"' in snap.embedded_source or "/assets/app.js" in snap.embedded_source

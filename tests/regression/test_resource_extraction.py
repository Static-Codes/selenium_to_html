from selenium_to_html.core.helpers.resource_helper import _extract_refs
from selenium_to_html.core.types.fetch_config import FetchConfig


def _urls(refs):
    return [r.url for r in refs]


def test_extract_refs_resolves_filters_dedupes_and_collects_tag_texts():
    html = """
    <base href="/sub/">
    <script src="app.js"></script>
    <script src="app.js#frag"></script>
    <link rel="stylesheet" href="https://other.test/x.css">
    <img src="/img.png">
    <img src="/img.png">
    <a href="mailto:a@b.test">m</a>
    """
    cfg = FetchConfig(include_media=True, same_origin_only=False)
    refs = _extract_refs(html, "https://example.test/page", "https://example.test/page", cfg, browser_base=False)
    by_url = {r.url: r for r in refs}
    assert "https://example.test/sub/app.js" in by_url
    assert by_url["https://example.test/sub/app.js"].occurrences == 2
    assert "https://other.test/x.css" in by_url
    assert by_url["https://example.test/img.png"].occurrences == 2
    assert len(by_url["https://example.test/img.png"].tag_texts) == 1
    assert all("mailto:" not in u for u in _urls(refs))


def test_extract_refs_uses_browser_base_over_base_tag_and_applies_same_origin():
    html = '<base href="/wrong/"><script src="app.js"></script><link rel="stylesheet" href="https://other.test/x.css">'
    cfg = FetchConfig(same_origin_only=True)
    refs = _extract_refs(html, "https://example.test/from-browser/", "https://example.test/page", cfg, browser_base=True)
    assert _urls(refs) == ["https://example.test/from-browser/app.js"]


def test_extract_refs_skips_unsupported_and_unparseable_schemes():
    html = '''
    <script src="data:text/plain,hi"></script>
    <script src="javascript:alert(1)"></script>
    <script src="blob:abc"></script>
    <script src="about:blank"></script>
    <script src="tel:+123"></script>
    <script src="ftp://example.test/a.js"></script>
    <script src="//example.test/rel.js"></script>
    '''
    cfg = FetchConfig()
    refs = _extract_refs(html, "https://example.test/page", "https://example.test/page", cfg, browser_base=True)
    assert _urls(refs) == ["https://example.test/rel.js"]


def test_extract_refs_parser_exception_returns_partial(monkeypatch):
    from selenium_to_html.core.helpers import resource_helper

    class BoomParser(resource_helper._ResourceParser):
        def feed(self, data):
            super().feed(data)
            raise ValueError("boom")

    monkeypatch.setattr(resource_helper, "_ResourceParser", BoomParser)
    refs = resource_helper._extract_refs(
        '<script src="/a.js"></script><script src="/b.js"></script>',
        "https://example.test/",
        "https://example.test/",
        FetchConfig(),
        browser_base=True,
    )
    assert "https://example.test/a.js" in _urls(refs)

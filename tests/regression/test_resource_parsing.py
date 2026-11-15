from selenium_to_html.core.types.resource_parsing import _ResourceParser


def test_resource_parser_discovers_scripts_links_base_and_media():
    html = """
    <html><head>
      <base href="/base/">
      <script src="/a.js"></script>
      <link rel="stylesheet preload" href="/a.css">
      <link rel="icon" href="/favicon.ico">
      <link rel="alternate" href="/skip.html">
      <img src="/img.png">
      <video><source src="/v.mp4"><track src="/c.vtt"></video>
      <audio src="/a.ogg"></audio>
      <embed src="/e.bin">
    </head></html>
    """
    p = _ResourceParser(include_media=True)
    p.feed(html)
    assert p.base_href == "/base/"
    found = p.found
    assert ("script", "src", "/a.js", "script", "") in found
    assert ("link", "href", "/a.css", "stylesheet", "") in found
    assert ("link", "href", "/favicon.ico", "link", "") in found
    assert all(item[2] != "/skip.html" for item in found)
    media = [f for f in found if f[3] == "media"]
    assert [m[2] for m in media] == ["/img.png", "/v.mp4", "/c.vtt", "/a.ogg", "/e.bin"]
    assert all(m[4] and m[4].lstrip().startswith("<") for m in media)


def test_resource_parser_ignores_media_when_disabled():
    html = '<img src="/img.png"><script src="/a.js"></script>'
    p = _ResourceParser(include_media=False)
    p.feed(html)
    assert p.found == [("script", "src", "/a.js", "script", "")]

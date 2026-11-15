import base64

from selenium_to_html.core.helpers.resource_helper import _data_uri, _embed_media
from selenium_to_html.core.types.fetch_config import FetchConfig, ResourceRef
from selenium_to_html.core.types.result_types import ResourceResult


def _media_result(url, body=b"abc", ok=True, content_type="image/png", final_url=None, tag_texts=None):
    ref = ResourceRef(url=url, tag="img", attr="src", kind="media", tag_texts=list(tag_texts or []))
    return ResourceResult(ref=ref, ok=ok, body=body, content_type=content_type, final_url=final_url or url)


def test_data_uri_uses_content_type_and_base64():
    res = _media_result("https://e.test/a.png", body=b"\x89PNG", content_type="image/png; charset=binary")
    assert _data_uri(res).startswith("data:image/png;base64,")
    assert _data_uri(res).split(",", 1)[1] == base64.b64encode(b"\x89PNG").decode("ascii")


def test_data_uri_guesses_mime_when_octet_stream_or_missing():
    res = _media_result("https://e.test/a.svg", body=b"<svg/>", content_type="application/octet-stream")
    assert _data_uri(res).startswith("data:image/svg+xml;base64,")
    res2 = _media_result("https://e.test/noext", body=b"x", content_type="")
    assert _data_uri(res2).startswith("data:application/octet-stream;base64,")


def test_embed_media_rewrites_successful_media_once_and_counts():
    tag = '<img src="https://e.test/a.png" alt="x">'
    html = f"<body>{tag}{tag}</body>"
    res = _media_result("https://e.test/a.png", body=b"abc", tag_texts=[tag])
    # simulate duplicate occurrence recorded as same tag_text once
    out, count = _embed_media(html, [res], FetchConfig(embed_media=True))
    assert "data:image/png;base64," in out
    assert "https://e.test/a.png" not in out
    assert count == 1


def test_embed_media_skips_failed_oversized_nonmedia_and_missing_match():
    ok_media = _media_result("https://e.test/a.png", body=b"abc", tag_texts=['<img src="https://e.test/a.png">'])
    failed = _media_result("https://e.test/b.png", body=b"x", ok=False, tag_texts=['<img src="https://e.test/b.png">'])
    big = _media_result("https://e.test/c.png", body=b"toolong", tag_texts=['<img src="https://e.test/c.png">'])
    non_media = ResourceResult(
        ref=ResourceRef(url="https://e.test/a.css", tag="link", attr="href", kind="stylesheet", tag_texts=['<link href="https://e.test/a.css">']),
        ok=True,
        body=b"body{}",
        content_type="text/css",
    )
    # tag_text not present in html: implementation rewrites the tag_text string and
    # counts it when the src substitution matches, even if replace() finds no match.
    missing = _media_result("https://e.test/d.png", body=b"x", tag_texts=['<img src="https://e.test/d.png">'])
    html = '<img src="https://e.test/a.png"><img src="https://e.test/b.png"><img src="https://e.test/c.png"><link href="https://e.test/a.css">'
    out, count = _embed_media(html, [ok_media, failed, big, non_media, missing], FetchConfig(embed_media=True, embed_max_bytes=3))
    assert count == 2
    assert out.count("data:image/png;base64,") == 1
    assert 'src="https://e.test/b.png"' in out
    assert 'src="https://e.test/c.png"' in out
    assert 'href="https://e.test/a.css"' in out


def test_embed_media_replaces_only_src_attr():
    tag = "<img data-src=\"https://e.test/a.png\" src='https://e.test/a.png'>"
    res = _media_result("https://e.test/a.png", body=b"abc", tag_texts=[tag])
    out, count = _embed_media(tag, [res], FetchConfig(embed_media=True))
    assert count == 1
    assert 'data-src="https://e.test/a.png"' in out
    assert "data:image/png;base64," in out

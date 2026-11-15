"""

This file contains the ResourceParser implementation which overrides html.parser.HTMLParser.

ResourceParser dynamically resolves tag tokens defined in MEDIA_TAG_TOKENS and extracts located resources.

Notably, it does NOT handle the optional media embedding; that is handled in resource_helper.embed_media.
"""

from __future__ import annotations

from html.parser import HTMLParser

RELATIVE_LINK_TOKENS = frozenset({
    "stylesheet", "icon", "shortcut", "apple-touch-icon",
    "apple-touch-icon-precomposed", "preload", "modulepreload",
    "prefetch", "manifest", "mask-icon",
})

MEDIA_TAG_TOKENS = frozenset({"img", "video", "audio", "source", "track", "embed"})


class _ResourceParser(HTMLParser):
    def __init__(self, include_media: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.include_media = include_media
        self.base_href: str | None = None
        
        # This can be a tag, attribute, raw value, kind, OR raw starttag text.
        # (tag, attr, raw value, kind, raw start-tag text)
        self.found: list[tuple[str, str, str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """
        An override of HTMLParser's handle_starttag
        Refs: 
        https://docs.python.org/3/library/html.parser.html#html.parser.HTMLParser.handle_starttag
        
        https://loadingindigo.mystrikingly.com/blog/python-head#:~:text=etc%2E%29%2E-,The,handle%5Fstartendtag%28%29%29%3A
        """

        attributes = {key.lower(): (val or "").strip() for key, val in attrs}

        # Handling <base> tags. 
        if tag == "base":
            if attributes.get("href") and self.base_href is None:
                self.base_href = attributes["href"]
        
        # Handling <script> tags.
        elif tag == "script":
            if attributes.get("src"):
                self.found.append((tag, "src", attributes["src"], tag, ""))

        # Handling <link> tags.
        elif tag == "link":
            rel_attrs = set(attributes.get("rel", "").lower().split())
            
            # Handling both 
            if attributes.get("href") and rel_attrs & RELATIVE_LINK_TOKENS:
                kind = "stylesheet" if "stylesheet" in rel_attrs else "link"
                self.found.append((tag, "href", attributes["href"], kind, ""))

        # The parser was explicitly designated to be discovery-only; ALL base64 operations are handled in resource_helper.embed_media. 
        elif self.include_media and tag in MEDIA_TAG_TOKENS:
            if attributes.get("src"):
                
                # The original source attribute is preserved here to ensure backwards compatibility with Selenium's driver.page_source.
                self.found.append(
                    (tag, "src", attributes["src"], "media", self.get_starttag_text() or "")
                )

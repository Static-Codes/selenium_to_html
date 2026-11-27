"""

This file contains the ResourceParser implementation which overrides html.parser.HTMLParser.

ResourceParser dynamically resolves tag tokens defined in MEDIA_TAG_TOKENS and extracts located resources.

Notably, it does NOT handle the optional media embedding; that is handled in resource_helper.embed_media.
"""

from __future__ import annotations

from html.parser import HTMLParser
import logging

RELATIVE_LINK_TOKENS = frozenset({
    "stylesheet", "icon", "shortcut", "apple-touch-icon",
    "apple-touch-icon-precomposed", "preload", "modulepreload",
    "prefetch", "manifest", "mask-icon",
})

MEDIA_TAG_TOKENS = frozenset({"image", "svg", "img", "video", "audio", "source", "track", "embed", })


class ResourceParser(HTMLParser):
    def __init__(self, include_media: bool, logger: logging.Logger, debug: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        
        # Whether or not media tags should be parsed.
        self.include_media = include_media

        # The logger used during execution.
        self.logger: logging.Logger = logger

        # If debug logs should be printed to stdout
        self.debug: bool = debug

        self.base_href: str | None = None
        
        # This can be a tag, attribute, raw value, kind, OR raw starttag text.
        # (tag, attr, raw value, kind, raw start-tag text)
        self.found_resources: list[tuple[str, str, str, str, str]] = []

        # Used to track the last reconstructed start tag text.
        self.last_tag_text: str = ""

        # Elements parsed but not captured as external resources, keyed by source position.
        self.inline_resources: dict[tuple[int, int], str] = {}

    def _handle_base_start_tag(self, attributes: dict[str, str]) -> None:
        """A helper func to handle a <base> tag in handle_starttag()."""
        if attributes.get("href") and self.base_href is None:
            self.base_href = attributes["href"]

    def _handle_script_tag(self, tag: str, attributes: dict[str, str]) -> None:
        """A helper func to handle a <script> tag in handle_starttag()."""
        if attributes.get("src"):
            self.found_resources.append((tag, "src", attributes["src"], tag, ""))

    def _handle_link_tag(self, tag: str, attributes: dict[str, str]) -> None:
        """A helper func to handle a <link> tag in handle_starttag(). (including css)."""
        rel_attrs = set(attributes.get("rel", "").lower().split())

        # Handling rel="stylesheet" (css) and all other rel types inside <link> tags.
        if attributes.get("href") and rel_attrs & RELATIVE_LINK_TOKENS:
            kind = "stylesheet" if "stylesheet" in rel_attrs else "link"
            self.found_resources.append((tag, "href", attributes["href"], kind, ""))

    def _handle_source_attributes(self, tag: str, attributes: dict[str, str], line: int) -> None:
        """
        A helper func to handle `src=` attributes in handle_starttag().
        The parser was explicitly designated to be discovery-only.
        ALL base64 operations are handled in resource_helper.embed_media.
        """
        if attributes.get("src"):
            # The original source attribute is preserved here to ensure backwards compatibility with Selenium's driver.page_source.
            self.found_resources.append(
                (tag, "src", attributes["src"], "media", self.get_starttag_text() or "")
            )
        else:
            if self.debug:
                self.logger.debug(" No 'src' attribute located for tag '<%s>' on line %d.", tag, line)

    def _set_last_tag_text(self, tag: str, attributes: dict[str, str]) -> None:
        self.last_tag_text = f"<{tag}"

        for key, val in attributes.items():
            self.last_tag_text += f' {key}="{val}"'

        self.last_tag_text += ">\n"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """
        An override of HTMLParser's handle_starttag
        Refs:
        https://docs.python.org/3/library/html.parser.html#html.parser.HTMLParser.handle_starttag

        https://loadingindigo.mystrikingly.com/blog/python-head#:~:text=etc%2E%29%2E-,The,handle%5Fstartendtag%28%29%29%3A
        """

        attributes = {key.lower(): (val or "").strip() for key, val in attrs}
        pos = self.getpos()

        if tag == "base":
            self._handle_base_start_tag(attributes)

        elif tag == "script":
            self._handle_script_tag(tag, attributes)

        elif tag == "link":
            self._handle_link_tag(tag, attributes)

        elif self.include_media and tag in MEDIA_TAG_TOKENS:
            self._handle_source_attributes(tag, attributes, pos[0])

        else:
            # Constructing a rough recreation of the html contents.
            self._set_last_tag_text(tag, attributes)

            # Storing resources that arent captured.
            self.inline_resources[pos] = self.last_tag_text

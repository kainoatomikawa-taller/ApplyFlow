"""html_to_text — minimal HTML-to-plain-text conversion for ATS board
descriptions (Greenhouse's `content`, Ashby's `descriptionHtml`) that
arrive as HTML with no plain-text alternative.

Not a general-purpose HTML sanitizer — just strips tags/scripts/styles and
collapses whitespace enough to produce a readable job description. No
third-party HTML-parsing library is a dependency of this project yet, so
this is built on the stdlib `html.parser` alone.
"""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"})
_SKIPPED_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.chunks.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = unescape("".join(extractor.chunks))
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line).strip()

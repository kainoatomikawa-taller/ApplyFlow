"""html_to_text — minimal HTML-to-plain-text conversion for ATS board
descriptions (Greenhouse's `content`, Ashby's `descriptionHtml`) that
arrive as HTML with no plain-text alternative.

Not a general-purpose HTML sanitizer — just strips tags/scripts/styles and
collapses whitespace enough to produce a readable job description. No
third-party HTML-parsing library is a dependency of this project yet, so
this is built on the stdlib `html.parser` alone.

Escaped HTML gets a second pass
-------------------------------
Greenhouse sends `content` with its tags *escaped* — `&lt;p&gt;` rather than
`<p>`. One extract-then-unescape pass over that produces plain text as far as the
parser is concerned, and then unescaping turns it straight back into markup: the
function used to return `<h2>Who we are</h2>` verbatim, and every Greenhouse
description was stored as HTML. So the result is re-examined, and run through a
second pass when it still looks like markup.

Two passes at most. A third would be indistinguishable from a description that
legitimately discusses HTML — a job posting quoting `&amp;lt;div&amp;gt;` in its
text means to show the reader a tag, and stripping it would be losing content
rather than cleaning it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"})
_SKIPPED_TAGS = frozenset({"script", "style"})

#: A tag-shaped run: `<p>`, `</div>`, `<br/>`, `<a href="...">`. Deliberately
#: narrow — it decides whether a second pass is warranted, so matching prose that
#: merely contains an angle bracket ("returns <5ms") would strip real content.
_TAG_PATTERN = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>")


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


def _strip_once(html: str) -> str:
    """Remove tags and resolve entities, exactly once.

    No explicit `unescape` here: `HTMLParser` converts character references
    itself (`convert_charrefs` is on by default), so calling it as well
    unescaped everything twice per pass. That is what made a description quoting
    `&amp;lt;div&amp;gt;` lose the tag it meant to show the reader.
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return "".join(extractor.chunks)


def html_to_text(html: str) -> str:
    text = _strip_once(html)
    if _TAG_PATTERN.search(text):
        # The input's tags were escaped, so unescaping revealed them. See the
        # module docstring for why exactly one extra pass.
        text = _strip_once(text)
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line).strip()

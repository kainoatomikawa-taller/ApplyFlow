"""ResumePdfRendererPort — outbound port for turning an ATS-safe resume's
text into a PDF file.

The application layer defines this abstraction; the infrastructure layer
implements it (see `AtsSafePdfRenderer`). Use cases never know which PDF
mechanism produces the bytes.

Text in, bytes out — and nothing else. The port deliberately offers no way
to pass a table, a column specification, a header, a footer, a logo, or a
style sheet, because a caller that cannot express those things cannot
produce a resume an ATS mis-parses. The single-column, no-furniture layout
this ticket requires is therefore a property of the interface, not a
convention implementations are trusted to follow.

Synchronous, like `TextExtractorPort`: rendering is pure computation over
bytes already in memory, so there is nothing to await.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ResumePdfRendererPort(ABC):
    """Renders ATS-safe plain text as a single-column PDF."""

    @abstractmethod
    def render(self, content: str, *, title: str) -> bytes:
        """Return a PDF of `content`, one line of text per line of input, in
        a single column with no headers, footers, or page numbers.

        `title` sets the document's title metadata only — it is never drawn
        onto a page, since a repeated banner is exactly the header content
        that ATS parsers either duplicate into every field or drop.

        The text must already be ATS-safe (see `AtsSafeTextFormatter`);
        rendering neither cleans nor validates it. Raises
        `src.application.exceptions.DocumentRenderError` if the content
        cannot be rendered.
        """

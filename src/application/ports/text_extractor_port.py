"""TextExtractorPort — an outbound port for pulling text out of a resume file.

The application layer defines this abstraction. The infrastructure layer
implements it with format-specific parsing libraries. A use case never
knows which library reads a PDF vs. a DOCX.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TextExtractorPort(ABC):
    """Extracts plain text from a resume file's raw bytes.

    Implementations raise `src.application.exceptions.TextExtractionError`
    for any file that is the right content type but unreadable (corrupt,
    empty, undecodable) — the caller doesn't need to know why parsing
    failed, only that it did.
    """

    @abstractmethod
    def extract_text(self, content: bytes, content_type: str) -> str:
        """Return the resume's text content."""

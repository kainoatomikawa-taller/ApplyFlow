"""ResumeTextExtractor — implements `TextExtractorPort` with `pypdf` /
`python-docx` for PDF/DOCX, and plain UTF-8 decoding for text uploads.

Any parsing failure (corrupt file, empty body, undecodable bytes) is
caught here and re-raised as `TextExtractionError` — the one error type
the application layer knows how to handle — so no third-party exception
type ever crosses the port boundary.
"""

from __future__ import annotations

import io

import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.application.exceptions import TextExtractionError
from src.application.ports.text_extractor_port import TextExtractorPort

_PDF_CONTENT_TYPE = "application/pdf"
_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_TEXT_CONTENT_TYPE = "text/plain"


class ResumeTextExtractor(TextExtractorPort):
    def extract_text(self, content: bytes, content_type: str) -> str:
        if content_type == _PDF_CONTENT_TYPE:
            text = self._extract_pdf(content)
        elif content_type == _DOCX_CONTENT_TYPE:
            text = self._extract_docx(content)
        elif content_type == _TEXT_CONTENT_TYPE:
            text = self._extract_plain_text(content)
        else:
            # Unreachable via UploadResume (format is validated first), but
            # a direct caller still gets a clear error rather than None.
            raise TextExtractionError(
                f"No text extractor registered for content type '{content_type}'."
            )

        if not text.strip():
            raise TextExtractionError(
                "No readable text could be extracted from the resume."
            )
        return text

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as exc:
            raise TextExtractionError(f"Unreadable PDF file: {exc}") from exc

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        try:
            document = docx.Document(io.BytesIO(content))
        except Exception as exc:  # noqa: BLE001 - python-docx raises plain Exception
            raise TextExtractionError(f"Unreadable DOCX file: {exc}") from exc
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    @staticmethod
    def _extract_plain_text(content: bytes) -> str:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TextExtractionError(
                f"Resume text file is not valid UTF-8: {exc}"
            ) from exc

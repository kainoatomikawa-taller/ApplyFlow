"""Tests for ResumeTextExtractor against real PDF/DOCX/plain-text bytes.

No mocking of `pypdf`/`python-docx` — these build small real files in
memory and prove the adapter actually parses them.
"""

from __future__ import annotations

import io

import docx
import pytest

from src.application.exceptions import TextExtractionError
from src.infrastructure.text_extraction.resume_text_extractor import (
    ResumeTextExtractor,
)

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _minimal_pdf_bytes(text: str) -> bytes:
    """Hand-build a tiny, valid, single-page PDF containing `text`."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 200 200] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode()
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream
        + b"\nendstream"
    )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(body)
        out.write(b"\nendobj\n")

    xref_offset = out.tell()
    count = len(objects) + 1
    out.write(f"xref\n0 {count}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(b"trailer\n")
    out.write(f"<< /Size {count} /Root 1 0 R >>\n".encode())
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n".encode())
    out.write(b"%%EOF")
    return out.getvalue()


def _minimal_docx_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extracts_text_from_pdf():
    content = _minimal_pdf_bytes("Jane Doe Resume")
    text = ResumeTextExtractor().extract_text(content, "application/pdf")
    assert "Jane Doe Resume" in text


def test_extracts_text_from_docx():
    content = _minimal_docx_bytes("Jane Doe Resume")
    text = ResumeTextExtractor().extract_text(content, _DOCX_CONTENT_TYPE)
    assert "Jane Doe Resume" in text


def test_extracts_text_from_plain_text():
    content = b"Jane Doe Resume"
    text = ResumeTextExtractor().extract_text(content, "text/plain")
    assert text == "Jane Doe Resume"


def test_corrupt_pdf_raises_text_extraction_error():
    with pytest.raises(TextExtractionError):
        ResumeTextExtractor().extract_text(b"not a real pdf", "application/pdf")


def test_corrupt_docx_raises_text_extraction_error():
    with pytest.raises(TextExtractionError):
        ResumeTextExtractor().extract_text(b"not a real docx", _DOCX_CONTENT_TYPE)


def test_non_utf8_plain_text_raises_text_extraction_error():
    with pytest.raises(TextExtractionError):
        ResumeTextExtractor().extract_text(b"\xff\xfe\x00\x01", "text/plain")


def test_empty_pdf_body_raises_text_extraction_error():
    content = _minimal_pdf_bytes("")
    with pytest.raises(TextExtractionError):
        ResumeTextExtractor().extract_text(content, "application/pdf")


def test_unregistered_content_type_raises_text_extraction_error():
    with pytest.raises(TextExtractionError):
        ResumeTextExtractor().extract_text(b"hello", "application/rtf")

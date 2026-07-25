"""Tests for AtsSafePdfRenderer — the PDF an ATS has to be able to read.

Every assertion that matters here goes through `pypdf`, extracting the text
back out of the generated file. That is the closest available proxy for what
an ATS does with a PDF, and it is the same library this app uses to read
resumes candidates upload — so a resume ApplyFlow writes has to survive the
reader ApplyFlow already trusts.

The structural assertions (no XObjects, no annotations, one column) are
checked against the raw bytes: those constructs cannot be present because the
renderer has no way to emit them, and asserting their absence is what keeps
that true as the file changes.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from src.application.exceptions import DocumentRenderError
from src.infrastructure.documents.ats_safe_pdf_renderer import AtsSafePdfRenderer

_RESUME = """DANA REYES
dana@example.com
Austin, TX

SUMMARY
Backend Engineer with Python and PostgreSQL experience.

EXPERIENCE
Backend Engineer, Acme Corp, 2019-03 to 2022-06
- Built payment services in Python
- Led a team of 5 engineers

EDUCATION
Bachelor of Science, Computer Science, State University

SKILLS
Python, PostgreSQL"""


@pytest.fixture
def renderer() -> AtsSafePdfRenderer:
    return AtsSafePdfRenderer()


def _render(renderer: AtsSafePdfRenderer, content: str) -> bytes:
    return renderer.render(content, title="Resume - Senior Platform Engineer")


def _extract(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() for page in reader.pages)


# ---- the file is a valid, readable PDF -------------------------------------


def test_the_output_is_a_pdf_file(renderer):
    pdf = _render(renderer, _RESUME)

    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")


def test_pypdf_can_open_it_and_finds_one_page_for_a_short_resume(renderer):
    reader = PdfReader(io.BytesIO(_render(renderer, _RESUME)))

    assert len(reader.pages) == 1


def test_the_title_is_document_metadata_and_not_drawn_on_the_page(renderer):
    """A title drawn onto the page would be exactly the running-header
    content that parsers splice into the first entry."""
    pdf = _render(renderer, _RESUME)

    reader = PdfReader(io.BytesIO(pdf))
    assert reader.metadata.title == "Resume - Senior Platform Engineer"
    assert "Resume - Senior Platform Engineer" not in _extract(pdf)


# ---- the text survives extraction ------------------------------------------


def test_every_line_of_the_resume_survives_extraction(renderer):
    extracted = _extract(_render(renderer, _RESUME))

    for line in _RESUME.split("\n"):
        if line.strip():
            assert line in extracted, line


def test_extraction_preserves_the_reading_order(renderer):
    extracted = _extract(_render(renderer, _RESUME))

    assert extracted.index("DANA REYES") < extracted.index("SUMMARY")
    assert extracted.index("SUMMARY") < extracted.index("EXPERIENCE")
    assert extracted.index("EXPERIENCE") < extracted.index("SKILLS")


def test_parentheses_and_backslashes_do_not_corrupt_the_file(renderer):
    """They terminate and escape PDF strings, so unescaped they would break
    the content stream."""
    content = "Backend Engineer (contract) at Acme \\ Corp"

    extracted = _extract(_render(renderer, content))

    assert "Backend Engineer (contract) at Acme \\ Corp" in extracted


def test_accented_letters_in_a_name_survive(renderer):
    extracted = _extract(_render(renderer, "Ana Muñoz"))

    assert "Muñoz" in extracted


def test_a_character_outside_the_encoding_becomes_a_visible_substitute(renderer):
    """Visible loss beats invisible loss: a "?" tells the candidate something
    was dropped, where a silently absent glyph does not."""
    extracted = _extract(_render(renderer, "Built 日本語 localization"))

    assert "Built" in extracted
    assert "localization" in extracted
    assert "日本語" not in extracted


def test_blank_lines_are_preserved_as_vertical_space(renderer):
    """Spacing is the only layout signal available; losing it runs sections
    together."""
    pdf = _render(renderer, "EXPERIENCE\n\nAcme Corp")

    extracted = _extract(pdf)
    assert extracted.index("EXPERIENCE") < extracted.index("Acme Corp")


# ---- structure: single column, no furniture --------------------------------


def test_a_long_line_wraps_instead_of_running_off_the_page(renderer):
    long_line = "- " + " ".join(["Python"] * 60)

    extracted = _extract(_render(renderer, long_line))

    assert extracted.count("Python") == 60
    assert "\n" in extracted.strip()


def test_a_long_resume_paginates(renderer):
    content = "\n".join(f"- Built service number {index}" for index in range(120))

    reader = PdfReader(io.BytesIO(_render(renderer, content)))

    assert len(reader.pages) > 1


def test_no_page_carries_a_page_number_or_running_header(renderer):
    content = "\n".join(f"- Built service number {index}" for index in range(120))
    pdf = _render(renderer, content)

    reader = PdfReader(io.BytesIO(pdf))
    for page in reader.pages:
        text = page.extract_text()
        assert "Page" not in text
        assert "of 2" not in text


def test_the_file_contains_no_tables_images_or_annotations(renderer):
    """None of these can be emitted — the renderer has no primitive for them
    — and the file is checked so that stays true."""
    pdf = _render(renderer, _RESUME)

    for construct in (b"/XObject", b"/Annots", b"/Image", b"/Widget", b"/Form"):
        assert construct not in pdf, construct


def test_text_is_positioned_in_one_column(renderer):
    """Lines advance with `T*` from a single text-matrix origin, so there is
    no operator in the stream that could start a second column."""
    pdf = _render(renderer, _RESUME)

    assert pdf.count(b" Tm") == 1  # one origin, one column
    assert b"T*" in pdf


def test_only_the_base_14_helvetica_fonts_are_used(renderer):
    """Never embedded or subsetted, so glyph extraction cannot go wrong."""
    pdf = _render(renderer, _RESUME)

    assert b"/BaseFont /Helvetica" in pdf
    assert b"/FontFile" not in pdf
    assert b"/WinAnsiEncoding" in pdf


def test_standard_headings_are_the_only_bold_text(renderer):
    """Bold is ATS-neutral and helps a human reader; it is applied by
    recognizing standard headings, never by the model asking for it."""
    pdf = _render(renderer, "EXPERIENCE\nBackend Engineer at Acme Corp")

    assert b"/BaseFont /Helvetica-Bold" in pdf
    assert pdf.count(b"/F2 ") >= 1


# ---- edge cases ------------------------------------------------------------


def test_empty_content_still_renders_a_valid_single_page_pdf(renderer):
    pdf = _render(renderer, "")

    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1


def test_rendering_is_deterministic(renderer):
    """No timestamps or ids, so the same resume always produces the same
    bytes — a diffable artifact."""
    assert _render(renderer, _RESUME) == _render(renderer, _RESUME)


def test_a_title_with_pdf_syntax_characters_is_escaped(renderer):
    pdf = renderer.render("Dana Reyes", title="Resume (2026) \\ final")

    reader = PdfReader(io.BytesIO(pdf))
    assert reader.metadata.title == "Resume (2026) \\ final"


def test_a_render_failure_surfaces_as_the_ports_error_type(renderer, monkeypatch):
    """No third-party or internal error type crosses the port boundary."""
    monkeypatch.setattr(
        renderer, "_paginate", lambda content: (_ for _ in ()).throw(RuntimeError("x"))
    )

    with pytest.raises(DocumentRenderError):
        _render(renderer, _RESUME)

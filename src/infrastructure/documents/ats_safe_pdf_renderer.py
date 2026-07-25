"""AtsSafePdfRenderer — implements `ResumePdfRendererPort` by writing a
minimal single-column PDF directly.

Why write the PDF by hand rather than reach for a layout library
--------------------------------------------------------------------
The ticket's requirement is a negative one: no tables, no text boxes, no
columns, no header/footer content. A general-purpose layout library can do
all of those things, so with one the requirement becomes a rule contributors
have to keep following. Here the file format is emitted directly and the
emitter has no primitive for any of them: there is one text object per page,
one font size, one left margin, and lines advance straight down the page.
A future change cannot accidentally introduce a table because there is no
table to introduce. That is worth more than a nicer-looking document, and it
also avoids adding a dependency for one small, stable output format.

What comes out is PDF 1.4 with the base-14 Helvetica fonts (never embedded,
never subsetted, so nothing can go wrong with glyph extraction), one content
stream per page, and no annotations, XObjects, or optional content. `pypdf`
— the same library this app uses to read *uploaded* resumes — extracts the
text back verbatim, which is the closest available proxy for what an ATS
does with the file, and the test suite asserts exactly that round trip.

Deliberate omissions, each an ATS failure mode
---------------------------------------------
- No page numbers, running headers, or footers. Parsers either splice them
  into the middle of a work-history entry or treat the first line of every
  page as a heading.
- No multi-column text. Two columns interleave into nonsense when read in
  content order.
- No images or vector drawing, so a scanned-looking resume can never be
  produced by this path.
- Nothing but WinAnsi-encodable text. A character outside that set becomes
  "?" rather than a glyph a parser might drop silently — visible loss beats
  invisible loss, and `AtsSafeTextFormatter` has already transliterated the
  punctuation that would otherwise land here.
"""

from __future__ import annotations

from src.application.exceptions import DocumentRenderError
from src.application.ports.resume_pdf_renderer_port import ResumePdfRendererPort
from src.domain.services.ats_section_headings import is_standard_section_heading

#: US Letter, in PDF points (1/72"). Chosen over A4 because the ATS market
#: this targets is US-centric; nothing else depends on the size.
_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_MARGIN = 54  # 0.75", comfortably inside every parser's crop assumptions

_FONT_SIZE = 10.5
_LEADING = 14.0
_REGULAR_FONT = "F1"
_BOLD_FONT = "F2"

#: Helvetica's average glyph width as a fraction of font size. An
#: approximation rather than a width table: the only consequence of being
#: slightly off is a wrapped line breaking a word or two early, and no ATS
#: reads column geometry. Erring narrow keeps text inside the margin.
_AVERAGE_GLYPH_WIDTH_RATIO = 0.52

_TEXT_WIDTH = _PAGE_WIDTH - (2 * _MARGIN)
_MAX_CHARS_PER_LINE = int(_TEXT_WIDTH / (_FONT_SIZE * _AVERAGE_GLYPH_WIDTH_RATIO))
_LINES_PER_PAGE = int((_PAGE_HEIGHT - (2 * _MARGIN)) / _LEADING)


class AtsSafePdfRenderer(ResumePdfRendererPort):
    def render(self, content: str, *, title: str) -> bytes:
        try:
            pages = self._paginate(content)
            return self._build_pdf(pages, title=title)
        except DocumentRenderError:
            raise
        except Exception as exc:  # noqa: BLE001 - port contract is one error type
            raise DocumentRenderError(f"Could not render resume PDF: {exc}") from exc

    # ---- layout --------------------------------------------------------------

    def _paginate(self, content: str) -> list[list[str]]:
        """Split `content` into pages of wrapped lines.

        Always at least one page, so an empty resume still renders a valid
        (blank) PDF rather than a malformed file.
        """
        wrapped: list[str] = []
        for line in content.split("\n"):
            wrapped.extend(self._wrap(line))

        pages = [
            wrapped[start : start + _LINES_PER_PAGE]
            for start in range(0, len(wrapped), _LINES_PER_PAGE)
        ]
        return pages or [[]]

    @staticmethod
    def _wrap(line: str) -> list[str]:
        """Break one line at word boundaries to fit the text column.

        A blank line stays one blank line — vertical spacing is the only
        layout signal this renderer has, and dropping it would run sections
        together. A single word longer than the column is left long rather
        than hyphenated: an over-long line is ugly, while a split word is a
        term an ATS then fails to match.
        """
        if not line.strip():
            return [""]
        if len(line) <= _MAX_CHARS_PER_LINE:
            return [line]

        lines: list[str] = []
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > _MAX_CHARS_PER_LINE:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    # ---- PDF assembly --------------------------------------------------------

    def _build_pdf(self, pages: list[list[str]], *, title: str) -> bytes:
        """Assemble the object graph, then serialize it with a cross-reference
        table.

        Object numbering is fixed up front so references can be written
        before the objects they point at exist: 1 catalog, 2 page tree,
        3 + 4 fonts, 5 document info, then one page object and one content
        stream per page.
        """
        first_page_object = 6
        page_object_numbers = [
            first_page_object + (index * 2) for index in range(len(pages))
        ]

        objects: dict[int, bytes] = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: (
                "<< /Type /Pages /Kids [{kids}] /Count {count} >>".format(
                    kids=" ".join(f"{number} 0 R" for number in page_object_numbers),
                    count=len(pages),
                ).encode("ascii")
            ),
            3: (
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Encoding /WinAnsiEncoding >>"
            ),
            4: (
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                b"/Encoding /WinAnsiEncoding >>"
            ),
            5: (
                b"<< /Title ("
                + self._escape(title)
                + b") /Producer (ApplyFlow) /Creator (ApplyFlow) >>"
            ),
        }

        for page_number, (page_object, lines) in enumerate(
            zip(page_object_numbers, pages, strict=True)
        ):
            content_object = page_object + 1
            objects[page_object] = (
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
                f"/Resources << /Font << /{_REGULAR_FONT} 3 0 R "
                f"/{_BOLD_FONT} 4 0 R >> >> "
                f"/Contents {content_object} 0 R >>"
            ).encode("ascii")
            stream = self._content_stream(lines)
            objects[content_object] = (
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                + stream
                + b"\nendstream"
            )
            del page_number  # numbering is positional; nothing is drawn per page

        return self._serialize(objects)

    def _content_stream(self, lines: list[str]) -> bytes:
        """One text object, one line per input line, advancing down the page.

        `T*` is the only positioning operator used: it moves to the next line
        at the set leading, so lines can only ever stack vertically in a
        single column. There is no operator here that could place text at an
        arbitrary x, which is what a second column would require.
        """
        top = _PAGE_HEIGHT - _MARGIN - _FONT_SIZE
        parts: list[bytes] = [
            b"BT",
            f"/{_REGULAR_FONT} {_FONT_SIZE} Tf".encode("ascii"),
            f"{_LEADING} TL".encode("ascii"),
            f"1 0 0 1 {_MARGIN} {top:.2f} Tm".encode("ascii"),
        ]

        for index, line in enumerate(lines):
            if index:
                parts.append(b"T*")
            if not line.strip():
                continue
            font = _BOLD_FONT if is_standard_section_heading(line) else _REGULAR_FONT
            parts.append(f"/{font} {_FONT_SIZE} Tf".encode("ascii"))
            parts.append(b"(" + self._escape(line) + b") Tj")

        parts.append(b"ET")
        return b"\n".join(parts)

    @staticmethod
    def _escape(text: str) -> bytes:
        """Encode text as a PDF literal string: WinAnsi bytes with the three
        characters that would otherwise end the string escaped."""
        encoded = text.encode("cp1252", errors="replace")
        for target, replacement in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
            encoded = encoded.replace(target, replacement)
        return encoded

    @staticmethod
    def _serialize(objects: dict[int, bytes]) -> bytes:
        """Write the objects out with a cross-reference table.

        Offsets have to be byte-exact — a reader that cannot resolve the
        xref falls back to scanning or gives up, and "gives up" is an ATS
        rejecting the file — so they are recorded while writing rather than
        computed afterward.
        """
        out = bytearray(b"%PDF-1.4\n")
        offsets: dict[int, int] = {}

        for number in sorted(objects):
            offsets[number] = len(out)
            out += f"{number} 0 obj\n".encode("ascii")
            out += objects[number]
            out += b"\nendobj\n"

        xref_offset = len(out)
        highest = max(objects)
        out += f"xref\n0 {highest + 1}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for number in range(1, highest + 1):
            out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
        out += (
            f"trailer\n<< /Size {highest + 1} /Root 1 0 R /Info 5 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        return bytes(out)

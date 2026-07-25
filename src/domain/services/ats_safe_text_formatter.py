"""AtsSafeTextFormatter — a pure domain service that keeps generated
documents plain enough for an applicant tracking system to parse, and
coherent after the provenance guard has removed whatever it couldn't back.

ATS parsers read plain text. Markdown syntax, box-drawing tables, decorative
bullet glyphs, smart quotes, and non-breaking spaces all survive a copy-paste
into an ATS form and then turn a candidate's experience into garbled tokens
or drop it entirely — a resume that reads beautifully and parses badly costs
the candidate the application. Models produce all of it unprompted, so the
prompts ask for plain text (see `LlmTailoredResumeGenerator` /
`LlmCoverLetterGenerator`) and this service enforces it regardless of what
came back.

Two steps, either side of the guard
-----------------------------------
`normalize_plain_text` runs *before* `ProvenanceGuard`, so the text the
guard validates is the text that ships — the guard never has to reason about
`**bold**` markers, and the lines it clears need no further rewriting. Both
generated documents get this pass: a cover letter is read by a person rather
than parsed for fields, but stray `**` markers in one still read as a
malfunction, and the hygiene is identical either way.

`drop_empty_sections` runs *after*, because a section can only become empty
once guarding has removed its contents: an "EXPERIENCE" heading over nothing
is exactly what a stripped fabrication leaves behind, and a resume with
hollow headings reads as broken rather than honest. This step is resume-only
— a cover letter has no section headings to hollow out.

Both steps only ever delete or transliterate characters. Neither can
introduce a word, so neither can smuggle in a claim the guard rejected or
never saw — the provenance decision stands whatever formatting does. Every
transformation here is also idempotent, so running it twice is harmless.
"""

from __future__ import annotations

import re
import unicodedata

#: Markdown emphasis/heading/code syntax, table pipes, and horizontal rules.
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_MARKDOWN_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{2,3}|`+)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*(?:[-*_=~]\s*){3,}$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?[\s:|-]*\|[\s:|-]*$")

#: Bullet glyphs an ATS parser has no reason to understand, mapped to the
#: one it always does. En/em dashes are absent deliberately: they are
#: transliterated to "-" before bullets are considered.
_BULLET_GLYPHS = "•◦▪▫‣⁃∙·●○■□➢➤»‧"
_BULLET_LINE_RE = re.compile(rf"^(\s*)[{re.escape(_BULLET_GLYPHS)}]+\s*")
_MARKDOWN_BULLET_RE = re.compile(r"^(\s*)[*+]\s+")

#: Characters that look like ASCII but aren't. Left as an explicit table
#: rather than a blanket ASCII-fold: transliterating a candidate's name
#: ("Muñoz" -> "Munoz") would misspell it, so accented letters are kept and
#: only punctuation is flattened.
_PUNCTUATION_TRANSLITERATIONS = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote / apostrophe
    "\u201a": "'",  # single low quote
    "\u201b": "'",  # single high-reversed quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u201e": '"',  # double low quote
    "\u2032": "'",  # prime
    "\u2033": '"',  # double prime
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # no-break space
    "\u2009": " ",  # thin space
    "\u202f": " ",  # narrow no-break space
    "\u2007": " ",  # figure space
    "\ufeff": "",  # byte-order mark
    "\u200b": "",  # zero-width space
}
_TRANSLITERATION_TABLE = str.maketrans(_PUNCTUATION_TRANSLITERATIONS)

#: The section headings ATS parsers are built to recognize. Used only to
#: decide whether a heading left with no body should be dropped: matching a
#: fixed, standard vocabulary means a candidate's all-caps name is never
#: mistaken for an empty section and deleted.
_STANDARD_SECTION_HEADINGS = frozenset(
    {
        "summary",
        "professional summary",
        "career summary",
        "objective",
        "profile",
        "experience",
        "work experience",
        "professional experience",
        "employment history",
        "education",
        "skills",
        "technical skills",
        "core skills",
        "certifications",
        "licenses and certifications",
        "projects",
        "publications",
        "awards",
        "achievements",
        "languages",
        "additional information",
        "references",
    }
)


class AtsSafeTextFormatter:
    """Flattens a generated resume to ATS-parseable plain text, and clears
    away sections the provenance guard emptied."""

    def normalize_plain_text(self, content: str) -> str:
        """Return `content` as plain text an ATS can parse.

        Markdown syntax, table rows, and decorative glyphs are removed or
        replaced with their plain equivalents; tabs become spaces (a tab is
        a column break to some parsers); typographic punctuation becomes
        ASCII; runs of blank lines collapse to one. Word content is
        untouched.
        """
        lines: list[str] = []
        for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = self._normalize_line(raw_line)
            if line is None:
                continue
            lines.append(line)
        return self._collapse_blank_runs(lines)

    def drop_empty_sections(self, content: str) -> str:
        """Return `content` with standard section headings that have no
        remaining body removed.

        A heading is dropped when the next non-blank line is another
        heading or the end of the document — the shape a resume takes when
        guarding removed everything a section claimed.
        """
        lines = content.split("\n")
        keep: list[str] = []
        for index, line in enumerate(lines):
            if self._is_standard_section_heading(line) and not self._has_body(
                lines, index
            ):
                continue
            keep.append(line)
        return self._collapse_blank_runs(keep)

    # ---- internals -----------------------------------------------------------

    def _normalize_line(self, line: str) -> str | None:
        """Return the ATS-safe form of one line, or None if the line is
        pure decoration (a horizontal rule, a table divider) that carries
        no content at all."""
        line = line.replace("\t", " ").translate(_TRANSLITERATION_TABLE)
        line = "".join(
            character
            for character in line
            if character == " " or unicodedata.category(character)[0] != "C"
        )

        if _HORIZONTAL_RULE_RE.match(line) or _TABLE_DIVIDER_RE.match(line):
            return None

        if _TABLE_ROW_RE.match(line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            line = " ".join(cell for cell in cells if cell)

        line = _MARKDOWN_HEADING_RE.sub("", line)
        line = _MARKDOWN_LINK_RE.sub(r"\1 \2", line)
        line = _BULLET_LINE_RE.sub("- ", line)
        line = _MARKDOWN_BULLET_RE.sub("- ", line)
        line = _MARKDOWN_EMPHASIS_RE.sub("", line)
        # Runs of spaces are how a model fakes columns ("Engineer     Acme
        # Corp"), and a parser reading that as one field garbles both. A
        # single-column plain-text resume carries no meaning in whitespace,
        # so runs collapse and indentation goes — including a nested
        # bullet's, which flattens to top level rather than half-indented.
        line = re.sub(r" {2,}", " ", line)
        return line.strip()

    @staticmethod
    def _collapse_blank_runs(lines: list[str]) -> str:
        """Join `lines`, collapsing runs of blank lines to a single one and
        trimming blank lines off both ends."""
        collapsed: list[str] = []
        for line in lines:
            if not line.strip():
                if not collapsed or collapsed[-1] != "":
                    collapsed.append("")
                continue
            collapsed.append(line)
        while collapsed and collapsed[0] == "":
            collapsed.pop(0)
        while collapsed and collapsed[-1] == "":
            collapsed.pop()
        return "\n".join(collapsed)

    @staticmethod
    def _is_standard_section_heading(line: str) -> bool:
        candidate = line.strip().rstrip(":").strip().lower()
        return candidate in _STANDARD_SECTION_HEADINGS

    @classmethod
    def _has_body(cls, lines: list[str], heading_index: int) -> bool:
        for line in lines[heading_index + 1 :]:
            if not line.strip():
                continue
            return not cls._is_standard_section_heading(line)
        return False

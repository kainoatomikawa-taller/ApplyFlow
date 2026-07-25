"""AtsSafetyValidator — a pure domain service that checks a finished resume
against the ATS-safety rules, and names what fails.

`AtsSafeTextFormatter` enforces those rules by rewriting; this proves the
rewriting worked. The two exist together on purpose: enforcement without a
check is a claim nobody verifies, and on a clean run this validator finds
nothing. A violation here is therefore not usually a candidate-data problem
— it means the formatter has a gap, or something downstream of it reintroduced
markup, and it should be read as a bug report about the pipeline. That is why
the resume flow logs a finding rather than silently correcting it a second
time: correcting it twice would hide the gap forever.

It is not a formatter and has no fix-up path. Reporting and rewriting stay
separate so a rule can be tightened here — flagging something previously
allowed — without that change quietly editing candidates' resumes.

The rules cover the failure modes ATS parsers actually have: markup they
render literally, whitespace and pipes they read as columns, headings they
don't recognize and so file under "other", page furniture they splice into
the middle of an entry, and characters they drop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.services.ats_section_headings import is_standard_section_heading

#: Rule identifiers. Stable strings rather than an enum so a report can be
#: serialized to an API client or a log line without translation, and so a
#: new rule is additive for consumers.
RULE_MARKDOWN_SYNTAX = "markdown_syntax"
RULE_TABLE_MARKUP = "table_markup"
RULE_COLUMN_WHITESPACE = "column_whitespace"
RULE_DECORATIVE_GLYPH = "decorative_glyph"
RULE_NON_STANDARD_HEADING = "non_standard_section_heading"
RULE_EMPTY_SECTION = "empty_section"
RULE_PAGE_FURNITURE = "page_furniture"
RULE_UNRENDERABLE_CHARACTER = "unrenderable_character"

_MARKDOWN_RE = re.compile(r"(^\s{0,3}#{1,6}\s)|(\*)|(__)|(`)|(\[[^\]]*\]\([^)]*\))")
_TABLE_ROW_RE = re.compile(r"\|")
_COLUMN_WHITESPACE_RE = re.compile(r"\S(\t| {2,})\S")
_DECORATIVE_GLYPH_RE = re.compile(
    r"[•◦▪▫‣⁃∙·●○" r"■□➢➤»‧─-╿←-⇿" r"\U0001f300-\U0001faff✀-➿️]"
)
#: Running headers, footers, and page numbers, whatever their casing.
_PAGE_FURNITURE_RE = re.compile(
    r"^\s*(page\s+\d+(\s*(of|/)\s*\d+)?|\d+\s*(of|/)\s*\d+"
    r"|confidential|curriculum vitae|résumé|resume)\s*$",
    re.IGNORECASE,
)
#: An all-caps line short enough to read as a heading rather than a sentence.
_HEADING_SHAPED_RE = re.compile(r"^[^a-z]*[A-Z][^a-z]*$")
_MAX_HEADING_LENGTH = 40


@dataclass(frozen=True)
class AtsSafetyViolation:
    """One ATS-safety rule a line breaks.

    `rule` is one of the module's `RULE_*` identifiers, `detail` explains it
    in a sentence, and `line` is the offending text — kept verbatim because
    a rule name without the line it fired on is not actionable. `line_number`
    is 1-indexed, matching how an editor counts.
    """

    rule: str
    detail: str
    line: str
    line_number: int


@dataclass(frozen=True)
class AtsSafetyReport:
    """The outcome of validating one document."""

    violations: tuple[AtsSafetyViolation, ...] = ()

    @property
    def is_safe(self) -> bool:
        """True when nothing broke a rule — the expected result."""
        return not self.violations

    @property
    def broken_rules(self) -> tuple[str, ...]:
        """The distinct rules that fired, in order of first appearance."""
        seen: list[str] = []
        for violation in self.violations:
            if violation.rule not in seen:
                seen.append(violation.rule)
        return tuple(seen)


class AtsSafetyValidator:
    """Checks a resume's text against the ATS-safety rules."""

    def validate(self, content: str) -> AtsSafetyReport:
        """Return every rule violation in `content`, in document order.

        A line can break more than one rule and is reported once per rule:
        a pipe-delimited row wrapped in bold markers is two distinct
        problems with two distinct fixes.
        """
        lines = content.split("\n")
        violations: list[AtsSafetyViolation] = []

        for index, line in enumerate(lines, start=1):
            violations.extend(self._check_line(line, index))
            violations.extend(self._check_heading(line, index, lines))

        return AtsSafetyReport(violations=tuple(violations))

    # ---- per-line rules ------------------------------------------------------

    def _check_line(self, line: str, line_number: int) -> list[AtsSafetyViolation]:
        found: list[AtsSafetyViolation] = []

        def add(rule: str, detail: str) -> None:
            found.append(
                AtsSafetyViolation(
                    rule=rule, detail=detail, line=line, line_number=line_number
                )
            )

        if not line.strip():
            return found

        if _MARKDOWN_RE.search(line):
            add(
                RULE_MARKDOWN_SYNTAX,
                "Markdown syntax is rendered literally by ATS parsers.",
            )
        if _TABLE_ROW_RE.search(line):
            add(
                RULE_TABLE_MARKUP,
                "Pipe characters read as table cells and scramble field order.",
            )
        if _COLUMN_WHITESPACE_RE.search(line):
            add(
                RULE_COLUMN_WHITESPACE,
                "Runs of whitespace simulate columns, which parsers read as "
                "one merged field.",
            )
        if _DECORATIVE_GLYPH_RE.search(line):
            add(
                RULE_DECORATIVE_GLYPH,
                "Decorative glyphs have no parser meaning and often drop the "
                "text around them.",
            )
        if _PAGE_FURNITURE_RE.match(line):
            add(
                RULE_PAGE_FURNITURE,
                "Page numbers and running headers get spliced into the "
                "surrounding entry.",
            )
        unrenderable = self._unrenderable_characters(line)
        if unrenderable:
            add(
                RULE_UNRENDERABLE_CHARACTER,
                f"Characters {unrenderable} cannot be rendered in the PDF's "
                "encoding and would be replaced.",
            )

        return found

    @staticmethod
    def _unrenderable_characters(line: str) -> str:
        """The characters that would not survive into the PDF, deduplicated
        and in order of appearance. Mirrors `AtsSafePdfRenderer`'s WinAnsi
        encoding, so this rule fires exactly when that renderer would
        substitute a "?"."""
        missing: list[str] = []
        for character in line:
            try:
                character.encode("cp1252")
            except UnicodeEncodeError:
                if character not in missing:
                    missing.append(character)
        return "".join(missing)

    # ---- structural rules ----------------------------------------------------

    def _check_heading(
        self, line: str, line_number: int, lines: list[str]
    ) -> list[AtsSafetyViolation]:
        """Heading rules, which need the lines around `line` to judge.

        The candidate's name is conventionally the first non-blank line and
        is often written in caps, so it is exempt from the heading-shape
        check — flagging someone's name as an unrecognized section would be
        noise, and it is not a heading whatever it looks like.
        """
        stripped = line.strip()
        if not stripped:
            return []

        if is_standard_section_heading(line):
            if self._section_is_empty(lines, line_number - 1):
                return [
                    AtsSafetyViolation(
                        rule=RULE_EMPTY_SECTION,
                        detail="A heading with no content beneath it reads as a "
                        "parsing failure.",
                        line=line,
                        line_number=line_number,
                    )
                ]
            return []

        if line_number == self._first_content_line_number(lines):
            return []
        if len(stripped) > _MAX_HEADING_LENGTH:
            return []
        if not _HEADING_SHAPED_RE.match(stripped):
            return []

        return [
            AtsSafetyViolation(
                rule=RULE_NON_STANDARD_HEADING,
                detail="Not a heading ATS parsers recognize; its section may be "
                "filed under 'other'.",
                line=line,
                line_number=line_number,
            )
        ]

    @staticmethod
    def _first_content_line_number(lines: list[str]) -> int:
        for index, line in enumerate(lines, start=1):
            if line.strip():
                return index
        return 0

    @staticmethod
    def _section_is_empty(lines: list[str], heading_index: int) -> bool:
        for line in lines[heading_index + 1 :]:
            if not line.strip():
                continue
            return is_standard_section_heading(line)
        return True

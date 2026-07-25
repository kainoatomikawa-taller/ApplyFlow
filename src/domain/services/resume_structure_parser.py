"""ResumeStructureParser — reads an ATS-safe resume's text back as the
structure a machine can consume: a contact block plus named sections.

This is the "structured export" half of the output requirement, and it is
derived rather than composed. The text is what the guard validated and what
the PDF renders, so parsing that same text guarantees all three artifacts
say exactly the same thing. Building a structure independently and rendering
text from it would allow the two to disagree — and the text is the one the
provenance guard cleared, so any disagreement would be the structure
asserting something unvalidated.

The parse is the same reading an ATS performs, which is the point: if a
standard heading did not survive into the text, no section appears here
either, and that absence is a truthful signal about how a parser will see
the file rather than a gap this service papers over.

Everything before the first recognized heading is the contact block, since
that is where a resume puts a name and contact details and where parsers
look for them. Lines under a heading belong to it until the next heading;
blank lines are layout, not content, so they are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.services.ats_section_headings import is_standard_section_heading


@dataclass(frozen=True)
class ResumeSection:
    """One section of a resume: its heading as written, and its lines."""

    heading: str
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumeStructure:
    """A resume as a parser sees it."""

    contact_lines: tuple[str, ...] = ()
    sections: tuple[ResumeSection, ...] = field(default_factory=tuple)

    @property
    def headings(self) -> tuple[str, ...]:
        return tuple(section.heading for section in self.sections)

    @property
    def is_empty(self) -> bool:
        return not self.contact_lines and not self.sections


class ResumeStructureParser:
    """Splits ATS-safe resume text into a contact block and its sections."""

    def parse(self, content: str) -> ResumeStructure:
        """Return `content` as a contact block plus one section per
        recognized heading, in document order."""
        contact_lines: list[str] = []
        sections: list[ResumeSection] = []
        current_heading: str | None = None
        current_lines: list[str] = []

        def close_section() -> None:
            if current_heading is not None:
                sections.append(
                    ResumeSection(heading=current_heading, lines=tuple(current_lines))
                )

        for raw_line in content.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if is_standard_section_heading(line):
                close_section()
                current_heading = line.rstrip(":").strip()
                current_lines = []
                continue
            if current_heading is None:
                contact_lines.append(line)
            else:
                current_lines.append(line)

        close_section()
        return ResumeStructure(
            contact_lines=tuple(contact_lines), sections=tuple(sections)
        )

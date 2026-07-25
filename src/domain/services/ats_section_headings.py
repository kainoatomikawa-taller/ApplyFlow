"""The section headings an applicant tracking system is built to recognize.

One definition, three readers: `AtsSafeTextFormatter` uses it to decide
which emptied headings to drop, `AtsSafetyValidator` to flag a heading a
parser won't know, and `ResumeStructureParser` to split a resume into
sections. Three copies of this vocabulary would drift, and a drifted copy
means a heading one service treats as structural and another treats as
prose.

The list is deliberately conservative — the headings ATS vendors document
as recognized, not every heading a resume could reasonably carry. An
unrecognized heading is not a formatting crime, but it does mean the text
beneath it may land in a parser's "other" bucket instead of its work-history
or education fields, so the validator surfaces it as something the candidate
should know about.
"""

from __future__ import annotations

#: Normalized (lowercased, colon-stripped) headings a parser recognizes.
STANDARD_SECTION_HEADINGS = frozenset(
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


def normalize_heading(line: str) -> str:
    """Reduce a line to the form `STANDARD_SECTION_HEADINGS` is keyed on, so
    "Experience:", "EXPERIENCE" and "experience" are one heading."""
    return line.strip().rstrip(":").strip().lower()


def is_standard_section_heading(line: str) -> bool:
    """True when `line` is a section heading an ATS parser recognizes."""
    return normalize_heading(line) in STANDARD_SECTION_HEADINGS

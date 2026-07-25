"""Tests for ResumeStructureParser — reading an ATS-safe resume back as the
structure a machine consumes.

The parse mirrors what an ATS does, so the notable cases are the ones where
it must report absence honestly rather than infer structure that isn't in
the text.
"""

from __future__ import annotations

import pytest

from src.domain.services.resume_structure_parser import ResumeStructureParser

_RESUME = """DANA REYES
dana@example.com
Austin, TX

SUMMARY
Backend Engineer with Python experience.

EXPERIENCE
Backend Engineer, Acme Corp, 2019-03 to 2022-06
- Built payment services in Python

SKILLS
Python, PostgreSQL"""


@pytest.fixture
def parser() -> ResumeStructureParser:
    return ResumeStructureParser()


def test_lines_before_the_first_heading_are_the_contact_block(parser):
    structure = parser.parse(_RESUME)

    assert structure.contact_lines == ("DANA REYES", "dana@example.com", "Austin, TX")


def test_each_heading_becomes_a_section_in_document_order(parser):
    structure = parser.parse(_RESUME)

    assert structure.headings == ("SUMMARY", "EXPERIENCE", "SKILLS")


def test_lines_belong_to_the_heading_above_them(parser):
    structure = parser.parse(_RESUME)

    experience = structure.sections[1]
    assert experience.heading == "EXPERIENCE"
    assert experience.lines == (
        "Backend Engineer, Acme Corp, 2019-03 to 2022-06",
        "- Built payment services in Python",
    )


def test_blank_lines_are_layout_and_do_not_survive_into_the_structure(parser):
    structure = parser.parse("EXPERIENCE\n\nAcme Corp\n\n\nBuilt services")

    assert structure.sections[0].lines == ("Acme Corp", "Built services")


def test_a_trailing_colon_is_stripped_from_a_heading(parser):
    structure = parser.parse("Skills:\nPython")

    assert structure.headings == ("Skills",)


def test_a_heading_is_recognized_whatever_its_casing(parser):
    structure = parser.parse("experience\nAcme Corp")

    assert structure.sections[0].lines == ("Acme Corp",)


def test_an_unrecognized_heading_is_not_treated_as_a_section(parser):
    """The parse reports what a parser will actually see: an unrecognized
    heading is content, which is exactly why the validator flags it."""
    structure = parser.parse("Dana Reyes\n\nAWARDS\nEmployee of the month")

    assert structure.headings == ("AWARDS",)

    unrecognized = parser.parse("Dana Reyes\n\nCAREER HIGHLIGHTS\nShipped billing")
    assert unrecognized.headings == ()
    assert "CAREER HIGHLIGHTS" in unrecognized.contact_lines


def test_a_resume_with_no_headings_is_all_contact_block(parser):
    structure = parser.parse("Dana Reyes\ndana@example.com")

    assert structure.contact_lines == ("Dana Reyes", "dana@example.com")
    assert structure.sections == ()


def test_a_heading_with_no_body_yields_an_empty_section(parser):
    """Reported as present-but-empty rather than dropped: the validator's
    job is to complain about it, not this one's to hide it."""
    structure = parser.parse("EXPERIENCE\nAcme Corp\n\nEDUCATION")

    assert structure.headings == ("EXPERIENCE", "EDUCATION")
    assert structure.sections[1].lines == ()


def test_repeated_headings_each_become_their_own_section(parser):
    structure = parser.parse("EXPERIENCE\nAcme Corp\n\nEXPERIENCE\nGlobex")

    assert structure.headings == ("EXPERIENCE", "EXPERIENCE")
    assert structure.sections[1].lines == ("Globex",)


def test_empty_content_parses_to_an_empty_structure(parser):
    structure = parser.parse("")

    assert structure.is_empty
    assert structure.contact_lines == ()
    assert structure.sections == ()


def test_surrounding_whitespace_is_trimmed_from_every_line(parser):
    structure = parser.parse("  EXPERIENCE  \n   Acme Corp   ")

    assert structure.headings == ("EXPERIENCE",)
    assert structure.sections[0].lines == ("Acme Corp",)


def test_the_structure_carries_no_text_the_resume_does_not(parser):
    """Derived, never composed: every line in the structure appears in the
    text it was parsed from."""
    structure = parser.parse(_RESUME)

    every_line = [*structure.contact_lines]
    for section in structure.sections:
        every_line.append(section.heading)
        every_line.extend(section.lines)
    assert all(line in _RESUME for line in every_line)

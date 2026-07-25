"""Tests for AtsSafetyValidator — the check that proves the ATS-safety rules
were actually enforced.

One test per rule, plus the cases where a rule must *not* fire: a validator
that cries wolf on a candidate's name or a hyphenated date range is one
whose findings get ignored.
"""

from __future__ import annotations

import pytest

from src.domain.services.ats_safety_validator import (
    RULE_COLUMN_WHITESPACE,
    RULE_DECORATIVE_GLYPH,
    RULE_EMPTY_SECTION,
    RULE_MARKDOWN_SYNTAX,
    RULE_NON_STANDARD_HEADING,
    RULE_PAGE_FURNITURE,
    RULE_TABLE_MARKUP,
    RULE_UNRENDERABLE_CHARACTER,
    AtsSafetyValidator,
)

_CLEAN_RESUME = """DANA REYES
dana@example.com

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
def validator() -> AtsSafetyValidator:
    return AtsSafetyValidator()


def _rules(validator: AtsSafetyValidator, content: str) -> tuple[str, ...]:
    return validator.validate(content).broken_rules


# ---- a clean resume passes --------------------------------------------------


def test_an_ats_safe_resume_passes_with_no_findings(validator):
    report = validator.validate(_CLEAN_RESUME)

    assert report.is_safe
    assert report.violations == ()
    assert report.broken_rules == ()


def test_empty_content_is_trivially_safe(validator):
    assert validator.validate("").is_safe


# ---- one test per rule -----------------------------------------------------


def test_markdown_syntax_is_flagged(validator):
    assert RULE_MARKDOWN_SYNTAX in _rules(validator, "**Backend Engineer** at Acme")
    assert RULE_MARKDOWN_SYNTAX in _rules(validator, "## EXPERIENCE")
    assert RULE_MARKDOWN_SYNTAX in _rules(validator, "Built `payment` services")
    assert RULE_MARKDOWN_SYNTAX in _rules(validator, "[Portfolio](https://x.example)")


def test_table_markup_is_flagged(validator):
    assert RULE_TABLE_MARKUP in _rules(validator, "| Role | Company |")


def test_a_pipe_used_as_a_contact_separator_is_still_flagged(validator):
    """Common in real resumes and still a parser hazard, so the candidate is
    told rather than left guessing why a field came through merged."""
    assert RULE_TABLE_MARKUP in _rules(validator, "dana@example.com | Austin, TX")


def test_column_simulating_whitespace_is_flagged(validator):
    assert RULE_COLUMN_WHITESPACE in _rules(validator, "Engineer      Acme Corp")
    assert RULE_COLUMN_WHITESPACE in _rules(validator, "Engineer\tAcme Corp")


def test_a_single_space_between_words_is_not_flagged(validator):
    assert RULE_COLUMN_WHITESPACE not in _rules(validator, "Backend Engineer at Acme")


def test_decorative_glyphs_are_flagged(validator):
    assert RULE_DECORATIVE_GLYPH in _rules(validator, "• Built payment services")
    assert RULE_DECORATIVE_GLYPH in _rules(validator, "▪ Led a team")


def test_a_plain_hyphen_bullet_is_not_flagged(validator):
    assert RULE_DECORATIVE_GLYPH not in _rules(validator, "- Built payment services")


def test_a_hyphenated_date_range_is_not_flagged(validator):
    assert _rules(validator, "Backend Engineer, Acme Corp, 2019-03 to 2022-06") == ()


def test_page_furniture_is_flagged(validator):
    for line in ("Page 1 of 2", "page 2", "1 of 3", "Confidential", "Curriculum Vitae"):
        assert RULE_PAGE_FURNITURE in _rules(validator, line), line


def test_a_line_that_merely_mentions_a_page_is_not_flagged(validator):
    assert RULE_PAGE_FURNITURE not in _rules(
        validator, "Built the page rendering service"
    )


def test_a_non_standard_heading_is_flagged(validator):
    content = "Dana Reyes\n\nAWARDS AND HONORS\nEmployee of the month"

    assert RULE_NON_STANDARD_HEADING in _rules(validator, content)


def test_a_standard_heading_is_not_flagged(validator):
    content = "Dana Reyes\n\nEXPERIENCE\nBackend Engineer at Acme Corp"

    assert RULE_NON_STANDARD_HEADING not in _rules(validator, content)


def test_a_heading_with_a_trailing_colon_is_recognized_as_standard(validator):
    content = "Dana Reyes\n\nSkills:\nPython"

    assert RULE_NON_STANDARD_HEADING not in _rules(validator, content)


def test_an_all_caps_name_on_the_first_line_is_never_flagged_as_a_heading(validator):
    """Flagging the candidate's own name would make every report noise."""
    content = "DANA REYES\n\nEXPERIENCE\nBackend Engineer at Acme Corp"

    assert RULE_NON_STANDARD_HEADING not in _rules(validator, content)


def test_a_sentence_is_not_mistaken_for_a_heading(validator):
    content = "Dana Reyes\n\nEXPERIENCE\nBuilt payment services in Python."

    assert RULE_NON_STANDARD_HEADING not in _rules(validator, content)


def test_a_long_all_caps_line_is_not_treated_as_a_heading(validator):
    content = (
        "Dana Reyes\n\nEXPERIENCE\n"
        "BUILT THE ENTIRE PAYMENT PLATFORM FROM SCRATCH OVER THREE YEARS"
    )

    assert RULE_NON_STANDARD_HEADING not in _rules(validator, content)


def test_an_empty_section_is_flagged(validator):
    content = "Dana Reyes\n\nEXPERIENCE\nAcme Corp\n\nEDUCATION"

    assert RULE_EMPTY_SECTION in _rules(validator, content)


def test_a_section_with_a_body_is_not_flagged(validator):
    content = "Dana Reyes\n\nEXPERIENCE\nAcme Corp\n\nSKILLS\nPython"

    assert RULE_EMPTY_SECTION not in _rules(validator, content)


def test_characters_the_pdf_cannot_render_are_flagged(validator):
    report = validator.validate("Built 日本語 localization")

    assert RULE_UNRENDERABLE_CHARACTER in report.broken_rules
    assert "日本語" in report.violations[0].detail


def test_accented_latin_letters_are_renderable_and_not_flagged(validator):
    """WinAnsi covers them, so a candidate named Muñoz is fine."""
    assert _rules(validator, "Ana Munoz") == ()
    assert RULE_UNRENDERABLE_CHARACTER not in _rules(validator, "Ana Muñoz")


# ---- report shape ----------------------------------------------------------


def test_a_violation_carries_the_rule_the_reason_the_line_and_its_number(validator):
    report = validator.validate("Dana Reyes\n| Role | Company |")

    violation = report.violations[0]
    assert violation.rule == RULE_TABLE_MARKUP
    assert violation.line == "| Role | Company |"
    assert violation.line_number == 2
    assert violation.detail


def test_one_line_can_break_several_rules_and_each_is_reported(validator):
    report = validator.validate("Dana Reyes\n**Engineer** | Acme      Corp")

    rules = {violation.rule for violation in report.violations}
    assert {
        RULE_MARKDOWN_SYNTAX,
        RULE_TABLE_MARKUP,
        RULE_COLUMN_WHITESPACE,
    } <= rules


def test_violations_come_back_in_document_order(validator):
    content = "Dana Reyes\n| a | b |\n• bullet"

    numbers = [v.line_number for v in validator.validate(content).violations]

    assert numbers == sorted(numbers)


def test_broken_rules_lists_each_rule_once(validator):
    content = "Dana Reyes\n| a | b |\n| c | d |"

    report = validator.validate(content)

    assert report.broken_rules == (RULE_TABLE_MARKUP,)
    assert len(report.violations) == 2


def test_blank_lines_break_no_rules(validator):
    assert validator.validate("Dana Reyes\n\n\n\nEXPERIENCE\nAcme Corp").is_safe


def test_the_validator_never_rewrites_its_input(validator):
    """Reporting and fixing stay separate, so tightening a rule here can
    never quietly edit a candidate's resume."""
    content = "Dana Reyes\n**Engineer**"

    report = validator.validate(content)

    assert report.violations[0].line == "**Engineer**"

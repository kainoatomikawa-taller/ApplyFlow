"""Tests for AtsSafeResumeFormatter — the two formatting passes that keep a
generated resume parseable and, after guarding, coherent.

Split by pass: what `normalize_plain_text` has to flatten before the guard
runs, what `drop_empty_sections` has to clear afterward, and the invariant
both share — they may delete and transliterate, never introduce a word.
"""

from __future__ import annotations

import pytest

from src.domain.services.ats_safe_resume_formatter import AtsSafeResumeFormatter


@pytest.fixture
def formatter() -> AtsSafeResumeFormatter:
    return AtsSafeResumeFormatter()


# ---- normalize_plain_text ---------------------------------------------------


def test_markdown_headings_lose_their_hashes(formatter):
    assert formatter.normalize_plain_text("## EXPERIENCE") == "EXPERIENCE"
    assert formatter.normalize_plain_text("###### Skills") == "Skills"


def test_markdown_emphasis_and_code_markers_are_removed(formatter):
    result = formatter.normalize_plain_text("**Backend Engineer** in `Python` and _x_")

    assert result == "Backend Engineer in Python and _x_"


def test_bold_underscores_are_removed_but_a_single_one_is_left_alone(formatter):
    """Snake_case identifiers and URLs contain single underscores; only
    doubled ones are markdown."""
    assert formatter.normalize_plain_text("__Lead__ on payment_service") == (
        "Lead on payment_service"
    )


def test_decorative_bullets_become_plain_hyphens(formatter):
    content = "• Built services\n▪ Led a team\n‣ Shipped billing\n* Wrote docs"

    assert formatter.normalize_plain_text(content) == (
        "- Built services\n- Led a team\n- Shipped billing\n- Wrote docs"
    )


def test_indentation_is_removed_rather_than_partly_preserved(formatter):
    """Whitespace carries no meaning in a single-column plain-text resume,
    and runs of it are how a model fakes columns — so a nested bullet
    flattens to top level instead of landing half-indented."""
    assert formatter.normalize_plain_text("    • Built services") == "- Built services"


def test_space_runs_used_to_fake_columns_collapse(formatter):
    assert formatter.normalize_plain_text("Engineer      Acme Corp") == (
        "Engineer Acme Corp"
    )


def test_table_rows_are_flattened_and_dividers_dropped(formatter):
    content = "| Role | Company |\n| --- | --- |\n| Engineer | Acme Corp |"

    assert formatter.normalize_plain_text(content) == (
        "Role Company\nEngineer Acme Corp"
    )


def test_horizontal_rules_are_dropped(formatter):
    assert formatter.normalize_plain_text("EXPERIENCE\n---\nAcme Corp") == (
        "EXPERIENCE\nAcme Corp"
    )


def test_markdown_links_keep_both_the_label_and_the_url(formatter):
    """An ATS should still see the URL, and a human still needs the label."""
    result = formatter.normalize_plain_text("[Portfolio](https://dana.example.com)")

    assert result == "Portfolio https://dana.example.com"


def test_typographic_punctuation_becomes_ascii(formatter):
    content = "Shipped the “billing” rewrite — Dana’s work…"

    assert formatter.normalize_plain_text(content) == (
        'Shipped the "billing" rewrite - Dana\'s work...'
    )


def test_accented_letters_in_a_name_are_never_transliterated(formatter):
    """Flattening punctuation is safe; flattening letters would misspell the
    candidate."""
    assert formatter.normalize_plain_text("Ana Muñoz") == "Ana Muñoz"


def test_tabs_and_invisible_characters_are_replaced(formatter):
    content = "Engineer\tAcme Corp (2019)​"

    assert formatter.normalize_plain_text(content) == "Engineer Acme Corp (2019)"


def test_blank_line_runs_collapse_and_edges_are_trimmed(formatter):
    content = "\n\nEXPERIENCE\n\n\n\nAcme Corp\n\n\n"

    assert formatter.normalize_plain_text(content) == "EXPERIENCE\n\nAcme Corp"


def test_windows_and_classic_mac_line_endings_are_normalized(formatter):
    assert formatter.normalize_plain_text("EXPERIENCE\r\nAcme\rCorp") == (
        "EXPERIENCE\nAcme\nCorp"
    )


def test_trailing_whitespace_is_stripped_from_every_line(formatter):
    assert formatter.normalize_plain_text("EXPERIENCE   \nAcme Corp\t") == (
        "EXPERIENCE\nAcme Corp"
    )


def test_normalizing_is_idempotent(formatter):
    content = "## EXPERIENCE\n• Built *payment* services\n\n\n| a | b |"

    once = formatter.normalize_plain_text(content)

    assert formatter.normalize_plain_text(once) == once


def test_normalizing_introduces_no_words(formatter):
    content = "## EXPERIENCE\n• **Built** payment services in `Python`"

    result = formatter.normalize_plain_text(content)

    assert set(result.split()) <= set(
        content.replace("*", " ").replace("`", " ").split()
    ) | {
        "-",
        "EXPERIENCE",
        "Built",
    }
    assert "Python" in result


def test_already_plain_text_is_returned_unchanged(formatter):
    content = "DANA REYES\ndana@example.com\n\nEXPERIENCE\n- Built payment services"

    assert formatter.normalize_plain_text(content) == content


# ---- drop_empty_sections ----------------------------------------------------


def test_a_heading_with_no_body_is_dropped(formatter):
    content = "EXPERIENCE\nAcme Corp\n\nEDUCATION"

    assert formatter.drop_empty_sections(content) == "EXPERIENCE\nAcme Corp"


def test_a_heading_followed_only_by_another_heading_is_dropped(formatter):
    content = "SUMMARY\n\nEXPERIENCE\nAcme Corp"

    assert formatter.drop_empty_sections(content) == "EXPERIENCE\nAcme Corp"


def test_consecutive_empty_headings_are_all_dropped(formatter):
    content = "SUMMARY\n\nCERTIFICATIONS\n\nSKILLS\n\nEXPERIENCE\nAcme Corp"

    assert formatter.drop_empty_sections(content) == "EXPERIENCE\nAcme Corp"


def test_a_heading_with_a_body_is_kept(formatter):
    content = "SKILLS\nPython\n\nEXPERIENCE\nAcme Corp"

    assert formatter.drop_empty_sections(content) == content


def test_headings_are_matched_case_insensitively_and_with_a_colon(formatter):
    content = "Experience:\n\nSkills\nPython"

    assert formatter.drop_empty_sections(content) == "Skills\nPython"


def test_a_non_standard_heading_is_never_dropped(formatter):
    """Only the ATS-standard vocabulary is droppable, so a candidate's
    all-caps name can't be mistaken for an empty section and deleted."""
    content = "DANA REYES\n\nEXPERIENCE\nAcme Corp"

    assert formatter.drop_empty_sections(content) == content


def test_an_all_caps_name_above_a_heading_survives(formatter):
    content = "DANA REYES\nEDUCATION"

    assert formatter.drop_empty_sections(content) == "DANA REYES"


def test_dropping_sections_is_idempotent(formatter):
    content = "SUMMARY\n\nEXPERIENCE\nAcme Corp\n\nEDUCATION"

    once = formatter.drop_empty_sections(content)

    assert formatter.drop_empty_sections(once) == once


def test_a_document_of_only_empty_headings_becomes_empty(formatter):
    assert formatter.drop_empty_sections("SUMMARY\n\nEXPERIENCE\n\nSKILLS") == ""


def test_empty_input_stays_empty(formatter):
    assert formatter.normalize_plain_text("") == ""
    assert formatter.drop_empty_sections("") == ""

"""Tests for matching a field of study against a dropdown's options.

The load-bearing rule is the "if and only if": a broader category may only be
chosen when the exact subject is not on offer. Nearly every test here exists to
pin one half of that, or to pin a broadening that must *not* happen.
"""

from __future__ import annotations

import pytest

from src.domain.services.subject_option_matcher import (
    match_subject_options,
    normalize_subject,
)

# -- Exact wins, always --------------------------------------------------------


def test_the_exact_subject_is_chosen_when_it_is_listed() -> None:
    match = match_subject_options(
        ("Applied Mathematics",), ["Applied Mathematics", "Mathematics"]
    )
    assert match is not None
    assert match.option == "Applied Mathematics"
    assert match.is_exact is True


def test_a_broader_category_is_never_preferred_over_the_exact_subject() -> None:
    """The "only if" half. Listing order must not matter, so the broader option
    is placed first here — the exact match still has to win."""
    match = match_subject_options(
        ("Applied Mathematics",), ["Mathematics", "Applied Mathematics"]
    )
    assert match is not None
    assert match.option == "Applied Mathematics"
    assert match.is_exact is True


def test_an_exact_match_differing_only_in_case_and_spacing_is_still_exact() -> None:
    match = match_subject_options(("applied   mathematics",), ["Applied Mathematics"])
    assert match is not None
    assert match.option == "Applied Mathematics"
    assert match.is_exact is True


def test_the_option_is_returned_in_the_forms_own_spelling() -> None:
    """What gets written has to be a string the form will accept, so the form's
    spelling wins over the candidate's."""
    match = match_subject_options(("applied mathematics",), ["APPLIED MATHEMATICS"])
    assert match is not None
    assert match.option == "APPLIED MATHEMATICS"


# -- Broadening by head noun ---------------------------------------------------


def test_an_applied_math_major_falls_back_to_mathematics() -> None:
    match = match_subject_options(
        ("Applied Mathematics",), ["Mathematics", "Physics", "Biology"]
    )
    assert match is not None
    assert match.option == "Mathematics"
    assert match.is_exact is False
    assert match.subject == "Applied Mathematics"


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Computer Engineering", "Engineering"),
        ("Mechanical Engineering", "Engineering"),
        ("Cognitive Science", "Science"),
        ("Applied Physics", "Physics"),
    ],
)
def test_the_trailing_words_name_the_category(subject: str, expected: str) -> None:
    match = match_subject_options((subject,), ["Engineering", "Science", "Physics"])
    assert match is not None
    assert match.option == expected


def test_the_longest_matching_category_wins() -> None:
    """A form offering both a specific and a general heading should get the
    specific one — broadening as little as the list allows."""
    match = match_subject_options(
        ("Electrical and Computer Engineering",),
        ["Engineering", "Computer Engineering"],
    )
    assert match is not None
    assert match.option == "Computer Engineering"


def test_a_leading_word_is_not_treated_as_the_category() -> None:
    """The trap this rule exists for. "Mathematics Education" is a degree in
    Education; answering "Mathematics" would misstate what was studied."""
    match = match_subject_options(
        ("Mathematics Education",), ["Mathematics", "Education"]
    )
    assert match is not None
    assert match.option == "Education"


def test_a_leading_word_alone_is_no_match_at_all() -> None:
    """With only the wrong-end word on offer, nothing is chosen — the field is
    surfaced rather than answered with "Mathematics"."""
    assert match_subject_options(("Mathematics Education",), ["Mathematics"]) is None


# -- Broadening by the curated table -------------------------------------------


def test_data_analytics_matches_a_form_that_says_data_science() -> None:
    match = match_subject_options(
        ("Data Analytics",), ["Data Science", "Computer Science"]
    )
    assert match is not None
    assert match.option == "Data Science"
    assert match.is_exact is False


def test_the_data_science_pairing_works_in_both_directions() -> None:
    match = match_subject_options(("Data Science",), ["Data Analytics", "Statistics"])
    assert match is not None
    assert match.option == "Data Analytics"


def test_an_abbreviation_resolves_to_the_full_subject() -> None:
    match = match_subject_options(("Comp Sci",), ["Computer Science", "Mathematics"])
    assert match is not None
    assert match.option == "Computer Science"
    assert match.is_exact is False


def test_the_head_noun_is_preferred_over_the_curated_table() -> None:
    """A trailing word is evidence from the subject itself; the table is an
    assumption made on the candidate's behalf. So "Analytics" — literally part of
    their major — beats the curated "Data Science"."""
    match = match_subject_options(("Data Analytics",), ["Data Science", "Analytics"])
    assert match is not None
    assert match.option == "Analytics"


def test_curated_parents_are_tried_most_specific_first() -> None:
    """Deterministic regardless of how the form orders its list."""
    forward = match_subject_options(("Biochemistry",), ["Biology", "Chemistry"])
    reverse = match_subject_options(("Biochemistry",), ["Chemistry", "Biology"])
    assert forward is not None and reverse is not None
    assert forward.option == reverse.option == "Chemistry"


# -- Several subjects ----------------------------------------------------------


def test_an_exact_match_on_a_second_major_beats_broadening_the_first() -> None:
    """Every subject is tried for an exact match before any is broadened, so a
    listed second major is chosen over a category standing in for the first."""
    match = match_subject_options(
        ("Applied Mathematics", "Computer Science"), ["Mathematics", "Computer Science"]
    )
    assert match is not None
    assert match.option == "Computer Science"
    assert match.is_exact is True
    assert match.subject == "Computer Science"


def test_the_candidates_own_order_breaks_a_tie_between_exact_matches() -> None:
    match = match_subject_options(
        ("Mathematics", "Computer Science"), ["Computer Science", "Mathematics"]
    )
    assert match is not None
    assert match.option == "Mathematics"


def test_a_second_major_is_broadened_when_neither_is_listed_exactly() -> None:
    match = match_subject_options(
        ("Basket Weaving", "Applied Mathematics"), ["Mathematics", "Biology"]
    )
    assert match is not None
    assert match.option == "Mathematics"
    assert match.subject == "Applied Mathematics"


# -- Refusing ------------------------------------------------------------------


def test_nothing_is_chosen_when_no_option_relates_to_the_subject() -> None:
    assert (
        match_subject_options(("Basket Weaving",), ["Mathematics", "Biology"]) is None
    )


def test_placeholder_options_are_not_matchable() -> None:
    """A "Select a major" prompt is not an answer."""
    assert match_subject_options(("Applied Mathematics",), ["", "   "]) is None


def test_no_options_means_no_match() -> None:
    assert match_subject_options(("Applied Mathematics",), []) is None


def test_no_subjects_means_no_match() -> None:
    assert match_subject_options((), ["Mathematics"]) is None
    assert match_subject_options(("", "  "), ["Mathematics"]) is None


def test_a_single_word_subject_is_never_broadened_into_an_unrelated_option() -> None:
    """There is no suffix shorter than the whole word, so nothing can stand in
    for it unless the table says so."""
    assert match_subject_options(("Mathematics",), ["Applied Mathematics"]) is None


# -- Normalization -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Applied Mathematics", "applied mathematics"),
        ("  Applied   Mathematics  ", "applied mathematics"),
        ("Computer Science (B.S.)", "computer science bs"),
        # The dropped "&" leaves no double space behind: whitespace is collapsed
        # after punctuation is removed, not before.
        ("Political Science & Government", "political science government"),
    ],
)
def test_normalize_subject_folds_case_spacing_and_punctuation(
    raw: str, expected: str
) -> None:
    assert normalize_subject(raw) == expected

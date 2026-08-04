"""Tests for `EducationEntry`'s majors and minors.

What is worth pinning here is not that two lists round-trip. It is the three
rules that make the split worth having at all: a blank row is not a subject, a
repeat states nothing new, and a minor never becomes a major — plus the derived
`field_of_study` that lets a single form box still be filled.
"""

from __future__ import annotations

import pytest

from src.domain.entities.education_entry import EducationEntry
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_source import ProvenanceSource


def _entry(**overrides: object) -> EducationEntry:
    kwargs: dict[str, object] = {
        "id": "edu-1",
        "institution_name": "State University",
        "degree": "Bachelor of Science",
        "source": ProvenanceSource.USER_ENTERED,
    }
    kwargs.update(overrides)
    return EducationEntry(**kwargs)  # type: ignore[arg-type]


# -- Cleaning ------------------------------------------------------------------


def test_blank_and_whitespace_only_subjects_are_dropped() -> None:
    """An editor with one input per subject produces an empty trailing row. That
    is a UI artifact, not something the candidate asserted."""
    entry = _entry(majors=("Computer Science", "", "   "), minors=("",))
    assert entry.majors == ("Computer Science",)
    assert entry.minors == ()


def test_repeats_are_dropped_case_insensitively_keeping_the_first_spelling() -> None:
    entry = _entry(majors=("Computer Science", "computer science", "Mathematics"))
    assert entry.majors == ("Computer Science", "Mathematics")


def test_subjects_are_stripped_but_internal_spacing_is_left_alone() -> None:
    assert _entry(majors=("  Computer   Science  ",)).majors == ("Computer   Science",)


def test_order_is_preserved_because_a_first_major_is_usually_the_primary_one() -> None:
    entry = _entry(majors=("Mathematics", "Physics", "Philosophy"))
    assert entry.majors == ("Mathematics", "Physics", "Philosophy")


def test_a_non_string_subject_is_refused() -> None:
    with pytest.raises(InvalidValueError):
        _entry(majors=("Computer Science", 42))


def test_a_list_is_accepted_and_normalised_to_a_tuple() -> None:
    """The HTTP layer hands over whatever JSON decoded to; the entity is what
    guarantees the stored shape."""
    entry = _entry(majors=["Computer Science"])
    assert entry.majors == ("Computer Science",)
    assert isinstance(entry.majors, tuple)


# -- Majors and minors stay distinct -------------------------------------------


def test_a_minor_is_never_merged_into_the_majors() -> None:
    """The reason the two are separate columns. A tailored résumé that read a
    minor as a major would claim the stronger credential."""
    entry = _entry(majors=("Computer Science",), minors=("Economics",))
    assert entry.majors == ("Computer Science",)
    assert entry.minors == ("Economics",)
    assert "Economics" not in (entry.field_of_study or "")


def test_the_same_subject_may_be_both_a_major_and_a_minor_at_once() -> None:
    """Deduplication is per list. Odd but not contradictory, and not this
    entity's business to reject."""
    entry = _entry(majors=("Music",), minors=("Music",))
    assert entry.majors == ("Music",)
    assert entry.minors == ("Music",)


# -- The derived single-string rendering ----------------------------------------


def test_field_of_study_joins_the_majors_for_forms_that_offer_one_box() -> None:
    entry = _entry(majors=("Computer Science", "Mathematics"))
    assert entry.field_of_study == "Computer Science, Mathematics"


def test_field_of_study_is_none_rather_than_empty_when_no_majors_are_stated() -> None:
    """`None` so "no majors on file" is indistinguishable from any other absent
    optional value, which is what the rest of the profile already assumes."""
    assert _entry().field_of_study is None
    assert _entry(majors=("",)).field_of_study is None


def test_field_of_study_ignores_minors_entirely() -> None:
    assert _entry(minors=("Economics",)).field_of_study is None


def test_field_of_study_cannot_be_set_directly() -> None:
    """It is derived, so there is no way for the joined string and the list to
    disagree with each other."""
    with pytest.raises((AttributeError, TypeError)):
        _entry().field_of_study = "Something Else"  # type: ignore[misc]


# -- Untouched invariants ------------------------------------------------------


def test_majors_and_minors_both_default_to_empty() -> None:
    entry = _entry()
    assert entry.majors == ()
    assert entry.minors == ()


def test_two_entries_do_not_share_a_default_subject_tuple() -> None:
    """A mutable default would have made every entry alias one list."""
    first, second = _entry(id="a"), _entry(id="b")
    assert first.majors is not second.majors or first.majors == ()
    assert first.majors == () and second.majors == ()

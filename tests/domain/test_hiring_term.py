"""Tests for `HiringTerm` and `JobSearchPreferences`.

The rule worth pinning is what an *unstated* year means. Boards publish "Summer
Intern" with no year constantly, and the choice between treating that as "any
year" and "no match" decides whether a term filter quietly hides postings the
candidate wants.
"""

from __future__ import annotations

import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.employment_type import EmploymentType
from src.domain.value_objects.hiring_term import HiringTerm, TermSeason
from src.domain.value_objects.job_search_preferences import JobSearchPreferences

SUMMER_2027 = HiringTerm(season=TermSeason.SUMMER, year=2027)
SUMMER_ANY = HiringTerm(season=TermSeason.SUMMER)
FALL_2026 = HiringTerm(season=TermSeason.FALL, year=2026)


# -- HiringTerm ----------------------------------------------------------------


def test_a_term_labels_itself_with_and_without_a_year() -> None:
    assert SUMMER_2027.label == "Summer 2027"
    assert SUMMER_ANY.label == "Summer"


def test_two_identical_terms_match() -> None:
    assert SUMMER_2027.matches(HiringTerm(season=TermSeason.SUMMER, year=2027))


def test_a_different_season_never_matches() -> None:
    assert not SUMMER_2027.matches(FALL_2026)
    assert not SUMMER_ANY.matches(HiringTerm(season=TermSeason.FALL))


def test_a_different_year_in_the_same_season_does_not_match() -> None:
    assert not SUMMER_2027.matches(HiringTerm(season=TermSeason.SUMMER, year=2026))


def test_an_unstated_year_matches_any_year_of_that_season() -> None:
    """The rule this value object exists for. A posting that says "Summer Intern"
    without a year is unknown, not a mismatch — hiding it would be
    indistinguishable from there being no such posting."""
    assert SUMMER_ANY.matches(SUMMER_2027)
    assert SUMMER_2027.matches(SUMMER_ANY)


def test_matching_is_symmetric() -> None:
    """Reads the same whichever side is the candidate's wish."""
    for left in (SUMMER_2027, SUMMER_ANY, FALL_2026):
        for right in (SUMMER_2027, SUMMER_ANY, FALL_2026):
            assert left.matches(right) == right.matches(left)


def test_a_season_is_required_to_be_a_real_season() -> None:
    with pytest.raises(InvalidValueError):
        HiringTerm(season="summer")  # type: ignore[arg-type]


@pytest.mark.parametrize("year", [1999, 2101, 20, 202700])
def test_an_implausible_year_is_refused(year: int) -> None:
    """A value this far out is a misread rather than a real term."""
    with pytest.raises(InvalidValueError):
        HiringTerm(season=TermSeason.SUMMER, year=year)


def test_a_boolean_is_not_a_year() -> None:
    with pytest.raises(InvalidValueError):
        HiringTerm(season=TermSeason.SUMMER, year=True)  # type: ignore[arg-type]


def test_terms_are_comparable_by_value() -> None:
    """Frozen and value-equal, so deduplication in preferences works."""
    assert HiringTerm(season=TermSeason.SUMMER, year=2027) == SUMMER_2027
    assert len({SUMMER_2027, HiringTerm(season=TermSeason.SUMMER, year=2027)}) == 1


# -- JobSearchPreferences ------------------------------------------------------


def test_nothing_stated_means_everything_is_wanted() -> None:
    """Silence is "show me everything", never "show me nothing" — the same rule
    the rest of matching follows for an unset profile field."""
    preferences = JobSearchPreferences()

    assert preferences.is_empty
    assert preferences.wants_employment_type(EmploymentType.FULL_TIME)
    assert preferences.wants_term(FALL_2026)


def test_a_stated_employment_type_excludes_the_others() -> None:
    preferences = JobSearchPreferences(
        employment_types=(EmploymentType.INTERNSHIP, EmploymentType.CO_OP)
    )

    assert preferences.wants_employment_type(EmploymentType.INTERNSHIP)
    assert not preferences.wants_employment_type(EmploymentType.FULL_TIME)


def test_a_stated_term_excludes_other_terms() -> None:
    preferences = JobSearchPreferences(terms=(SUMMER_2027,))

    assert preferences.wants_term(SUMMER_2027)
    assert not preferences.wants_term(FALL_2026)
    # ...but a posting with no year stated still gets through.
    assert preferences.wants_term(SUMMER_ANY)


def test_stating_terms_does_not_narrow_employment_types_or_the_reverse() -> None:
    """The two axes are independent: asking only for Summer 2027 must not also
    silently restrict which kinds of role are shown."""
    preferences = JobSearchPreferences(terms=(SUMMER_2027,))

    assert preferences.wants_employment_type(EmploymentType.FULL_TIME)
    assert not preferences.states_employment_types
    assert preferences.states_terms


def test_duplicates_are_dropped_and_order_is_kept() -> None:
    preferences = JobSearchPreferences(
        employment_types=(
            EmploymentType.INTERNSHIP,
            EmploymentType.CO_OP,
            EmploymentType.INTERNSHIP,
        ),
        terms=(SUMMER_2027, FALL_2026, SUMMER_2027),
    )

    assert preferences.employment_types == (
        EmploymentType.INTERNSHIP,
        EmploymentType.CO_OP,
    )
    assert preferences.terms == (SUMMER_2027, FALL_2026)


def test_a_wrong_type_in_either_list_is_refused() -> None:
    with pytest.raises(InvalidValueError):
        JobSearchPreferences(employment_types=("internship",))  # type: ignore[arg-type]
    with pytest.raises(InvalidValueError):
        JobSearchPreferences(terms=(EmploymentType.INTERNSHIP,))  # type: ignore[arg-type]


def test_an_unbounded_list_is_refused() -> None:
    with pytest.raises(InvalidValueError):
        JobSearchPreferences(
            terms=tuple(
                HiringTerm(season=TermSeason.SUMMER, year=2000 + offset)
                for offset in range(20)
            )
        )

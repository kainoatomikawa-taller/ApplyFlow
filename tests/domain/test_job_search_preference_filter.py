"""Tests for `JobSearchPreferenceFilter`.

This filter can remove a posting from the candidate's list, so the cases that
matter most are the ones where it must *not*: an unstated preference, and a
posting whose employment type or term could not be extracted.
"""

from __future__ import annotations

from src.domain.services.job_search_preference_filter import JobSearchPreferenceFilter
from src.domain.value_objects.employment_type import EmploymentType
from src.domain.value_objects.hiring_term import HiringTerm, TermSeason
from src.domain.value_objects.job_function import JobFunction
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.job_search_preferences import JobSearchPreferences

SUMMER_2027 = HiringTerm(season=TermSeason.SUMMER, year=2027)
FALL_2026 = HiringTerm(season=TermSeason.FALL, year=2026)

WANTS_INTERNSHIPS = JobSearchPreferences(
    employment_types=(EmploymentType.INTERNSHIP, EmploymentType.CO_OP)
)
WANTS_SUMMER_2027 = JobSearchPreferences(terms=(SUMMER_2027,))


def _filter() -> JobSearchPreferenceFilter:
    return JobSearchPreferenceFilter()


# -- Nothing stated ------------------------------------------------------------


def test_a_candidate_who_stated_nothing_sees_everything() -> None:
    result = _filter().evaluate(
        JobSearchPreferences(),
        JobRequirements(
            employment_type=EmploymentType.FULL_TIME, hiring_term=FALL_2026
        ),
    )

    assert result.matches
    assert result.reasons == ()


# -- Employment type -----------------------------------------------------------


def test_a_wanted_employment_type_matches() -> None:
    result = _filter().evaluate(
        WANTS_INTERNSHIPS, JobRequirements(employment_type=EmploymentType.INTERNSHIP)
    )
    assert result.matches


def test_an_unwanted_employment_type_is_filtered_with_a_reason() -> None:
    """The scenario the phase was built for: an undergraduate looking for an
    internship should not be shown senior full-time roles."""
    result = _filter().evaluate(
        WANTS_INTERNSHIPS, JobRequirements(employment_type=EmploymentType.FULL_TIME)
    )

    assert not result.matches
    assert result.reasons == ("This is a full time role",)


def test_a_new_grad_role_is_filtered_out_for_someone_wanting_internships() -> None:
    """A new-grad role is full-time work aimed at graduating students, which is
    why it is its own type rather than folded into `FULL_TIME` — a junior wants
    neither, but a senior wants exactly this one."""
    result = _filter().evaluate(
        WANTS_INTERNSHIPS, JobRequirements(employment_type=EmploymentType.NEW_GRAD)
    )
    assert not result.matches


def test_an_unextracted_employment_type_is_never_filtered() -> None:
    """ "We could not tell what kind of role this is" does not mean "this is not
    the kind you asked for"."""
    result = _filter().evaluate(WANTS_INTERNSHIPS, JobRequirements())
    assert result.matches


# -- Terms ---------------------------------------------------------------------


def test_a_wanted_term_matches() -> None:
    result = _filter().evaluate(
        WANTS_SUMMER_2027, JobRequirements(hiring_term=SUMMER_2027)
    )
    assert result.matches


def test_another_term_is_filtered_with_a_reason() -> None:
    result = _filter().evaluate(
        WANTS_SUMMER_2027, JobRequirements(hiring_term=FALL_2026)
    )

    assert not result.matches
    assert result.reasons == ("This is for Fall 2026",)


def test_a_posting_with_no_year_stated_survives_a_year_specific_wish() -> None:
    """46 of the corpus's postings state a term and many state only a season. A
    filter that dropped those would hide real matches."""
    result = _filter().evaluate(
        WANTS_SUMMER_2027,
        JobRequirements(hiring_term=HiringTerm(season=TermSeason.SUMMER)),
    )
    assert result.matches


def test_a_posting_with_no_term_at_all_survives() -> None:
    result = _filter().evaluate(WANTS_SUMMER_2027, JobRequirements())
    assert result.matches


# -- Both axes together --------------------------------------------------------


def test_both_mismatches_are_reported_not_just_the_first() -> None:
    """So a candidate can see the whole reason a posting was hidden rather than
    fixing one preference and finding another."""
    preferences = JobSearchPreferences(
        employment_types=(EmploymentType.INTERNSHIP,), terms=(SUMMER_2027,)
    )

    result = _filter().evaluate(
        preferences,
        JobRequirements(
            employment_type=EmploymentType.FULL_TIME, hiring_term=FALL_2026
        ),
    )

    assert not result.matches
    assert len(result.reasons) == 2


def test_matching_one_axis_is_not_enough_when_the_other_fails() -> None:
    preferences = JobSearchPreferences(
        employment_types=(EmploymentType.INTERNSHIP,), terms=(SUMMER_2027,)
    )

    result = _filter().evaluate(
        preferences,
        JobRequirements(
            employment_type=EmploymentType.INTERNSHIP, hiring_term=FALL_2026
        ),
    )

    assert not result.matches
    assert result.reasons == ("This is for Fall 2026",)


# -- Function (Phase 3) --------------------------------------------------------
#
# Function is the axis a candidate picks by, and the one most often unextractable:
# it is inferred from a posting's prose, so "could not tell" is common. The cases
# below that assert a posting *survives* matter more than the ones that filter.

WANTS_ENGINEERING = JobSearchPreferences(
    functions=(JobFunction.SOFTWARE_ENGINEERING, JobFunction.DATA_SCIENCE)
)


def test_a_wanted_function_matches() -> None:
    result = _filter().evaluate(
        WANTS_ENGINEERING,
        JobRequirements(job_function=JobFunction.SOFTWARE_ENGINEERING),
    )
    assert result.matches


def test_an_unwanted_function_is_filtered_with_a_reason() -> None:
    result = _filter().evaluate(
        WANTS_ENGINEERING, JobRequirements(job_function=JobFunction.SALES)
    )

    assert not result.matches
    assert result.reasons == ("This is a sales role",)


def test_an_unclassified_posting_is_never_filtered_by_function() -> None:
    """The most important case for this axis. A posting's function is inferred
    from prose, so `None` is common — hiding those would shrink the list in a way
    indistinguishable from there being no such jobs."""
    result = _filter().evaluate(WANTS_ENGINEERING, JobRequirements())
    assert result.matches


def test_adjacent_data_functions_are_separate_and_both_selectable() -> None:
    """Employers use "analytics" and "data science" interchangeably; the domain
    keeps them apart because the work differs. Someone who wants either selects
    both, which is why this is a set rather than a single choice."""
    wants_analytics_only = JobSearchPreferences(functions=(JobFunction.DATA_ANALYTICS,))

    assert (
        not _filter()
        .evaluate(
            wants_analytics_only, JobRequirements(job_function=JobFunction.DATA_SCIENCE)
        )
        .matches
    )
    assert (
        _filter()
        .evaluate(
            JobSearchPreferences(
                functions=(JobFunction.DATA_ANALYTICS, JobFunction.DATA_SCIENCE)
            ),
            JobRequirements(job_function=JobFunction.DATA_SCIENCE),
        )
        .matches
    )


def test_the_three_axes_are_independent() -> None:
    """Stating a function must not narrow employment types or terms, and a posting
    has to clear all three to survive."""
    preferences = JobSearchPreferences(
        employment_types=(EmploymentType.INTERNSHIP,),
        terms=(SUMMER_2027,),
        functions=(JobFunction.SOFTWARE_ENGINEERING,),
    )

    # Clears all three.
    assert (
        _filter()
        .evaluate(
            preferences,
            JobRequirements(
                employment_type=EmploymentType.INTERNSHIP,
                hiring_term=SUMMER_2027,
                job_function=JobFunction.SOFTWARE_ENGINEERING,
            ),
        )
        .matches
    )

    # Right role and term, wrong function.
    result = _filter().evaluate(
        preferences,
        JobRequirements(
            employment_type=EmploymentType.INTERNSHIP,
            hiring_term=SUMMER_2027,
            job_function=JobFunction.CONSULTING,
        ),
    )
    assert not result.matches
    assert result.reasons == ("This is a consulting role",)


def test_stating_only_a_function_leaves_the_other_axes_open() -> None:
    assert WANTS_ENGINEERING.wants_employment_type(EmploymentType.FULL_TIME)
    assert WANTS_ENGINEERING.wants_term(FALL_2026)
    assert WANTS_ENGINEERING.states_functions
    assert not WANTS_ENGINEERING.states_terms

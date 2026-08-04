"""UpdateJobSearchPreferences use case — record what kind of work the candidate
wants to see.

A whole-value replace, like every other profile section: the submitted lists are
the preferences, and sending empty ones is how the candidate turns filtering back
off. That has to be expressible, which is why this is not a merge.

Nothing here is stamped with a `ProvenanceSource`. Every other profile writer
stamps one because it is recording a claim that may later be asserted to an
employer; a preference is never asserted to anyone and can only ever be the
candidate's own statement, so there would be nothing for the tag to distinguish.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import (
    JobSearchPreferencesInput,
    ProfileOutput,
)
from src.application.exceptions import UnknownProfileEnumValueError
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import InvalidValueError, ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.employment_type import EmploymentType
from src.domain.value_objects.hiring_term import HiringTerm, TermSeason
from src.domain.value_objects.job_search_preferences import JobSearchPreferences


class UpdateJobSearchPreferences:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, request: JobSearchPreferencesInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        profile.set_job_search_preferences(
            JobSearchPreferences(
                employment_types=tuple(
                    _parse_employment_type(value) for value in request.employment_types
                ),
                terms=tuple(
                    _parse_term(term.season, term.year) for term in request.terms
                ),
            )
        )
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _parse_employment_type(value: str) -> EmploymentType:
    """An unrecognized value is refused rather than dropped.

    The opposite of how the repository reads these back, and deliberately so: a
    stored value that no longer parses is history to salvage, while an
    unrecognized value arriving from a client is a caller mistake, and silently
    discarding it would leave the candidate believing they had set a preference
    that is not being applied.
    """
    try:
        return EmploymentType(value.strip().lower())
    except ValueError as exc:
        raise UnknownProfileEnumValueError(
            "employment type",
            value,
            tuple(member.value for member in EmploymentType),
        ) from exc


def _parse_term(season: str, year: int | None) -> HiringTerm:
    try:
        return HiringTerm(season=TermSeason(season.strip().lower()), year=year)
    except ValueError as exc:
        raise UnknownProfileEnumValueError(
            "term season", season, tuple(member.value for member in TermSeason)
        ) from exc
    except InvalidValueError as exc:
        # A year outside the sane range. Reported as the bad value it is rather
        # than quietly stored as "any year", which would silently widen the
        # candidate's filter instead of telling them they mistyped.
        raise UnknownProfileEnumValueError(
            "term year", str(year), ("a four-digit year between 2000 and 2100",)
        ) from exc

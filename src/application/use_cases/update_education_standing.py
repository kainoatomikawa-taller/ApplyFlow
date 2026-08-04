"""UpdateEducationStanding use case — record where the candidate is in their
education right now.

The reason this section exists is that `highest_degree` could only say what the
candidate had *finished*, so a current undergraduate had no honest answer to give:
the true one ("high school") disqualified them from most of the roles they wanted,
and the useful one was a claim about a degree they had not completed. This stores
the missing fact instead of asking them to misstate the existing one.

A whole-value replace, like every other section here. The three parts constrain
each other — you cannot be "not enrolled" and also graduating in 2027 — so they
are validated together by `EducationStanding` rather than set one at a time
through a half-valid intermediate state.

Not stamped with a `ProvenanceSource`, and deliberately never parsed off a
résumé. A résumé states dates, not whether someone is enrolled *today*, and
inferring "still studying" from an education entry with no end date is exactly the
kind of guess that would then be compared against a posting's eligibility rule.
Only the candidate can say this.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import (
    EducationStandingInput,
    ProfileOutput,
)
from src.application.exceptions import UnknownProfileEnumValueError
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import (
    InvalidValueError,
    ProfileNotFoundError,
)
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.degree_level import DegreeLevel
from src.domain.value_objects.education_standing import (
    EducationStanding,
    EnrollmentStatus,
)


class UpdateEducationStanding:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, request: EducationStandingInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        status = _parse_enrollment_status(request.enrollment_status)
        degree = _parse_degree_in_progress(request.degree_in_progress)

        try:
            standing = EducationStanding(
                enrollment_status=status,
                degree_in_progress=degree,
                expected_graduation=request.expected_graduation,
            )
        except InvalidValueError as exc:
            # The contradiction `EducationStanding` refuses: not enrolled, yet
            # pursuing something. Surfaced as a validation error against the field
            # the candidate has to change rather than as a 500, since the payload
            # is individually valid and only jointly wrong.
            raise UnknownProfileEnumValueError(
                "enrollment status",
                str(request.enrollment_status),
                (
                    "undergraduate or graduate when a degree in progress or "
                    "expected graduation is given",
                ),
            ) from exc

        profile.set_education_standing(standing)
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _parse_enrollment_status(value: str | None) -> EnrollmentStatus | None:
    """An omitted status means *unanswered*, not "not enrolled".

    The distinction is the whole reason the field is optional: "I have finished
    studying" is a fact eligibility filtering may act on, while "I have not said"
    must never cost the candidate a posting. Submitting nothing therefore clears
    the section back to unanswered rather than asserting the first.

    Empty input is not an error for the same reason it is not elsewhere in the
    editor: a `<select>` with nothing chosen submits an empty string, and treating
    that as invalid would make clearing the section impossible from a browser.
    """
    if value is None or not value.strip():
        return None
    try:
        return EnrollmentStatus(value.strip().lower())
    except ValueError as exc:
        raise UnknownProfileEnumValueError(
            "enrollment status",
            value,
            tuple(member.value for member in EnrollmentStatus),
        ) from exc


def _parse_degree_in_progress(value: str | None) -> DegreeLevel | None:
    if value is None or not value.strip():
        return None
    try:
        return DegreeLevel(value.strip().lower())
    except ValueError as exc:
        raise UnknownProfileEnumValueError(
            "degree in progress",
            value,
            tuple(member.value for member in DegreeLevel),
        ) from exc

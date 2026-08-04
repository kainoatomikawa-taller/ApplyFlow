"""UpdateProfileQualifications use case — held clearance and highest degree.

These two are the odd pair in the profile: nothing fills them into an
application form. They exist for `HardDisqualifierFilter`, which compares them
against a posting's stated requirements to decide whether a job is worth showing
at all.

That makes their absence meaningful in a specific way worth preserving: an
unstated value is "unknown", never "the candidate has none". The filter is built
so a gap in the candidate's own data never disqualifies them — see `UserProfile`
— so clearing a value here restores that state rather than asserting a negative.

Both are enums, and unrecognized input is refused rather than coerced. An
invalid clearance level would otherwise land in the profile as a string the
matching layer silently fails to match on.
"""

from __future__ import annotations

from typing import TypeVar

from src.application.dtos.profile_dtos import ProfileOutput, QualificationsInput
from src.application.exceptions import UnknownProfileEnumValueError
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.clearance_level import ClearanceLevel
from src.domain.value_objects.degree_level import DegreeLevel


class UpdateProfileQualifications:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, request: QualificationsInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        profile.set_clearance_level(
            parse_optional_enum(
                ClearanceLevel, request.clearance_level, "clearance level"
            )
        )
        profile.set_highest_degree(
            parse_optional_enum(DegreeLevel, request.highest_degree, "highest degree")
        )
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


#: The profile's two "qualification" enums. A `TypeVar` rather than PEP 695's
#: inline syntax because this project targets Python 3.11.
_EnumT = TypeVar("_EnumT", ClearanceLevel, DegreeLevel)


def parse_optional_enum(
    enum_type: type[_EnumT], value: str | None, label: str
) -> _EnumT | None:
    """Resolve a wire value to one of the profile's enums, or None.

    Empty and whitespace-only are treated as None — "cleared", not "invalid" —
    because a `<select>` with no selection submits an empty string, and refusing
    that would make clearing a value impossible from a browser.

    Anything else that is not a member raises, naming the accepted values, so a
    stale client is told what to send rather than only that it was wrong.
    """
    if value is None or not value.strip():
        return None
    try:
        return enum_type(value.strip())
    except ValueError:
        raise UnknownProfileEnumValueError(
            label, value, tuple(member.value for member in enum_type)
        ) from None

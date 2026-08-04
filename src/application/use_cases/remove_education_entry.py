"""RemoveEducationEntry use case — delete one qualification from the profile.

Same contract as `RemoveWorkHistoryEntry`, including raising when the id is not
on the profile rather than treating the delete as already done.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository


class RemoveEducationEntry:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: str, entry_id: str) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)

        profile.remove_education(entry_id)
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)

"""RemoveWorkHistoryEntry use case — delete one job from the profile.

The counterpart the profile never had. Until it existed, a résumé parse could
only append, so a mis-parsed job — or a duplicate from parsing the same résumé
twice — was permanent.

Removing an entry that is not there raises rather than succeeding quietly.
Deleting is idempotent from the candidate's point of view, but "the thing you
asked me to delete was not on your profile" is worth saying: the usual cause is a
stale list in another tab, and reporting it is how the client learns to refresh.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository


class RemoveWorkHistoryEntry:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: str, entry_id: str) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)

        profile.remove_work_history(entry_id)
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)

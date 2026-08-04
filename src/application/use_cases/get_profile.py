"""GetProfile use case — the candidate's own profile, for reading and editing.

The first read path this profile has ever had. Until the editor existed, a
profile could only be *written* (by résumé parsing) and read back once, in the
response to that same parse — so a candidate could not see what had been stored
about them, let alone check whether the parser got it right.

Raises rather than returning None for a missing profile. "No profile yet" is a
real state — a new account that has neither uploaded a résumé nor filled in the
contact section — and it needs a distinct answer, because the remedy is specific:
save your name and email, which is the one section that can create a profile.
Returning an empty `ProfileOutput` would require inventing a name and an email
the aggregate insists on, and returning None would push the "does it exist?"
branch into every caller.

Reads encrypted columns, so the caller must already be inside an authorized
decryption scope — for the HTTP path that is `get_current_user`.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository


class GetProfile:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: str) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)
        return ProfileMapper.to_output(profile)

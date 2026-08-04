"""UpdateProfileLinks use case — portfolio, LinkedIn, and GitHub URLs.

Same shape as `UpdateProfileAddress`: a full replacement of the section, an
all-empty submission clears it, and the source is `None` for an empty set so the
domain's "a source is required once there is data" rule is met rather than
side-stepped.

`ProfileLinks` validates the URLs themselves — this use case does not, because
"is that a URL" is a rule about the value and belongs with the value.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileLinksInput, ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource


class UpdateProfileLinks:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, request: ProfileLinksInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        links = ProfileLinks(
            portfolio_url=_clean(request.portfolio_url),
            linkedin_url=_clean(request.linkedin_url),
            github_url=_clean(request.github_url),
        )
        source = ProvenanceSource.USER_ENTERED if links != ProfileLinks() else None
        profile.set_links(links, source)
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

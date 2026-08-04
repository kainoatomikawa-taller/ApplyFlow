"""UpdateProfileAddress use case — the candidate's postal address.

A full replacement of the section: an omitted field is cleared, and an
all-empty submission clears the address entirely. That is how the candidate
deletes it, and it is why the domain's `set_address` treats a source as
required only once the address carries data — there is no fact left to
attribute to an empty one.

Stamped `USER_ENTERED`, like every section of the editor. The address is one of
the five slots an application form fills straight from the profile, so getting
its provenance right is what lets the review screen say where the value came
from.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import AddressInput, ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.address import Address
from src.domain.value_objects.provenance_source import ProvenanceSource


class UpdateProfileAddress:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def execute(self, request: AddressInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        address = Address(
            street_address=_clean(request.street_address),
            city=_clean(request.city),
            state_or_region=_clean(request.state_or_region),
            postal_code=_clean(request.postal_code),
            country=_clean(request.country),
        )
        # `None` for an empty address, so the domain's "a source is only required
        # once there is data" rule is satisfied rather than worked around.
        source = ProvenanceSource.USER_ENTERED if address != Address() else None
        profile.set_address(address, source)
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

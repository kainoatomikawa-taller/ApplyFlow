"""SaveContactDetails use case — the contact section, and the only path that can
create a profile from nothing.

Why this one section creates the profile
---------------------------------------
`UserProfile` requires a `full_name` and an `email`; every other field on it is
optional. So the contact section is the only input that carries enough to bring a
profile into existence, and that makes it the front door: a candidate with no
résumé types their name and email here, and the rest of the editor unlocks.

Before this existed, the *only* way a profile came into being was parsing an
uploaded résumé. Anyone without a résumé — or with one the parser could not read
a name and email out of — had no way to have a profile at all, and therefore no
way to reach the work-authorization and EEO records that the whole sensitive-field
apparatus reads from.

Create-or-update rather than separate endpoints, because the client cannot know
which it is doing without a round trip it would then have to race against, and
because the candidate's intent is the same either way: "this is who I am".

Provenance
----------
Always `USER_ENTERED`. That is the point of the section, and it is load-bearing
rather than cosmetic: `WorkAuthorization.ATTESTING_SOURCES` treats
`USER_ENTERED` as candidate-attested, and a profile whose contact details were
parsed from a résumé keeps saying `PARSED_RESUME` until the candidate saves them
here. Re-stamping on save is how a parsed profile becomes an attested one.

A full replacement of the group, not a patch: a field the client omits is
cleared. The seven contact fields share one `contact_source`, so they move
together or the tag would describe a mix of provenances (see
`UserProfile.set_contact_details`).
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ContactDetailsInput, ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.user_profile import UserProfile
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.provenance_source import ProvenanceSource


class SaveContactDetails:
    def __init__(
        self, repository: ProfileRepository, id_generator: IdGeneratorPort
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    async def execute(self, request: ContactDetailsInput) -> ProfileOutput:
        email = EmailAddress(request.email)
        profile = await self._repository.get_by_user_id(request.user_id)

        if profile is None:
            profile = UserProfile(
                id=self._id_generator.new_id(),
                user_id=request.user_id,
                full_name=request.full_name,
                email=email,
                contact_source=ProvenanceSource.USER_ENTERED,
                phone=_clean(request.phone),
                headline=_clean(request.headline),
                location=_clean(request.location),
                middle_name=_clean(request.middle_name),
                preferred_name=_clean(request.preferred_name),
            )
            await self._repository.add(profile)
            return ProfileMapper.to_output(profile)

        profile.set_contact_details(
            full_name=request.full_name,
            email=email,
            source=ProvenanceSource.USER_ENTERED,
            phone=_clean(request.phone),
            headline=_clean(request.headline),
            location=_clean(request.location),
            middle_name=_clean(request.middle_name),
            preferred_name=_clean(request.preferred_name),
        )
        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _clean(value: str | None) -> str | None:
    """Whitespace-only input means "not provided", not a value of spaces.

    Matters more here than it looks: a `middle_name` of `"  "` would read as "I
    have a middle name" and be written into a form, while `None` reads as "I have
    none" and correctly leaves the field alone. The difference between those two
    is one stray keystroke in a text box, so it is normalized at the boundary
    rather than trusted.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

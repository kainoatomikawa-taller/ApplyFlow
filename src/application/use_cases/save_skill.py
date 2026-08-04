"""SaveSkill use case — add or correct one skill on the profile.

Same shape as the other two collection savers. The one difference is the
uniqueness rule: skills are unique per profile by case-insensitive name, enforced
by the domain on both add and update, so renaming a skill onto another's name is
refused while recasing its own is not.

`proficiency` is an enum and unrecognized input raises rather than being dropped —
a silently ignored proficiency would read as "not stated", which is a different
claim from the one the candidate made.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileOutput, SkillInput
from src.application.exceptions import UnknownProfileEnumValueError
from src.application.mappers.profile_mapper import ProfileMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.skill import Skill
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.proficiency_level import ProficiencyLevel
from src.domain.value_objects.provenance_source import ProvenanceSource


class SaveSkill:
    def __init__(
        self, repository: ProfileRepository, id_generator: IdGeneratorPort
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    async def execute(self, request: SkillInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        is_new = request.entry_id is None
        skill = Skill(
            id=request.entry_id or self._id_generator.new_id(),
            name=request.name,
            proficiency=_parse_proficiency(request.proficiency),
            years_of_experience=request.years_of_experience,
            source=ProvenanceSource.USER_ENTERED,
        )
        if is_new:
            profile.add_skill(skill)
        else:
            profile.update_skill(skill)

        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _parse_proficiency(value: str | None) -> ProficiencyLevel | None:
    """Empty means "not stated"; anything else has to be a real level."""
    if value is None or not value.strip():
        return None
    try:
        return ProficiencyLevel(value.strip())
    except ValueError:
        raise UnknownProfileEnumValueError(
            "proficiency",
            value,
            tuple(member.value for member in ProficiencyLevel),
        ) from None

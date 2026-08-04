"""SaveEducationEntry use case — add or correct one qualification.

Same shape and same reasoning as `SaveWorkHistoryEntry`: create-or-update keyed
on `entry_id`, server-generated ids, stamped `USER_ENTERED`, and per-entry rather
than whole-list so a résumé-parsed entry the candidate never touched keeps its
own provenance.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import EducationInput, ProfileOutput
from src.application.mappers.profile_mapper import ProfileMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.education_entry import EducationEntry
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.provenance_source import ProvenanceSource


class SaveEducationEntry:
    def __init__(
        self, repository: ProfileRepository, id_generator: IdGeneratorPort
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    async def execute(self, request: EducationInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        is_new = request.entry_id is None
        entry = EducationEntry(
            id=request.entry_id or self._id_generator.new_id(),
            institution_name=request.institution_name,
            degree=request.degree,
            field_of_study=_clean(request.field_of_study),
            start_date=request.start_date,
            end_date=request.end_date,
            description=_clean(request.description),
            source=ProvenanceSource.USER_ENTERED,
        )
        if is_new:
            profile.add_education(entry)
        else:
            profile.update_education(entry)

        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

"""SaveWorkHistoryEntry use case — add or correct one job on the profile.

Create-or-update in one use case, keyed on whether the input carries an
`entry_id`. From the candidate's point of view "save this job" is one action, and
splitting it would mean two nearly identical use cases whose only difference is
which domain method they call.

Ids are server-generated. A client-supplied id on create could claim one that
belongs to another entry, and there is no reason the browser should be choosing
them.

Per-entry rather than "replace the whole list" for a specific reason: provenance.
Rewriting the list would re-stamp every entry `USER_ENTERED`, including ones the
résumé parser produced and the candidate never touched — quietly relabelling
parsed facts as attested ones. Editing one entry touches one entry's source.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import ProfileOutput, WorkHistoryInput
from src.application.mappers.profile_mapper import ProfileMapper
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.provenance_source import ProvenanceSource


class SaveWorkHistoryEntry:
    def __init__(
        self, repository: ProfileRepository, id_generator: IdGeneratorPort
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    async def execute(self, request: WorkHistoryInput) -> ProfileOutput:
        profile = await self._repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        is_new = request.entry_id is None
        entry = WorkHistoryEntry(
            id=request.entry_id or self._id_generator.new_id(),
            company_name=request.company_name,
            job_title=request.job_title,
            start_date=request.start_date,
            end_date=request.end_date,
            location=_clean(request.location),
            description=_clean(request.description),
            source=ProvenanceSource.USER_ENTERED,
        )
        if is_new:
            profile.add_work_history(entry)
        else:
            # Raises `ProfileEntryNotFoundError` rather than appending when the
            # id names nothing — a stale edit must not become a duplicate.
            profile.update_work_history(entry)

        await self._repository.update(profile)
        return ProfileMapper.to_output(profile)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

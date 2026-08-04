"""GetEeoSelfIdentification use case — read back the voluntary EEO record.

For the candidate's own eyes and for the data export. Never for filling a form:
see `SaveEeoSelfIdentification` for the full statement of what this record is and
is not for, and the static guard that enforces it.

Returns the all-unanswered state rather than raising when nothing is stored — the
editor has to render "you have not answered these", and that is not an error.

Reads encrypted columns, so the caller must already be inside an authorized
decryption scope.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import EeoSelfIdentificationOutput
from src.application.mappers.eeo_mapper import EeoMapper
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.consent_purpose import ConsentPurpose


class GetEeoSelfIdentification:
    def __init__(
        self,
        *,
        profile_repository: ProfileRepository,
        consent_repository: ConsentRepository,
    ) -> None:
        self._profile_repository = profile_repository
        self._consent_repository = consent_repository

    async def execute(self, user_id: str) -> EeoSelfIdentificationOutput:
        profile = await self._profile_repository.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)

        consent = await self._consent_repository.get(
            user_id=user_id, purpose=ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE
        )
        return EeoMapper.to_output(
            profile.eeo_self_identification, consent_granted=consent.is_granted
        )

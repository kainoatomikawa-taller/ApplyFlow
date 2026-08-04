"""GetWorkAuthorization use case — read back the stored legal declarations.

Its own use case rather than a field on `ProfileOutput`, for the same reason the
EEO record is separate: this is the most consequential data on the profile, and
keeping it out of the payload every profile view loads means a client has to ask
for it deliberately.

Returns a record even when nothing is stored — all-None, `is_candidate_attested`
false — because "you have not told us" is a state the editor has to render, and
distinguishing it from "the request failed" should not require the caller to
handle an exception.

`consent_granted` comes from the ledger so the editor can pre-tick the
acknowledgement for someone who has already agreed, rather than making them
re-affirm every time they correct a visa type.

Reads encrypted columns; the caller must already be inside an authorized
decryption scope.
"""

from __future__ import annotations

from src.application.dtos.profile_dtos import WorkAuthorizationOutput
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.consent_purpose import ConsentPurpose


class GetWorkAuthorization:
    def __init__(
        self,
        *,
        profile_repository: ProfileRepository,
        consent_repository: ConsentRepository,
    ) -> None:
        self._profile_repository = profile_repository
        self._consent_repository = consent_repository

    async def execute(self, user_id: str) -> WorkAuthorizationOutput:
        profile = await self._profile_repository.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)

        consent = await self._consent_repository.get(
            user_id=user_id, purpose=ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE
        )
        record = profile.work_authorization
        if record is None:
            return WorkAuthorizationOutput(
                status=None,
                citizenship_country=None,
                visa_type=None,
                requires_sponsorship=None,
                details=None,
                source=None,
                is_candidate_attested=False,
                consent_granted=consent.is_granted,
            )
        return WorkAuthorizationOutput(
            status=record.status.value,
            citizenship_country=record.citizenship_country,
            visa_type=record.visa_type,
            requires_sponsorship=record.requires_sponsorship,
            details=record.details,
            source=record.source.value,
            is_candidate_attested=record.is_candidate_attested,
            consent_granted=consent.is_granted,
        )

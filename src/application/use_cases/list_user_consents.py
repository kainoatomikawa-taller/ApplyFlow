"""ListUserConsents use case — every purpose and where it stands.

Complete rather than only-what-was-answered. The repository returns one ledger
per declared purpose including the ones this user has never seen, so a consent
screen renders the full set and a purpose added by a release shows up as
undecided instead of missing. That is why `ConsentStateOutput` carries `decided`
alongside `granted`: a purpose permitted because it is contract-based looks
identical to a granted one if you read `granted` alone, and a UI that conflated
them would show the user a "yes" they never gave.
"""

from __future__ import annotations

from src.application.dtos.data_rights_dtos import ConsentStateOutput
from src.application.mappers.consent_mapper import ConsentMapper
from src.domain.repositories.consent_repository import ConsentRepository


class ListUserConsents:
    def __init__(self, repository: ConsentRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: str) -> list[ConsentStateOutput]:
        records = await self._repository.list_for_user(user_id)
        return [ConsentMapper.to_state(record) for record in records]

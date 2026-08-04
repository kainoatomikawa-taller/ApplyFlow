"""RecordConsent use case — the user grants or withdraws consent for one
purpose.

Thin on purpose. Every rule that governs a consent decision lives in the domain
— the withdrawal refusal on `ConsentDecision`, the ordering and no-op rules on
`ConsentRecord` — so what is left here is the orchestration: parse the purpose
that arrived from outside, load the ledger, append, persist if anything changed.

The one decision this use case does make is to report `changed` rather than
swallowing a no-op. A client re-sending the state of a toggle it already
rendered is the common case, and appending for it would fill the Art. 7(1)
demonstration record with entries that demonstrate nothing. Reporting it lets
the caller say "already set" without diffing before and after.

Parsing the purpose string happens here, once, rather than in each adapter. An
unrecognized value is an `UnknownConsentPurposeError` the interface layer maps to
a 400 — the domain enum never sees a value it does not have a member for.
"""

from __future__ import annotations

from src.application.dtos.data_rights_dtos import (
    RecordConsentInput,
    RecordConsentOutput,
)
from src.application.exceptions import UnknownConsentPurposeError
from src.application.mappers.consent_mapper import ConsentMapper
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose


class RecordConsent:
    def __init__(self, repository: ConsentRepository) -> None:
        self._repository = repository

    async def execute(self, request: RecordConsentInput) -> RecordConsentOutput:
        purpose = parse_consent_purpose(request.purpose)
        record = await self._repository.get(user_id=request.user_id, purpose=purpose)
        changed = record.record(
            ConsentDecision(
                purpose=purpose,
                granted=request.granted,
                decided_at=request.decided_at,
                policy_version=request.policy_version,
            )
        )
        if changed:
            await self._repository.save(record)
        return RecordConsentOutput(
            state=ConsentMapper.to_state(record), changed=changed
        )


def parse_consent_purpose(value: str) -> ConsentPurpose:
    """Resolve a wire value to a `ConsentPurpose`.

    Shared with the read path (`ListUserConsents` has no need of it, but any
    future per-purpose endpoint does) so that "which purposes exist" has exactly
    one answer across the adapters.

    Raises:
        UnknownConsentPurposeError: naming the available purposes, so a caller
            with a stale client is told what to send rather than only that it
            was wrong.
    """
    try:
        return ConsentPurpose(value)
    except ValueError:
        raise UnknownConsentPurposeError(
            value, tuple(purpose.value for purpose in ConsentPurpose)
        ) from None

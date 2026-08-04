"""SaveWorkAuthorization use case — the record the whole sensitive-field
apparatus reads from, and the one nothing in production could write.

Why this use case matters more than its size suggests
----------------------------------------------------
Epics 01, 05 and 07 built an elaborate machine around work authorization: a
thirteen-case truth table in `decide_sensitive_field`, exact-or-refuse answers, a
dedicated encrypted table, a greedy-label guard, 118 acceptance tests. All of it
ran on a record that **no code path outside the test suite could create**. The
résumé parser does not produce one (deliberately — `ATTESTING_SOURCES` excludes
`PARSED_RESUME`, because a model's reading of a visa mention is not a declaration
the candidate made), and there was no endpoint. So in a real deployment the table
was always empty, every legal question was handed back to the candidate, and the
machine was correct and inert.

This is the write path. The record it stores is `USER_ENTERED`, which is what
`WorkAuthorization.is_candidate_attested` requires, which is what
`decide_sensitive_field` requires before a value may be asserted to an employer.

Consent, recorded in the same request
-------------------------------------
This stores GDPR Art. 9 special-category data, whose lawful basis is
`EXPLICIT_CONSENT` — opt-in, and not something to infer from a request arriving.
So the input carries an explicit acknowledgement (the box the candidate ticks next
to the notice text), and saving records a consent grant against
`SENSITIVE_ATTRIBUTE_STORAGE` in the same operation. One form, one submit, and a
consent ledger that can still demonstrate what was agreed and when.

**Consent is recorded before the profile is written**, and the order is not
arbitrary. These are two commits, so one can fail after the other succeeds, and
the two failure modes are not symmetric: a grant with no stored data is harmless
(permission is not a claim that data exists), while stored special-category data
with no record of permission is the case that matters. So the record of
permission goes first.

`RecordConsent` is deliberately *not* called — a use case may not depend on
another use case. The ledger is written through `ConsentRepository` directly,
exactly as `EraseUserData` does for the withdrawals it records.

Clearing needs no acknowledgement: consent is required to store data, not to
delete it. Nor does clearing withdraw consent — deleting data and revoking
permission are different acts, and conflating them would force a candidate who
fixed a typo to re-consent.
"""

from __future__ import annotations

from datetime import datetime

from src.application.dtos.profile_dtos import (
    WorkAuthorizationInput,
    WorkAuthorizationOutput,
)
from src.application.exceptions import (
    SensitiveStorageNotAcknowledgedError,
    UnknownProfileEnumValueError,
)
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus

#: The purpose both sensitive profile sections are stored under. One purpose
#: covering work authorization and EEO together, matching what its description
#: already tells the candidate — see `ConsentMapper.describe`.
_PURPOSE = ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE


class SaveWorkAuthorization:
    def __init__(
        self,
        *,
        profile_repository: ProfileRepository,
        consent_repository: ConsentRepository,
    ) -> None:
        self._profile_repository = profile_repository
        self._consent_repository = consent_repository

    async def execute(
        self,
        request: WorkAuthorizationInput,
        *,
        decided_at: datetime,
        policy_version: str,
    ) -> WorkAuthorizationOutput:
        profile = await self._profile_repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        is_clearing = request.status is None
        if not is_clearing and not request.consent_acknowledged:
            raise SensitiveStorageNotAcknowledgedError("work authorization")

        if not is_clearing:
            await record_sensitive_storage_consent(
                self._consent_repository,
                user_id=request.user_id,
                decided_at=decided_at,
                policy_version=policy_version,
            )

        profile.set_work_authorization(self._to_value_object(request))
        await self._profile_repository.update(profile)

        return await self._to_output(profile, request.user_id)

    @staticmethod
    def _to_value_object(
        request: WorkAuthorizationInput,
    ) -> WorkAuthorization | None:
        if request.status is None:
            return None
        try:
            status = WorkAuthorizationStatus(request.status.strip())
        except ValueError:
            raise UnknownProfileEnumValueError(
                "work authorization status",
                request.status,
                tuple(member.value for member in WorkAuthorizationStatus),
            ) from None
        return WorkAuthorization(
            status=status,
            # The whole point of this use case: what the candidate typed is
            # theirs, which is what makes it autofillable.
            source=ProvenanceSource.USER_ENTERED,
            citizenship_country=_clean(request.citizenship_country),
            visa_type=_clean(request.visa_type),
            requires_sponsorship=request.requires_sponsorship,
            details=_clean(request.details),
        )

    async def _to_output(
        self, profile: UserProfile, user_id: str
    ) -> WorkAuthorizationOutput:
        record = profile.work_authorization
        consent = await self._consent_repository.get(user_id=user_id, purpose=_PURPOSE)
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


async def record_sensitive_storage_consent(
    repository: ConsentRepository,
    *,
    user_id: str,
    decided_at: datetime,
    policy_version: str,
) -> bool:
    """Append a grant for `SENSITIVE_ATTRIBUTE_STORAGE`; return whether the
    ledger changed.

    Shared by both sensitive sections, since both store data under the same
    purpose and both record the grant the same way. A module-level function
    rather than a base class: it is one append, and the two use cases have
    nothing else in common.

    Re-saving the same section appends nothing — `ConsentRecord.record` declines
    a decision that restates the current one, so the demonstration record stays a
    log of decisions rather than of clicks.
    """
    record = await repository.get(user_id=user_id, purpose=_PURPOSE)
    changed = record.record(
        ConsentDecision(
            purpose=_PURPOSE,
            granted=True,
            decided_at=decided_at,
            policy_version=policy_version,
        )
    )
    if changed:
        await repository.save(record)
    return changed


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

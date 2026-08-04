"""SaveEeoSelfIdentification use case — the candidate's own voluntary EEO record.

What this record is *for*, stated plainly because the answer is narrow
--------------------------------------------------------------------
Two uses, and no others:

1. The candidate seeing, correcting, and withdrawing what is stored about them.
2. The GDPR data export.

It is **not** an autofill source. `decide_sensitive_field` refuses EEO
unconditionally, and it must not become a suggestion source on the review screen
either: a disclosure made to one employer is a decision for that application, and
carrying it forward would convert a per-application choice into a standing one.
`AnswerApplicationField` already declines to write these answers into
`AnswerMemory` for the same reason.

That refusal is enforced structurally as well as behaviourally. A static guard
(`test_the_eeo_record_is_unreachable_from_every_form_filling_module`) allows only
a named set of modules to read the record, and this file and its sibling reader
are on that list precisely because a profile editor is not on the way to a form.
Anything that *is* on the way to a form must stay off it.

Consent
-------
Same treatment as work authorization, and the same purpose covers both: an
explicit acknowledgement travels with the data, the grant is recorded before the
write, and clearing needs no acknowledgement because consent is required to store
rather than to delete.

Every category is independently optional, and None means "I did not answer this
one" — which is a different state from `DECLINE_TO_SELF_IDENTIFY`, itself one of
the answers. Storing all-None clears the record entirely.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from src.application.dtos.profile_dtos import (
    EeoSelfIdentificationInput,
    EeoSelfIdentificationOutput,
)
from src.application.exceptions import (
    SensitiveStorageNotAcknowledgedError,
    UnknownProfileEnumValueError,
)
from src.application.mappers.eeo_mapper import EeoMapper
from src.application.use_cases.save_work_authorization import (
    record_sensitive_storage_consent,
)
from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.consent_purpose import ConsentPurpose
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.provenance_source import ProvenanceSource

_CategoryT = TypeVar(
    "_CategoryT", GenderIdentity, RaceEthnicity, VeteranStatus, DisabilityStatus
)


class SaveEeoSelfIdentification:
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
        request: EeoSelfIdentificationInput,
        *,
        decided_at: datetime,
        policy_version: str,
    ) -> EeoSelfIdentificationOutput:
        profile = await self._profile_repository.get_by_user_id(request.user_id)
        if profile is None:
            raise ProfileNotFoundError(request.user_id)

        record = self._to_value_object(request)
        if record is not None and not request.consent_acknowledged:
            raise SensitiveStorageNotAcknowledgedError("EEO self-identification")

        if record is not None:
            await record_sensitive_storage_consent(
                self._consent_repository,
                user_id=request.user_id,
                decided_at=decided_at,
                policy_version=policy_version,
            )

        profile.set_eeo_self_identification(record)
        await self._profile_repository.update(profile)

        consent = await self._consent_repository.get(
            user_id=request.user_id,
            purpose=ConsentPurpose.SENSITIVE_ATTRIBUTE_STORAGE,
        )
        return EeoMapper.to_output(record, consent_granted=consent.is_granted)

    @staticmethod
    def _to_value_object(
        request: EeoSelfIdentificationInput,
    ) -> EeoSelfIdentification | None:
        gender = _parse(GenderIdentity, request.gender_identity, "gender identity")
        race = _parse(RaceEthnicity, request.race_ethnicity, "race/ethnicity")
        veteran = _parse(VeteranStatus, request.veteran_status, "veteran status")
        disability = _parse(
            DisabilityStatus, request.disability_status, "disability status"
        )
        if gender is None and race is None and veteran is None and disability is None:
            # Nothing answered — clear the record rather than storing a row of
            # four NULLs, so "not provided" stays the absence of a row.
            return None
        return EeoSelfIdentification(
            source=ProvenanceSource.USER_ENTERED,
            gender_identity=gender,
            race_ethnicity=race,
            veteran_status=veteran,
            disability_status=disability,
        )


def _parse(
    enum_type: type[_CategoryT], value: str | None, label: str
) -> _CategoryT | None:
    """Empty means "this category was left unanswered", which is a real state and
    not the same as declining — `DECLINE_TO_SELF_IDENTIFY` is an answer."""
    if value is None or not value.strip():
        return None
    try:
        return enum_type(value.strip())
    except ValueError:
        raise UnknownProfileEnumValueError(
            label, value, tuple(member.value for member in enum_type)
        ) from None

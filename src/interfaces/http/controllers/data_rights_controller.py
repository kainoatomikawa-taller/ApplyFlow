"""Data-subject rights HTTP controller: export, erasure, and consent.

Thin: validate input -> call use case -> serialize. No business logic, no DB or
file-system access, no domain entity manipulation.

Privacy notes specific to these endpoints:

* **The subject is always the token's.** No endpoint here takes a user id, an
  email, or any other identifier — the person whose data is exported or erased is
  the one the verified bearer token names. There is no admin path, and adding one
  would need its own authorization story rather than a query parameter.
* **Nothing personal in a URL.** The one path parameter is a consent purpose,
  which names a kind of processing rather than anything about a person (see
  ADR 0003 and `tests/interfaces/http/test_no_pii_in_urls.py`).
* **The export body is the most sensitive response this API produces.** It is
  therefore a POST-free GET with no caching semantics worth relying on and — the
  part this module controls — nothing about its contents in any log line. What is
  logged is category counts, never records.

`GET /api/privacy/export` rather than a job-and-download flow because at
single-user scale the data fits in a response. The multi-user version of this is
an asynchronous export written to signed-URL storage, which is called out in
docs/decisions/0004-gdpr-ccpa-groundwork.md rather than pretended away.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.data_rights_dtos import (
    ConsentStateOutput,
    DataSubjectRef,
    DeferredCategoryOutput,
    ErasureRequestInput,
    RecordConsentInput,
)
from src.application.exceptions import (
    ErasureNotAcknowledgedError,
    PersonalDataCoverageError,
    UnknownConsentPurposeError,
)
from src.application.use_cases.erase_user_data import EraseUserData
from src.application.use_cases.export_user_data import ExportUserData
from src.application.use_cases.list_user_consents import ListUserConsents
from src.application.use_cases.record_consent import RecordConsent
from src.domain.exceptions import (
    ConsentLedgerOutOfOrderError,
    ConsentNotWithdrawableError,
)
from src.interfaces.http.dependencies import (
    get_current_user,
    get_erase_user_data_use_case,
    get_export_user_data_use_case,
    get_list_user_consents_use_case,
    get_privacy_policy_version,
    get_record_consent_use_case,
)
from src.interfaces.http.schemas import (
    ConsentDecisionResponse,
    ConsentStateResponse,
    DeferredCategoryResponse,
    ErasedCategoryResponse,
    ErasureReceiptResponse,
    ErasureRequest,
    ExportedCategoryResponse,
    PersonalDataExportResponse,
    RecordConsentRequest,
    RecordConsentResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/privacy",
    tags=["privacy"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/export", response_model=PersonalDataExportResponse)
async def export_my_data(
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ExportUserData = Depends(get_export_user_data_use_case),
) -> PersonalDataExportResponse:
    """A complete, portable copy of the authenticated user's data.

    GDPR Art. 15/20 and CCPA §1798.110/130. The email on the token is passed
    along because one store predates the account model and files rows under an
    address — see the `legacy_applications` category.
    """
    try:
        output = await use_case.execute(
            DataSubjectRef(user_id=user.subject, email=user.email),
            generated_at=datetime.now(UTC),
        )
    except PersonalDataCoverageError as exc:
        # A 500 rather than a partial 200: the request cannot be answered
        # correctly, and returning the sections that did resolve would deliver a
        # copy whose gaps are indistinguishable from having no data there.
        logger.error("Personal data export refused as incomplete: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    logger.info(
        "Personal data export produced: %d categories, %d records",
        len(output.categories),
        sum(category.record_count for category in output.categories),
    )
    return PersonalDataExportResponse(
        format_version=output.format_version,
        subject_user_id=output.subject_user_id,
        generated_at=output.generated_at,
        consent_policy_version=output.consent_policy_version,
        categories=[
            ExportedCategoryResponse(
                key=category.key,
                description=category.description,
                store=category.store,
                lawful_basis=category.lawful_basis,
                record_count=category.record_count,
                records=[dict(record) for record in category.records],
            )
            for category in output.categories
        ],
        deferred_categories=[
            _deferred_response(category) for category in output.deferred_categories
        ],
        consents=[_consent_response(state) for state in output.consents],
        consent_history=[
            ConsentDecisionResponse(
                purpose=decision.purpose,
                granted=decision.granted,
                decided_at=decision.decided_at,
                policy_version=decision.policy_version,
            )
            for decision in output.consent_history
        ],
        limitations=list(output.limitations),
    )


@router.post("/erasure", response_model=ErasureReceiptResponse)
async def erase_my_data(
    request: ErasureRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: EraseUserData = Depends(get_erase_user_data_use_case),
    policy_version: str = Depends(get_privacy_policy_version),
) -> ErasureReceiptResponse:
    """Erase everything erasable about the authenticated user.

    GDPR Art. 17 and CCPA §1798.105. Irreversible: `acknowledged` must be true,
    and a request without it is a 400 rather than a no-op, so a client that
    forgot is told instead of believing the erasure ran.

    A 200 with a receipt rather than a 204, because what was erased and what was
    retained is the substance of the response — see `ErasureReceiptResponse`.
    """
    try:
        output = await use_case.execute(
            ErasureRequestInput(
                subject=DataSubjectRef(user_id=user.subject, email=user.email),
                requested_at=datetime.now(UTC),
                acknowledged=request.acknowledged,
                policy_version=policy_version,
                reason=request.reason,
            )
        )
    except ErasureNotAcknowledgedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except PersonalDataCoverageError as exc:
        logger.error("Personal data erasure refused as incomplete: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    logger.info(
        "Personal data erasure completed: %d records across %d categories, "
        "%d consent purposes withdrawn",
        output.total_records_erased,
        len(output.erased),
        len(output.consents_withdrawn),
    )
    return ErasureReceiptResponse(
        subject_user_id=output.subject_user_id,
        executed_at=output.executed_at,
        total_records_erased=output.total_records_erased,
        erased=[
            ErasedCategoryResponse(
                key=category.key,
                description=category.description,
                store=category.store,
                records_erased=category.records_erased,
            )
            for category in output.erased
        ],
        retained=[_deferred_response(category) for category in output.retained],
        consents_withdrawn=list(output.consents_withdrawn),
        limitations=list(output.limitations),
    )


@router.get("/consents", response_model=list[ConsentStateResponse])
async def list_my_consents(
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListUserConsents = Depends(get_list_user_consents_use_case),
) -> list[ConsentStateResponse]:
    """Every consent purpose and where it stands, including unanswered ones."""
    states = await use_case.execute(user.subject)
    return [_consent_response(state) for state in states]


@router.put("/consents/{purpose}", response_model=RecordConsentResponse)
async def record_my_consent(
    purpose: str,
    request: RecordConsentRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: RecordConsent = Depends(get_record_consent_use_case),
    policy_version: str = Depends(get_privacy_policy_version),
) -> RecordConsentResponse:
    """Grant or withdraw consent for one purpose.

    PUT rather than POST: the addressed resource is the user's decision about
    this purpose, and re-sending the same decision is idempotent (it appends
    nothing — see `ConsentRecord.record`). The ledger underneath is still
    append-only; what is idempotent is the request, not the storage.

    The policy version comes from the deployment, not the body. A client that
    could assert which notice it had shown could record consent against a notice
    the user never saw.
    """
    try:
        output = await use_case.execute(
            RecordConsentInput(
                user_id=user.subject,
                purpose=purpose,
                granted=request.granted,
                decided_at=datetime.now(UTC),
                policy_version=policy_version,
            )
        )
    except UnknownConsentPurposeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ConsentNotWithdrawableError as exc:
        # 409 rather than 400: the request is well-formed and the purpose is
        # real; what cannot be done is stop this processing while the account
        # exists. The message points at erasure, which is the request that can.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ConsentLedgerOutOfOrderError as exc:
        # Only reachable if this process's clock has gone backwards relative to
        # a decision already stored. A 409 says "retry", which is right — the
        # next attempt will carry a later timestamp.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    logger.info(
        "Consent decision recorded: purpose=%s granted=%s changed=%s",
        output.state.purpose,
        output.state.granted,
        output.changed,
    )
    return RecordConsentResponse(
        state=_consent_response(output.state), changed=output.changed
    )


def _consent_response(state: ConsentStateOutput) -> ConsentStateResponse:
    return ConsentStateResponse(**state.__dict__)


def _deferred_response(
    category: DeferredCategoryOutput,
) -> DeferredCategoryResponse:
    return DeferredCategoryResponse(**category.__dict__)

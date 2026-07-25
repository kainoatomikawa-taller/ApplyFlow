"""Application-document HTTP controller — read access to the exact resumes
and cover letters that were produced for a job.

Thin: validate input -> call use case -> serialize. No business logic, no
DB access, no domain entity manipulation.

Read-only on purpose. There is no POST here: a snapshot is written by the
generation flow that produced the document (see `GenerateTailoredResume`),
so a route that accepted document text would let a caller store something
the provenance guard never saw and label it as sent. There is no PUT or
DELETE either, because a record of what went out is not editable.

The routes span two prefixes — job-scoped reads under `/api/job-postings`
and id-scoped reads under `/api/application-documents` — so this router
declares full paths instead of a single prefix.

A 404 covers both "no such document" and "not this candidate's document",
so the API never confirms another candidate's ids exist.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.application_document_dtos import (
    GetApplicationDocumentInput,
    GetLatestApplicationDocumentInput,
    ListApplicationDocumentsInput,
)
from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.use_cases.get_application_document import GetApplicationDocument
from src.application.use_cases.get_latest_application_document import (
    GetLatestApplicationDocument,
)
from src.application.use_cases.list_application_documents import (
    ListApplicationDocuments,
)
from src.domain.exceptions import (
    ApplicationDocumentNotFoundError,
    DocumentSnapshotIntegrityError,
    InvalidValueError,
    NoStoredApplicationDocumentError,
)
from src.interfaces.http.dependencies import (
    get_application_document_use_case,
    get_current_user,
    get_latest_application_document_use_case,
    get_list_application_documents_use_case,
)
from src.interfaces.http.schemas import (
    ApplicationDocumentResponse,
    ApplicationDocumentSummaryResponse,
)

router = APIRouter(
    tags=["application-documents"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/api/application-documents",
    response_model=list[ApplicationDocumentSummaryResponse],
)
async def list_application_documents(
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListApplicationDocuments = Depends(
        get_list_application_documents_use_case
    ),
) -> list[ApplicationDocumentSummaryResponse]:
    """Every document stored for the current user, newest first."""
    outputs = await use_case.execute(
        ListApplicationDocumentsInput(user_id=user.subject, limit=limit)
    )
    return [ApplicationDocumentSummaryResponse(**asdict(o)) for o in outputs]


@router.get(
    "/api/job-postings/{job_posting_id}/documents",
    response_model=list[ApplicationDocumentSummaryResponse],
)
async def list_documents_for_job(
    job_posting_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListApplicationDocuments = Depends(
        get_list_application_documents_use_case
    ),
) -> list[ApplicationDocumentSummaryResponse]:
    """One job's full history — both document kinds, every version."""
    outputs = await use_case.execute(
        ListApplicationDocumentsInput(
            user_id=user.subject, job_posting_id=job_posting_id, limit=limit
        )
    )
    return [ApplicationDocumentSummaryResponse(**asdict(o)) for o in outputs]


@router.get(
    "/api/job-postings/{job_posting_id}/documents/{document_kind}/latest",
    response_model=ApplicationDocumentResponse,
)
async def get_latest_document_for_job(
    job_posting_id: str,
    document_kind: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetLatestApplicationDocument = Depends(
        get_latest_application_document_use_case
    ),
) -> ApplicationDocumentResponse:
    """The document this application went out with — the reuse path that
    replaces regenerating one."""
    try:
        output = await use_case.execute(
            GetLatestApplicationDocumentInput(
                user_id=user.subject,
                job_posting_id=job_posting_id,
                document_kind=document_kind,
            )
        )
    except InvalidValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except NoStoredApplicationDocumentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except DocumentSnapshotIntegrityError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return ApplicationDocumentResponse(**asdict(output))


@router.get(
    "/api/application-documents/{document_id}",
    response_model=ApplicationDocumentResponse,
)
async def get_application_document(
    document_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetApplicationDocument = Depends(get_application_document_use_case),
) -> ApplicationDocumentResponse:
    """One stored snapshot by id, with its exact text."""
    try:
        output = await use_case.execute(
            GetApplicationDocumentInput(
                user_id=user.subject, document_id=document_id
            )
        )
    except ApplicationDocumentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except DocumentSnapshotIntegrityError as exc:
        # A stored document that no longer matches its digest is a corrupted
        # record, not a bad request: refusing it beats presenting altered
        # content as what the candidate sent.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return ApplicationDocumentResponse(**asdict(output))

"""Document-revision HTTP controller — the candidate's edited resume or
cover letter, on its way back through the provenance guard.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/LLM access, no domain entity manipulation.

Why this is a separate router from `application_document_controller`: that
one is read-only over the snapshot archive, and this one writes. The write
is not an exception to the rule stated there — a caller still cannot store
text the guard never saw. It goes through `ReviseGeneratedDocument`, which
guards the submitted text against the candidate's attested facts before
anything is archived, and stores the result as the next version rather than
altering an existing snapshot.

Status codes mirror the generation routes, because the pipeline behind them
makes the same distinctions. A 201 can still carry `violations`: the guard
removed lines the candidate's edit asserted without backing, and the stored
version is what survived. A 422 means either the edit named a document kind
that does not exist, or nothing attested survived the guard — in the latter
case there is no version to store, and saying so beats recording a husk of
headings as the document that went out.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.generation_dtos import ReviseGeneratedDocumentInput
from src.application.exceptions import (
    DocumentVersionConflictError,
    UnattestedGenerationError,
)
from src.application.use_cases.revise_generated_document import ReviseGeneratedDocument
from src.domain.exceptions import (
    InvalidValueError,
    JobPostingNotFoundError,
    ProfileNotFoundError,
)
from src.interfaces.http.dependencies import (
    get_current_user,
    get_revise_generated_document_use_case,
)
from src.interfaces.http.schemas import GuardedDocumentResponse, ReviseDocumentRequest

router = APIRouter(
    prefix="/api/job-postings",
    tags=["document-revisions"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/{job_posting_id}/documents/{document_kind}/revisions",
    response_model=GuardedDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def revise_generated_document(
    job_posting_id: str,
    document_kind: str,
    body: ReviseDocumentRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ReviseGeneratedDocument = Depends(get_revise_generated_document_use_case),
) -> GuardedDocumentResponse:
    try:
        output = await use_case.execute(
            ReviseGeneratedDocumentInput(
                user_id=user.subject,
                job_posting_id=job_posting_id,
                document_kind=document_kind,
                content=body.content,
            )
        )
    except (JobPostingNotFoundError, ProfileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (InvalidValueError, UnattestedGenerationError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DocumentVersionConflictError as exc:
        # A concurrent write claimed the same snapshot version. Same as the
        # generation routes: retrying is the resolution, because the
        # existing snapshot records a document that was already produced.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return GuardedDocumentResponse(**asdict(output))

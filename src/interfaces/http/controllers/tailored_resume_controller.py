"""Tailored-resume HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/LLM access, no domain entity manipulation.

Status codes carry the distinctions the pipeline makes. A 200 can still
include `violations`: the guard removed what it couldn't back and the
returned resume is made only of attested claims, so that is a successful
request with a diagnostic attached, not a failure. A 422 means nothing
attested survived at all (`UnattestedGenerationError`) — there is no
document to return, and saying so beats handing back a page of headings.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.generation_dtos import GenerateTailoredResumeInput
from src.application.exceptions import (
    ExternalServiceError,
    UnattestedGenerationError,
)
from src.application.use_cases.generate_tailored_resume import GenerateTailoredResume
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.interfaces.http.dependencies import (
    get_current_user,
    get_generate_tailored_resume_use_case,
)
from src.interfaces.http.schemas import GuardedDocumentResponse

router = APIRouter(
    prefix="/api/job-postings",
    tags=["tailored-resume"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/{job_posting_id}/tailored-resume",
    response_model=GuardedDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_tailored_resume(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GenerateTailoredResume = Depends(get_generate_tailored_resume_use_case),
) -> GuardedDocumentResponse:
    try:
        output = await use_case.execute(
            GenerateTailoredResumeInput(
                user_id=user.subject, job_posting_id=job_posting_id
            )
        )
    except (JobPostingNotFoundError, ProfileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UnattestedGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return GuardedDocumentResponse(**asdict(output))

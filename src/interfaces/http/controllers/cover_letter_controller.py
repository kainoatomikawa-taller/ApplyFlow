"""Cover-letter HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/LLM access, no domain entity manipulation.

Status codes mirror the tailored-resume route, because the pipeline behind
both makes the same distinctions. A 201 can still carry `violations`: the
guard removed what it couldn't back and the returned letter is made only of
attested claims, so that is a success with a diagnostic attached. A 422
means nothing attested survived (`UnattestedGenerationError`) — a letter of
pure enthusiasm is not something to hand a candidate as finished work.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.generation_dtos import GenerateCoverLetterInput
from src.application.exceptions import (
    DocumentVersionConflictError,
    ExternalServiceError,
    UnattestedGenerationError,
)
from src.application.use_cases.generate_cover_letter import GenerateCoverLetter
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.interfaces.http.dependencies import (
    get_current_user,
    get_generate_cover_letter_use_case,
)
from src.interfaces.http.schemas import GuardedDocumentResponse

router = APIRouter(
    prefix="/api/job-postings",
    tags=["cover-letter"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/{job_posting_id}/cover-letter",
    response_model=GuardedDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_cover_letter(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GenerateCoverLetter = Depends(get_generate_cover_letter_use_case),
) -> GuardedDocumentResponse:
    try:
        output = await use_case.execute(
            GenerateCoverLetterInput(
                user_id=user.subject, job_posting_id=job_posting_id
            )
        )
    except (JobPostingNotFoundError, ProfileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UnattestedGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DocumentVersionConflictError as exc:
        # Same as the resume route: a concurrent generation claimed this
        # snapshot version, and the fix is to retry rather than overwrite a
        # letter that was already produced.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return GuardedDocumentResponse(**asdict(output))

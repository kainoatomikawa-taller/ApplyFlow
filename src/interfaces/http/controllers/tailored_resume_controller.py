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

import base64
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.generation_dtos import (
    GenerateTailoredResumeInput,
    TailoredResumeOutput,
)
from src.application.exceptions import (
    DocumentRenderError,
    DocumentVersionConflictError,
    ExternalServiceError,
    UnattestedGenerationError,
)
from src.application.use_cases.generate_tailored_resume import GenerateTailoredResume
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.interfaces.http.dependencies import (
    get_current_user,
    get_generate_tailored_resume_use_case,
)
from src.interfaces.http.schemas import (
    AtsSafetyViolationResponse,
    GuardedDocumentResponse,
    ResumeExportsResponse,
    ResumeSectionResponse,
    TailoredResumeResponse,
)

router = APIRouter(
    prefix="/api/job-postings",
    tags=["tailored-resume"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/{job_posting_id}/tailored-resume",
    response_model=TailoredResumeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_tailored_resume(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GenerateTailoredResume = Depends(get_generate_tailored_resume_use_case),
) -> TailoredResumeResponse:
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
    except DocumentVersionConflictError as exc:
        # A concurrent generation for this job claimed the same snapshot
        # version. Retrying is the resolution; overwriting is not, because
        # the existing snapshot records a document that was already produced.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except DocumentRenderError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return _to_response(output)


def _to_response(output: TailoredResumeOutput) -> TailoredResumeResponse:
    """Serialize the use case's output, base64-encoding the PDF.

    Mapped field by field rather than via `asdict`, because the PDF is raw
    bytes: transport encoding is this layer's job, and the DTO should not
    carry a base64 string just to make JSON serialization convenient.
    """
    exports = output.exports
    return TailoredResumeResponse(
        document=GuardedDocumentResponse(**asdict(output.document)),
        exports=ResumeExportsResponse(
            text=exports.text,
            pdf_base64=base64.b64encode(exports.pdf).decode("ascii"),
            pdf_byte_size=len(exports.pdf),
            contact_lines=list(exports.contact_lines),
            sections=[
                ResumeSectionResponse(heading=section.heading, lines=section.lines)
                for section in exports.sections
            ],
        ),
        ats_safety_violations=[
            AtsSafetyViolationResponse(**asdict(violation))
            for violation in output.ats_safety_violations
        ],
    )

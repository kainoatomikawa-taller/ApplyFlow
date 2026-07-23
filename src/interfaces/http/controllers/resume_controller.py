"""Resume HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/file-system access, no domain entity manipulation.

Security note: the resume id is always taken from the path or the
authenticated bearer token, never from a query string, so it never ends
up in server access logs or browser history. Only the id — never the
original filename or extracted text — appears in any exception message
raised from this module.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.resume_dtos import UploadResumeInput
from src.application.exceptions import TextExtractionError
from src.application.use_cases.get_resume import GetResume
from src.application.use_cases.list_resumes import ListResumes
from src.application.use_cases.upload_resume import UploadResume
from src.domain.exceptions import (
    FileTooLargeError,
    ResumeNotFoundError,
    UnsupportedFileFormatError,
)
from src.interfaces.http.dependencies import (
    get_current_user,
    get_list_resumes_use_case,
    get_resume_use_case,
    get_upload_resume_use_case,
)
from src.interfaces.http.schemas import ResumeResponse

router = APIRouter(
    prefix="/api/resumes",
    tags=["resumes"],
    dependencies=[Depends(get_current_user)],
)


@router.post("", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UploadResume = Depends(get_upload_resume_use_case),
) -> ResumeResponse:
    content = await file.read()
    try:
        output = await use_case.execute(
            UploadResumeInput(
                user_id=user.subject,
                original_filename=file.filename or "resume",
                content_type=file.content_type or "application/octet-stream",
                content=content,
            )
        )
    except UnsupportedFileFormatError as exc:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)
        ) from exc
    except TextExtractionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return ResumeResponse(**output.__dict__)


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetResume = Depends(get_resume_use_case),
) -> ResumeResponse:
    try:
        output = await use_case.execute(resume_id, user.subject)
    except ResumeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ResumeResponse(**output.__dict__)


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListResumes = Depends(get_list_resumes_use_case),
) -> list[ResumeResponse]:
    outputs = await use_case.execute(user.subject)
    return [ResumeResponse(**o.__dict__) for o in outputs]

"""Job application HTTP controller.

Thin: validate input (via Pydantic schemas) -> call use case -> serialize.
No business logic, no DB access, no domain entity manipulation.
HTTP status codes are decided here based on application/domain exceptions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.job_application_dtos import (
    AnalyzeApplicationInput,
    CreateJobApplicationInput,
)
from src.application.use_cases.analyze_job_application import (
    AnalyzeJobApplication,
)
from src.application.use_cases.create_job_application import (
    CreateJobApplication,
)
from src.application.use_cases.list_candidate_applications import (
    ListCandidateApplications,
)
from src.application.use_cases.submit_job_application import (
    SubmitJobApplication,
)
from src.domain.exceptions import (
    ApplicationNotFoundError,
    BusinessRuleViolationError,
    InvalidValueError,
)
from src.interfaces.http.dependencies import (
    get_analyze_use_case,
    get_create_use_case,
    get_list_use_case,
    get_submit_use_case,
)
from src.interfaces.http.schemas import (
    AnalyzeApplicationRequest,
    ApplicationResponse,
    CreateApplicationRequest,
)

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    body: CreateApplicationRequest,
    use_case: CreateJobApplication = Depends(get_create_use_case),
) -> ApplicationResponse:
    try:
        output = await use_case.execute(
            CreateJobApplicationInput(
                candidate_email=str(body.candidate_email),
                company_name=body.company_name,
                role_title=body.role_title,
                job_description=body.job_description,
            )
        )
    except InvalidValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return ApplicationResponse(**output.__dict__)


@router.post("/{application_id}/analyze", response_model=ApplicationResponse)
async def analyze_application(
    application_id: str,
    body: AnalyzeApplicationRequest,
    use_case: AnalyzeJobApplication = Depends(get_analyze_use_case),
) -> ApplicationResponse:
    try:
        output = await use_case.execute(
            AnalyzeApplicationInput(
                application_id=application_id, resume_text=body.resume_text
            )
        )
    except ApplicationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ApplicationResponse(**output.__dict__)


@router.post("/{application_id}/submit", response_model=ApplicationResponse)
async def submit_application(
    application_id: str,
    use_case: SubmitJobApplication = Depends(get_submit_use_case),
) -> ApplicationResponse:
    try:
        output = await use_case.execute(application_id)
    except ApplicationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ApplicationResponse(**output.__dict__)


@router.get("", response_model=list[ApplicationResponse])
async def list_applications(
    candidate_email: str,
    use_case: ListCandidateApplications = Depends(get_list_use_case),
) -> list[ApplicationResponse]:
    outputs = await use_case.execute(candidate_email)
    return [ApplicationResponse(**o.__dict__) for o in outputs]

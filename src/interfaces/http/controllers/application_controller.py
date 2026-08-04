"""Job application HTTP controller.

Thin: validate input (via Pydantic schemas) -> call use case -> serialize.
No business logic, no DB access, no domain entity manipulation.
HTTP status codes are decided here based on application/domain exceptions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
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
    get_current_user,
    get_list_use_case,
    get_submit_use_case,
)
from src.interfaces.http.schemas import (
    AnalyzeApplicationRequest,
    ApplicationResponse,
    CreateApplicationRequest,
)

router = APIRouter(
    prefix="/api/applications",
    tags=["applications"],
    dependencies=[Depends(get_current_user)],
)


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
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListCandidateApplications = Depends(get_list_use_case),
) -> list[ApplicationResponse]:
    """List the authenticated candidate's applications.

    The email comes from the verified bearer token, not from a
    `?candidate_email=` query parameter as it once did. Two reasons, and the
    second is the one that forced the change:

    * A query string is the least private part of a request. It lands in
      access logs, proxy and CDN logs, browser history, and `Referer` headers
      sent to third parties — none of which this application controls, and
      all of which sit outside the encryption-at-rest boundary that every
      other copy of this address lives behind.
    * It was never really an input. This is a single-user application (see
      `AuthenticatedUserDTO`), so the only email the caller could legitimately
      pass is the one already on their token — the parameter was a way to ask
      for someone else's applications, answered by whatever the repository
      happened to hold.

    A token with no `email` claim gets a 400 rather than an empty list, so a
    misconfigured auth provider is a loud failure instead of a page that
    silently shows nothing.
    """
    if not user.email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The authenticated token carries no email claim, so there is no "
            "candidate to list applications for.",
        )
    outputs = await use_case.execute(user.email)
    return [ApplicationResponse(**o.__dict__) for o in outputs]

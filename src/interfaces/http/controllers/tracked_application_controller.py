"""Application tracker HTTP controller — what the candidate has sent, where each
one stands, and moving one along.

Thin: validate input -> call use cases -> serialize. No business logic, no DB
access, no domain entity manipulation. Which statuses exist, which moves are
legal, and what counts as "still open" are all decided inward.

Why the status route is a PATCH and not a POST
---------------------------------------------
It changes one field of an existing record to a value the client names, and
sending the same request twice leaves the application in the same place — the
second attempt is refused by the transition rules rather than adding a second
identical step. That is a PATCH. (It is not idempotent in the strict sense: the
first call succeeds and the second 409s. What matters is that no repeat can
produce a *duplicate* history entry.)

Status codes
------------
- an unknown status name, or `draft`, is a **422**: the request is well-formed
  but names something a sent application cannot be. The message lists what is
  accepted.
- a status change the lifecycle does not allow — `rejected` back to
  `interviewing`, or a move to the status it already holds — is a **409**. The
  domain refuses, and the refusal text names the two statuses.
- an application that does not exist, *or* belongs to another candidate, is a
  **404** in both cases. Telling them apart would confirm that someone else's
  application exists under a guessed id.
- asking for open applications and specific statuses at once is a **422**: it is
  a contradiction, and returning the intersection would hide the caller's bug.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.tracked_application_dtos import (
    GetTrackedApplicationInput,
    ListApplicationsForJobInput,
    ListTrackedApplicationsInput,
    TrackedApplicationOutput,
    UpdateApplicationStatusInput,
)
from src.application.use_cases.get_tracked_application import GetTrackedApplication
from src.application.use_cases.list_applications_for_job import ListApplicationsForJob
from src.application.use_cases.list_tracked_applications import ListTrackedApplications
from src.application.use_cases.update_application_status import UpdateApplicationStatus
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    TrackedApplicationNotFoundError,
)
from src.interfaces.http.dependencies import (
    get_current_user,
    get_list_applications_for_job_use_case,
    get_list_tracked_applications_use_case,
    get_tracked_application_use_case,
    get_update_application_status_use_case,
)
from src.interfaces.http.schemas import (
    TrackedApplicationListResponse,
    TrackedApplicationResponse,
    UpdateApplicationStatusRequest,
)

router = APIRouter(
    prefix="/api/tracked-applications",
    tags=["application-tracking"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=TrackedApplicationListResponse)
async def list_tracked_applications(
    status_filter: list[str] | None = Query(
        default=None,
        alias="status",
        description=(
            "Only applications in these statuses. Repeat the parameter for "
            "several (?status=applied&status=interviewing). Omit for all."
        ),
    ),
    open_only: bool = Query(
        default=False,
        description=(
            "Only applications that are still live. Cannot be combined with "
            "'status'."
        ),
    ),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListTrackedApplications = Depends(get_list_tracked_applications_use_case),
) -> TrackedApplicationListResponse:
    """This candidate's sent applications, most recently applied first."""
    try:
        outputs = await use_case.execute(
            ListTrackedApplicationsInput(
                user_id=user.subject,
                statuses=tuple(status_filter) if status_filter is not None else None,
                open_only=open_only,
                limit=limit,
            )
        )
    except InvalidValueError as exc:
        # An unknown status name, or 'status' and 'open_only' together.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _list_response(outputs)


@router.get("/{application_id}", response_model=TrackedApplicationResponse)
async def get_tracked_application(
    application_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetTrackedApplication = Depends(get_tracked_application_use_case),
) -> TrackedApplicationResponse:
    """One sent application, with its full status history."""
    try:
        output = await use_case.execute(
            GetTrackedApplicationInput(
                user_id=user.subject, application_id=application_id
            )
        )
    except TrackedApplicationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _response(output)


@router.patch("/{application_id}/status", response_model=TrackedApplicationResponse)
async def update_application_status(
    application_id: str,
    body: UpdateApplicationStatusRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateApplicationStatus = Depends(get_update_application_status_use_case),
) -> TrackedApplicationResponse:
    """Move this application to a new status, recording the move.

    Returns the whole application rather than just the new status, because the
    change also moves `current_status_since`, may close the application
    (`is_open`), and always appends to `status_history` — a client that patched
    only its local `status` field would be showing three stale ones.
    """
    try:
        output = await use_case.execute(
            UpdateApplicationStatusInput(
                user_id=user.subject,
                application_id=application_id,
                status=body.status,
                note=body.note,
            )
        )
    except TrackedApplicationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        # A move the lifecycle does not allow — including a move to the status
        # the application is already in.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InvalidValueError as exc:
        # Not a status at all, 'draft', or a backdated change.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _response(output)


@router.get("/by-job/{job_posting_id}", response_model=TrackedApplicationListResponse)
async def list_applications_for_job(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListApplicationsForJob = Depends(get_list_applications_for_job_use_case),
) -> TrackedApplicationListResponse:
    """Every application this candidate sent to one posting — normally one, two
    if they applied again later.

    Under `/by-job/` rather than at `/{job_posting_id}` so a posting id can
    never be read as an application id by the route above.
    """
    outputs = await use_case.execute(
        ListApplicationsForJobInput(user_id=user.subject, job_posting_id=job_posting_id)
    )
    return _list_response(outputs)


def _response(output: TrackedApplicationOutput) -> TrackedApplicationResponse:
    return TrackedApplicationResponse(**asdict(output))


def _list_response(
    outputs: list[TrackedApplicationOutput],
) -> TrackedApplicationListResponse:
    return TrackedApplicationListResponse(
        applications=[_response(output) for output in outputs],
        # Counted from what the use case returned, so it agrees with the list
        # the client is holding. On a filtered or limited read it is the number
        # of open applications *in this response*, which is what a header
        # rendered alongside these rows should show.
        open_count=sum(1 for output in outputs if output.is_open),
    )

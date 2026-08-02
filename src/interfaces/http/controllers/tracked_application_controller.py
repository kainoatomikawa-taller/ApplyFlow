"""Tracked-application HTTP controller — the tracker: what the candidate has
sent, and where each one stands (Epic 06).

Thin: validate input -> call use case -> serialize. No business logic, no
DB access, no domain entity manipulation.

Two routes, and no more
-----------------------
A read of the feed, and a status change. There is deliberately no POST that
creates a tracked application: a record exists because an application was
*sent*, so it is written by the flow that sends one (`SubmitApplicationReview`
via `SubmittedApplicationLog`). A route that accepted a tracked application
would let a caller assert that an employer received a document, which is the
one thing this table must never be able to say untruthfully.

There is no DELETE either. Erasing a candidate's history is Epic 07's
deliberate, user-scoped purge, not something a stray request can reach —
`TrackedApplicationRepository` has no `delete` for the same reason.

Status codes
------------
- **404** no such application, *or* it belongs to another candidate. The two
  are indistinguishable on purpose, so the API never confirms an id exists.
- **409** the status is real but the move is not one the lifecycle allows
  (`rejected` back to `interviewing`). The request was well-formed and the
  domain refuses it as things stand, which is what 409 is for.
- **422** the value is not an application status at all, or is one this
  record cannot hold (`draft` — see `TrackedApplication`).
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.tracked_application_dtos import (
    ListTrackedApplicationsInput,
    UpdateTrackedApplicationStatusInput,
)
from src.application.use_cases.list_tracked_applications import (
    ListTrackedApplications,
)
from src.application.use_cases.update_tracked_application_status import (
    UpdateTrackedApplicationStatus,
)
from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    TrackedApplicationNotFoundError,
)
from src.interfaces.http.dependencies import (
    get_current_user,
    get_list_tracked_applications_use_case,
    get_update_tracked_application_status_use_case,
)
from src.interfaces.http.schemas import (
    TrackedApplicationResponse,
    UpdateApplicationStatusRequest,
)

router = APIRouter(
    prefix="/api/tracked-applications",
    tags=["tracked-applications"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[TrackedApplicationResponse])
async def list_tracked_applications(
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListTrackedApplications = Depends(get_list_tracked_applications_use_case),
) -> list[TrackedApplicationResponse]:
    """Every application the current user has sent, most recently applied
    first, each with the exact documents that went out with it."""
    outputs = await use_case.execute(
        ListTrackedApplicationsInput(user_id=user.subject, limit=limit)
    )
    return [TrackedApplicationResponse(**asdict(output)) for output in outputs]


@router.patch("/{application_id}/status", response_model=TrackedApplicationResponse)
async def update_tracked_application_status(
    application_id: str,
    body: UpdateApplicationStatusRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: UpdateTrackedApplicationStatus = Depends(
        get_update_tracked_application_status_use_case
    ),
) -> TrackedApplicationResponse:
    """Record what became of this application.

    PATCH rather than PUT: the status is the one field of a tracked
    application that changes, and the rest of the record — what was sent, and
    when — is not editable through any route.

    Returns the updated record, including the next set of
    `allowed_next_statuses`, so the screen that made the change re-renders
    from what was stored rather than from what it assumed.
    """
    try:
        output = await use_case.execute(
            UpdateTrackedApplicationStatusInput(
                user_id=user.subject,
                application_id=application_id,
                status=body.status,
            )
        )
    except TrackedApplicationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        # A real status, but not a move the lifecycle allows. Nothing was
        # written — the domain refuses before the repository is reached.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return TrackedApplicationResponse(**asdict(output))

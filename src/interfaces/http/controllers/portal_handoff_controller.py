"""Application-portal HTTP controller — inspecting a portal, and the hand-offs
that come out of it.

Thin: validate input -> call use case -> serialize. No business logic, no
DB/browser access, no domain entity manipulation.

Status codes, and why these ones:

- inspecting a portal that turns out to have a boundary is **200, not an
  error**. Nothing failed — ApplyFlow did exactly what it should and stopped.
  The response says so in `is_handed_off` and carries the hand-off; a 4xx/5xx
  would push clients into treating a correct, expected outcome as a fault to
  retry.
- a browser that cannot reach the portal at all (`BrowserNavigationError`) is
  502: the upstream did not answer.
- resolving a hand-off that was already resolved is 409, because the domain
  refuses the second transition (`HandoffStatus`) — the honest answer to a
  double-clicked "continue" is "that already happened", not a silently
  rewritten record.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.portal_handoff_dtos import (
    InspectApplicationPortalInput,
    ListPortalHandoffsInput,
    PortalHandoffOutput,
    ResolvePortalHandoffInput,
)
from src.application.exceptions import BrowserAutomationError, BrowserNavigationError
from src.application.use_cases.abandon_portal_handoff import AbandonPortalHandoff
from src.application.use_cases.inspect_application_portal import (
    InspectApplicationPortal,
)
from src.application.use_cases.list_portal_handoffs import ListPortalHandoffs
from src.application.use_cases.resume_portal_handoff import ResumePortalHandoff
from src.domain.exceptions import (
    BusinessRuleViolationError,
    JobPostingNotFoundError,
    PortalHandoffNotFoundError,
)
from src.interfaces.http.dependencies import (
    get_abandon_portal_handoff_use_case,
    get_current_user,
    get_inspect_application_portal_use_case,
    get_list_portal_handoffs_use_case,
    get_resume_portal_handoff_use_case,
)
from src.interfaces.http.schemas import (
    InspectPortalRequest,
    InspectPortalResponse,
    PortalHandoffListResponse,
    PortalHandoffResponse,
    ResolvePortalHandoffRequest,
)

router = APIRouter(
    prefix="/api/portal",
    tags=["portal"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/inspections", response_model=InspectPortalResponse)
async def inspect_application_portal(
    body: InspectPortalRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: InspectApplicationPortal = Depends(
        get_inspect_application_portal_use_case
    ),
) -> InspectPortalResponse:
    """Open the posting's application portal and report what it presents —
    either its questions, or the hand-off that stopped ApplyFlow."""
    try:
        output = await use_case.execute(
            InspectApplicationPortalInput(
                user_id=user.subject, job_posting_id=body.job_posting_id
            )
        )
    except JobPostingNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BrowserNavigationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except BrowserAutomationError as exc:
        # The browser itself could not do its job (no Chromium on the host, a
        # page that crashed). Ours to fix, so 500 rather than 502.
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)
        ) from exc
    return InspectPortalResponse(**asdict(output))


@router.get("/handoffs", response_model=PortalHandoffListResponse)
async def list_portal_handoffs(
    open_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ListPortalHandoffs = Depends(get_list_portal_handoffs_use_case),
) -> PortalHandoffListResponse:
    """What is waiting on the candidate, and what recently was."""
    output = await use_case.execute(
        ListPortalHandoffsInput(
            user_id=user.subject, open_only=open_only, limit=limit
        )
    )
    return PortalHandoffListResponse(**asdict(output))


@router.post("/handoffs/{handoff_id}/resume", response_model=PortalHandoffResponse)
async def resume_portal_handoff(
    handoff_id: str,
    body: ResolvePortalHandoffRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ResumePortalHandoff = Depends(get_resume_portal_handoff_use_case),
) -> PortalHandoffResponse:
    """The candidate did the human-only step; ApplyFlow may work this portal
    again. Records their assertion — it does not claim the boundary is gone
    (see `ResumePortalHandoff`)."""
    output = await _resolve(
        use_case, handoff_id=handoff_id, user=user, note=body.note
    )
    return PortalHandoffResponse(**asdict(output))


@router.post("/handoffs/{handoff_id}/abandon", response_model=PortalHandoffResponse)
async def abandon_portal_handoff(
    handoff_id: str,
    body: ResolvePortalHandoffRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: AbandonPortalHandoff = Depends(get_abandon_portal_handoff_use_case),
) -> PortalHandoffResponse:
    """The candidate is finishing this application themselves; ApplyFlow stops
    waiting on it."""
    output = await _resolve(
        use_case, handoff_id=handoff_id, user=user, note=body.note
    )
    return PortalHandoffResponse(**asdict(output))


async def _resolve(
    use_case: ResumePortalHandoff | AbandonPortalHandoff,
    *,
    handoff_id: str,
    user: AuthenticatedUserDTO,
    note: str,
) -> PortalHandoffOutput:
    """Both resolutions map the same two failures the same way, so the mapping
    lives once: an id that is not this candidate's is 404 (never 403 — that
    would confirm the id exists), and a hand-off already resolved is 409."""
    try:
        return await use_case.execute(
            ResolvePortalHandoffInput(
                user_id=user.subject, handoff_id=handoff_id, note=note
            )
        )
    except PortalHandoffNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

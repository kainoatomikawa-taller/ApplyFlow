"""Review-and-submit HTTP controller — where the candidate sees the filled
application, changes it, and submits it themselves.

Thin: validate input -> call use cases -> serialize. No business logic, no
DB/browser access, no domain entity manipulation.

The one place this controller sequences rather than delegates
------------------------------------------------------------
Opening a review is three steps in a fixed order, and the order is the safety
property:

1. `InspectApplicationPortal` — read the portal *before touching it*. If it has
   a hard boundary (a CAPTCHA, a signature, a sign-in wall) the response is the
   hand-off and nothing was filled.
2. `AutofillApplicationForm` — fill what can be filled from the candidate's own
   record, and screenshot the result.
3. `OpenApplicationReview` — turn that report into the review the candidate
   works with.

Only the sequencing lives here; every rule lives inward. Step 3 re-checks the
hand-off gate itself, so skipping step 1 could not produce a review on a walled
portal — step 1 exists to avoid filling a form that was never going to be
submittable, not to be the gate.

Status codes
------------
- being stopped at a hard boundary is a **200** with `review: null` and the
  hand-off attached. Nothing failed; ApplyFlow did exactly what it should.
- a portal that is not one of the supported ATS platforms is a 422: the
  candidate applies by hand, and the message says so.
- an unreachable portal is a 502; a browser that cannot run at all is a 500.
- submitting with a blocker standing, or submitting twice, is a 409 — the
  domain refuses, and the refusal text names what is missing.
"""

from __future__ import annotations

import base64
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.application_autofill_dtos import (
    AutofillApplicationFormInput,
)
from src.application.dtos.application_review_dtos import (
    ApplicationReviewOutput,
    GetApplicationReviewInput,
    OpenApplicationReviewInput,
    ReviseReviewedAnswerInput,
    SubmitApplicationReviewInput,
)
from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.dtos.portal_handoff_dtos import InspectApplicationPortalInput
from src.application.exceptions import (
    BrowserAutomationError,
    BrowserNavigationError,
    UnsupportedAtsFormError,
    UseCaseError,
)
from src.application.use_cases.autofill_application_form import AutofillApplicationForm
from src.application.use_cases.get_application_review import GetApplicationReview
from src.application.use_cases.inspect_application_portal import (
    InspectApplicationPortal,
)
from src.application.use_cases.open_application_review import OpenApplicationReview
from src.application.use_cases.revise_reviewed_answer import ReviseReviewedAnswer
from src.application.use_cases.submit_application_review import SubmitApplicationReview
from src.domain.exceptions import (
    ApplicationReviewNotFoundError,
    BusinessRuleViolationError,
    JobPostingNotFoundError,
    NoActiveApplicationReviewError,
    ProfileNotFoundError,
    ReviewedAnswerNotFoundError,
)
from src.interfaces.http.dependencies import (
    get_application_review_use_case,
    get_autofill_application_form_use_case,
    get_current_user,
    get_inspect_application_portal_use_case,
    get_open_application_review_use_case,
    get_revise_reviewed_answer_use_case,
    get_submit_application_review_use_case,
)
from src.interfaces.http.schemas import (
    ApplicationReviewResponse,
    OpenApplicationReviewResponse,
    PortalHandoffResponse,
    ReviseReviewedAnswerRequest,
    SubmitApplicationReviewRequest,
    SubmitApplicationReviewResponse,
)

router = APIRouter(
    prefix="/api",
    tags=["application-review"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/job-postings/{job_posting_id}/review",
    response_model=OpenApplicationReviewResponse,
)
async def open_application_review(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    inspect: InspectApplicationPortal = Depends(
        get_inspect_application_portal_use_case
    ),
    autofill: AutofillApplicationForm = Depends(
        get_autofill_application_form_use_case
    ),
    open_review: OpenApplicationReview = Depends(get_open_application_review_use_case),
) -> OpenApplicationReviewResponse:
    """Fill this posting's application form and open a review over it.

    Replaces whatever review was in progress for this posting — a fresh fill
    pass supersedes answers the candidate had not submitted. A review already
    submitted is never touched.
    """
    try:
        inspection = await inspect.execute(
            InspectApplicationPortalInput(
                user_id=user.subject, job_posting_id=job_posting_id
            )
        )
        if inspection.is_handed_off:
            # Nothing was filled, and nothing should be: the portal wants
            # something only the candidate can do.
            return OpenApplicationReviewResponse(
                job_posting_id=job_posting_id,
                review=None,
                handoff=(
                    PortalHandoffResponse(**asdict(inspection.handoff))
                    if inspection.handoff is not None
                    else None
                ),
            )

        report = await autofill.execute(
            AutofillApplicationFormInput(
                user_id=user.subject, job_posting_id=job_posting_id
            )
        )
        output = await open_review.execute(
            OpenApplicationReviewInput(
                user_id=user.subject,
                job_posting_id=job_posting_id,
                autofill=report,
            )
        )
    except (JobPostingNotFoundError, ProfileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UnsupportedAtsFormError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    except UseCaseError as exc:
        # A form that presented no fields, or a mismatched report — neither is
        # something a retry fixes, and both are explained in the message.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    except BrowserNavigationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except BrowserAutomationError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)
        ) from exc

    return OpenApplicationReviewResponse(
        job_posting_id=output.job_posting_id,
        review=_optional_review_response(output.review),
        handoff=(
            PortalHandoffResponse(**asdict(output.handoff))
            if output.handoff is not None
            else None
        ),
        screenshot_base64=(
            base64.b64encode(output.screenshot_png).decode("ascii")
            if output.screenshot_png
            else None
        ),
    )


@router.get(
    "/job-postings/{job_posting_id}/review",
    response_model=ApplicationReviewResponse,
)
async def get_application_review(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: GetApplicationReview = Depends(get_application_review_use_case),
) -> ApplicationReviewResponse:
    """The review this candidate is in the middle of for this posting."""
    try:
        output = await use_case.execute(
            GetApplicationReviewInput(
                user_id=user.subject, job_posting_id=job_posting_id
            )
        )
    except NoActiveApplicationReviewError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _review_response(output)


@router.post(
    "/application-reviews/{review_id}/answers/{field_key}",
    response_model=ApplicationReviewResponse,
)
async def revise_reviewed_answer(
    review_id: str,
    field_key: str,
    body: ReviseReviewedAnswerRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: ReviseReviewedAnswer = Depends(get_revise_reviewed_answer_use_case),
) -> ApplicationReviewResponse:
    """Write an answer, approve the one that is there, or decline the field.

    Returns the whole review, because one decision can change what stands
    between the candidate and submitting.
    """
    try:
        output = await use_case.execute(
            ReviseReviewedAnswerInput(
                user_id=user.subject,
                review_id=review_id,
                field_key=field_key,
                action=body.action,
                value=body.value,
            )
        )
    except (ApplicationReviewNotFoundError, ReviewedAnswerNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        # The review was already submitted, so its answers are the record of
        # what was sent and no longer editable.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UseCaseError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    return _review_response(output)


@router.post(
    "/application-reviews/{review_id}/submit",
    response_model=SubmitApplicationReviewResponse,
)
async def submit_application_review(
    review_id: str,
    body: SubmitApplicationReviewRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SubmitApplicationReview = Depends(get_submit_application_review_use_case),
) -> SubmitApplicationReviewResponse:
    """The candidate submits this application.

    The only route that marks an application as sent, and it is reachable only
    by the candidate's own request. Refused while any blocker stands — an
    unconfirmed legal declaration, an undecided EEO question, an open hard-stop
    hand-off — and refused a second time on a review already submitted.
    """
    try:
        output = await use_case.execute(
            SubmitApplicationReviewInput(
                user_id=user.subject, review_id=review_id, note=body.note
            )
        )
    except ApplicationReviewNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BusinessRuleViolationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SubmitApplicationReviewResponse(
        review=_review_response(output.review),
        apply_url=output.apply_url,
    )


def _review_response(output: ApplicationReviewOutput) -> ApplicationReviewResponse:
    return ApplicationReviewResponse(**asdict(output))


def _optional_review_response(
    output: ApplicationReviewOutput | None,
) -> ApplicationReviewResponse | None:
    """Only the open route can legitimately have no review — a hard stop means
    nothing was filled. Kept separate from `_review_response` so that case
    cannot leak into a response that promises one."""
    return None if output is None else _review_response(output)

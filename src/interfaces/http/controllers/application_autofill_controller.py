"""Portal autofill, review, and submit HTTP controller.

Thin: validate input -> call use case -> serialize. No business logic, no
browser, no policy. Every gate that decides whether an application may be
sent lives in `SubmitApplicationForm`; this module's only job in that regard
is to turn each refusal into the right status code and to pass the refusal's
detail through intact.

The flow these four routes make
-------------------------------
    POST   /api/job-postings/{id}/autofill        fill the form, park it
    POST   /api/autofill-sessions/{id}/fields/{field_id}
                                                 answer what was surfaced
    POST   /api/autofill-sessions/{id}/submit    send it
    DELETE /api/autofill-sessions/{id}           walk away

Submission is its own request, made by the candidate, carrying their
confirmations. There is no flag on the autofill route that submits, and no
route that fills and sends in one step — the shape of this API is half of
"nothing is submitted unattended".

Why some errors carry a structured detail
-----------------------------------------
Most refusals here are things the candidate can act on, and a string cannot
carry them well enough: a hand-off needs the boundaries (each with its own
instruction) so a UI can render them; an unconfirmed-fields refusal needs the
field labels; an ambiguous submit needs the button labels to choose between.
Those responses use an object detail with a `message` plus the specifics.
Everything else stays a plain string, as elsewhere in this app.

Status codes
------------
- **404** the posting, the profile, the review session, or the field is not
  there. A review session that expired, was already submitted, or belongs to
  someone else is indistinguishable from one that never existed.
- **409** the request was well-formed and the flow refuses it as things
  stand: a hand-off is required, confirmations are missing, required answers
  are missing, the form offers several submit buttons, or the page moved
  under the snapshot. All are retriable after the candidate does something.
- **422** this portal is not one field mapping covers, or the value cannot go
  into that field.
- **502** the portal or the browser failed — a page that would not load, a
  control that would not accept the press. Nothing was sent.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.application.dtos.application_autofill_dtos import (
    ApplicationAutofillOutput,
    ApplicationBoundaryOutput,
    AutofillApplicationFormInput,
    AutofilledFieldOutput,
)
from src.application.dtos.application_review_dtos import (
    AnswerApplicationFieldInput,
    ApplicationSubmissionOutput,
    DiscardApplicationReviewInput,
    SubmitApplicationFormInput,
)
from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.exceptions import (
    AmbiguousSubmitControlError,
    ApplicationHandoffRequiredError,
    BrowserAutomationError,
    BrowserNavigationError,
    FormFieldNotFillableError,
    IncompleteApplicationError,
    RejectedFieldValueError,
    ReviewFieldNotFoundError,
    ReviewSessionNotFoundError,
    StaleFormFieldError,
    SubmitControlNotPressableError,
    SubmitControlUnavailableError,
    UnconfirmedSensitiveFieldsError,
    UnsupportedAtsFormError,
)
from src.application.use_cases.answer_application_field import AnswerApplicationField
from src.application.use_cases.autofill_application_form import AutofillApplicationForm
from src.application.use_cases.discard_application_review import (
    DiscardApplicationReview,
)
from src.application.use_cases.submit_application_form import SubmitApplicationForm
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.interfaces.http.dependencies import (
    get_answer_application_field_use_case,
    get_autofill_application_form_use_case,
    get_current_user,
    get_discard_application_review_use_case,
    get_submit_application_form_use_case,
)
from src.interfaces.http.schemas import (
    AnswerApplicationFieldRequest,
    ApplicationAutofillResponse,
    ApplicationBoundaryResponse,
    ApplicationSubmissionResponse,
    AutofilledFieldResponse,
    SubmitApplicationRequest,
)

#: A form that moved underneath the parked snapshot. One message, because the
#: remedy is one thing: read the form again by running the autofill again.
_STALE_FORM_DETAIL = (
    "The application form changed underneath this review, so ApplyFlow can no "
    "longer be sure which field is which. Nothing was sent — run the autofill "
    "again to work from the form as it is now."
)

autofill_router = APIRouter(
    prefix="/api/job-postings",
    tags=["application-autofill"],
    dependencies=[Depends(get_current_user)],
)

review_router = APIRouter(
    prefix="/api/autofill-sessions",
    tags=["application-autofill"],
    dependencies=[Depends(get_current_user)],
)


@autofill_router.post(
    "/{job_posting_id}/autofill", response_model=ApplicationAutofillResponse
)
async def autofill_application_form(
    job_posting_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: AutofillApplicationForm = Depends(
        get_autofill_application_form_use_case
    ),
) -> ApplicationAutofillResponse:
    """Fill the posting's application form and hand back the filled form.

    A 200 with `requires_handoff` set is a successful request: ApplyFlow read
    the page, found something only the candidate can do, and is saying so.
    That is a result, not an error — the failures here are a portal that is
    out of scope, missing data, or a page that would not load.
    """
    try:
        output = await use_case.execute(
            AutofillApplicationFormInput(
                user_id=user.subject, job_posting_id=job_posting_id
            )
        )
    except (JobPostingNotFoundError, ProfileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UnsupportedAtsFormError as exc:
        # Refused before a browser opened: the field-mapping rules cover
        # Greenhouse, Lever, and Ashby, and pointing them at another portal
        # would confidently fill the wrong fields.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except StaleFormFieldError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _STALE_FORM_DETAIL) from exc
    except BrowserNavigationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except BrowserAutomationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return _to_autofill_response(output)


@review_router.post(
    "/{review_session_id}/fields/{field_id}",
    response_model=ApplicationAutofillResponse,
)
async def answer_application_field(
    review_session_id: str,
    field_id: str,
    body: AnswerApplicationFieldRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: AnswerApplicationField = Depends(get_answer_application_field_use_case),
) -> ApplicationAutofillResponse:
    """Write the candidate's own answer into one field of the parked form.

    The whole updated report comes back, because an answer can change what is
    left to do — including clearing the last thing standing between this
    application and the Submit button.
    """
    try:
        output = await use_case.execute(
            AnswerApplicationFieldInput(
                user_id=user.subject,
                review_session_id=review_session_id,
                field_id=field_id,
                value=body.value,
            )
        )
    except (ReviewSessionNotFoundError, ReviewFieldNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RejectedFieldValueError as exc:
        # The field cannot represent this value, and the portal said what it
        # would take. Nothing was written.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except StaleFormFieldError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _STALE_FORM_DETAIL) from exc
    except FormFieldNotFillableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return _to_autofill_response(output)


@review_router.post(
    "/{review_session_id}/submit", response_model=ApplicationSubmissionResponse
)
async def submit_application_form(
    review_session_id: str,
    body: SubmitApplicationRequest,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: SubmitApplicationForm = Depends(get_submit_application_form_use_case),
) -> ApplicationSubmissionResponse:
    """Send the reviewed application, on this candidate's instruction.

    Every refusal below happened *before* anything was pressed, and each one
    names what the candidate has to do first. A 200 means the button was
    pressed — read `is_confirmed_sent` for whether the portal accepted it.
    """
    try:
        output = await use_case.execute(
            SubmitApplicationFormInput(
                user_id=user.subject,
                review_session_id=review_session_id,
                confirmed_field_ids=tuple(body.confirmed_field_ids),
                submit_control_label=body.submit_control_label,
            )
        )
    except ReviewSessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ApplicationHandoffRequiredError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": str(exc),
                "apply_url": exc.apply_url,
                "boundaries": [
                    _to_boundary_response(boundary).model_dump()
                    for boundary in exc.boundaries
                ],
            },
        ) from exc
    except UnconfirmedSensitiveFieldsError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "unconfirmed_fields": list(exc.labels)},
        ) from exc
    except IncompleteApplicationError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "unanswered_required_fields": list(exc.labels)},
        ) from exc
    except AmbiguousSubmitControlError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "submit_controls": list(exc.available)},
        ) from exc
    except SubmitControlUnavailableError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "submit_controls": list(exc.available)},
        ) from exc
    except StaleFormFieldError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _STALE_FORM_DETAIL) from exc
    except SubmitControlNotPressableError as exc:
        # The press itself failed, so nothing was sent and the review is
        # still open — retrying is safe, which a 502 leaves room for.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return _to_submission_response(output)


@review_router.delete(
    "/{review_session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def discard_application_review(
    review_session_id: str,
    user: AuthenticatedUserDTO = Depends(get_current_user),
    use_case: DiscardApplicationReview = Depends(
        get_discard_application_review_use_case
    ),
) -> Response:
    """Abandon a filled form without sending it, closing its browser."""
    try:
        await use_case.execute(
            DiscardApplicationReviewInput(
                user_id=user.subject, review_session_id=review_session_id
            )
        )
    except ReviewSessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- Serialization -----------------------------------------------------------


def _to_autofill_response(
    output: ApplicationAutofillOutput,
) -> ApplicationAutofillResponse:
    """Serialize a filled form, base64-encoding the screenshot.

    Mapped field by field rather than via `asdict` because the screenshot is
    raw bytes: transport encoding is this layer's job, and the DTO should not
    carry a base64 string to make JSON convenient. The derived properties are
    sent as computed here, so a client never has to reimplement the
    submission gates to know whether its Submit button can work.
    """
    return ApplicationAutofillResponse(
        job_posting_id=output.job_posting_id,
        apply_url=output.apply_url,
        ats_provider=output.ats_provider,
        fields=[_to_field_response(item) for item in output.fields],
        screenshot_png_base64=_encode(output.screenshot_png),
        boundaries=[
            _to_boundary_response(boundary) for boundary in output.boundaries
        ],
        review_session_id=output.review_session_id,
        review_expires_at=output.review_expires_at,
        requires_handoff=output.requires_handoff,
        can_be_submitted_here=output.can_be_submitted_here,
        fields_awaiting_confirmation=[
            item.field_id for item in output.fields_awaiting_confirmation
        ],
        unanswered_required_fields=[
            item.field_id for item in output.unanswered_required_fields
        ],
    )


def _to_submission_response(
    output: ApplicationSubmissionOutput,
) -> ApplicationSubmissionResponse:
    return ApplicationSubmissionResponse(
        job_posting_id=output.job_posting_id,
        submitted_at=output.submitted_at,
        pressed_control=output.pressed_control,
        final_url=output.final_url,
        confirmation_excerpt=output.confirmation_excerpt,
        screenshot_png_base64=_encode(output.screenshot_png),
        outstanding_boundaries=[
            _to_boundary_response(boundary)
            for boundary in output.outstanding_boundaries
        ],
        is_confirmed_sent=output.is_confirmed_sent,
    )


def _to_field_response(item: AutofilledFieldOutput) -> AutofilledFieldResponse:
    return AutofilledFieldResponse(
        field_id=item.field_id,
        label=item.label,
        kind=item.kind,
        required=item.required,
        outcome=item.outcome,
        slot=item.slot,
        value=item.value,
        is_derived=item.is_derived,
        reason=item.reason,
        detail=item.detail,
        is_sensitive=item.is_sensitive,
        sensitivity=item.sensitivity,
        requires_confirmation=item.requires_confirmation,
        answered_by_candidate=item.answered_by_candidate,
    )


def _to_boundary_response(
    boundary: ApplicationBoundaryOutput,
) -> ApplicationBoundaryResponse:
    return ApplicationBoundaryResponse(
        kind=boundary.kind,
        evidence=boundary.evidence,
        instruction=boundary.instruction,
        stopped_autofill=boundary.stopped_autofill,
        blocks_submission=boundary.blocks_submission,
    )


def _encode(image: bytes | None) -> str | None:
    return base64.b64encode(image).decode("ascii") if image is not None else None

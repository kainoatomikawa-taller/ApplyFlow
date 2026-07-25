"""Mapper between ApplicationReview and its DTOs, and between a fill report and
the answers a review starts from.

The second half is the interesting one. An autofill report describes *what
happened to a widget* — filled, attached, surfaced, not accepted, failed. A
review describes *what the answer is and who is responsible for it*. Collapsing
five outcomes onto two origins is a real decision, and it is made once, here,
so no screen has to re-derive it:

- `FILLED` / `ATTACHED` → an answer ApplyFlow wrote (`AUTOFILLED`).
- everything else → no answer yet (`UNANSWERED`), with the report's reason
  carried through as the explanation the candidate reads.

`NOT_ACCEPTED` is the case worth stating explicitly: ApplyFlow had a value, the
portal refused it, so the field is *unanswered* even though a value exists.
Showing it as filled would tell the candidate their form is complete when the
portal has already rejected that answer — so the refused value goes into the
explanation ("we tried X; the form accepts Y") and the field waits for them.

Attachments are a related case: `ATTACHED` records a filename, not an answer a
candidate can edit as text. It is reported as autofilled with the filename as
its value, which is what a reviewer needs to see ("your resume PDF is on it"),
and editing it does what editing any answer does — replaces what will be sent
with the candidate's own words. Re-uploading a different file from this screen
is not something this flow offers yet.
"""

from __future__ import annotations

from src.application.dtos.application_autofill_dtos import (
    ApplicationAutofillOutput,
    AutofilledFieldOutput,
)
from src.application.dtos.application_review_dtos import (
    ApplicationReviewOutput,
    ReviewedAnswerOutput,
    SubmissionBlockerOutput,
)
from src.application.dtos.portal_handoff_dtos import PortalHandoffOutput
from src.domain.entities.application_review import ApplicationReview
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    FieldSensitivity,
)
from src.domain.value_objects.reviewed_answer import AnswerOrigin, ReviewedAnswer
from src.domain.value_objects.submission_blocker import SubmissionBlocker


class ApplicationReviewMapper:
    """Translates fill reports into reviewable answers, and reviews into DTOs.

    `user_id` is never mapped out: every read is already scoped to the
    requesting candidate by the use case, so echoing it back would only widen
    what a response carries.
    """

    @staticmethod
    def answers_from_autofill(
        autofill: ApplicationAutofillOutput,
    ) -> tuple[ReviewedAnswer, ...]:
        """Build the starting answers for a review from one fill pass.

        Keys are assigned from the field's position on the page, so they are
        stable for as long as the review lives and mean nothing outside it.
        """
        return tuple(
            ApplicationReviewMapper._answer_from_field(f"f{index}", item)
            for index, item in enumerate(autofill.fields)
        )

    @staticmethod
    def _answer_from_field(key: str, item: AutofilledFieldOutput) -> ReviewedAnswer:
        answered = item.was_applied
        return ReviewedAnswer(
            key=key,
            label=item.label,
            widget_kind=item.kind,
            value=item.value if answered and item.value else "",
            slot=_slot(item.slot),
            sensitivity=_sensitivity(item.sensitivity),
            required=item.required,
            origin=(
                AnswerOrigin.AUTOFILLED if answered else AnswerOrigin.UNANSWERED
            ),
            explanation=_explanation(item),
        )

    @staticmethod
    def to_output(
        review: ApplicationReview,
        *,
        handoff: PortalHandoffOutput | None = None,
        has_open_handoff: bool = False,
    ) -> ApplicationReviewOutput:
        """Serialize a review, with the submit gate computed against the
        hand-off state the caller just read."""
        blockers = review.blockers(has_open_handoff=has_open_handoff)
        return ApplicationReviewOutput(
            id=review.id,
            job_posting_id=review.job_posting_id,
            apply_url=review.apply_url,
            ats_provider=review.ats_provider,
            status=review.status.value,
            is_open=review.is_open,
            created_at=review.created_at,
            answers=[
                ApplicationReviewMapper.answer_to_output(item)
                for item in review.answers
            ],
            blockers=[
                ApplicationReviewMapper.blocker_to_output(item) for item in blockers
            ],
            can_submit=review.is_open and not blockers,
            handoff=handoff,
            unanswered_required_keys=[
                item.key for item in review.unanswered_required_answers
            ],
            screenshot_captured=review.screenshot_captured,
            submitted_at=review.submitted_at,
            submission_note=review.submission_note,
        )

    @staticmethod
    def answer_to_output(answer: ReviewedAnswer) -> ReviewedAnswerOutput:
        return ReviewedAnswerOutput(
            key=answer.key,
            label=answer.label,
            widget_kind=answer.widget_kind,
            value=answer.value,
            required=answer.required,
            origin=answer.origin.value,
            slot=answer.slot.value if answer.slot is not None else None,
            sensitivity=(
                answer.sensitivity.value if answer.sensitivity is not None else None
            ),
            is_sensitive=answer.is_sensitive,
            needs_decision=answer.needs_candidate_decision,
            explanation=answer.explanation,
        )

    @staticmethod
    def blocker_to_output(blocker: SubmissionBlocker) -> SubmissionBlockerOutput:
        return SubmissionBlockerOutput(
            kind=blocker.kind.value,
            detail=blocker.detail,
            field_key=blocker.field_key,
            field_label=blocker.field_label,
        )


def _slot(value: str | None) -> ApplicationFieldSlot | None:
    """Resolve a slot name from a report, tolerating one this build does not
    know.

    A report is application-layer data, not user input, so an unknown slot
    means the two halves are out of step. Dropping it to None loses a label on
    a review screen; refusing the whole review over it would lose the
    candidate's work — and the sensitivity flag, which is what actually has to
    survive, is carried separately for exactly this reason.
    """
    if value is None:
        return None
    try:
        return ApplicationFieldSlot(value)
    except ValueError:
        return None


def _sensitivity(value: str | None) -> FieldSensitivity | None:
    if value is None:
        return None
    try:
        return FieldSensitivity(value)
    except ValueError:
        # Fail closed: an unrecognized category is still a category somebody
        # marked sensitive, so it must not silently become an ordinary field.
        # Treated as the stricter of the two, which is never autofilled.
        return FieldSensitivity.VOLUNTARY_SELF_ID


def _explanation(item: AutofilledFieldOutput) -> str:
    """What to tell the candidate about this field, from the report's own
    reason and detail."""
    if item.outcome == "not_accepted" and item.value:
        # The one case where the report holds a value the review must NOT show
        # as the answer: the portal refused it. It belongs in the explanation
        # instead, because "we tried X and it was refused" is what the candidate
        # needs to pick something the form will take.
        refused = f"ApplyFlow tried '{item.value}' and the form refused it."
        return f"{refused} {item.detail}".strip() if item.detail else refused
    if item.detail:
        return item.detail
    reason = item.reason
    return _REASON_TEXT.get(reason, "") if reason is not None else ""


#: Report reason codes turned into something a candidate can act on. The codes
#: come from `SurfaceReason` (plus the two the executing pass adds); anything
#: not listed falls back to the report's own `detail`, or to nothing.
_REASON_TEXT: dict[str, str] = {
    "unrecognized": (
        "ApplyFlow does not recognize this question — it is usually one the "
        "company wrote itself. Your answer, please."
    ),
    "no_profile_data": (
        "Your profile does not answer this yet. Filling it in there fixes it "
        "for every future application."
    ),
    "requires_candidate_answer": (
        "ApplyFlow never answers this one. It is yours to answer or decline."
    ),
    "sensitive_data_not_attested": (
        "This legal question is answered in your profile, but not from "
        "something you stated yourself — so it needs you to say it."
    ),
    "sensitive_answer_not_derivable": (
        "Your record does not settle this legal question exactly, and "
        "answering it approximately is the one thing it must not do."
    ),
    "unsupported_field_kind": (
        "ApplyFlow will not write into this widget — either it cannot take the "
        "answer, or it is a field only you may fill."
    ),
    "document_not_generated": (
        "No document has been generated for this job yet. Generate one and run "
        "the fill again, or answer this field yourself."
    ),
    "value_too_long": (
        "The answer is longer than this field allows. It was left alone rather "
        "than cut off mid-sentence — you decide what to trim."
    ),
}

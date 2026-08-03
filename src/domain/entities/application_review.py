"""ApplicationReview entity — the filled application as the candidate sees it
before it goes anywhere, and the record of them sending it.

Why this exists
---------------
An autofill pass produces a report. A report is not something a person can act
on: it cannot be corrected, it does not remember which legal declarations they
have looked at, and it disappears when the response does. This entity is the
same information turned into a working surface — every question in page order,
every answer editable, every sensitive field waiting on an explicit decision —
and it survives the request, so the candidate can leave, come back, and finish.

The user is the submitter, and it is enforced here
--------------------------------------------------
`record_submission` is the only way to reach `SUBMITTED_BY_USER`, and it
refuses while any blocker stands. Three properties, in order of how much they
matter:

1. **Nothing submits by itself.** No scheduled task, no model, and no other use
   case calls this method — the only caller is the route the candidate's own
   click reaches. The status name says who did it, so the record stays
   checkable long after the code has moved on.
2. **Consent is a precondition, not a formality.** Every sensitive field must
   be settled first (`PENDING_SENSITIVE_DECISION`), and an open hard-stop
   hand-off blocks too (`OPEN_HARD_STOP`) — handing someone an application to
   send through a portal that is still walled is handing them a dead end.
3. **What was approved is frozen.** After submission the answers cannot be
   edited: they are the record of what the candidate actually sent, and the
   same reasoning that makes `ApplicationDocument` write-once applies to them.

What this entity does *not* claim
---------------------------------
It does not claim ApplyFlow pressed the portal's submit button. It cannot —
the browser harness discovers no buttons, so there is nothing there to press
(see `BrowserAutomationPort`). `record_submission` records that the candidate
took the application and sent it, which is why the status is
`SUBMITTED_BY_USER` rather than `SUBMITTED`. Anything stronger would be a
claim nobody made.

SENSITIVE: `answers` carries what goes onto a real application — name, email,
address, and the work-authorization declarations. Flagged on
`ApplicationReviewModel` too, and never logged: log the review `id`, the
`job_posting_id`, and counts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import ClassVar

from src.domain.exceptions import (
    BusinessRuleViolationError,
    InvalidValueError,
    ReviewedAnswerNotFoundError,
)
from src.domain.value_objects.review_status import ReviewStatus
from src.domain.value_objects.reviewed_answer import ReviewedAnswer
from src.domain.value_objects.submission_blocker import (
    SubmissionBlocker,
    SubmissionBlockerKind,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ApplicationReview:
    """One filled application, under review by the candidate."""

    SENSITIVE: ClassVar[bool] = True
    MAX_NOTE_LENGTH: ClassVar[int] = 1000

    id: str
    user_id: str
    job_posting_id: str
    #: The apply URL the pass ended on — where the candidate goes to send it.
    apply_url: str
    #: Which ATS platform the form was read as (an `AtsProvider` value).
    ats_provider: str
    #: Every question the form presented, in page order. Never empty: a review
    #: of nothing is not a review (see `__post_init__`).
    answers: tuple[ReviewedAnswer, ...]
    status: ReviewStatus = ReviewStatus.IN_REVIEW
    created_at: datetime = field(default_factory=_utcnow)
    #: Whether the pass captured a screenshot of the filled form. The image
    #: itself is not stored on the entity — it is proof for the session that
    #: produced it, not part of the record.
    screenshot_captured: bool = False
    submitted_at: datetime | None = None
    #: What the candidate said when they submitted, in their own words.
    #: SENSITIVE, same as the answers.
    submission_note: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "user_id", "job_posting_id", "apply_url"):
            if not str(getattr(self, name)).strip():
                raise InvalidValueError(
                    f"ApplicationReview requires a non-empty {name}."
                )
        if not isinstance(self.answers, tuple):
            raise InvalidValueError("ApplicationReview.answers must be a tuple.")
        if not self.answers:
            raise InvalidValueError(
                "ApplicationReview requires at least one answer — a review of a "
                "form with no questions is nothing for a candidate to check."
            )
        if not all(isinstance(item, ReviewedAnswer) for item in self.answers):
            raise InvalidValueError(
                "ApplicationReview.answers must contain only ReviewedAnswer values."
            )
        keys = [item.key for item in self.answers]
        if len(set(keys)) != len(keys):
            raise InvalidValueError(
                "ApplicationReview answer keys must be unique — a duplicate key "
                "means an edit could land on the wrong question."
            )
        if not isinstance(self.status, ReviewStatus):
            raise InvalidValueError("ApplicationReview requires a valid ReviewStatus.")
        if len(self.submission_note) > ApplicationReview.MAX_NOTE_LENGTH:
            raise InvalidValueError(
                "ApplicationReview.submission_note cannot exceed "
                f"{ApplicationReview.MAX_NOTE_LENGTH} characters."
            )
        if self.status.is_open:
            if self.submitted_at is not None:
                raise InvalidValueError(
                    "A review still in progress cannot have a submitted_at."
                )
            if self.submission_note:
                raise InvalidValueError(
                    "A review still in progress cannot carry a submission note."
                )
        elif self.submitted_at is None:
            raise InvalidValueError(
                "A submitted review requires a submitted_at — the record of when "
                "the candidate sent it is the point of the record."
            )

    # ---- Construction --------------------------------------------------------

    @classmethod
    def open_for(
        cls,
        *,
        review_id: str,
        user_id: str,
        job_posting_id: str,
        apply_url: str,
        ats_provider: str,
        answers: tuple[ReviewedAnswer, ...],
        screenshot_captured: bool = False,
        created_at: datetime | None = None,
    ) -> ApplicationReview:
        """Open a review over the answers a fill pass produced."""
        return cls(
            id=review_id,
            user_id=user_id,
            job_posting_id=job_posting_id,
            apply_url=apply_url,
            ats_provider=ats_provider,
            answers=answers,
            status=ReviewStatus.IN_REVIEW,
            created_at=created_at or _utcnow(),
            screenshot_captured=screenshot_captured,
        )

    # ---- Reading -------------------------------------------------------------

    def answer(self, key: str) -> ReviewedAnswer:
        """The answer addressed by `key`.

        Raises `ReviewedAnswerNotFoundError` rather than returning None: an
        edit aimed at a key this review does not have is a caller bug, and
        silently doing nothing with it would look to the candidate like their
        change was saved.
        """
        for item in self.answers:
            if item.key == key:
                return item
        raise ReviewedAnswerNotFoundError(review_id=self.id, field_key=key)

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    @property
    def sensitive_answers(self) -> tuple[ReviewedAnswer, ...]:
        """Every sensitive field, settled or not, in page order — what a review
        screen flags distinctly."""
        return tuple(item for item in self.answers if item.is_sensitive)

    @property
    def answers_awaiting_decision(self) -> tuple[ReviewedAnswer, ...]:
        """Sensitive fields the candidate has not settled yet."""
        return tuple(item for item in self.answers if item.needs_candidate_decision)

    @property
    def unanswered_required_answers(self) -> tuple[ReviewedAnswer, ...]:
        """Fields the portal marked required that still have no answer.

        Warnings, not blockers — see `SubmissionBlocker` for why a `required`
        flag ApplyFlow may have misread must not lock a candidate out of
        submitting their own application.
        """
        return tuple(
            item for item in self.answers if item.required and not item.is_answered
        )

    def blockers(self, *, has_open_handoff: bool) -> tuple[SubmissionBlocker, ...]:
        """Everything standing between the candidate and submitting.

        `has_open_handoff` is passed in rather than looked up: whether a
        hand-off is open is a fact about another aggregate, and an entity that
        went and read it would need a repository to do it.
        """
        found: list[SubmissionBlocker] = []
        if has_open_handoff:
            found.append(
                SubmissionBlocker(
                    kind=SubmissionBlockerKind.OPEN_HARD_STOP,
                    detail=(
                        "This portal stopped ApplyFlow at something only you can "
                        "do. Deal with that hand-off first — submitting through a "
                        "portal that is still blocked would not get you anywhere."
                    ),
                )
            )
        for item in self.answers_awaiting_decision:
            found.append(
                SubmissionBlocker(
                    kind=SubmissionBlockerKind.PENDING_SENSITIVE_DECISION,
                    detail=_decision_prompt(item),
                    field_key=item.key,
                    field_label=item.label,
                )
            )
        return tuple(found)

    def can_submit(self, *, has_open_handoff: bool) -> bool:
        return self.is_open and not self.blockers(has_open_handoff=has_open_handoff)

    # ---- The candidate's edits -----------------------------------------------

    def with_answer(self, key: str, value: str) -> ApplicationReview:
        """The candidate's own answer for one field."""
        return self._revised(key, lambda item: item.answered(value))

    def with_confirmation(self, key: str) -> ApplicationReview:
        """The candidate approves one field's answer as it stands."""
        return self._revised(key, lambda item: item.confirmed())

    def with_declined(self, key: str) -> ApplicationReview:
        """The candidate deliberately leaves one field blank."""
        return self._revised(key, lambda item: item.declined())

    # ---- Submission ----------------------------------------------------------

    def record_submission(
        self,
        *,
        has_open_handoff: bool,
        note: str = "",
        submitted_at: datetime | None = None,
    ) -> ApplicationReview:
        """Record that the candidate is sending this application.

        The only path to `SUBMITTED_BY_USER`, and it refuses while anything is
        unsettled — so "the candidate consented to every sensitive field on
        this form" is a property of every submitted review rather than
        something a UI was trusted to have asked about.

        Raises:
            BusinessRuleViolationError: if a blocker stands, or if this review
                was already submitted.
        """
        blockers = self.blockers(has_open_handoff=has_open_handoff)
        if blockers:
            raise BusinessRuleViolationError(
                "This application is not ready to submit: "
                + "; ".join(blocker.detail for blocker in blockers)
            )
        return replace(
            self,
            status=self.status.transition_to(ReviewStatus.SUBMITTED_BY_USER),
            submitted_at=submitted_at or _utcnow(),
            submission_note=note.strip(),
        )

    # ---- internals -----------------------------------------------------------

    def _revised(
        self, key: str, revise: Callable[[ReviewedAnswer], ReviewedAnswer]
    ) -> ApplicationReview:
        """Replace one answer, refusing to touch a submitted review.

        Editing after submission is refused rather than allowed-and-recorded:
        the answers are what the candidate sent, and a record that can be
        rewritten afterwards cannot serve as one.
        """
        if not self.is_open:
            raise BusinessRuleViolationError(
                "This application was already submitted, so its answers can no "
                "longer be edited — they are the record of what you sent."
            )
        current = self.answer(key)
        revised = revise(current)
        return replace(
            self,
            answers=tuple(
                revised if item.key == key else item for item in self.answers
            ),
        )


def _decision_prompt(answer: ReviewedAnswer) -> str:
    """What to ask the candidate about one undecided sensitive field.

    The two categories need different asks, and saying "please review this
    field" for both would flatten the distinction the domain draws between a
    declaration the candidate is accountable for and a disclosure that is
    theirs to make or refuse.
    """
    label = answer.label or "this field"
    if answer.is_voluntary_self_id:
        return (
            f"'{label}' is voluntary self-identification. ApplyFlow never "
            "answers it — answer it yourself or decline it."
        )
    if answer.was_autofilled:
        return (
            f"'{label}' is a legal declaration ApplyFlow filled from your "
            "record. Confirm it, change it, or decline to answer it here."
        )
    return (
        f"'{label}' is a legal declaration ApplyFlow would not answer for you. "
        "Answer it yourself or decline it."
    )

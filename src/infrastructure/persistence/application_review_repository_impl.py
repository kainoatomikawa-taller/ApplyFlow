"""SQLAlchemy implementation of the ApplicationReviewRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.

`update` reads the row first rather than merging blindly: a merge that found
nothing would insert, resurrecting a review the candidate had already finished
with and presenting it as still editable.

The `answers` JSON is rebuilt through `ReviewedAnswer`'s own constructor rather
than trusted, so a row a migration or a manual edit left in an impossible state
— a declined answer that still carries a value, a sensitivity category nothing
recognizes — surfaces as an error instead of being shown to a candidate as
their application.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.application_review import ApplicationReview
from src.domain.exceptions import ApplicationReviewNotFoundError, InvalidValueError
from src.domain.repositories.application_review_repository import (
    ApplicationReviewRepository,
)
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    FieldSensitivity,
)
from src.domain.value_objects.review_status import ReviewStatus
from src.domain.value_objects.reviewed_answer import AnswerOrigin, ReviewedAnswer
from src.infrastructure.persistence.models import ApplicationReviewModel


class SqlAlchemyApplicationReviewRepository(ApplicationReviewRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, review: ApplicationReview) -> None:
        self._session.add(self._to_model(review))
        await self._session.commit()

    async def update(self, review: ApplicationReview) -> None:
        model = await self._session.get(ApplicationReviewModel, review.id)
        if model is None:
            raise ApplicationReviewNotFoundError(review.id)
        model.apply_url = review.apply_url
        model.ats_provider = review.ats_provider
        model.status = review.status.value
        model.answers = _answers_to_json(review)
        model.screenshot_captured = review.screenshot_captured
        model.submitted_at = review.submitted_at
        model.submission_note = review.submission_note
        await self._session.commit()

    async def get_by_id(self, review_id: str) -> ApplicationReview | None:
        model = await self._session.get(ApplicationReviewModel, review_id)
        return self._to_entity(model) if model else None

    async def get_active_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> ApplicationReview | None:
        result = await self._session.execute(
            select(ApplicationReviewModel)
            .where(
                ApplicationReviewModel.user_id == user_id,
                ApplicationReviewModel.job_posting_id == job_posting_id,
                ApplicationReviewModel.status == ReviewStatus.IN_REVIEW.value,
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    async def supersede_active(self, *, user_id: str, job_posting_id: str) -> None:
        """Delete the in-progress review for this candidate and posting, if any.

        Deleted rather than archived, and only ever the in-progress one: a set
        of answers the candidate never submitted is a draft that a fresh fill
        pass replaces, not a record of anything. The status predicate is what
        keeps a submitted review — which *is* a record — out of reach of this.
        """
        await self._session.execute(
            delete(ApplicationReviewModel).where(
                ApplicationReviewModel.user_id == user_id,
                ApplicationReviewModel.job_posting_id == job_posting_id,
                ApplicationReviewModel.status == ReviewStatus.IN_REVIEW.value,
            )
        )
        await self._session.commit()

    async def list_for_user(
        self, user_id: str, *, limit: int = 100
    ) -> list[ApplicationReview]:
        result = await self._session.execute(
            select(ApplicationReviewModel)
            .where(ApplicationReviewModel.user_id == user_id)
            .order_by(ApplicationReviewModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: ApplicationReview) -> ApplicationReviewModel:
        return ApplicationReviewModel(
            id=entity.id,
            user_id=entity.user_id,
            job_posting_id=entity.job_posting_id,
            apply_url=entity.apply_url,
            ats_provider=entity.ats_provider,
            status=entity.status.value,
            answers=_answers_to_json(entity),
            created_at=entity.created_at,
            screenshot_captured=entity.screenshot_captured,
            submitted_at=entity.submitted_at,
            submission_note=entity.submission_note,
        )

    @staticmethod
    def _to_entity(model: ApplicationReviewModel) -> ApplicationReview:
        return ApplicationReview(
            id=model.id,
            user_id=model.user_id,
            job_posting_id=model.job_posting_id,
            apply_url=model.apply_url,
            ats_provider=model.ats_provider,
            answers=_answers_from_json(model.id, model.answers),
            status=ReviewStatus(model.status),
            created_at=model.created_at,
            screenshot_captured=bool(model.screenshot_captured),
            submitted_at=model.submitted_at,
            submission_note=model.submission_note or "",
        )


def _answers_to_json(review: ApplicationReview) -> list[dict[str, Any]]:
    return [
        {
            "key": answer.key,
            "label": answer.label,
            "widget_kind": answer.widget_kind,
            "value": answer.value,
            "slot": answer.slot.value if answer.slot is not None else None,
            "sensitivity": (
                answer.sensitivity.value if answer.sensitivity is not None else None
            ),
            "required": answer.required,
            "origin": answer.origin.value,
            "decided_by_candidate": answer.decided_by_candidate,
            "explanation": answer.explanation,
        }
        for answer in review.answers
    ]


def _answers_from_json(review_id: str, stored: object) -> tuple[ReviewedAnswer, ...]:
    """Rebuild the answers, refusing a row that no longer describes a form.

    Every value goes back through `ReviewedAnswer`, so the invariants that make
    a review meaningful — a declined answer carries no value, an origin is one
    of four — are enforced on the way out of the database as well as on the way
    in.
    """
    if not isinstance(stored, list):
        raise InvalidValueError(
            f"Application review '{review_id}' has a malformed answers column."
        )
    answers: list[ReviewedAnswer] = []
    for item in stored:
        if not isinstance(item, dict):
            raise InvalidValueError(
                f"Application review '{review_id}' has a malformed answer entry."
            )
        answers.append(
            ReviewedAnswer(
                key=str(item.get("key", "")),
                label=str(item.get("label", "")),
                widget_kind=str(item.get("widget_kind", "")),
                value=str(item.get("value") or ""),
                slot=_enum_or_none(ApplicationFieldSlot, item.get("slot")),
                sensitivity=_enum_or_none(FieldSensitivity, item.get("sensitivity")),
                required=bool(item.get("required", False)),
                origin=_origin(review_id, item.get("origin")),
                decided_by_candidate=bool(item.get("decided_by_candidate", False)),
                explanation=str(item.get("explanation") or ""),
            )
        )
    return tuple(answers)


def _origin(review_id: str, value: object) -> AnswerOrigin:
    try:
        return AnswerOrigin(str(value))
    except ValueError as exc:
        raise InvalidValueError(
            f"Application review '{review_id}' names an unknown answer origin "
            f"'{value}'."
        ) from exc


def _enum_or_none(enum_type: Any, value: object) -> Any:
    """Resolve a stored enum member, or None when the column held none.

    An unrecognized *slot* is tolerated as None — it costs a label on a review
    screen. An unrecognized *sensitivity* is not tolerated by the caller
    (`ReviewedAnswer` refuses a non-member), because losing that flag would
    render a legal declaration as an ordinary text box.
    """
    if value is None or value == "":
        return None
    try:
        return enum_type(value)
    except ValueError:
        if enum_type is FieldSensitivity:
            raise
        return None

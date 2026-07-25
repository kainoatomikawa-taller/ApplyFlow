"""SQLAlchemy implementation of the TrackedApplicationRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.

An insert that violates an integrity constraint is translated into one of two
application-layer errors, and the distinction matters because the remedies are
opposites:

- A **unique** violation on (`user_id`, `submission_key`) means this submission
  is already logged, so the correct response is to use the existing row —
  `ApplicationAlreadyLoggedError`, which `SubmittedApplicationLog` catches as
  part of its normal idempotent path.
- A **foreign key** violation means something filed an application against a
  posting or a document snapshot that was never stored, and a tracker entry
  whose documents point nowhere cannot do the one thing the tracker exists for.
  That is `TrackedApplicationReferenceError`, and it is a real failure.

Collapsing both into one error would make a duplicate submit indistinguishable
from a dangling reference, which would either turn a harmless retry into a
500 or turn a corrupt row into a silent success.

Reads order by `applied_at` and then `id`. The tie-break matters: two
applications recorded in the same clock tick (a backfill, or a test) would
otherwise come back in whatever order the planner chose, and "most recent
first" would not be a stable answer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.exceptions import (
    ApplicationAlreadyLoggedError,
    ApplicationError,
    TrackedApplicationReferenceError,
)
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)
from src.domain.value_objects.application_status import ApplicationStatus
from src.infrastructure.persistence.models import TrackedApplicationModel

#: Postgres SQLSTATE for `unique_violation`. Checked rather than matching on
#: the driver's message text, which is not a stable interface.
_UNIQUE_VIOLATION = "23505"


def _is_unique_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == _UNIQUE_VIOLATION


class SqlAlchemyTrackedApplicationRepository(TrackedApplicationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, application: TrackedApplication) -> None:
        self._session.add(self._to_model(application))
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._translate(application, exc) from exc

    async def get_by_id(self, application_id: str) -> TrackedApplication | None:
        model = await self._session.get(TrackedApplicationModel, application_id)
        return self._to_entity(model) if model else None

    async def get_by_submission_key(
        self, *, user_id: str, submission_key: str
    ) -> TrackedApplication | None:
        result = await self._session.execute(
            select(TrackedApplicationModel).where(
                TrackedApplicationModel.user_id == user_id,
                TrackedApplicationModel.submission_key == submission_key,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def update(self, application: TrackedApplication) -> None:
        model = await self._session.get(TrackedApplicationModel, application.id)
        if model is None:
            self._session.add(self._to_model(application))
        else:
            self._apply_entity_to_model(application, model)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._translate(application, exc) from exc

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[TrackedApplication]:
        result = await self._session.execute(
            select(TrackedApplicationModel)
            .where(TrackedApplicationModel.user_id == user_id)
            .order_by(
                TrackedApplicationModel.applied_at.desc(),
                TrackedApplicationModel.id.desc(),
            )
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> list[TrackedApplication]:
        result = await self._session.execute(
            select(TrackedApplicationModel)
            .where(
                TrackedApplicationModel.user_id == user_id,
                TrackedApplicationModel.job_posting_id == job_posting_id,
            )
            .order_by(
                TrackedApplicationModel.applied_at.desc(),
                TrackedApplicationModel.id.desc(),
            )
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    # ---- error translation ---------------------------------------------------

    @staticmethod
    def _translate(
        application: TrackedApplication, exc: IntegrityError
    ) -> ApplicationError:
        """Classify an integrity failure — see the module docstring on why a
        duplicate submission and a dangling reference must not collapse into
        one error."""
        if _is_unique_violation(exc):
            return ApplicationAlreadyLoggedError(
                user_id=application.user_id,
                submission_key=application.submission_key,
            )
        return TrackedApplicationReferenceError(
            job_posting_id=application.job_posting_id,
            resume_document_id=application.resume_document_id,
            cover_letter_document_id=application.cover_letter_document_id,
        )

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: TrackedApplication) -> TrackedApplicationModel:
        return TrackedApplicationModel(
            id=entity.id,
            user_id=entity.user_id,
            job_posting_id=entity.job_posting_id,
            submission_key=entity.submission_key,
            company_name=entity.company_name,
            role_title=entity.role_title,
            applied_at=entity.applied_at,
            status=entity.status.value,
            resume_document_id=entity.resume_document_id,
            cover_letter_document_id=entity.cover_letter_document_id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _apply_entity_to_model(
        entity: TrackedApplication, model: TrackedApplicationModel
    ) -> None:
        # `job_posting_id`, `submission_key`, `applied_at`,
        # `resume_document_id`, and `created_at` are deliberately not written
        # back. They state what was sent and when, which is not something a
        # lifecycle update revises — the domain has no operation that changes
        # them either.
        model.company_name = entity.company_name
        model.role_title = entity.role_title
        model.status = entity.status.value
        model.cover_letter_document_id = entity.cover_letter_document_id
        model.updated_at = entity.updated_at

    @staticmethod
    def _to_entity(model: TrackedApplicationModel) -> TrackedApplication:
        return TrackedApplication(
            id=model.id,
            user_id=model.user_id,
            job_posting_id=model.job_posting_id,
            submission_key=model.submission_key,
            company_name=model.company_name,
            role_title=model.role_title,
            applied_at=model.applied_at,
            status=ApplicationStatus(model.status),
            resume_document_id=model.resume_document_id,
            cover_letter_document_id=model.cover_letter_document_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

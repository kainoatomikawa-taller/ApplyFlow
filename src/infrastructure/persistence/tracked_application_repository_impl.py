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

Status history is written with the row, never separately
-------------------------------------------------------
Every read loads an application's `application_status_events` and rebuilds its
`status_history`; every write commits the row and its new history entries in one
transaction. Both halves matter for the same reason: the entity's invariant is
that its current status is the one its history ends at, so a read that skipped
the history would hand back an application the entity would then "helpfully"
seed with a one-entry history that never happened, and a write that committed
them apart could leave the two disagreeing permanently.

The history is append-only, so `update` inserts the entries whose `sequence` is
beyond what is already stored and touches nothing else. It never rewrites or
deletes an entry — not as an optimization, but because a status change is a
thing that happened, and the primary key on
(`tracked_application_id`, `sequence`) is what makes appending one twice a
constraint violation rather than a duplicated step.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

from sqlalchemy import func, select
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
from src.domain.value_objects.application_status_change import ApplicationStatusChange
from src.domain.value_objects.canonical_job_identity import CanonicalJobIdentity
from src.infrastructure.persistence.models import (
    ApplicationStatusEventModel,
    TrackedApplicationModel,
)

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
        # The seeded initial entry is part of the record being created, so it
        # goes in the same transaction: an application with no history would be
        # read back as one whose history had to be invented.
        #
        # Flushed before the history rows are added, and this is load-bearing:
        # these two models are deliberately not joined by a `relationship()`,
        # and a bare foreign key tells SQLAlchemy's unit of work nothing about
        # save order — so without the flush the child insert can be emitted
        # first and violate the constraint. Still one transaction; only the
        # statement order inside it is being fixed.
        await self._flush_new(application)
        for event in self._to_event_models(application, from_sequence=0):
            self._session.add(event)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._translate(application, exc) from exc

    async def _flush_new(self, application: TrackedApplication) -> None:
        """Emit the pending application row so its history can reference it.

        A flush can raise the same integrity failures a commit can — a
        duplicate submission key, a dangling document reference — so it is
        translated here rather than surfacing as a raw `IntegrityError` from
        halfway through a write.
        """
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._translate(application, exc) from exc

    async def get_by_id(self, application_id: str) -> TrackedApplication | None:
        model = await self._session.get(TrackedApplicationModel, application_id)
        if model is None:
            return None
        return await self._to_entity_with_history(model)

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
        if model is None:
            return None
        return await self._to_entity_with_history(model)

    async def update(self, application: TrackedApplication) -> None:
        model = await self._session.get(TrackedApplicationModel, application.id)
        if model is None:
            self._session.add(self._to_model(application))
            # Same ordering requirement as `add` — see `_flush_new`.
            await self._flush_new(application)
            stored_events = 0
        else:
            self._apply_entity_to_model(application, model)
            stored_events = await self._stored_event_count(application.id)
        # Append only what is not stored yet. The history is append-only, so
        # everything below `stored_events` is already the same row it was; the
        # primary key would refuse a second copy of it anyway.
        for event in self._to_event_models(application, from_sequence=stored_events):
            self._session.add(event)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._translate(application, exc) from exc

    async def list_by_user_id(
        self,
        user_id: str,
        *,
        statuses: Collection[ApplicationStatus] | None = None,
        limit: int = 100,
    ) -> list[TrackedApplication]:
        query = select(TrackedApplicationModel).where(
            TrackedApplicationModel.user_id == user_id
        )
        if statuses is not None:
            # An empty collection filters everything out, which is the honest
            # reading of "none of these statuses" — `IN ()` rather than "no
            # filter at all". See the repository interface.
            query = query.where(
                TrackedApplicationModel.status.in_(
                    [status.value for status in statuses]
                )
            )
        result = await self._session.execute(
            query.order_by(
                TrackedApplicationModel.applied_at.desc(),
                TrackedApplicationModel.id.desc(),
            ).limit(limit)
        )
        return await self._to_entities_with_history(result.scalars().all())

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
        return await self._to_entities_with_history(result.scalars().all())

    async def list_applied_identities(
        self, *, user_id: str
    ) -> list[CanonicalJobIdentity]:
        """Every distinct role this candidate has applied to.

        Selects the three snapshot columns rather than whole rows: the caller
        needs a complete set (see the interface on why a limit would be
        wrong), and three short strings per application keeps that cheap. The
        SQL `DISTINCT` collapses byte-identical rows only — `CanonicalJobIdentity`
        does the real collapsing, since "Acme  Corp" and "acme corp" are one
        role to the domain and two to Postgres. Building the value objects
        through `of` is what keeps that rule in the domain and out of here.
        """
        result = await self._session.execute(
            select(
                TrackedApplicationModel.company_name,
                TrackedApplicationModel.role_title,
                TrackedApplicationModel.job_location,
            )
            .where(TrackedApplicationModel.user_id == user_id)
            .distinct()
        )
        return [
            CanonicalJobIdentity.of(
                company=company_name, title=role_title, location=job_location
            )
            for company_name, role_title, job_location in result.all()
        ]

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

    # ---- status history ------------------------------------------------------

    async def _stored_event_count(self, application_id: str) -> int:
        """How many history entries are already persisted for this application.

        A count rather than `max(sequence) + 1` because `sequence` is gap-free
        by construction, and a count says plainly what the caller wants to
        know: how far the stored history already goes.
        """
        result = await self._session.execute(
            select(func.count())
            .select_from(ApplicationStatusEventModel)
            .where(ApplicationStatusEventModel.tracked_application_id == application_id)
        )
        return int(result.scalar_one())

    @staticmethod
    def _to_event_models(
        entity: TrackedApplication, *, from_sequence: int
    ) -> list[ApplicationStatusEventModel]:
        """Rows for the history entries at or after `from_sequence`."""
        return [
            ApplicationStatusEventModel(
                tracked_application_id=entity.id,
                sequence=sequence,
                status=change.status.value,
                previous_status=(
                    change.previous_status.value
                    if change.previous_status is not None
                    else None
                ),
                changed_at=change.changed_at,
                note=change.note,
            )
            for sequence, change in enumerate(entity.status_history)
            if sequence >= from_sequence
        ]

    async def _load_history(self, application_id: str) -> list[ApplicationStatusChange]:
        """This application's history, oldest first.

        Ordered by `sequence`, not `changed_at`: two changes recorded in the
        same clock tick have a definite order only in the sequence, and the
        entity validates the chain it is handed — so an order that put them the
        other way round would be rejected rather than quietly accepted.
        """
        result = await self._session.execute(
            select(ApplicationStatusEventModel)
            .where(ApplicationStatusEventModel.tracked_application_id == application_id)
            .order_by(ApplicationStatusEventModel.sequence.asc())
        )
        return [
            ApplicationStatusChange(
                status=ApplicationStatus(model.status),
                changed_at=model.changed_at,
                previous_status=(
                    ApplicationStatus(model.previous_status)
                    if model.previous_status is not None
                    else None
                ),
                note=model.note or "",
            )
            for model in result.scalars().all()
        ]

    async def _to_entity_with_history(
        self, model: TrackedApplicationModel
    ) -> TrackedApplication:
        return self._to_entity(model, history=await self._load_history(model.id))

    async def _to_entities_with_history(
        self, models: Iterable[TrackedApplicationModel]
    ) -> list[TrackedApplication]:
        """Rebuild whole aggregates for a list of rows.

        One history query per application. A single query over all of them
        would be fewer round trips, and is the change to make if a candidate's
        feed ever grows enough for it to matter — but `limit` caps this at 100
        by default, and correctness here is worth more than the round trips: a
        list of applications missing their histories is a list the entity would
        seed with histories that never happened.
        """
        return [await self._to_entity_with_history(model) for model in models]

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
            job_location=entity.job_location,
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
        model.job_location = entity.job_location
        model.status = entity.status.value
        model.cover_letter_document_id = entity.cover_letter_document_id
        model.updated_at = entity.updated_at

    @staticmethod
    def _to_entity(
        model: TrackedApplicationModel,
        *,
        history: list[ApplicationStatusChange] | None = None,
    ) -> TrackedApplication:
        """Rebuild the aggregate.

        `history` is passed rather than defaulted to empty by accident: an empty
        list is a legitimate value only for a row written before this table
        existed, and the entity seeds that case itself (see
        `TrackedApplication._validate_history`). Every caller here loads the
        history first.
        """
        return TrackedApplication(
            id=model.id,
            user_id=model.user_id,
            job_posting_id=model.job_posting_id,
            submission_key=model.submission_key,
            company_name=model.company_name,
            role_title=model.role_title,
            job_location=model.job_location,
            applied_at=model.applied_at,
            status=ApplicationStatus(model.status),
            resume_document_id=model.resume_document_id,
            cover_letter_document_id=model.cover_letter_document_id,
            status_history=list(history) if history else [],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

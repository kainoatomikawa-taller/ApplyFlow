"""SQLAlchemy implementation of the ApplicationDocumentRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.

Two things worth knowing about this class:

`_to_entity` verifies every row against its stored digest before returning
it. That check is the domain's (`ApplicationDocument.ensure_content_matches`)
— this class only supplies the recorded digest to compare against. A row
whose content changed after it was written raises rather than being handed
back as the document that was sent.

A duplicate `(user_id, job_posting_id, document_kind, version)` insert is
translated into `DocumentVersionConflictError` rather than surfacing as a
driver-level integrity error. That collision means two concurrent
generations both read the same version count, so one of them numbered
itself wrong; the constraint is what turns a silently duplicated "version 2"
into a failure the caller can retry.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.exceptions import DocumentVersionConflictError
from src.domain.entities.application_document import ApplicationDocument
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.infrastructure.persistence.models import ApplicationDocumentModel


class SqlAlchemyApplicationDocumentRepository(ApplicationDocumentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: ApplicationDocument) -> None:
        self._session.add(self._to_model(document))
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DocumentVersionConflictError(
                document_kind=document.document_kind.value,
                job_posting_id=document.job_posting_id,
                version=document.version,
            ) from exc

    async def get_by_id(self, document_id: str) -> ApplicationDocument | None:
        model = await self._session.get(ApplicationDocumentModel, document_id)
        return self._to_entity(model) if model else None

    async def count_versions(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ApplicationDocumentModel)
            .where(
                ApplicationDocumentModel.user_id == user_id,
                ApplicationDocumentModel.job_posting_id == job_posting_id,
                ApplicationDocumentModel.document_kind == document_kind.value,
            )
        )
        return int(result.scalar_one())

    async def get_latest(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> ApplicationDocument | None:
        result = await self._session.execute(
            select(ApplicationDocumentModel)
            .where(
                ApplicationDocumentModel.user_id == user_id,
                ApplicationDocumentModel.job_posting_id == job_posting_id,
                ApplicationDocumentModel.document_kind == document_kind.value,
            )
            # Ordered by version, not created_at: the version number is what
            # defines succession here, and two snapshots written in the same
            # clock tick must still order deterministically.
            .order_by(ApplicationDocumentModel.version.desc())
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    async def list_for_job(
        self, *, user_id: str, job_posting_id: str, limit: int = 100
    ) -> list[ApplicationDocument]:
        result = await self._session.execute(
            select(ApplicationDocumentModel)
            .where(
                ApplicationDocumentModel.user_id == user_id,
                ApplicationDocumentModel.job_posting_id == job_posting_id,
            )
            .order_by(
                ApplicationDocumentModel.created_at.desc(),
                ApplicationDocumentModel.version.desc(),
            )
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[ApplicationDocument]:
        result = await self._session.execute(
            select(ApplicationDocumentModel)
            .where(ApplicationDocumentModel.user_id == user_id)
            .order_by(
                ApplicationDocumentModel.created_at.desc(),
                ApplicationDocumentModel.version.desc(),
            )
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _to_model(entity: ApplicationDocument) -> ApplicationDocumentModel:
        return ApplicationDocumentModel(
            id=entity.id,
            user_id=entity.user_id,
            job_posting_id=entity.job_posting_id,
            document_kind=entity.document_kind.value,
            content=entity.content,
            content_sha256=entity.content_sha256,
            version=entity.version,
            backing_sources=[source.value for source in entity.backing_sources],
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_entity(model: ApplicationDocumentModel) -> ApplicationDocument:
        document = ApplicationDocument(
            id=model.id,
            user_id=model.user_id,
            job_posting_id=model.job_posting_id,
            document_kind=GeneratedDocumentKind(model.document_kind),
            content=model.content,
            version=model.version,
            backing_sources=tuple(
                ProvenanceSource(source) for source in model.backing_sources
            ),
            created_at=model.created_at,
        )
        document.ensure_content_matches(model.content_sha256)
        return document

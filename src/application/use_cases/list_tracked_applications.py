"""ListTrackedApplications use case — the tracker's feed: every application
the candidate has sent, most recently applied first, each with the exact
documents that went out with it.

Why it resolves the document references
---------------------------------------
The row stores ids (see `TrackedApplication` for why it must). This use case
follows them, so one request answers "what did I send to whom, and when" —
the question the tracker screen exists to answer. Leaving the client to
resolve them would be two extra round trips per row.

Resolved by id, and *not* by "the latest document for this job"
---------------------------------------------------------------
The distinction is the whole ticket. `get_latest` answers "the newest resume
produced for this job", which is the right question at send time and the
wrong one afterwards: a candidate who revises their resume and applies
somewhere else has a newer version, and reading it here would restate history
— the tracker would show a document the employer never received. So this
follows the ids frozen onto the row at send time, whatever has been produced
since.

A reference that no longer resolves is reported, not raised
-----------------------------------------------------------
The write path refuses to create one (`TrackedApplicationReferenceError`) and
the schema's `ON DELETE RESTRICT` refuses to break one, so a `None` here means
something has gone wrong beneath both. It still comes back as a row with an
empty document reference rather than an exception, because the alternative is
one unreadable row hiding the candidate's entire application history. What
they sent is missing; *that they applied* is not, and that is the part the
suppression rule depends on.

Documents are read once per distinct id
---------------------------------------
Two applications to the same posting reference the same snapshots, and a
candidate who re-applies to a role has several. Caching within the call keeps
a thirty-row feed from re-reading the same document thirty times; it is
per-call, so nothing here can serve a stale snapshot.
"""

from __future__ import annotations

import logging

from src.application.dtos.tracked_application_dtos import (
    ListTrackedApplicationsInput,
    TrackedApplicationOutput,
)
from src.application.mappers.tracked_application_mapper import (
    TrackedApplicationMapper,
)
from src.domain.entities.application_document import ApplicationDocument
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)

logger = logging.getLogger(__name__)


class ListTrackedApplications:
    def __init__(
        self,
        tracked_application_repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
    ) -> None:
        self._applications = tracked_application_repository
        self._documents = document_repository

    async def execute(
        self, dto: ListTrackedApplicationsInput
    ) -> list[TrackedApplicationOutput]:
        applications = await self._applications.list_by_user_id(
            dto.user_id, limit=dto.limit
        )

        resolved: dict[str, ApplicationDocument | None] = {}

        async def snapshot(document_id: str | None) -> ApplicationDocument | None:
            if document_id is None:
                return None
            if document_id not in resolved:
                resolved[document_id] = await self._documents.get_by_id(document_id)
            return resolved[document_id]

        outputs: list[TrackedApplicationOutput] = []
        for application in applications:
            resume = await snapshot(application.resume_document_id)
            if resume is None:
                # Ids only: the row is not sensitive, the document's text is.
                logger.error(
                    "tracked application=%s references resume document=%s, "
                    "which no longer resolves; reporting the application "
                    "without it",
                    application.id,
                    application.resume_document_id,
                )
            cover_letter = await snapshot(application.cover_letter_document_id)
            outputs.append(
                TrackedApplicationMapper.to_output(
                    application, resume=resume, cover_letter=cover_letter
                )
            )
        return outputs

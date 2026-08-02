"""SentDocumentResolver — turns a tracked application's document references
into the snapshots they point at.

Why a shared service rather than a step inside each read: three use cases read
tracked applications (`ListTrackedApplications`, `GetTrackedApplication`,
`ListApplicationsForJob`), and a use case must not depend on another use case
(see `src/application/CLAUDE.md`). Written three times, "follow the two ids,
tolerate a reference that does not resolve, do not fetch the same document
twice" is exactly the logic that drifts — and the way it drifts is that one of
the three quietly starts answering with a document nobody sent.

It resolves by id, and it cannot do anything else
-------------------------------------------------
There is no `get_latest` call here and no way to make one: this service holds
the document repository only to read ids off it. That is the whole point.
`get_latest(user, job, kind)` is the right question at *send* time — it is what
`SubmittedApplicationLog` asks — and the wrong one afterwards, because a
candidate who revises their resume has a newer version stored against the same
job. Reading it here would make the tracker restate history, showing a document
the employer never received with nothing to indicate anything had changed.

A reference that does not resolve is reported, not raised
---------------------------------------------------------
The write path refuses to create one (`TrackedApplicationReferenceError`) and
the schema's `ON DELETE RESTRICT` refuses to break one, so a `None` here means
something has gone wrong beneath both. It still comes back as an absent
document rather than an exception, because the alternative is one unreadable
row hiding the candidate's entire application history. What was sent is
missing; *that they applied* is not, and that is the fact the matching layer's
suppression depends on.

Read once per distinct id
-------------------------
Two applications to the same posting reference the same snapshots, and a
candidate who re-applies to a role has several. The cache is per-resolver, and
a resolver is built per request, so nothing here can serve a stale snapshot
across requests.
"""

from __future__ import annotations

import logging

from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)

logger = logging.getLogger(__name__)


class SentDocumentResolver:
    """Resolves the documents a tracked application was sent with."""

    def __init__(self, document_repository: ApplicationDocumentRepository) -> None:
        self._documents = document_repository
        self._resolved: dict[str, ApplicationDocument | None] = {}

    async def resolve(
        self, application: TrackedApplication
    ) -> tuple[ApplicationDocument | None, ApplicationDocument | None]:
        """Return `(resume, cover_letter)` for one application.

        Either may be None: the cover letter because plenty of forms never ask
        for one, the resume only if its reference no longer resolves — which is
        logged at ERROR, because it should not be possible.
        """
        resume = await self._snapshot(application.resume_document_id)
        if resume is None:
            # Ids only: the row is not sensitive, the document's text is.
            logger.error(
                "tracked application=%s references resume document=%s, which no "
                "longer resolves; reporting the application without it",
                application.id,
                application.resume_document_id,
            )
        cover_letter = await self._snapshot(application.cover_letter_document_id)
        return resume, cover_letter

    async def _snapshot(self, document_id: str | None) -> ApplicationDocument | None:
        if document_id is None:
            return None
        if document_id not in self._resolved:
            self._resolved[document_id] = await self._documents.get_by_id(document_id)
        return self._resolved[document_id]

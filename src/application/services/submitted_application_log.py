"""SubmittedApplicationLog — the one place a sent application becomes a
tracked record.

Why a shared service rather than a step inside the submit use case: a use case
must not depend on another use case (see `src/application/CLAUDE.md`), and
"find the documents that were sent, copy the role and company, insert once and
only once" is precisely the logic that drifts when it is written twice. The same
reasoning already put `ApplicationDocumentArchive` here — and this service is
its counterpart at the other end of the flow: that one stores what was
produced, this one records that it went out.

It reuses, it never regenerates
-------------------------------
The documents are read through `ApplicationDocumentRepository.get_latest`,
which is the documented answer to "the resume/letter this application went out
with". Nothing here can generate a document: this service has no generator, no
LLM port, and no way to acquire one. That is deliberate — regenerating at log
time would read today's profile through today's model and could record a
document the employer never received, which is the entire failure
`ApplicationDocument` exists to prevent. A missing resume is therefore an
error, never a prompt to produce one.

Role, company, and the date are not parameters a caller can get wrong
--------------------------------------------------------------------
The role and company come from the posting, copied by
`TrackedApplication.record_sent`; the caller passes the posting id, not a label.
The date is the submission time the caller observed. So the three "captured
automatically" fields are derived from records that already exist rather than
re-supplied at the call site, where they could disagree with them.

Idempotent, and reliable in the way that actually matters
--------------------------------------------------------
Logging is keyed on `submission_key` — the id of the submission event, in
practice the submitted review's. Read first, then insert; if the insert loses a
race, the unique constraint refuses it and the loser returns the row that won
(`ApplicationAlreadyLoggedError`). A double-clicked submit button, a client
retry, and a repair pass over a submission that failed to log all converge on
one record.

That is what makes the caller's error handling safe: a submission whose logging
failed can simply be logged again with the same key. Nothing here should be
allowed to fail a submission that already happened — the application is with
the employer whether or not the tracker heard about it — so callers log the
failure and carry on, and the retry-safety above is what makes that recoverable
rather than a silent hole.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.application.exceptions import ApplicationAlreadyLoggedError
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.tracked_application import TrackedApplication
from src.domain.exceptions import (
    JobPostingNotFoundError,
    NoStoredApplicationDocumentError,
)
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind

logger = logging.getLogger(__name__)


class SubmittedApplicationLog:
    """Records a submitted application, exactly once, against the documents
    that were actually sent."""

    def __init__(
        self,
        tracked_application_repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
        job_posting_repository: JobPostingRepository,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._applications = tracked_application_repository
        self._documents = document_repository
        self._postings = job_posting_repository
        self._id_generator = id_generator

    async def record(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        submission_key: str,
        applied_at: datetime,
    ) -> TrackedApplication:
        """Log this submission as a tracked application and return the record.

        Returns the existing record unchanged if this submission was already
        logged, so calling it twice is a no-op rather than a duplicate.

        Raises:
            JobPostingNotFoundError: if the posting does not exist — role and
                company are copied from it, so there is nothing to record
                against.
            NoStoredApplicationDocumentError: if no resume snapshot was ever
                stored for this job. Deliberately an error: the alternative
                would be logging an application whose resume reference is
                empty, or generating one now and calling it what was sent.
        """
        already_logged = await self._applications.get_by_submission_key(
            user_id=user_id, submission_key=submission_key
        )
        if already_logged is not None:
            logger.info(
                "submission=%s is already logged as application=%s; not "
                "logging it twice",
                submission_key,
                already_logged.id,
            )
            return already_logged

        posting = await self._postings.get_by_id(job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(job_posting_id)

        resume = await self._documents.get_latest(
            user_id=user_id,
            job_posting_id=job_posting_id,
            document_kind=GeneratedDocumentKind.TAILORED_RESUME,
        )
        if resume is None:
            raise NoStoredApplicationDocumentError(
                job_posting_id, GeneratedDocumentKind.TAILORED_RESUME.value
            )
        # Optional by design: plenty of forms never ask for one, and a
        # fabricated reference would be worse than an honest absence.
        cover_letter = await self._documents.get_latest(
            user_id=user_id,
            job_posting_id=job_posting_id,
            document_kind=GeneratedDocumentKind.COVER_LETTER,
        )

        # `record_sent` re-checks that each snapshot is the right kind and
        # belongs to this candidate and posting — see `TrackedApplication`.
        application = TrackedApplication.record_sent(
            application_id=self._id_generator.new_id(),
            user_id=user_id,
            job_posting=posting,
            submission_key=submission_key,
            resume_document=resume,
            cover_letter_document=cover_letter,
            applied_at=applied_at,
        )
        try:
            await self._applications.add(application)
        except ApplicationAlreadyLoggedError:
            # Lost the race against a concurrent log of the same submission —
            # the other request's row is the one record of this application.
            winner = await self._applications.get_by_submission_key(
                user_id=user_id, submission_key=submission_key
            )
            if winner is None:
                # The constraint fired but nothing is readable: not a race, so
                # do not paper over it.
                raise
            logger.info(
                "submission=%s was logged concurrently as application=%s",
                submission_key,
                winner.id,
            )
            return winner

        # Ids only — the documents' content is sensitive (see
        # `ApplicationDocument`), and the role/company are already on the row.
        logger.info(
            "logged application=%s for user=%s job=%s from submission=%s "
            "(resume=%s cover_letter=%s)",
            application.id,
            user_id,
            job_posting_id,
            submission_key,
            application.resume_document_id,
            application.cover_letter_document_id or "none",
        )
        return application

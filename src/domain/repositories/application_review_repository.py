"""ApplicationReviewRepository — the abstraction (WHAT, not HOW).

This interface lives in the domain layer. The concrete implementation lives in
infrastructure/. The domain and application layers depend only on this
abstraction, never on a specific database.

Why a review is stored
----------------------
Because reviewing a filled application is not something anyone does in one
sitting. The candidate reads the answers, goes to check what visa type is on
their permit, comes back, changes two fields, and submits an hour later. A
review that lived only in a response body would lose every decision they had
already made — including the sensitive ones they had confirmed, which are
exactly the ones nobody should have to make twice.

One open review per posting
---------------------------
`get_active_for_job` answers "what is this candidate in the middle of for this
job". At most one review is open at a time, enforced in the database as well:
two would mean two sets of answers for one application and no way to say which
the candidate meant. Re-running a fill pass supersedes the open one rather than
adding a second (see `add`).

Submitted reviews are history, not clutter
------------------------------------------
They stay, and `list_for_user` returns them, because a submitted review is the
record of what the candidate sent — the tracker (Epic 06) reads it, and so does
anyone asking "what did I actually tell this employer?". There is no `delete`
for the same reason `ApplicationDocumentRepository` has none: erasing a
candidate's data is a deliberate, user-scoped purge (Epic 07), not an ambient
capability any caller can reach for.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.entities.application_review import ApplicationReview


class ApplicationReviewRepository(ABC):
    """Persistence contract for candidate reviews of filled applications."""

    @abstractmethod
    async def add(self, review: ApplicationReview) -> None:
        """Persist a newly opened review.

        The caller supersedes any review already open for the same
        (candidate, posting) first — see `supersede_active`.
        """

    @abstractmethod
    async def update(self, review: ApplicationReview) -> None:
        """Persist a changed review — an edited answer, or a submission.

        Raises `ApplicationReviewNotFoundError` if it does not exist: an
        update that silently inserted would resurrect a review the candidate
        had already finished with.
        """

    @abstractmethod
    async def get_by_id(self, review_id: str) -> ApplicationReview | None:
        """Return one review by id, or None if it does not exist."""

    @abstractmethod
    async def get_active_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> ApplicationReview | None:
        """Return the review still open for this candidate and posting, or
        None. At most one can exist."""

    @abstractmethod
    async def supersede_active(self, *, user_id: str, job_posting_id: str) -> None:
        """Drop the review still open for this candidate and posting, if any.

        Called before opening a fresh one, so a new fill pass replaces the
        answers a candidate had not submitted rather than competing with them.
        Only ever affects a review still in progress: a submitted one is a
        record of what was sent and is never touched by this.
        """

    @abstractmethod
    async def list_for_user(
        self, user_id: str, *, limit: int = 100
    ) -> list[ApplicationReview]:
        """Return this candidate's reviews, open and submitted, newest first."""

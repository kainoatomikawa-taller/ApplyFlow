"""ReviewStatus — the lifecycle of one application review.

    IN_REVIEW ──► SUBMITTED_BY_USER

Two states, one transition, and the name of the second one is the point:
nothing in ApplyFlow can reach it on its own. It is recorded when the
candidate says they are sending the application, and the record is what makes
"the user is the submitter" checkable after the fact rather than a claim in a
docstring.

`SUBMITTED_BY_USER` is terminal, and that is deliberate rather than
incidental. The answers a candidate approved are what went to an employer; a
state that allowed further editing would let the stored record drift away from
what was actually sent — the same reason `ApplicationDocument` snapshots are
write-once. Applying again to the same posting opens a new review; it does not
reopen this one.

There is no `ABANDONED`. A review nobody submits costs nothing and blocks
nothing: opening a fresh one supersedes it (see
`ApplicationReviewRepository.get_active_for_job`). That is different from a
hand-off, which sits in the candidate's queue asking to be cleared and
therefore needs a way to say "I dealt with this myself".
"""

from __future__ import annotations

from enum import StrEnum

from src.domain.exceptions import BusinessRuleViolationError


class ReviewStatus(StrEnum):
    """The state of a candidate's review of a filled application."""

    #: The candidate can still edit every answer. Nothing has been sent.
    IN_REVIEW = "in_review"

    #: The candidate submitted the application. Reachable only through
    #: `ApplicationReview.record_submission`, which no scheduled task, model,
    #: or background flow calls.
    SUBMITTED_BY_USER = "submitted_by_user"

    def can_transition_to(self, target: ReviewStatus) -> bool:
        return target in _ALLOWED_TRANSITIONS[self]

    def transition_to(self, target: ReviewStatus) -> ReviewStatus:
        """Return the target status if the transition is valid.

        Raises:
            BusinessRuleViolationError: if it is not — which is what stops a
                second submission from rewriting the record of the first, on a
                double-clicked button or a second open tab.
        """
        if not self.can_transition_to(target):
            raise BusinessRuleViolationError(
                f"Cannot move this application review from '{self.value}' to "
                f"'{target.value}'."
            )
        return target

    @property
    def is_open(self) -> bool:
        """Whether the candidate can still change their answers."""
        return self is ReviewStatus.IN_REVIEW

    @property
    def is_terminal(self) -> bool:
        return not _ALLOWED_TRANSITIONS[self]


_ALLOWED_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.IN_REVIEW: {ReviewStatus.SUBMITTED_BY_USER},
    ReviewStatus.SUBMITTED_BY_USER: set(),
}

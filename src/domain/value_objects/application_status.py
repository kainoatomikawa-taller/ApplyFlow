"""ApplicationStatus value object.

Models the lifecycle of a job application as a finite state machine.
Contains the business rules for which transitions are allowed.
"""

from __future__ import annotations

from enum import StrEnum

from src.domain.exceptions import BusinessRuleViolationError


class ApplicationStatus(StrEnum):
    """The status of a job application."""

    DRAFT = "draft"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

    def can_transition_to(self, target: ApplicationStatus) -> bool:
        """Return whether a transition to ``target`` is permitted."""
        return target in _ALLOWED_TRANSITIONS[self]

    def transition_to(self, target: ApplicationStatus) -> ApplicationStatus:
        """Return the target status if the transition is valid.

        Raises:
            BusinessRuleViolationError: if the transition is not allowed.
        """
        if not self.can_transition_to(target):
            raise BusinessRuleViolationError(
                f"Cannot move application from '{self.value}' to '{target.value}'."
            )
        return target

    @property
    def is_terminal(self) -> bool:
        """Whether no further transitions are possible."""
        return not _ALLOWED_TRANSITIONS[self]


_ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: {
        ApplicationStatus.APPLIED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.APPLIED: {
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.INTERVIEWING: {
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.OFFER: {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.WITHDRAWN: set(),
}

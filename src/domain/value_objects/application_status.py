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
    def allowed_transitions(self) -> tuple[ApplicationStatus, ...]:
        """Every status this one may move to, in lifecycle order.

        Exposed so that callers which have to *offer* the choice — a tracker
        screen's status control, an API response listing what a candidate may
        do next — read the rules from here instead of restating them. A UI
        that enumerated its own would eventually offer a transition
        `transition_to` refuses, and the candidate would meet the refusal
        only after making the choice.

        Ordered by `_STATUS_ORDER` rather than by set iteration, so the same
        status always yields the same sequence: a control whose options
        reshuffle between renders is a control people misclick.
        """
        return tuple(
            sorted(_ALLOWED_TRANSITIONS[self], key=lambda s: _STATUS_ORDER.index(s))
        )

    @property
    def is_terminal(self) -> bool:
        """Whether no further transitions are possible."""
        return not _ALLOWED_TRANSITIONS[self]


#: Lifecycle order, used only to give `allowed_transitions` a stable
#: sequence. Not a ranking — `WITHDRAWN` is not "worse" than `REJECTED` — just
#: the order these read naturally in when offered as choices.
_STATUS_ORDER: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.DRAFT,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
)

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

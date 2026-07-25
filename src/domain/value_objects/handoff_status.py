"""HandoffStatus — the lifecycle of one hand-off to the candidate.

Three states, and the reason there are exactly three is that a hand-off has
to answer two different questions at once: "is ApplyFlow waiting on the
person?" and "how did that end?".

    AWAITING_USER ──► RESUMED     (the person did the step; automation may go on)
                  └─► ABANDONED   (the person is finishing this one themselves)

`AWAITING_USER` is the only open state, and it is the one that has to be
unambiguous: while a hand-off sits there, nothing downstream may fill this
portal's form. Both exits are terminal, because neither is a pause — the
person has answered, and a later boundary on the same portal is a new
hand-off with its own evidence, not a reopening of this one. That keeps the
record honest about *when* each boundary was hit instead of collapsing a
sequence of them into one mutable row.

`ABANDONED` is a legitimate ending, not a failure. "I will finish this
application myself" is frequently the right answer to an account wall, and a
lifecycle with no way to say it would leave candidates with a list of
hand-offs they can never clear.
"""

from __future__ import annotations

from enum import StrEnum

from src.domain.exceptions import BusinessRuleViolationError


class HandoffStatus(StrEnum):
    """The state of a hand-off to the candidate."""

    #: ApplyFlow has stopped and is waiting on the person. Automation on this
    #: portal is paused for as long as a hand-off is in this state.
    AWAITING_USER = "awaiting_user"

    #: The person did the human-only step and asked ApplyFlow to continue.
    RESUMED = "resumed"

    #: The person took the application over; ApplyFlow is not continuing it.
    ABANDONED = "abandoned"

    def can_transition_to(self, target: HandoffStatus) -> bool:
        """Return whether a transition to ``target`` is permitted."""
        return target in _ALLOWED_TRANSITIONS[self]

    def transition_to(self, target: HandoffStatus) -> HandoffStatus:
        """Return the target status if the transition is valid.

        Raises:
            BusinessRuleViolationError: if the transition is not allowed —
                which is what stops a hand-off already resolved from being
                resolved a second time, by a double-clicked button or by two
                tabs open on the same panel.
        """
        if not self.can_transition_to(target):
            raise BusinessRuleViolationError(
                f"Cannot move this hand-off from '{self.value}' to "
                f"'{target.value}'; it was already resolved as '{self.value}'."
            )
        return target

    @property
    def is_open(self) -> bool:
        """Whether ApplyFlow is still waiting on the candidate."""
        return self is HandoffStatus.AWAITING_USER

    @property
    def is_terminal(self) -> bool:
        return not _ALLOWED_TRANSITIONS[self]


_ALLOWED_TRANSITIONS: dict[HandoffStatus, set[HandoffStatus]] = {
    HandoffStatus.AWAITING_USER: {
        HandoffStatus.RESUMED,
        HandoffStatus.ABANDONED,
    },
    HandoffStatus.RESUMED: set(),
    HandoffStatus.ABANDONED: set(),
}

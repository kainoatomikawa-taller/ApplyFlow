"""ApplicationStatusChange value object — one entry in an application's
status history.

Why the history is a list of these rather than a "previous status" column
------------------------------------------------------------------------
A single `previous_status` field remembers exactly one step back, which is the
one thing a tracker cannot work with. The questions this history exists to
answer are all about the *shape* of a search over time: how long an application
sat at `applied` before anyone replied, which applications reached
`interviewing` and how fast, whether an offer followed a first-round screen or
three. None of those are answerable from the current status plus one hop.

Why each entry names the status it came *from*
---------------------------------------------
`previous_status` is redundant with the preceding entry's `status` — and that is
the point. It is what makes one row self-describing: a follow-up view reading a
single change can say "rejected after interviewing" without fetching its
neighbour, and a history whose entries disagree with their neighbours is
detectably corrupt rather than silently plausible. `TrackedApplication` checks
that agreement when it loads (see `_validate_history`).

`previous_status` is None for exactly one entry: the first, recorded when the
application was sent. Nothing preceded it.

Immutable, like every value object here
---------------------------------------
A status change is something that happened. Editing one would be rewriting
history rather than recording it, so this is frozen and `TrackedApplication`
only ever appends. That is also why there is no id: an entry is identified by
the application it belongs to and its position in that application's history,
not by an identity of its own.

Not sensitive. A status, a timestamp, and a short note about a job search
carry nothing that `WorkAuthorization` or `AnswerMemory` do — but see `note`
for the one caveat that keeps it that way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.application_status import ApplicationStatus


@dataclass(frozen=True)
class ApplicationStatusChange:
    """One recorded move of an application from one status to another."""

    #: Long enough for "recruiter screen booked for the 14th", short enough
    #: that the column is not an unbounded text sink. Matches
    #: `PortalHandoff.MAX_NOTE_LENGTH` so the two note fields cannot disagree
    #: about what an over-long note is.
    MAX_NOTE_LENGTH: ClassVar[int] = 1000

    #: The status the application moved *to*. Never `DRAFT`: a tracked
    #: application exists because it was sent (see `TrackedApplication`), so
    #: there is no history entry that could legitimately name it.
    status: ApplicationStatus
    #: When the move happened. Timezone-aware for the same reason
    #: `applied_at` is: a history ordered across a DST change or a deploy in
    #: another region still has to order correctly.
    changed_at: datetime
    #: Where it moved *from* — None only for the entry recorded at send time.
    previous_status: ApplicationStatus | None = None
    #: Why, in the candidate's own words. Optional, and free text: "referred
    #: by Dana", "third round is a system design interview". Empty means they
    #: did not say, which is not the same as a note saying nothing.
    #:
    #: A candidate can type anything here, so treat it as they would any text
    #: they wrote: fine to show them, fine to store, not something to
    #: interpret. It is the one field on this value object that is worth
    #: keeping out of logs — log the statuses and the timestamp instead.
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ApplicationStatus):
            raise InvalidValueError(
                "ApplicationStatusChange requires a valid ApplicationStatus."
            )
        if self.previous_status is not None and not isinstance(
            self.previous_status, ApplicationStatus
        ):
            raise InvalidValueError(
                "ApplicationStatusChange.previous_status must be an "
                "ApplicationStatus or None."
            )
        if self.status is ApplicationStatus.DRAFT:
            raise InvalidValueError(
                "An application's history cannot record a move to "
                f"'{ApplicationStatus.DRAFT.value}' — a tracked application "
                "exists because it was sent."
            )
        # A move to the status it is already in is not a move. Refused here as
        # well as by the transition rules, because an entry like that would
        # make "how long has it been at this status?" unanswerable — the
        # history would carry two different answers for one state.
        if self.previous_status is not None and self.previous_status is self.status:
            raise InvalidValueError(
                f"An application's history cannot record a move from "
                f"'{self.status.value}' to itself."
            )
        if self.changed_at.tzinfo is None:
            raise InvalidValueError(
                "ApplicationStatusChange.changed_at must be timezone-aware so "
                "a history orders correctly across regions."
            )
        if len(self.note) > ApplicationStatusChange.MAX_NOTE_LENGTH:
            raise InvalidValueError(
                "ApplicationStatusChange.note cannot exceed "
                f"{ApplicationStatusChange.MAX_NOTE_LENGTH} characters."
            )

    @property
    def is_initial(self) -> bool:
        """Whether this is the entry recorded when the application was sent —
        the only one with nothing before it."""
        return self.previous_status is None

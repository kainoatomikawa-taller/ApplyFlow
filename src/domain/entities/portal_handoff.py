"""PortalHandoff entity — the record of ApplyFlow stopping at a boundary and
asking the candidate to take over.

What it is for
--------------
A hand-off is not an error report. It is the state that makes a pause
*resumable*: it says which portal was being worked on, where automation got
to, what it hit, why ApplyFlow refuses to do that step, and whether the person
has since dealt with it. Without a stored hand-off, "the app stopped" is an
error message in a log — the candidate reloads the page and has no idea what
happened or what to do, and nothing downstream can tell a portal that is
waiting on a human from one that is simply untouched.

Resumption is the candidate's assertion, and it is recorded as one
--------------------------------------------------------------------
`resume()` means "the person says they did the human-only step". It
deliberately does not mean "ApplyFlow verified the boundary is gone", and
pretending otherwise would be a lie the design cannot support: the candidate
solves a CAPTCHA or signs in *in their own browser*, and ApplyFlow's next
session carries none of that — a fresh session would still see the wall. So
the entity records the assertion (with an optional note in the candidate's own
words) and lets the next inspection speak for itself: if a boundary is still
there, that inspection raises a *new* hand-off with fresh evidence rather than
quietly reopening this one. The candidate is never told a boundary was cleared
on evidence nobody has.

`abandon()` is the other honest ending — "I am finishing this application
myself" — and the reason a hand-off can always be cleared. An account wall on
a portal that requires a real account may never become automatable; a
lifecycle that only allowed "resumed" would leave that hand-off open forever.

Immutable, and re-detection is a new value
------------------------------------------
Frozen: every transition returns a new instance rather than mutating this one,
so a hand-off cannot be advanced by accident halfway through a use case, and
the state a caller is holding stays the state it decided on. `redetected()`
covers the ordinary case of inspecting the same portal twice while the person
has not acted yet — it refreshes the evidence and the paused URL on the *same*
hand-off (same id, same `created_at`) instead of stacking a second row for
the same unresolved boundary, which is what keeps "what is waiting on me?"
answerable at a glance.

SENSITIVE: `resolution_note` is free text the candidate wrote, so it can
contain anything they thought was relevant — an email address they registered
with, a reference number, a reason. It inherits the strictest treatment
rather than the mildest: flagged on `PortalHandoffModel` too, and never
logged. The evidence lines are the opposite: they describe the portal's own
page, carry nothing about the candidate, and are safe to log and display.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import ClassVar

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.handoff_status import HandoffStatus
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PortalHandoff:
    """One paused portal, waiting on the candidate."""

    SENSITIVE: ClassVar[bool] = True
    #: Long enough for a candidate to explain what they did, short enough
    #: that the column is not an unbounded text sink.
    MAX_NOTE_LENGTH: ClassVar[int] = 1000

    id: str
    user_id: str
    job_posting_id: str
    #: The apply URL automation was asked to work on.
    apply_url: str
    #: Where it actually got to when it stopped — often not `apply_url`, and
    #: the difference is itself informative: an apply link that redirected to
    #: `/login` has explained the hand-off in one field. This is the URL the
    #: candidate should open to finish the step.
    paused_url: str
    #: Every boundary found on that page, with its evidence. Never empty —
    #: see `__post_init__`.
    hard_stops: tuple[HardStop, ...]
    status: HandoffStatus = HandoffStatus.AWAITING_USER
    created_at: datetime = field(default_factory=_utcnow)
    #: When the boundary was last seen on the page. Equal to `created_at`
    #: until an inspection re-reads the same unresolved hand-off, so a stale
    #: hand-off is distinguishable from one confirmed a minute ago.
    last_detected_at: datetime | None = None
    resolved_at: datetime | None = None
    #: What the candidate said when they resolved it, in their own words.
    #: SENSITIVE — see the module docstring.
    resolution_note: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "user_id", "job_posting_id", "apply_url", "paused_url"):
            if not str(getattr(self, name)).strip():
                raise InvalidValueError(f"PortalHandoff requires a non-empty {name}.")
        # A tuple, not any sequence: a list would be a mutable field on a
        # frozen entity, which is exactly the immutability this class claims.
        if not isinstance(self.hard_stops, tuple):
            raise InvalidValueError("PortalHandoff.hard_stops must be a tuple.")
        if not self.hard_stops:
            raise InvalidValueError(
                "PortalHandoff requires at least one hard stop — a hand-off "
                "with no boundary to explain is a pause with no reason."
            )
        if not all(isinstance(stop, HardStop) for stop in self.hard_stops):
            raise InvalidValueError(
                "PortalHandoff.hard_stops must contain only HardStop values."
            )
        if not isinstance(self.status, HandoffStatus):
            raise InvalidValueError("PortalHandoff requires a valid HandoffStatus.")
        if len(self.resolution_note) > PortalHandoff.MAX_NOTE_LENGTH:
            raise InvalidValueError(
                "PortalHandoff.resolution_note cannot exceed "
                f"{PortalHandoff.MAX_NOTE_LENGTH} characters."
            )
        # The status and the resolution have to agree, in both directions: an
        # open hand-off that carries a resolution, or a resolved one that
        # carries no time, is a row nothing downstream can interpret.
        if self.status.is_open:
            if self.resolved_at is not None:
                raise InvalidValueError(
                    "A hand-off still awaiting the candidate cannot have a "
                    "resolved_at."
                )
            if self.resolution_note:
                raise InvalidValueError(
                    "A hand-off still awaiting the candidate cannot carry a "
                    "resolution note."
                )
        elif self.resolved_at is None:
            raise InvalidValueError(
                f"A hand-off resolved as '{self.status.value}' requires a "
                "resolved_at."
            )
        if self.last_detected_at is None:
            # Defaulted here rather than with a factory so it is the *same*
            # instant as `created_at` on a fresh hand-off, instead of a few
            # microseconds later for no reason a reader could explain.
            object.__setattr__(self, "last_detected_at", self.created_at)

    # ---- Construction --------------------------------------------------------

    @classmethod
    def raise_for(
        cls,
        *,
        handoff_id: str,
        user_id: str,
        job_posting_id: str,
        apply_url: str,
        paused_url: str,
        hard_stops: tuple[HardStop, ...],
        detected_at: datetime | None = None,
    ) -> PortalHandoff:
        """Open a hand-off for boundaries just found on a portal page."""
        detected = detected_at or _utcnow()
        return cls(
            id=handoff_id,
            user_id=user_id,
            job_posting_id=job_posting_id,
            apply_url=apply_url,
            paused_url=paused_url,
            hard_stops=hard_stops,
            status=HandoffStatus.AWAITING_USER,
            created_at=detected,
            last_detected_at=detected,
        )

    # ---- Behaviors -----------------------------------------------------------

    def redetected(
        self,
        *,
        hard_stops: tuple[HardStop, ...],
        paused_url: str,
        detected_at: datetime | None = None,
    ) -> PortalHandoff:
        """Return this hand-off with the newest reading of the same portal.

        For inspecting a portal again while the candidate has not acted yet.
        The evidence and paused URL are replaced (a portal can present a
        different boundary on a second visit — a wall where there was a
        CAPTCHA) while the id and `created_at` are kept, so the candidate
        keeps seeing one hand-off for one unresolved portal rather than a new
        one per attempt.
        """
        if not self.status.is_open:
            raise self._already_resolved("re-detect a boundary on")
        return replace(
            self,
            hard_stops=hard_stops,
            paused_url=paused_url,
            last_detected_at=detected_at or _utcnow(),
        )

    def resume(
        self, *, note: str = "", resolved_at: datetime | None = None
    ) -> PortalHandoff:
        """Record that the candidate did the human-only step and wants
        ApplyFlow to continue.

        This is their assertion, not a verification — see the module
        docstring for why nothing here claims the boundary is gone.
        """
        return self._resolve(HandoffStatus.RESUMED, note=note, resolved_at=resolved_at)

    def abandon(
        self, *, note: str = "", resolved_at: datetime | None = None
    ) -> PortalHandoff:
        """Record that the candidate is finishing this application themselves."""
        return self._resolve(
            HandoffStatus.ABANDONED, note=note, resolved_at=resolved_at
        )

    @property
    def is_open(self) -> bool:
        """Whether ApplyFlow is still waiting on the candidate. While this is
        true, nothing may fill this portal's form."""
        return self.status.is_open

    @property
    def kinds(self) -> tuple[HardStopKind, ...]:
        """Which boundaries this hand-off is about, deduplicated, in the order
        they were detected."""
        seen: list[HardStopKind] = []
        for stop in self.hard_stops:
            if stop.kind not in seen:
                seen.append(stop.kind)
        return tuple(seen)

    @property
    def required_human_actions(self) -> tuple[str, ...]:
        """What the candidate has to do, one line per distinct boundary."""
        return tuple(kind.human_action for kind in self.kinds)

    @property
    def evidence(self) -> tuple[str, ...]:
        """Every evidence line across every boundary, deduplicated — the
        whole case for stopping, in one list."""
        lines: list[str] = []
        for stop in self.hard_stops:
            for line in stop.evidence:
                if line not in lines:
                    lines.append(line)
        return tuple(lines)

    # ---- internals -----------------------------------------------------------

    def _resolve(
        self, target: HandoffStatus, *, note: str, resolved_at: datetime | None
    ) -> PortalHandoff:
        return replace(
            self,
            # Raises BusinessRuleViolationError on a hand-off already
            # resolved, which is what makes a double-submitted "continue"
            # a rejected request rather than a rewritten record.
            status=self.status.transition_to(target),
            resolved_at=resolved_at or _utcnow(),
            resolution_note=note.strip(),
        )

    def _already_resolved(self, attempted: str) -> InvalidValueError:
        return InvalidValueError(
            f"Cannot {attempted} a hand-off already resolved as "
            f"'{self.status.value}'."
        )

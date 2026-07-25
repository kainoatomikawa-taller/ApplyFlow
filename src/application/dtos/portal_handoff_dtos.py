"""DTOs — input/output contracts for inspecting an application portal and for
the hand-offs that come out of it (see `PortalHandoff`).

The inspection output is one shape with a rule attached: **`handoff` and
`fields` are mutually exclusive.** When a boundary was found, the hand-off is
populated and the field list is empty — not because the fields could not be
read, but because they are deliberately withheld. Handing back a fillable form
alongside "we stopped at a sign-in wall" would make the pause advisory, and an
advisory pause is one a caller can forget to honor. The one that matters here
cannot be forgotten, because there is nothing to fill.

Everything here is plain data: strings, not `HardStopKind`; ISO datetimes come
from the entity unchanged. The interface layer serializes DTOs directly, so a
domain enum leaking this far would end up in a JSON response body by accident
rather than by decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class InspectApplicationPortalInput:
    """Ask what a posting's application portal is actually presenting."""

    user_id: str
    job_posting_id: str


@dataclass(frozen=True)
class HardStopOutput:
    """One boundary found on the portal, with the case for stopping.

    `evidence` describes the portal's page, never the candidate — safe to log
    and to show. `refusal_reason` and `human_action` come from the domain so
    every surface explains the stop the same way.
    """

    kind: str
    refusal_reason: str
    human_action: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PortalHandoffOutput:
    """A hand-off's full state — what was hit, where, and how it stands.

    `resolution_note` is candidate free text and inherits `PortalHandoff`'s
    sensitivity: returned to its own owner, never logged.
    """

    id: str
    job_posting_id: str
    apply_url: str
    #: Where automation stopped, and the URL the candidate should open to
    #: finish the step themselves. Often not `apply_url`.
    paused_url: str
    status: str
    is_open: bool
    created_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str = ""
    hard_stops: list[HardStopOutput] = field(default_factory=list)


@dataclass(frozen=True)
class PortalFieldOutput:
    """One question the portal asks, as a caller downstream of a clean
    inspection would need to see it.

    Carries no field handle: handles are only meaningful inside the browser
    session that minted them, and that session is closed by the time this DTO
    exists. This is a description of what the form wants, not a way to write
    to it.
    """

    label: str
    kind: str
    name: str = ""
    required: bool = False
    #: Set when this field is one only the candidate may fill. Reported
    #: rather than hidden, so a caller can see exactly which question forced
    #: the hand-off — see `FormField.human_only_boundary`.
    human_only_boundary: str | None = None


@dataclass(frozen=True)
class InspectApplicationPortalOutput:
    """What the portal presented, and whether ApplyFlow may proceed.

    `is_handed_off` is the single question a caller should branch on. When it
    is true, `handoff` is set and `fields` is empty (see the module
    docstring).
    """

    job_posting_id: str
    apply_url: str
    #: The URL the browser actually landed on — a redirect into a login flow
    #: is itself a finding.
    landed_url: str
    is_handed_off: bool
    handoff: PortalHandoffOutput | None = None
    fields: list[PortalFieldOutput] = field(default_factory=list)
    #: Set when this inspection found no boundary while a hand-off was still
    #: open for the posting: the wall the candidate was asked about is gone,
    #: so the hand-off resolved itself and this is the id it resolved. The
    #: one case where ApplyFlow closes a hand-off on its own evidence rather
    #: than on the candidate's word.
    cleared_handoff_id: str | None = None


@dataclass(frozen=True)
class ResolvePortalHandoffInput:
    """Record how the candidate dealt with a hand-off.

    `note` is optional and free text, capped by the entity
    (`PortalHandoff.MAX_NOTE_LENGTH`).
    """

    user_id: str
    handoff_id: str
    note: str = ""


@dataclass(frozen=True)
class ListPortalHandoffsInput:
    """List a candidate's hand-offs, newest first.

    Resolved ones are included by default: "this portal made me sign in and I
    handled it yesterday" is exactly the context that stops someone doing the
    step twice.
    """

    user_id: str
    open_only: bool = False
    limit: int = 100


@dataclass(frozen=True)
class ListPortalHandoffsOutput:
    handoffs: list[PortalHandoffOutput] = field(default_factory=list)
    #: How many of them are still waiting on the candidate — what a badge or
    #: banner needs without re-counting the list.
    open_count: int = 0

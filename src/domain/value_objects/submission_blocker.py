"""SubmissionBlocker — a reason ApplyFlow will not hand an application over to
be sent, and what the candidate has to do about it.

Blockers exist so the refusal is *data* rather than an exception message. A
review screen has to show, at all times, exactly what stands between the
candidate and the submit button — "Submit is disabled" with no explanation is
the failure mode this type is designed to prevent. The same list is then
re-checked at submission (see `ApplicationReview.record_submission`), so the
button and the rule can never disagree.

Only two kinds, and both are about consent rather than completeness:

- **`PENDING_SENSITIVE_DECISION`** — a legal declaration or an EEO question
  the candidate has not settled. Nothing derived from their record gets
  asserted to an employer until they say so, and declining is always one of
  the ways to say it.
- **`OPEN_HARD_STOP`** — the portal has a boundary ApplyFlow refuses to cross
  (a CAPTCHA, a signature, a sign-in wall) and the candidate has not dealt with
  it yet. Handing them an application to send through a portal that is still
  blocked would be handing them a dead end.

What is deliberately *not* a blocker: a required field with no answer. The
`required` flag is only as trustworthy as the portal's markup — the browser
port says so explicitly, and treats `False` as "not asserted" rather than
"optional" — so a candidate who has answered the question on the portal itself
must not be locked out of recording their own submission by a signal ApplyFlow
may have read wrongly. Those fields are surfaced as warnings, prominently, and
the candidate decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.domain.exceptions import InvalidValueError


class SubmissionBlockerKind(StrEnum):
    """Why a review cannot be handed over yet."""

    #: A sensitive field the candidate has not confirmed, answered, or
    #: declined. Carries the answer's key.
    PENDING_SENSITIVE_DECISION = "pending_sensitive_decision"

    #: An unresolved hard-stop hand-off on this portal (see `PortalHandoff`).
    OPEN_HARD_STOP = "open_hard_stop"


@dataclass(frozen=True)
class SubmissionBlocker:
    """One thing standing between the candidate and submitting."""

    kind: SubmissionBlockerKind
    #: What the candidate has to do, in their words rather than the system's.
    detail: str
    #: The answer this blocker is about, when it is about one.
    field_key: str | None = None
    #: The field's label, so a review screen can point at it without looking
    #: the answer up again.
    field_label: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SubmissionBlockerKind):
            raise InvalidValueError(
                "SubmissionBlocker requires a valid SubmissionBlockerKind."
            )
        if not self.detail.strip():
            raise InvalidValueError(
                "SubmissionBlocker requires a detail — a blocker the candidate "
                "cannot act on is just a disabled button."
            )

"""ApplicationBoundary — a point on an application form that a human, and
only a human, may cross.

Three of them exist, and they are the ones an automated filler must never
try to get past: a **login** wall, a **CAPTCHA**, and a request for the
candidate's **signature**. Each is a deliberate check by the portal that
the party filling this form is the person applying, and defeating any of
them is either impossible, dishonest, or both:

- a **login** asks for a credential — ApplyFlow holds none and must never
  invent one;
- a **CAPTCHA** asks the filler to prove it is not a program, which is the
  one question ApplyFlow cannot answer truthfully;
- a **signature** is the candidate personally attesting to the application,
  which nothing else can do on their behalf.

So this type never carries "how to get past it". It carries what was seen,
what it means for the pass in progress, and what to tell the candidate.

Two different stops
-------------------
The kinds are not interchangeable, and treating them as one would be wrong
in both directions:

`stops_autofill` — a login wall means the page in the browser is not the
application form at all. Filling it would type the candidate's details into
a sign-in box for an account that may not exist. Nothing is filled.

`blocks_unattended_submit` — true for all three. It is the weaker,
universal statement: this application cannot be carried to submission
without the candidate acting personally on the page. A CAPTCHA sitting at
the foot of an otherwise ordinary form does not stop the form being filled
— filling is most of the value, and the candidate still gets it — but it
does stop ApplyFlow pressing submit for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApplicationBoundaryKind(StrEnum):
    """What kind of human-only check was found on the page."""

    #: A sign-in or account-creation wall standing between the browser and
    #: the application form.
    LOGIN = "login"
    #: A challenge asking the filler to prove it is a person.
    CAPTCHA = "captcha"
    #: A request for the candidate's own signature — drawn, typed, or
    #: through an e-signature provider.
    SIGNATURE = "signature"


#: What the candidate is told for each kind. Written as instructions to a
#: person rather than as an error, because that is what they are: the work
#: has not failed, it has reached the part only they can do.
_INSTRUCTIONS: dict[ApplicationBoundaryKind, str] = {
    ApplicationBoundaryKind.LOGIN: (
        "This portal wants you signed in before it will show the application "
        "form. ApplyFlow holds no credentials for it and will not fill a "
        "sign-in form, so nothing was entered. Open the apply link yourself, "
        "sign in, and run the autofill again from the page the form is on."
    ),
    ApplicationBoundaryKind.CAPTCHA: (
        "This form carries a CAPTCHA — a check that the applicant is a "
        "person. Only you can answer it, so ApplyFlow will not submit this "
        "application. Open the apply link yourself to finish and send it."
    ),
    ApplicationBoundaryKind.SIGNATURE: (
        "This form asks for your signature. A signature is yours to give and "
        "cannot be entered on your behalf, so ApplyFlow will not submit this "
        "application. Open the apply link yourself to sign and send it."
    ),
}

#: The kinds that mean the page in front of the browser is not the
#: application form, so nothing on it may be filled.
_STOPS_AUTOFILL: frozenset[ApplicationBoundaryKind] = frozenset(
    {ApplicationBoundaryKind.LOGIN}
)


@dataclass(frozen=True)
class ApplicationBoundary:
    """One human-only check found on an application page.

    `evidence` is what was actually seen — "a reCAPTCHA frame", "a password
    field on the form" — and is meant to be shown to the candidate. A
    boundary with no evidence would be an assertion the reviewer cannot
    check, which on a stop this consequential is not good enough.
    """

    kind: ApplicationBoundaryKind
    evidence: str

    def __post_init__(self) -> None:
        if not self.evidence.strip():
            raise ValueError(
                "An ApplicationBoundary must record what was seen; a stop "
                "with no evidence cannot be reviewed or argued with."
            )

    @property
    def stops_autofill(self) -> bool:
        """Whether this boundary means nothing on the page may be filled."""
        return self.kind in _STOPS_AUTOFILL

    @property
    def blocks_unattended_submit(self) -> bool:
        """Whether this boundary puts submission beyond ApplyFlow's reach.

        True for every kind. It is stated as a property rather than assumed
        at each call site so that adding a kind forces the question to be
        answered here, in the one place the policy lives.
        """
        return True

    @property
    def instruction(self) -> str:
        """What to tell the candidate, in their terms."""
        return _INSTRUCTIONS[self.kind]

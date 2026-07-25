"""HardStopKind — the boundaries automation is never allowed to cross on an
application portal.

These are not "hard" because they are technically difficult. Each one is a
step where the act itself is the point: a CAPTCHA exists to establish that a
human is present, a signature is a legal attestation made by a named person,
and a credential is that person's identity. Software that performs any of
them is not automating a chore, it is impersonating the candidate — so
ApplyFlow stops and asks the person to do it.

That is why the enum is closed and small. It is not a list of "things the
autofill layer hasn't learned yet", to be shortened as the harness gets
better; every member here stays a hand-off no matter how capable the
automation becomes. Portal quirks that merely *need work* (custom combobox
widgets, multi-page wizards) are not modeled here at all — they are missing
capabilities, not boundaries.

Each member carries the two sentences the rest of the system needs to explain
itself: why ApplyFlow stopped, and what the person now has to do. Keeping them
here rather than in the UI means the answer cannot drift between the API, the
web app, and a future CLI — and the reason ApplyFlow refuses is a rule about
the product, not a piece of copy.
"""

from __future__ import annotations

from enum import StrEnum


class HardStopKind(StrEnum):
    """A boundary that ends automation and hands control to the candidate."""

    #: A challenge whose only purpose is to prove a human is present
    #: (reCAPTCHA, hCaptcha, Turnstile, "I am not a robot", an image or
    #: audio challenge).
    CAPTCHA = "captcha"

    #: A field or embedded flow that takes a legally binding signature —
    #: drawn, typed-as-signature, or handed to a signing provider.
    ELECTRONIC_SIGNATURE = "electronic_signature"

    #: A sign-in or account-creation gate: the portal wants credentials
    #: before it will show or accept the application.
    ACCOUNT_WALL = "account_wall"

    @property
    def refusal_reason(self) -> str:
        """Why ApplyFlow will not do this itself — the safety principle,
        stated in one sentence, for an API response or a UI panel."""
        return _REFUSAL_REASONS[self]

    @property
    def human_action(self) -> str:
        """What the candidate has to do to get past this boundary."""
        return _HUMAN_ACTIONS[self]


_REFUSAL_REASONS: dict[HardStopKind, str] = {
    HardStopKind.CAPTCHA: (
        "A CAPTCHA asks whether a human is present. ApplyFlow never answers "
        "one — solving it would be a machine asserting it is you."
    ),
    HardStopKind.ELECTRONIC_SIGNATURE: (
        "A signature is a legal attestation by a named person. ApplyFlow "
        "never signs on your behalf, however the portal collects it."
    ),
    HardStopKind.ACCOUNT_WALL: (
        "This portal wants credentials. ApplyFlow never creates accounts and "
        "never types passwords, so it stops at the sign-in gate."
    ),
}

_HUMAN_ACTIONS: dict[HardStopKind, str] = {
    HardStopKind.CAPTCHA: (
        "Open the portal yourself and complete the challenge, then come back "
        "and continue."
    ),
    HardStopKind.ELECTRONIC_SIGNATURE: (
        "Open the portal yourself and sign the form — read what you are "
        "attesting to before you do."
    ),
    HardStopKind.ACCOUNT_WALL: (
        "Open the portal yourself and sign in (or create the account) with "
        "credentials you control, then come back and continue."
    ),
}

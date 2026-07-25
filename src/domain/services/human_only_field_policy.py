"""HumanOnlyFieldPolicy — decides whether a single form field is one only the
candidate may ever fill.

The same safety policy as `HardStopDetector`, applied to one control instead
of a whole page, and both exist because they fail differently:

- The **page-level** check runs once, before anything is filled, and answers
  "should ApplyFlow touch this form at all?". It can be defeated by a portal
  that reveals its signature block only on the second page of a wizard, or
  that swaps in a login prompt after a session expires mid-fill.
- The **field-level** check runs on every single write. It is what makes
  "ApplyFlow never types a password" a property of the system rather than a
  promise about its callers: the write is refused at the point where typing
  physically happens, so no use case, and no model driving one, can produce
  a keystroke into a credential, a signature, or a challenge answer.

Password fields are recognized by kind, not by vocabulary — `type="password"`
is a credential whatever it is labeled, including on a portal that labels it
"Access code". Everything else is recognized from the markup's own names,
because portals that mask a plain text input with JavaScript leave the type
attribute saying nothing useful.

Takes primitives rather than a form-field object: the field description lives
in the application layer's browser port, and the domain does not import it.
The caller passes what it has.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.domain.services.hard_stop_vocabulary import (
    CAPTCHA_LABEL_TOKENS,
    CREDENTIAL_LABEL_TOKENS,
    SIGNATURE_LABEL_TOKENS,
    contains_any,
)
from src.domain.value_objects.hard_stop_kind import HardStopKind


class HumanOnlyFieldPolicy:
    """Recognizes fields that are boundaries in themselves."""

    #: The browser port's name for a control that is a credential by
    #: construction. Compared as a string because the port's field-kind
    #: enum lives outside the domain.
    PASSWORD_KIND_NAME = "password"

    @staticmethod
    def boundary_for(
        *,
        kind_name: str = "",
        label: str = "",
        name: str = "",
        attribute_values: Iterable[str] = (),
    ) -> HardStopKind | None:
        """Return the boundary this field belongs to, or None if it is an
        ordinary question ApplyFlow may answer.

        `attribute_values` is whatever else the markup said about the control
        — its id, autocomplete hint, `data-*` values — which is where a
        JavaScript-masked credential field usually gives itself away.
        """
        if kind_name.casefold() == HumanOnlyFieldPolicy.PASSWORD_KIND_NAME:
            return HardStopKind.ACCOUNT_WALL

        haystack = " ".join(
            part.casefold()
            for part in (label, name, *attribute_values)
            if part and part.strip()
        )
        if not haystack:
            return None
        # CAPTCHA is checked first: a control named "captcha_signature" is a
        # challenge answer, and reading it as a signature would still refuse
        # the write but would explain the refusal wrongly.
        if contains_any(CAPTCHA_LABEL_TOKENS, haystack):
            return HardStopKind.CAPTCHA
        if contains_any(SIGNATURE_LABEL_TOKENS, haystack):
            return HardStopKind.ELECTRONIC_SIGNATURE
        if contains_any(CREDENTIAL_LABEL_TOKENS, haystack):
            return HardStopKind.ACCOUNT_WALL
        return None

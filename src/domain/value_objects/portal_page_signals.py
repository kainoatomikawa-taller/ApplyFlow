"""PortalPageSignals — everything the domain gets to know about a portal page
it never sees.

`HardStopDetector` has to answer "is there a boundary on this page?", and the
page is a live browser document living in infrastructure. This value object is
the seam: infrastructure reads the DOM once and reduces it to these facts,
then the domain reasons over them. Nothing here is a DOM node, a selector, or
a browser handle, so the detection rules stay testable from a literal and
stay honest about their inputs — a rule can only use a signal that was
actually collected.

The split of what lives here is deliberate:

- **Readable surfaces** (`title`, `text`, `field_labels`) are what the page
  says to a person. Phrase rules match against these.
- **Machine surfaces** (`url`, `frame_urls`, `script_urls`, `element_hints`)
  are what the page loads and how its markup is named. Vendor rules match
  against these, because a CAPTCHA widget is recognizable by the script it
  pulls in long before it says anything.
- **Form shape** (`password_field_count`, `fillable_field_count`) is what the
  page is asking for. A password field is the one signal that needs no
  interpretation at all.

Signals are collected across the main document *and* its frames, because ATS
forms are routinely embedded in an iframe — a sign-in wall inside the frame is
still a sign-in wall, and a detector reading only the outer document would
report a clean page.

This object makes no judgments. It normalizes (lowercases, joins) so that
every rule matches against the same shape, and stops there: deciding what a
match *means* is `HardStopDetector`'s job, and keeping that boundary is why
one can be reviewed without the other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.domain.exceptions import InvalidValueError

#: What separates one URL segment from the next. `-` and `_` are absent on
#: purpose: they occur *inside* the names being matched ("sign-in").
_SEGMENT_DELIMITERS = re.compile(r"[/?&=#.:]+")


@dataclass(frozen=True)
class PortalPageSignals:
    """A reduced, judgment-free reading of one portal page."""

    #: The URL actually landed on, which is frequently not the apply URL that
    #: was opened — a portal that redirects to its login page has already
    #: said something important in this one field.
    url: str
    title: str = ""
    #: The page's visible text, main document and frames together. Truncated
    #: by whoever collects it; detection rules only ever look for phrases.
    text: str = ""
    #: The URL of every frame on the page, including the main one.
    frame_urls: tuple[str, ...] = ()
    #: The `src` of every script the page loads.
    script_urls: tuple[str, ...] = ()
    #: Markup names from elements that can host a widget (ids, classes,
    #: control names, `data-*` names and values). Vendor widgets are named
    #: after themselves far more reliably than they are described in prose.
    element_hints: tuple[str, ...] = ()
    #: The label of every fillable field discovered on the page.
    field_labels: tuple[str, ...] = ()
    #: How many password inputs the page presents. Non-zero is the least
    #: ambiguous signal there is: a form asking for a password is a form
    #: ApplyFlow will not fill.
    password_field_count: int = 0
    #: How many fillable fields there are in total — what separates "a form
    #: with a login link in the header" from "a login page".
    fillable_field_count: int = 0

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise InvalidValueError(
                "PortalPageSignals requires the URL the signals were read "
                "from — a reading with no page is not evidence of anything."
            )
        for name in ("frame_urls", "script_urls", "element_hints", "field_labels"):
            if not isinstance(getattr(self, name), tuple):
                raise InvalidValueError(f"PortalPageSignals.{name} must be a tuple.")
        if self.password_field_count < 0 or self.fillable_field_count < 0:
            raise InvalidValueError(
                "PortalPageSignals field counts cannot be negative."
            )

    # ---- normalized views ----------------------------------------------------

    @property
    def readable_text(self) -> str:
        """Everything the page says to a person, lowercased and joined —
        one haystack for phrase rules, so no rule has to remember which of
        the title, the body, or a field label a phrase might appear in."""
        return " ".join(
            part.casefold()
            for part in (self.title, self.text, *self.field_labels)
            if part
        )

    @property
    def machine_tokens(self) -> str:
        """Everything the page loads or names itself, lowercased and joined
        — one haystack for vendor rules."""
        return " ".join(
            part.casefold()
            for part in (
                self.url,
                *self.frame_urls,
                *self.script_urls,
                *self.element_hints,
            )
            if part
        )

    @property
    def url_path_segments(self) -> tuple[str, ...]:
        """The URLs the browser actually navigated to, broken into lowercased
        path segments — host labels, path elements, query keys and values.

        Two deliberate narrowings, each closing a real false positive:

        - only navigated URLs, never scripts or markup names. A bundle served
          from an `/auth/` directory says nothing about the page that loaded
          it.
        - segments, not substrings, so a rule can require a *whole* one.
          DocuSign signs from `docusign.net/signing/...`, and "signing"
          contains "signin" — matched loosely, every signature page would be
          reported as a sign-in wall.

        Split on the characters that delimit structure (`/ ? & = # . :`) while
        keeping `-` and `_` inside a segment, so "sign-in" survives as one
        thing to match.
        """
        segments: list[str] = []
        for url in (self.url, *self.frame_urls):
            for raw in _SEGMENT_DELIMITERS.split(url.casefold()):
                segment = raw.strip()
                if segment and segment not in segments:
                    segments.append(segment)
        return tuple(segments)

    @property
    def normalized_field_labels(self) -> tuple[str, ...]:
        """Field labels on their own, lowercased.

        Kept separate from `readable_text` because a word means something
        different depending on where it appears: "signature" in a job
        description is prose ("signature required upon hire"), while
        "Signature" as the label of a field the portal wants filled is the
        boundary itself.
        """
        return tuple(label.casefold() for label in self.field_labels if label.strip())

    @property
    def has_password_field(self) -> bool:
        return self.password_field_count > 0

    @property
    def presents_a_fillable_form(self) -> bool:
        return self.fillable_field_count > 0

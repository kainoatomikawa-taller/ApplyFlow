"""HardStopDetector — decides whether a portal page has a boundary ApplyFlow
must not cross, and hands back the evidence for saying so.

Pure and total: it takes a `PortalPageSignals` reading and returns zero or
more `HardStop`s. No I/O, no browser, no model call — which matters more here
than in most domain services, because this is the check that stands between
"ApplyFlow filled a form" and "ApplyFlow answered a human-verification
challenge on your behalf". A rule that can be read in one file and exercised
from a literal is a rule that can be audited.

Why rules rather than a model
-----------------------------
An LLM would recognize more phrasings, and would also be a component that
can be talked out of its answer by the page it is reading — a portal's own
text is untrusted input. This check is a safety gate, so it is deterministic,
inspectable, and identical on every run. Reach for a model to *describe* a
page, never to decide whether ApplyFlow may act on it.

Why several signals per kind
----------------------------
Each boundary is looked for on every surface it shows up on, because portals
differ in which one gives it away:

- a CAPTCHA is usually visible in the scripts and iframes first, sometimes
  only in the prose ("complete the security check"), and occasionally only in
  a field label;
- a signature can be a provider's embedded flow, a canvas widget, or a plain
  text field labeled "Signature";
- an account wall can be an outright redirect to `/login`, a page of prose
  about signing in, or — least ambiguous of all — a password field.

Any one surface matching is enough. Requiring agreement between two would
trade a class of false hand-offs for a class of missed boundaries, and those
costs are nowhere near symmetric (see `hard_stop_vocabulary`).

What is deliberately NOT a hard stop
------------------------------------
An "I certify that the above is true" checkbox, an "I agree to the privacy
policy" checkbox, a "Sign in" link in a page header, and a page that merely
mentions passwords in prose. All of them are ordinary furniture on ATS forms.
Treating them as boundaries would hand off every application, which reads as
caution but is really just a broken product — and a hand-off that fires
constantly is a hand-off candidates learn to click past without reading.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.domain.services.hard_stop_vocabulary import (
    ACCOUNT_WALL_PHRASES,
    ACCOUNT_WALL_URL_SEGMENTS,
    CAPTCHA_LABEL_TOKENS,
    CAPTCHA_PHRASES,
    CAPTCHA_VENDOR_TOKENS,
    CREDENTIAL_LABEL_TOKENS,
    SIGNATURE_LABEL_TOKENS,
    SIGNATURE_PHRASES,
    SIGNATURE_VENDOR_TOKENS,
    contains_any,
)
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.domain.value_objects.portal_page_signals import PortalPageSignals

#: How many evidence lines one boundary reports. The first few are the
#: strongest (vendor matches are collected before prose), and a hand-off panel
#: listing forty near-identical phrase hits explains less than one listing
#: four, not more.
_MAX_EVIDENCE_LINES = 6

#: Per-surface caps, for the same reason. One vendor match settles what the
#: page loaded — the vocabulary is ordered most specific first, so the one
#: reported names the actual provider rather than a generic substring of it.
_MAX_VENDOR_MATCHES = 1
_MAX_PHRASE_MATCHES = 3
_MAX_LABEL_MATCHES = 2


class HardStopDetector:
    """Recognizes hard boundaries on a portal page from its signals alone."""

    def detect(self, signals: PortalPageSignals) -> tuple[HardStop, ...]:
        """Return every boundary found on this page, in `HardStopKind` order.

        The order is fixed rather than "most confident first" so that two
        readings of the same page always produce the same record — a
        hand-off is stored, re-read, and compared against a later reading.
        An empty result means no boundary was recognized, which is the only
        condition under which anything above may go on to fill this form.
        """
        found: list[HardStop] = []
        for kind, evidence in (
            (HardStopKind.CAPTCHA, self._captcha_evidence(signals)),
            (HardStopKind.ELECTRONIC_SIGNATURE, self._signature_evidence(signals)),
            (HardStopKind.ACCOUNT_WALL, self._account_wall_evidence(signals)),
        ):
            if evidence:
                found.append(HardStop(kind=kind, evidence=evidence))
        return tuple(found)

    def has_hard_stop(self, signals: PortalPageSignals) -> bool:
        """Whether this page has any boundary at all — the one question a
        caller that only needs to decide "stop or continue" should ask."""
        return bool(self.detect(signals))

    # ---- per-boundary rules --------------------------------------------------

    def _captcha_evidence(self, signals: PortalPageSignals) -> tuple[str, ...]:
        lines = [
            f"the page loads a known CAPTCHA component ('{token}')"
            for token in _matches(
                CAPTCHA_VENDOR_TOKENS, signals.machine_tokens, _MAX_VENDOR_MATCHES
            )
        ]
        lines += [
            f"the page reads '{phrase}'"
            for phrase in _matches(
                CAPTCHA_PHRASES, signals.readable_text, _MAX_PHRASE_MATCHES
            )
        ]
        lines += [
            f"a field asks for a challenge answer ('{label}')"
            for label in _label_matches(
                CAPTCHA_LABEL_TOKENS, signals.normalized_field_labels
            )
        ]
        return _capped(lines)

    def _signature_evidence(self, signals: PortalPageSignals) -> tuple[str, ...]:
        lines = [
            f"the page loads a known e-signature component ('{token}')"
            for token in _matches(
                SIGNATURE_VENDOR_TOKENS, signals.machine_tokens, _MAX_VENDOR_MATCHES
            )
        ]
        lines += [
            f"the page reads '{phrase}'"
            for phrase in _matches(
                SIGNATURE_PHRASES, signals.readable_text, _MAX_PHRASE_MATCHES
            )
        ]
        lines += [
            f"a field asks to be signed ('{label}')"
            for label in _label_matches(
                SIGNATURE_LABEL_TOKENS, signals.normalized_field_labels
            )
        ]
        return _capped(lines)

    def _account_wall_evidence(self, signals: PortalPageSignals) -> tuple[str, ...]:
        lines: list[str] = []
        if signals.has_password_field:
            # First, and unconditional: this is the one signal that needs no
            # interpretation. Whatever else the page is, it is asking for a
            # credential, and ApplyFlow does not have one to give.
            fields = _count(signals.password_field_count, "password field")
            lines.append(f"the form presents {fields}")
        lines += [
            f"the URL ApplyFlow landed on is a credential page ('/{segment}')"
            for segment in _segment_matches(
                ACCOUNT_WALL_URL_SEGMENTS,
                signals.url_path_segments,
                _MAX_VENDOR_MATCHES,
            )
        ]
        lines += [
            f"the page reads '{phrase}'"
            for phrase in _matches(
                ACCOUNT_WALL_PHRASES, signals.readable_text, _MAX_PHRASE_MATCHES
            )
        ]
        lines += [
            f"a field asks for a credential ('{label}')"
            for label in _label_matches(
                CREDENTIAL_LABEL_TOKENS, signals.normalized_field_labels
            )
        ]
        return _capped(lines)


def _matches(needles: Iterable[str], haystack: str, limit: int) -> list[str]:
    """The first `limit` needles present in `haystack`, in vocabulary order —
    which is most-specific first, so a truncated list keeps the entry that
    says the most (see `hard_stop_vocabulary`)."""
    if not haystack:
        return []
    found: list[str] = []
    for needle in needles:
        if needle in haystack:
            found.append(needle)
            if len(found) >= limit:
                break
    return found


def _segment_matches(
    needles: Iterable[str], segments: Iterable[str], limit: int
) -> list[str]:
    """The first `limit` needles that appear as a WHOLE segment.

    Exact equality, not containment — see `PortalPageSignals.url_path_segments`
    for the signature-page-read-as-a-login-wall this prevents.
    """
    present = set(segments)
    found: list[str] = []
    for needle in needles:
        if needle in present:
            found.append(needle)
            if len(found) >= limit:
                break
    return found


def _label_matches(needles: Iterable[str], labels: Iterable[str]) -> list[str]:
    """Every label that contains one of `needles`, deduplicated.

    Reports the label rather than the token that matched it: "a field asks to
    be signed ('applicant signature')" tells the candidate which field to look
    for, while "('signature')" only repeats the rule.
    """
    matched: list[str] = []
    for label in labels:
        if contains_any(needles, label) and label not in matched:
            matched.append(label)
            if len(matched) >= _MAX_LABEL_MATCHES:
                break
    return matched


def _capped(lines: list[str]) -> tuple[str, ...]:
    """Deduplicate, preserve order, and keep the list explainable."""
    unique: list[str] = []
    for line in lines:
        if line not in unique:
            unique.append(line)
    return tuple(unique[:_MAX_EVIDENCE_LINES])


def _count(quantity: int, noun: str) -> str:
    return f"{quantity} {noun}" if quantity == 1 else f"{quantity} {noun}s"

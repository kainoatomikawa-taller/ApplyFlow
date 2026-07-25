"""detect_application_boundaries — reads one observation of an application
page and reports every human-only check on it.

A pure function over `PageSignals` plus the two things the form controls
say (their labels, and whether any of them takes a password). No browser,
no I/O, no state: the same observation always yields the same verdict, so
every rule below can be exercised against a literal signal set.

What it is looking for
----------------------
Three kinds (`ApplicationBoundaryKind`), each recognized from several
independent angles, because portals differ in which of them they leave
visible:

- **the provider's own URL** on a frame or script — `google.com/recaptcha`,
  `challenges.cloudflare.com`, `docusign.net`. The most reliable signal
  there is: it is the widget's actual origin, not prose about it.
- **markup tokens** — `g-recaptcha`, `cf-turnstile`, `signature-pad`. What
  a widget leaves behind before (or instead of) painting.
- **the visible text and the field labels** — the last resort, and the only
  angle available for a portal that renders its own challenge.

Why the phrase rules are so narrow
----------------------------------
A false negative here costs a candidate a stalled application they can see
and fix. A false positive costs them the entire autofill on a form that was
perfectly fillable — and worse, it teaches them to ignore the hand-off
message, which is the one message in this flow that must be believed.

That asymmetry is why the text rules only match phrases that are an
*instruction to the person* ("draw your signature", "type your full name to
sign") and never descriptive prose. In particular, "constitutes an
electronic signature" is deliberately not a marker: it appears in the
boilerplate consent paragraph on a large share of ordinary ATS forms that
ask for no signature at all. A form that genuinely wants one puts a widget
or a field there, and those are what this detects.

The password rule, and what it costs
------------------------------------
A password field on an apply form is treated as a login boundary — which
stops the pass, since `LOGIN` stops autofill. That is the deliberate
reading: a portal asking for a credential is asking to be signed into, and
ApplyFlow has none and may never invent one. It is knowingly conservative
about the rarer shape (a portal offering *optional* account creation
alongside its form): on such a page the candidate loses an autofill and is
told exactly why, which is the affordable side of this trade. None of the
three supported platforms serves a password field on a public apply form.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from src.domain.value_objects.application_boundary import (
    ApplicationBoundary,
    ApplicationBoundaryKind,
)
from src.domain.value_objects.page_signals import PageSignals

#: Substrings that identify a challenge provider by the URL a frame or
#: script was loaded from. Matched against the lowercased URL, so a match
#: anywhere in host or path counts — providers move their paths around far
#: more often than they change domain.
_CAPTCHA_URL_MARKERS: tuple[str, ...] = (
    "recaptcha",
    "hcaptcha",
    "captcha",
    "challenges.cloudflare.com",
    "turnstile",
    "arkoselabs",
    "funcaptcha",
    "geetest",
)

#: Markup tokens (an `id` or a `class`) the common challenge widgets leave
#: on the page, including before they have painted anything.
_CAPTCHA_MARKERS: tuple[str, ...] = (
    "g-recaptcha",
    "h-captcha",
    "cf-turnstile",
    "recaptcha",
    "hcaptcha",
    "captcha",
)

#: Visible-text phrases that only appear when a person is being challenged.
_CAPTCHA_PHRASES: tuple[str, ...] = (
    "i'm not a robot",
    "i am not a robot",
    "verify you are human",
    "verify that you are human",
    "verify you are a human",
    "confirm you are human",
    "complete the captcha",
)

#: E-signature providers, by the URL their embedded widget loads from.
_SIGNATURE_URL_MARKERS: tuple[str, ...] = (
    "docusign",
    "hellosign",
    "dropboxsign",
    "adobesign",
    "echosign",
    "signnow",
    "signaturit",
)

#: Markup tokens left by a signature widget — nearly always a canvas the
#: candidate draws on.
_SIGNATURE_MARKERS: tuple[str, ...] = (
    "signature-pad",
    "signaturepad",
    "signature-canvas",
    "signature-field",
    "esignature",
    "e-signature",
    "signature",
)

#: Field labels that mean this control *is* the signature.
_SIGNATURE_LABEL_PHRASES: tuple[str, ...] = (
    "signature",
    "sign here",
    "sign below",
    "e-sign",
)

#: Visible-text phrases that instruct the person to sign. Instructions
#: only — see the module docstring on why descriptive prose about
#: electronic signatures is excluded.
_SIGNATURE_PHRASES: tuple[str, ...] = (
    "draw your signature",
    "sign here",
    "sign below",
    "type your full name to sign",
    "type your name to sign",
    "your signature is required",
)

#: URL path fragments that name a sign-in route. Matched against the path
#: only: a posting whose *company* is called "Login Inc." would otherwise
#: be unreachable, and query strings routinely carry a `redirect_to` that
#: names the sign-in page the portal will use if you are not signed in —
#: which is not the page you are on.
_LOGIN_PATH_MARKERS: tuple[str, ...] = (
    "/login",
    "/log-in",
    "/signin",
    "/sign-in",
    "/sign_in",
    "/users/sign_in",
    "/auth/",
    "/account/login",
    "/sessions/new",
)

#: Visible-text phrases that mean the portal is asking to be signed into
#: before it will show the form.
_LOGIN_PHRASES: tuple[str, ...] = (
    "sign in to continue",
    "log in to continue",
    "sign in to apply",
    "log in to apply",
    "sign in to your account",
    "log in to your account",
    "create an account to apply",
    "please sign in",
    "please log in",
)


def is_signature_field(label: str) -> bool:
    """Whether a field with this label is asking to be *signed*.

    The field-level half of the signature rule, sharing one vocabulary with
    the page-level detection above so the two can never disagree about what
    a signature request looks like.

    It exists because the most common shape of a signature on an ATS form is
    an ordinary text input labelled "Signature (type your full name)" — and
    an autofiller reading that label finds the candidate's name in it and
    obliges. Typing someone's name into a signature box *is* signing for
    them, which is the one thing this epic's boundary rules exist to
    prevent; a hand-off that refuses to submit but has already signed would
    be worse than useless.
    """
    return any(phrase in label.casefold() for phrase in _SIGNATURE_LABEL_PHRASES)


def detect_application_boundaries(
    signals: PageSignals,
    *,
    field_labels: Sequence[str] = (),
    has_password_field: bool = False,
) -> tuple[ApplicationBoundary, ...]:
    """Report every human-only check visible in one page observation.

    Returned in a fixed order — login, CAPTCHA, signature — so a caller
    rendering them, or a test asserting on them, sees the same sequence
    every time. At most one boundary per kind: a page carrying three
    reCAPTCHA signals is one CAPTCHA, and listing it three times would
    just make the hand-off harder to read.
    """
    text = signals.visible_text.casefold()
    urls = tuple(
        url.casefold() for url in (*signals.frame_urls, *signals.script_urls) if url
    )
    markers = tuple(marker.casefold() for marker in signals.element_markers if marker)
    labels = tuple(label.casefold() for label in field_labels if label)

    found = (
        _detect_login(signals.url, text, has_password_field=has_password_field),
        _detect_captcha(text, urls, markers),
        _detect_signature(text, urls, markers, labels),
    )
    return tuple(boundary for boundary in found if boundary is not None)


def _detect_login(
    url: str, text: str, *, has_password_field: bool
) -> ApplicationBoundary | None:
    """A sign-in wall between the browser and the application form.

    The password field is checked first because it is the strongest signal
    and the one whose evidence a candidate can verify at a glance — "this
    page asked for a password" needs no further argument.
    """
    if has_password_field:
        return _boundary(
            ApplicationBoundaryKind.LOGIN, "the page asks for a password"
        )

    path = _path_of(url).casefold()
    hit = _first_hit(_LOGIN_PATH_MARKERS, path)
    if hit is not None:
        return _boundary(
            ApplicationBoundaryKind.LOGIN,
            f"the page's own URL names a sign-in route ('{hit}')",
        )

    hit = _first_hit(_LOGIN_PHRASES, text)
    if hit is not None:
        return _boundary(ApplicationBoundaryKind.LOGIN, f"the page says '{hit}'")
    return None


def _detect_captcha(
    text: str, urls: Sequence[str], markers: Sequence[str]
) -> ApplicationBoundary | None:
    hit = _first_hit_in(_CAPTCHA_URL_MARKERS, urls)
    if hit is not None:
        return _boundary(
            ApplicationBoundaryKind.CAPTCHA,
            f"the page loads a challenge widget from '{hit}'",
        )

    hit = _first_hit_in(_CAPTCHA_MARKERS, markers, whole_token=True)
    if hit is not None:
        return _boundary(
            ApplicationBoundaryKind.CAPTCHA,
            f"the form carries a challenge widget ('{hit}')",
        )

    hit = _first_hit(_CAPTCHA_PHRASES, text)
    if hit is not None:
        return _boundary(ApplicationBoundaryKind.CAPTCHA, f"the page says '{hit}'")
    return None


def _detect_signature(
    text: str,
    urls: Sequence[str],
    markers: Sequence[str],
    labels: Sequence[str],
) -> ApplicationBoundary | None:
    hit = _first_hit_in(_SIGNATURE_URL_MARKERS, urls)
    if hit is not None:
        return _boundary(
            ApplicationBoundaryKind.SIGNATURE,
            f"the page embeds an e-signature provider ('{hit}')",
        )

    hit = _first_hit_in(_SIGNATURE_MARKERS, markers, whole_token=True)
    if hit is not None:
        return _boundary(
            ApplicationBoundaryKind.SIGNATURE,
            f"the form carries a signature widget ('{hit}')",
        )

    hit = _first_label_hit(_SIGNATURE_LABEL_PHRASES, labels)
    if hit is not None:
        return _boundary(
            ApplicationBoundaryKind.SIGNATURE,
            f"the form has a field labelled '{hit}'",
        )

    hit = _first_hit(_SIGNATURE_PHRASES, text)
    if hit is not None:
        return _boundary(ApplicationBoundaryKind.SIGNATURE, f"the page says '{hit}'")
    return None


def _boundary(kind: ApplicationBoundaryKind, evidence: str) -> ApplicationBoundary:
    return ApplicationBoundary(kind=kind, evidence=evidence)


def _first_hit(needles: Iterable[str], haystack: str) -> str | None:
    """The first needle `haystack` contains, or None."""
    if not haystack:
        return None
    return next((needle for needle in needles if needle in haystack), None)


def _first_hit_in(
    needles: Iterable[str], haystacks: Sequence[str], *, whole_token: bool = False
) -> str | None:
    """The first haystack matching any needle, reported as the haystack.

    The *observed* value is returned rather than the rule that matched it,
    because that is what makes the evidence checkable: "loads a widget from
    `https://www.google.com/recaptcha/api2/anchor`" tells a candidate
    something, "matched 'recaptcha'" does not.

    `whole_token` compares markup tokens for equality instead of
    containment, so a company class name like `captcha-free-hiring` cannot
    be read as a challenge widget.
    """
    for haystack in haystacks:
        for needle in needles:
            matched = haystack == needle if whole_token else needle in haystack
            if matched:
                return haystack
    return None


def _first_label_hit(needles: Iterable[str], labels: Sequence[str]) -> str | None:
    """The first field label containing any needle, reported as the label."""
    for label in labels:
        if any(needle in label for needle in needles):
            return label
    return None


def _path_of(url: str) -> str:
    """The path component of `url`, without host or query.

    Hand-rolled rather than `urlparse` to keep this module free of imports
    that would tempt it into resolving or fetching anything: it is reading
    a string it was handed, not addressing a resource.
    """
    without_scheme = url.split("://", 1)[-1]
    without_query = without_scheme.split("?", 1)[0].split("#", 1)[0]
    slash = without_query.find("/")
    return without_query[slash:] if slash >= 0 else "/"

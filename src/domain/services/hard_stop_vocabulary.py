"""The vocabulary that recognizes a hard boundary on an application portal.

One definition, two readers: `HardStopDetector` matches it against a whole
page to decide whether to hand off, and `HumanOnlyFieldPolicy` matches it
against a single field to decide whether that field may ever be filled. Two
copies would drift, and a drifted copy is the worst possible bug here — a
field the page-level rules called a boundary but the field-level rules agreed
to type into.

How the lists are chosen
------------------------
**Vendor tokens** are matched against what a page loads and how its markup is
named (`PortalPageSignals.machine_tokens`). They are the strongest signals
available: a CAPTCHA is recognizable from the script it pulls in before it
renders anything, and a signing provider names its own iframe. Substrings are
matched, so `recaptcha` also catches `recaptcha__en.js` and
`www.recaptcha.net`.

**Phrases** are matched against what the page says to a person. They are
weaker (a phrase can appear in a job description) and are chosen to be
*actionable* rather than merely topical: "log in to apply" is a wall,
"benefits include login-free SSO" is prose.

**Label tokens** are matched only against the labels of fields the portal
wants filled, where a single word is decisive: a field labeled "Signature" is
the boundary, while "signature" in body text is not.

The lists err toward stopping, and the asymmetry is the point. A false
hand-off costs the candidate one look at a page they were going to see
anyway. A missed boundary costs the thing this whole module exists to
prevent: software answering a "are you human?" challenge, signing an
attestation, or typing a credential on someone's behalf. Those are not
equivalent errors, so they are not weighted equally.
"""

from __future__ import annotations

from collections.abc import Iterable


def contains_any(needles: Iterable[str], haystack: str) -> bool:
    """Whether any vocabulary entry appears in an already-lowercased string.

    Lives with the vocabulary rather than in either reader, so both match it
    the same way — substring, case-folded by the caller — and neither can
    quietly adopt stricter matching than the other.
    """
    return any(needle in haystack for needle in needles)


#: CAPTCHA and bot-challenge providers, matched against machine surfaces.
#:
#: Ordered most specific first, and every list in this module follows that
#: rule: readers report only the first few matches as evidence, so the entry
#: that names the actual vendor should be the one the candidate is shown.
#: Bare "captcha" comes last on purpose — it subsumes most vendors and catches
#: any in-house challenge that names itself honestly, but "loads a known
#: CAPTCHA component ('recaptcha')" says more than "('captcha')".
CAPTCHA_VENDOR_TOKENS: tuple[str, ...] = (
    "g-recaptcha",
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "challenges.cloudflare.com",
    "arkoselabs",
    "funcaptcha",
    "geetest",
    "friendlycaptcha",
    "altcha",
    "datadome",
    "perimeterx",
    "data-sitekey",
    "captcha",
)

#: What a challenge says to the person in front of it.
CAPTCHA_PHRASES: tuple[str, ...] = (
    "i'm not a robot",
    "i am not a robot",
    "verify you are human",
    "verify you're human",
    "verify that you are human",
    "confirm you are human",
    "prove you are human",
    "are you a human",
    "human verification",
    "not a robot",
    "security check",
    "complete the captcha",
    "type the characters you see",
    "enter the characters",
    "select all images",
    "unusual traffic",
)

#: Field labels and control names that mean "answer the challenge here".
CAPTCHA_LABEL_TOKENS: tuple[str, ...] = (
    "captcha",
    "verification code shown",
    "characters you see",
    "i am not a robot",
    "i'm not a robot",
)

#: E-signature providers and the widget names signature pads use.
SIGNATURE_VENDOR_TOKENS: tuple[str, ...] = (
    "docusign",
    "adobesign",
    "echosign",
    "hellosign",
    "dropboxsign",
    "signnow",
    "pandadoc",
    "eversign",
    "signaturepad",
    "signature-pad",
    "signature_pad",
    "esignature",
    "e-signature",
    "esign",
)

#: What a page says when it is collecting a signature. Deliberately excludes
#: bare "i certify" and "i agree": an attestation checkbox appears on very
#: nearly every ATS form, and treating one as a signature would hand off
#: every application ApplyFlow ever touched, which is not a safer product —
#: it is an unusable one. What is kept are phrases that describe the act of
#: signing, not of agreeing.
SIGNATURE_PHRASES: tuple[str, ...] = (
    "electronic signature",
    "e-signature",
    "esignature",
    "sign electronically",
    "electronically sign",
    "digital signature",
    "draw your signature",
    "sign here",
    "sign below",
    "by signing below",
    "signature required",
    "type your full name to sign",
    "type your name to sign",
    "typing your name below",
    "your typed name",
    "adopt your signature",
    "docusign",
)

#: Field labels that mean "sign in this box". A field the portal wants a
#: signature written into is a boundary regardless of what the surrounding
#: prose says.
SIGNATURE_LABEL_TOKENS: tuple[str, ...] = (
    "signature",
    "sign here",
    "signed by",
    "e-sign",
    "esign",
)

#: What a sign-in or account-creation gate says. Every one of these ties the
#: credential to *getting further* — which is what makes it a wall rather
#: than a "Sign in" link sitting in a page header.
ACCOUNT_WALL_PHRASES: tuple[str, ...] = (
    "sign in to continue",
    "sign in to apply",
    "log in to continue",
    "log in to apply",
    "login to apply",
    "sign in to your account",
    "please sign in",
    "please log in",
    "you must be signed in",
    "you must be logged in",
    "you need an account",
    "create an account to apply",
    "create an account to continue",
    "create your account",
    "register to apply",
    "already have an account",
    "forgot your password",
    "forgot password",
    "sign in with",
    "continue with google",
    "continue with linkedin",
    "session has expired",
    "your session expired",
)

#: Path segments a portal uses for its credential pages, matched against the
#: URL actually landed on — so an apply link that redirects into a login flow
#: is caught by where it ended up rather than by what it displays.
#:
#: Matched as WHOLE segments (see `PortalPageSignals.url_path_segments`), not
#: as substrings, and that is not fussiness. DocuSign serves its signing flow
#: from `docusign.net/signing/...`, and "signing" contains "signin" — a
#: substring rule reports every signature page as a sign-in wall, which names
#: the wrong boundary and tells the candidate to do the wrong thing.
ACCOUNT_WALL_URL_SEGMENTS: tuple[str, ...] = (
    "login",
    "log-in",
    "signin",
    "sign-in",
    "sign_in",
    "register",
    "registration",
    "create-account",
    "createaccount",
    "auth",
    "oauth",
    "oauth2",
    "sso",
    "session",
)

#: Control names and labels that ask for a credential. `type="password"` is
#: handled on its own (see `HumanOnlyFieldPolicy`) because it needs no
#: vocabulary at all; these catch the portals that mask a plain text input
#: with JavaScript, where the type attribute says nothing.
CREDENTIAL_LABEL_TOKENS: tuple[str, ...] = (
    "password",
    "passphrase",
    "pwd",
    "confirm password",
    "new password",
    "one-time code",
    "verification code",
    "authenticator code",
    "2fa",
    "mfa code",
)

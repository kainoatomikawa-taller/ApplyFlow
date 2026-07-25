"""Tests for HardStopDetector — the check that decides whether ApplyFlow may
touch a portal's form at all.

Two halves, and both matter equally:

- every boundary is recognized on every surface it realistically shows up on
  (a vendor script, the page's prose, a field label, the landed URL, a
  password box), because a portal that gives it away on only one surface is
  the normal case rather than the exotic one;
- the ordinary furniture of an ATS form does *not* trip it. A detector that
  hands off every application would look cautious and be useless, and a
  hand-off that fires constantly is one candidates learn to click past.
"""

from __future__ import annotations

import pytest

from src.domain.exceptions import InvalidValueError
from src.domain.services.hard_stop_detector import HardStopDetector
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.domain.value_objects.portal_page_signals import PortalPageSignals

#: A perfectly ordinary Greenhouse-style application form: real questions, an
#: attestation checkbox, a privacy link, and a "Sign in" link in the header.
#: Nothing here is a boundary, and every false-positive test starts from it.
ORDINARY_FORM = PortalPageSignals(
    url="https://boards.greenhouse.io/globex/jobs/4242",
    title="Senior Platform Engineer at Globex",
    text=(
        "Apply for this job. Attach your resume. I certify that the "
        "information provided is true and complete to the best of my "
        "knowledge. I agree to the privacy policy. Sign in Careers Home. "
        "Passwords are never shared with third parties."
    ),
    frame_urls=("https://boards.greenhouse.io/globex/jobs/4242",),
    script_urls=("https://boards.greenhouse.io/embed/job_board.js",),
    element_hints=("application-form", "field-name", "data-source", "submit-btn"),
    field_labels=(
        "Full name",
        "Email",
        "Phone",
        "Resume",
        "Why do you want to work here?",
        "I certify the above is accurate",
    ),
    fillable_field_count=6,
)


@pytest.fixture
def detector() -> HardStopDetector:
    return HardStopDetector()


def _signals(**overrides: object) -> PortalPageSignals:
    """An ordinary form with something changed — so each test states only the
    one signal it is about."""
    base = {
        "url": ORDINARY_FORM.url,
        "title": ORDINARY_FORM.title,
        "text": ORDINARY_FORM.text,
        "frame_urls": ORDINARY_FORM.frame_urls,
        "script_urls": ORDINARY_FORM.script_urls,
        "element_hints": ORDINARY_FORM.element_hints,
        "field_labels": ORDINARY_FORM.field_labels,
        "password_field_count": ORDINARY_FORM.password_field_count,
        "fillable_field_count": ORDINARY_FORM.fillable_field_count,
    }
    base.update(overrides)
    return PortalPageSignals(**base)  # type: ignore[arg-type]


def _kinds(detector: HardStopDetector, signals: PortalPageSignals) -> set[HardStopKind]:
    return {stop.kind for stop in detector.detect(signals)}


# ---- the page that must NOT hand off ----------------------------------------


def test_an_ordinary_application_form_is_not_a_hard_stop(detector):
    assert detector.detect(ORDINARY_FORM) == ()
    assert detector.has_hard_stop(ORDINARY_FORM) is False


def test_an_attestation_checkbox_is_not_a_signature(detector):
    """"I certify that the above is true" appears on nearly every ATS form.
    Reading it as an e-signature would hand off every application."""
    signals = _signals(
        text="I certify that the information above is accurate. I agree to the terms.",
        field_labels=("Full name", "I certify the above is accurate"),
    )

    assert HardStopKind.ELECTRONIC_SIGNATURE not in _kinds(detector, signals)


def test_a_sign_in_link_in_the_header_is_not_an_account_wall(detector):
    """A portal that offers an account is not a portal that requires one."""
    signals = _signals(
        text="Apply for this job. Sign in Careers Create profile Help",
        element_hints=("header-signin", "nav-login-link"),
    )

    assert HardStopKind.ACCOUNT_WALL not in _kinds(detector, signals)


def test_prose_about_signatures_on_hire_is_not_a_signature_boundary(detector):
    """A job description mentioning a signature later in the process is
    describing a future event, not asking for one now."""
    signals = _signals(
        text=(
            "An offer letter will require a signature upon hire. Background "
            "checks apply."
        )
    )

    assert HardStopKind.ELECTRONIC_SIGNATURE not in _kinds(detector, signals)


def test_a_script_served_from_an_auth_directory_is_not_a_login_page(detector):
    """URL rules read only where the browser actually navigated. A bundle
    under `/auth/` on a page whose form is fillable is not a wall."""
    signals = _signals(
        script_urls=("https://cdn.globex.example.com/auth/session-widget.js",)
    )

    assert detector.detect(signals) == ()


# ---- CAPTCHA ----------------------------------------------------------------


def test_a_recaptcha_frame_is_a_captcha_hard_stop(detector):
    signals = _signals(
        frame_urls=(
            ORDINARY_FORM.url,
            "https://www.google.com/recaptcha/api2/anchor?k=6Lc",
        )
    )

    stops = detector.detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.CAPTCHA]
    assert any("recaptcha" in line for line in stops[0].evidence)


def test_a_captcha_vendor_script_is_enough_on_its_own(detector):
    """Recognized before the widget renders a single word — which is the
    whole reason machine surfaces are read at all."""
    signals = _signals(script_urls=("https://hcaptcha.com/1/api.js",))

    assert _kinds(detector, signals) == {HardStopKind.CAPTCHA}


def test_a_turnstile_widget_named_only_in_the_markup_is_caught(detector):
    signals = _signals(element_hints=("cf-turnstile", "data-sitekey", "0x4aaa"))

    assert _kinds(detector, signals) == {HardStopKind.CAPTCHA}


def test_a_challenge_recognized_only_from_its_prose_is_caught(detector):
    """An in-house challenge that loads no vendor script still says what it
    is to the person in front of it."""
    signals = _signals(
        text="Security check: confirm you are human before continuing.",
        script_urls=(),
        element_hints=("challenge-box",),
    )

    assert _kinds(detector, signals) == {HardStopKind.CAPTCHA}


def test_only_the_most_specific_vendor_match_is_reported(detector):
    """"recaptcha" also contains "captcha". The candidate is shown the entry
    that names the provider, not a generic substring of it."""
    signals = _signals(script_urls=("https://www.google.com/recaptcha/api.js",))

    vendor_lines = [
        line
        for line in detector.detect(signals)[0].evidence
        if "loads a known CAPTCHA component" in line
    ]

    assert len(vendor_lines) == 1
    assert "recaptcha" in vendor_lines[0]


# ---- e-signature ------------------------------------------------------------


def test_a_docusign_frame_is_a_signature_hard_stop(detector):
    signals = _signals(
        frame_urls=(ORDINARY_FORM.url, "https://na3.docusign.net/signing/1"),
    )

    assert _kinds(detector, signals) == {HardStopKind.ELECTRONIC_SIGNATURE}


def test_a_field_labelled_signature_is_a_signature_hard_stop(detector):
    """The label is decisive where the prose is not: a field the portal wants
    a signature written into is the boundary itself."""
    signals = _signals(
        field_labels=("Full name", "Applicant signature", "Date"),
        fillable_field_count=3,
    )

    stops = detector.detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.ELECTRONIC_SIGNATURE]
    assert any("applicant signature" in line for line in stops[0].evidence)


def test_a_signature_pad_widget_is_caught_from_the_markup(detector):
    signals = _signals(element_hints=("signature-pad", "canvas-wrapper"))

    assert _kinds(detector, signals) == {HardStopKind.ELECTRONIC_SIGNATURE}


def test_typing_your_name_as_a_signature_is_a_signature_hard_stop(detector):
    signals = _signals(
        text="Type your full name to sign this authorization electronically."
    )

    assert _kinds(detector, signals) == {HardStopKind.ELECTRONIC_SIGNATURE}


# ---- account wall -----------------------------------------------------------


def test_a_password_field_is_always_an_account_wall(detector):
    """The one signal that needs no interpretation: whatever else the page
    is, it is asking for a credential ApplyFlow does not have."""
    signals = _signals(
        field_labels=("Email", "Password"),
        password_field_count=1,
        fillable_field_count=2,
    )

    stops = detector.detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.ACCOUNT_WALL]
    assert stops[0].evidence[0] == "the form presents 1 password field"


def test_an_apply_link_that_redirected_to_a_login_page_is_an_account_wall(detector):
    """Where the browser *landed* is the signal — the apply URL promised a
    form and the portal answered with a credential page."""
    signals = _signals(
        url="https://globex.example.com/login?next=/apply/4242",
        frame_urls=("https://globex.example.com/login?next=/apply/4242",),
        text="Welcome back",
        field_labels=(),
        fillable_field_count=0,
    )

    stops = detector.detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.ACCOUNT_WALL]
    assert any("credential page" in line for line in stops[0].evidence)


def test_a_page_demanding_sign_in_to_apply_is_an_account_wall(detector):
    signals = _signals(text="You must be signed in to apply for this role.")

    assert _kinds(detector, signals) == {HardStopKind.ACCOUNT_WALL}


def test_an_account_creation_step_is_an_account_wall(detector):
    signals = _signals(
        text="Create an account to apply. Already have an account? Sign in.",
        field_labels=("Email", "Choose a password", "Confirm password"),
        fillable_field_count=3,
    )

    assert _kinds(detector, signals) == {HardStopKind.ACCOUNT_WALL}


def test_a_page_with_no_form_at_all_can_still_be_a_boundary(detector):
    """An SSO gate presents nothing fillable. A detector that needed a form
    to reason about would report this page as clean."""
    signals = PortalPageSignals(
        url="https://globex.example.com/sso/start",
        title="Sign in to continue",
        text="Continue with Google",
    )

    assert _kinds(detector, signals) == {HardStopKind.ACCOUNT_WALL}


# ---- several at once --------------------------------------------------------


def test_a_login_page_behind_a_captcha_reports_both_in_a_fixed_order(detector):
    """Two boundaries, and the order never varies: a stored hand-off is
    re-read and compared against later readings of the same portal."""
    signals = _signals(
        url="https://globex.example.com/login",
        frame_urls=("https://www.google.com/recaptcha/api2/anchor",),
        text="Sign in to continue. Verify you are human.",
        field_labels=("Email", "Password"),
        password_field_count=1,
        fillable_field_count=2,
    )

    assert [stop.kind for stop in detector.detect(signals)] == [
        HardStopKind.CAPTCHA,
        HardStopKind.ACCOUNT_WALL,
    ]


def test_evidence_is_capped_so_a_hand_off_stays_readable(detector):
    signals = _signals(
        url="https://globex.example.com/login",
        text=(
            "Sign in to continue. Please log in. Already have an account? "
            "Forgot your password? You must be signed in. Create your account. "
            "Your session expired."
        ),
        field_labels=("Email", "Password", "Confirm password", "One-time code"),
        password_field_count=2,
        fillable_field_count=4,
    )

    evidence = detector.detect(signals)[0].evidence

    assert 0 < len(evidence) <= 6
    assert len(set(evidence)) == len(evidence)


# ---- the signals value object ----------------------------------------------


def test_signals_require_the_url_they_were_read_from():
    """A reading with no page is not evidence about any page."""
    with pytest.raises(InvalidValueError):
        PortalPageSignals(url="  ")


def test_signals_reject_a_negative_field_count():
    with pytest.raises(InvalidValueError):
        PortalPageSignals(url="https://x.example.com", fillable_field_count=-1)


def test_matching_is_case_insensitive(detector):
    """Portals capitalize however they like; the rules do not care."""
    signals = _signals(text="SIGN IN TO CONTINUE", field_labels=("EMAIL",))

    assert _kinds(detector, signals) == {HardStopKind.ACCOUNT_WALL}

"""Tests for `detect_application_boundaries` — the rules that decide when
an application page has reached a point only the candidate can pass.

Both directions are tested deliberately and at similar weight. A missed
boundary is an application that stalls; a *false* boundary is an autofill
the candidate loses on a form that was perfectly fillable, plus a hand-off
message they learn to disbelieve. The "ordinary form" cases below are what
keeps the second from happening.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from src.domain.services.application_boundary_detector import (
    detect_application_boundaries,
)
from src.domain.value_objects.application_boundary import (
    ApplicationBoundary,
    ApplicationBoundaryKind,
)
from src.domain.value_objects.page_signals import PageSignals

Kind = ApplicationBoundaryKind

#: A plausible Greenhouse form: no challenge, no signature, no login.
ORDINARY_TEXT = (
    "Apply for Senior Backend Engineer at Globex. "
    "Fill in the fields below and attach your resume. "
    "By submitting this application you confirm the information is accurate."
)


def kinds(
    signals: PageSignals,
    *,
    field_labels: Sequence[str] = (),
    has_password_field: bool = False,
) -> tuple[ApplicationBoundaryKind, ...]:
    boundaries = detect_application_boundaries(
        signals, field_labels=field_labels, has_password_field=has_password_field
    )
    return tuple(boundary.kind for boundary in boundaries)


# ---- Nothing to hand off ----------------------------------------------------


def test_an_ordinary_application_form_has_no_boundaries() -> None:
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text=ORDINARY_TEXT,
        frame_urls=("https://boards.greenhouse.io/embed/job_app",),
        script_urls=("https://boards.greenhouse.io/embed/job_board.js",),
        element_markers=("application-form", "field", "resume-upload"),
    )

    assert (
        detect_application_boundaries(
            signals, field_labels=("First name", "Email", "Resume")
        )
        == ()
    )


def test_the_consent_paragraph_about_electronic_signatures_is_not_a_boundary() -> None:
    """The single most common false positive available here.

    A large share of ordinary ATS forms carry boilerplate saying that
    submitting constitutes an electronic signature. No signature is being
    asked for — there is no widget and no field — and treating that
    sentence as a boundary would block submission on forms that never
    wanted one.
    """
    signals = PageSignals(
        url="https://jobs.lever.co/globex/8f2a/apply",
        visible_text=(
            "By clicking Submit Application, I agree that this submission "
            "constitutes an electronic signature and that the information "
            "provided is true."
        ),
        element_markers=("application", "consent"),
    )

    assert detect_application_boundaries(signals, field_labels=("Full name",)) == ()


def test_a_company_class_name_that_merely_contains_a_marker_is_not_a_widget() -> None:
    """Markup tokens are matched whole. `captcha-free-hiring` is a claim in
    a class name, not a challenge."""
    signals = PageSignals(
        url="https://jobs.ashbyhq.com/globex/1a2b",
        visible_text=ORDINARY_TEXT,
        element_markers=("captcha-free-hiring", "no-captcha-here"),
    )

    assert detect_application_boundaries(signals) == ()


def test_a_redirect_parameter_naming_a_sign_in_page_is_not_a_login_wall() -> None:
    """The path is what says where you are; the query says where you would
    be sent *if* you were not signed in."""
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001?redirect_to=/login",
        visible_text=ORDINARY_TEXT,
    )

    assert detect_application_boundaries(signals) == ()


# ---- CAPTCHA ----------------------------------------------------------------


@pytest.mark.parametrize(
    "frame_url",
    [
        "https://www.google.com/recaptcha/api2/anchor?k=6Lc",
        "https://newassets.hcaptcha.com/captcha/v1/frame",
        "https://challenges.cloudflare.com/turnstile/v0/api.js",
        "https://client-api.arkoselabs.com/v2/enforcement.html",
    ],
)
def test_a_challenge_widget_frame_is_a_captcha(frame_url: str) -> None:
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text=ORDINARY_TEXT,
        frame_urls=(frame_url,),
    )

    assert kinds(signals) == (Kind.CAPTCHA,)


def test_a_challenge_script_counts_before_the_widget_has_painted() -> None:
    """A challenge that has fetched its script but not yet rendered is
    still a challenge — the form is not submittable without it."""
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text=ORDINARY_TEXT,
        script_urls=("https://www.google.com/recaptcha/api.js",),
    )

    assert kinds(signals) == (Kind.CAPTCHA,)


def test_a_challenge_container_token_is_a_captcha() -> None:
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text=ORDINARY_TEXT,
        element_markers=("application-form", "g-recaptcha"),
    )

    assert kinds(signals) == (Kind.CAPTCHA,)


def test_a_self_rendered_challenge_is_caught_by_what_it_asks() -> None:
    """A portal painting its own challenge exposes no provider URL and no
    known token; the instruction to the person is all that is left."""
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text="Before you continue, please verify you are human.",
    )

    assert kinds(signals) == (Kind.CAPTCHA,)


def test_the_evidence_names_what_was_actually_seen() -> None:
    """Evidence is shown to the candidate, so it reports the observation
    rather than the rule that matched it."""
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        frame_urls=("https://www.google.com/recaptcha/api2/anchor?k=6Lc",),
    )

    (boundary,) = detect_application_boundaries(signals)
    assert "https://www.google.com/recaptcha/api2/anchor?k=6lc" in boundary.evidence


# ---- Signature --------------------------------------------------------------


def test_an_embedded_e_signature_provider_is_a_signature_boundary() -> None:
    signals = PageSignals(
        url="https://jobs.lever.co/globex/8f2a/apply",
        visible_text=ORDINARY_TEXT,
        frame_urls=("https://demo.docusign.net/signing/embedded",),
    )

    assert kinds(signals) == (Kind.SIGNATURE,)


def test_a_signature_pad_widget_is_a_signature_boundary() -> None:
    signals = PageSignals(
        url="https://jobs.lever.co/globex/8f2a/apply",
        visible_text=ORDINARY_TEXT,
        element_markers=("application", "signature-pad"),
    )

    assert kinds(signals) == (Kind.SIGNATURE,)


def test_a_field_asking_for_a_signature_is_a_signature_boundary() -> None:
    """The typed-name shape: an ordinary text input whose label is the
    whole boundary."""
    signals = PageSignals(
        url="https://jobs.lever.co/globex/8f2a/apply", visible_text=ORDINARY_TEXT
    )

    assert kinds(
        signals, field_labels=("Full name", "Signature (type your full name)")
    ) == (Kind.SIGNATURE,)


def test_an_instruction_to_sign_is_a_signature_boundary() -> None:
    signals = PageSignals(
        url="https://jobs.lever.co/globex/8f2a/apply",
        visible_text="Please draw your signature in the box below.",
    )

    assert kinds(signals) == (Kind.SIGNATURE,)


# ---- Login ------------------------------------------------------------------


def test_a_password_field_is_a_login_boundary() -> None:
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text="Welcome back.",
    )

    assert kinds(signals, has_password_field=True) == (Kind.LOGIN,)


def test_a_sign_in_route_is_a_login_boundary() -> None:
    signals = PageSignals(
        url="https://boards.greenhouse.io/users/sign_in?next=/globex/jobs/4001",
        visible_text="Welcome back.",
    )

    assert kinds(signals) == (Kind.LOGIN,)


def test_a_page_asking_to_be_signed_into_is_a_login_boundary() -> None:
    signals = PageSignals(
        url="https://jobs.ashbyhq.com/globex/1a2b",
        visible_text="Please sign in to continue to the application.",
    )

    assert kinds(signals) == (Kind.LOGIN,)


def test_the_login_evidence_leads_with_the_password_field() -> None:
    """The strongest signal, and the one a candidate can check at a glance."""
    signals = PageSignals(url="https://portal.example.com/users/sign_in")

    (boundary,) = detect_application_boundaries(signals, has_password_field=True)
    assert boundary.evidence == "the page asks for a password"


# ---- Several at once --------------------------------------------------------


def test_every_boundary_on_a_page_is_reported_in_a_fixed_order() -> None:
    """All three at once — the order is login, CAPTCHA, signature, so a
    hand-off screen and a test read the same sequence every time."""
    signals = PageSignals(
        url="https://portal.example.com/sign-in",
        visible_text="Please sign in to continue. Then draw your signature.",
        frame_urls=("https://www.google.com/recaptcha/api2/anchor",),
    )

    assert kinds(signals, has_password_field=True) == (
        Kind.LOGIN,
        Kind.CAPTCHA,
        Kind.SIGNATURE,
    )


def test_one_kind_is_reported_once_however_many_signals_agree() -> None:
    signals = PageSignals(
        url="https://boards.greenhouse.io/globex/jobs/4001",
        visible_text="Tick the box to confirm you are human.",
        frame_urls=("https://www.google.com/recaptcha/api2/anchor",),
        script_urls=("https://www.google.com/recaptcha/api.js",),
        element_markers=("g-recaptcha", "recaptcha"),
    )

    assert kinds(signals) == (Kind.CAPTCHA,)


# ---- What a boundary means --------------------------------------------------


def test_only_a_login_stops_the_autofill_pass() -> None:
    """A CAPTCHA or a signature request sits on a form that is otherwise
    worth filling; a login wall means the form is not even on screen."""
    seen = "seen"
    assert ApplicationBoundary(Kind.LOGIN, seen).stops_autofill is True
    assert ApplicationBoundary(Kind.CAPTCHA, seen).stops_autofill is False
    assert ApplicationBoundary(Kind.SIGNATURE, seen).stops_autofill is False


def test_every_boundary_blocks_submission() -> None:
    for kind in ApplicationBoundaryKind:
        assert ApplicationBoundary(kind, "seen").blocks_unattended_submit is True


def test_every_boundary_can_tell_the_candidate_what_to_do() -> None:
    for kind in ApplicationBoundaryKind:
        instruction = ApplicationBoundary(kind, "seen").instruction
        assert instruction.strip()
        # It has to say what the candidate does next, not just what failed.
        assert "you" in instruction.casefold()


def test_a_boundary_must_record_what_was_seen() -> None:
    with pytest.raises(ValueError, match="what was seen"):
        ApplicationBoundary(Kind.CAPTCHA, "   ")

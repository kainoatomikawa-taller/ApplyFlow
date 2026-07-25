"""Tests for HumanOnlyFieldPolicy — the per-field half of the safety rule.

This is what stands behind "ApplyFlow never solves CAPTCHAs, creates accounts,
or enters passwords" at the level of a single control, so the tests are about
two things: it recognizes a credential/signature/challenge field however the
portal dressed it up, and it does not claim ordinary application questions.
"""

from __future__ import annotations

from src.domain.services.human_only_field_policy import HumanOnlyFieldPolicy
from src.domain.value_objects.hard_stop_kind import HardStopKind

boundary_for = HumanOnlyFieldPolicy.boundary_for


# ---- credentials ------------------------------------------------------------


def test_a_password_input_is_a_boundary_by_kind_alone():
    """No vocabulary involved: `type="password"` is a credential whatever the
    portal labels it."""
    assert (
        boundary_for(kind_name="password", label="Access code")
        is HardStopKind.ACCOUNT_WALL
    )


def test_a_text_input_named_password_is_a_boundary():
    """Portals that mask a plain text input with JavaScript leave the type
    attribute saying nothing, so the markup's own names are read too."""
    assert (
        boundary_for(kind_name="text", label="", name="user_password")
        is HardStopKind.ACCOUNT_WALL
    )


def test_an_autocomplete_hint_gives_a_disguised_credential_away():
    assert (
        boundary_for(
            kind_name="text",
            label="Enter your details",
            attribute_values=("current-password",),
        )
        is HardStopKind.ACCOUNT_WALL
    )


def test_a_one_time_code_field_is_a_credential():
    assert (
        boundary_for(kind_name="text", label="One-time code")
        is HardStopKind.ACCOUNT_WALL
    )


# ---- signatures and challenges ---------------------------------------------


def test_a_signature_field_is_a_signature_boundary():
    assert (
        boundary_for(kind_name="text", label="Applicant signature")
        is HardStopKind.ELECTRONIC_SIGNATURE
    )


def test_a_captcha_response_field_is_a_captcha_boundary():
    assert (
        boundary_for(kind_name="text", name="g-recaptcha-response")
        is HardStopKind.CAPTCHA
    )


def test_a_control_naming_both_reads_as_the_challenge():
    """A field called "captcha_signature" is a challenge answer. Either way
    the write is refused; the boundary reported has to be the right one so
    the candidate is told to do the right thing."""
    assert (
        boundary_for(kind_name="text", name="captcha_signature")
        is HardStopKind.CAPTCHA
    )


# ---- ordinary questions -----------------------------------------------------


def test_ordinary_application_questions_are_not_boundaries():
    for label, name in (
        ("Full name", "full_name"),
        ("Email", "email"),
        ("Why do you want to work here?", "cover_letter"),
        ("Are you authorized to work in the US?", "authorized"),
        ("LinkedIn profile", "linkedin_url"),
        ("Desired salary", "salary"),
    ):
        assert boundary_for(kind_name="text", label=label, name=name) is None, label


def test_a_field_with_nothing_said_about_it_is_not_a_boundary():
    """An unnamed, unlabeled text box is an unknown question, not a
    credential — guessing otherwise would refuse to fill real forms."""
    assert boundary_for(kind_name="text") is None


def test_a_resume_upload_is_not_a_boundary():
    assert boundary_for(kind_name="file", label="Resume", name="resume") is None

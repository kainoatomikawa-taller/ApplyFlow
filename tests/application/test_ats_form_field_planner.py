"""Tests for `AtsFormFieldPlanner` — the decision made about each field,
before anything touches a browser."""

from datetime import date

import pytest

from src.application.ports.browser_automation_port import (
    FormField,
    FormFieldKind,
    FormFieldOption,
)
from src.application.services.ats_form_field_planner import (
    AtsFormFieldPlanner,
    FieldDisposition,
    SurfaceReason,
)
from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.user_profile import UserProfile
from src.domain.value_objects.application_field_slot import ApplicationFieldSlot
from src.domain.value_objects.ats_provider import AtsProvider
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource

Slot = ApplicationFieldSlot


def field(
    label: str = "",
    *,
    handle: str = "h1",
    kind: FormFieldKind = FormFieldKind.TEXT,
    name: str = "",
    required: bool = False,
    options: tuple[FormFieldOption, ...] = (),
    attributes: dict[str, str] | None = None,
) -> FormField:
    return FormField(
        handle=handle,
        kind=kind,
        label=label,
        name=name,
        required=required,
        options=options,
        attributes=attributes or {},
    )


@pytest.fixture
def planner() -> AtsFormFieldPlanner:
    return AtsFormFieldPlanner()


@pytest.fixture
def profile() -> UserProfile:
    profile = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
        phone="+1 512 555 0100",
    )
    profile.set_links(
        ProfileLinks(linkedin_url="https://www.linkedin.com/in/danareyes"),
        ProvenanceSource.USER_ENTERED,
    )
    profile.add_education(
        EducationEntry(
            id="edu-1",
            institution_name="UT Austin",
            degree="B.S.",
            field_of_study="Computer Science",
            start_date=date(2012, 8, 1),
            end_date=date(2016, 5, 15),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    return profile


def plan_one(planner, profile, form_field, provider=AtsProvider.GREENHOUSE):
    planned = planner.plan((form_field,), provider=provider, profile=profile)
    assert len(planned) == 1
    return planned[0]


# ---- Standard fields are filled ---------------------------------------------


@pytest.mark.parametrize(
    ("label", "name", "kind", "expected_slot", "expected_value"),
    [
        (
            "Email *",
            "job_application[email]",
            FormFieldKind.EMAIL,
            Slot.EMAIL,
            "dana@example.com",
        ),
        (
            "Phone",
            "job_application[phone]",
            FormFieldKind.PHONE,
            Slot.PHONE,
            "+1 512 555 0100",
        ),
        (
            "LinkedIn URL",
            "",
            FormFieldKind.URL,
            Slot.LINKEDIN_URL,
            "https://www.linkedin.com/in/danareyes",
        ),
        (
            "School",
            "job_application[educations][][school_name_id]",
            FormFieldKind.TEXT,
            Slot.SCHOOL,
            "UT Austin",
        ),
    ],
)
def test_recognized_fields_with_profile_data_are_filled(
    planner, profile, label, name, kind, expected_slot, expected_value
):
    planned = plan_one(planner, profile, field(label, kind=kind, name=name))

    assert planned.disposition is FieldDisposition.FILL
    assert planned.slot is expected_slot
    assert planned.value == expected_value
    assert planned.surface_reason is None


def test_a_derived_value_is_planned_and_flagged(planner, profile):
    planned = plan_one(
        planner, profile, field("First Name *", name="job_application[first_name]")
    )

    assert planned.disposition is FieldDisposition.FILL
    assert planned.value == "Dana"
    assert planned.is_derived is True


def test_a_select_is_filled_and_left_for_the_harness_to_accept_or_refuse(
    planner, profile
):
    """The planner does not pre-check options against the value: matching an
    option is the harness's job, and it refuses rather than approximates."""
    planned = plan_one(
        planner,
        profile,
        field(
            "Degree",
            kind=FormFieldKind.SELECT,
            name="job_application[educations][][degree_id]",
            options=(FormFieldOption(label="B.S.", value="4"),),
        ),
    )

    assert planned.disposition is FieldDisposition.FILL
    assert planned.value == "B.S."


# ---- Documents ---------------------------------------------------------------


def test_a_resume_upload_is_planned_as_an_attachment(planner, profile):
    planned = plan_one(
        planner,
        profile,
        field("Resume/CV *", kind=FormFieldKind.FILE, name="job_application[resume]"),
    )

    assert planned.disposition is FieldDisposition.ATTACH_DOCUMENT
    assert planned.slot is Slot.RESUME
    assert planned.document_kind is GeneratedDocumentKind.TAILORED_RESUME


def test_a_cover_letter_textarea_is_planned_as_pasted_text(planner, profile):
    """Whether the document arrives as a file or as text is the form's
    choice, not the slot's."""
    planned = plan_one(
        planner,
        profile,
        field(
            "Cover Letter",
            kind=FormFieldKind.TEXTAREA,
            name="job_application[cover_letter_text]",
        ),
    )

    assert planned.disposition is FieldDisposition.FILL_DOCUMENT_TEXT
    assert planned.slot is Slot.COVER_LETTER
    assert planned.document_kind is GeneratedDocumentKind.COVER_LETTER


def test_a_cover_letter_checkbox_is_surfaced_not_ticked(planner, profile):
    """ "I'd like to include a cover letter" is a preference, not the
    document — answering it would be guessing at intent."""
    planned = plan_one(
        planner,
        profile,
        field("Include a cover letter", kind=FormFieldKind.CHECKBOX),
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot is Slot.COVER_LETTER
    assert planned.surface_reason is SurfaceReason.UNSUPPORTED_FIELD_KIND


# ---- Surfacing ---------------------------------------------------------------


def test_an_unrecognized_field_is_surfaced_with_that_reason(planner, profile):
    planned = plan_one(
        planner,
        profile,
        field(
            "Why do you want to work at Globex?",
            kind=FormFieldKind.TEXTAREA,
            name="job_application[answers_attributes][0][text_value]",
            required=True,
        ),
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot is None
    assert planned.surface_reason is SurfaceReason.UNRECOGNIZED
    assert planned.value is None


def test_a_recognized_field_with_no_profile_data_is_surfaced_as_such(planner, profile):
    """Distinguishing this from "unrecognized" is the point: this one the
    candidate can fix once, on their profile, for every future application."""
    planned = plan_one(planner, profile, field("GitHub URL", kind=FormFieldKind.URL))

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot is Slot.GITHUB_URL
    assert planned.surface_reason is SurfaceReason.NO_PROFILE_DATA


@pytest.mark.parametrize(
    "label",
    [
        "Are you legally authorized to work in the United States?",
        "Will you now or in the future require sponsorship?",
        "Gender",
        "Race / Ethnicity",
        "Are you a protected veteran?",
        "Disability status",
    ],
)
def test_sensitive_self_identification_is_recognized_and_refused(
    planner, profile, label
):
    """Recognized — so a reviewer is told which question it is — and never
    filled."""
    planned = plan_one(
        planner,
        profile,
        field(
            label,
            kind=FormFieldKind.SELECT,
            options=(FormFieldOption(label="Yes", value="1"),),
        ),
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot in {Slot.WORK_AUTHORIZATION, Slot.EEO_SELF_IDENTIFICATION}
    assert planned.surface_reason is SurfaceReason.REQUIRES_CANDIDATE_ANSWER
    assert planned.value is None


def test_a_password_field_is_never_filled(planner, profile):
    planned = plan_one(
        planner, profile, field("Email", kind=FormFieldKind.PASSWORD, name="email")
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.surface_reason is SurfaceReason.UNSUPPORTED_FIELD_KIND


def test_a_checkbox_where_a_value_was_expected_is_surfaced(planner, profile):
    """Writing "+1 512 555 0100" into a tick box means the field was read
    wrongly, so a human looks at it rather than the harness guessing a
    boolean."""
    planned = plan_one(
        planner, profile, field("Phone", kind=FormFieldKind.CHECKBOX, name="phone")
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot is Slot.PHONE
    assert planned.surface_reason is SurfaceReason.UNSUPPORTED_FIELD_KIND


def test_missing_profile_data_is_reported_ahead_of_an_awkward_widget(planner, profile):
    """Both are true of this field; "your profile is silent" is the one the
    candidate can act on."""
    planned = plan_one(
        planner, profile, field("GitHub URL", kind=FormFieldKind.CHECKBOX)
    )

    assert planned.surface_reason is SurfaceReason.NO_PROFILE_DATA


# ---- Completeness ------------------------------------------------------------


def test_every_field_is_returned_in_page_order(planner, profile):
    """Nothing is filtered out. A field the planner dropped is a field nobody
    ever hears about again, which fails the same rule as guessing at it."""
    fields = (
        field("Email", handle="f0", kind=FormFieldKind.EMAIL, name="email"),
        field("Why us?", handle="f1", kind=FormFieldKind.TEXTAREA),
        field("Gender", handle="f2", kind=FormFieldKind.SELECT),
        field("Resume", handle="f3", kind=FormFieldKind.FILE, name="resume"),
    )

    planned = planner.plan(fields, provider=AtsProvider.LEVER, profile=profile)

    assert [item.field.handle for item in planned] == ["f0", "f1", "f2", "f3"]
    assert [item.disposition for item in planned] == [
        FieldDisposition.FILL,
        FieldDisposition.SURFACE,
        FieldDisposition.SURFACE,
        FieldDisposition.ATTACH_DOCUMENT,
    ]


def test_no_field_is_ever_planned_without_a_disposition(planner, profile):
    """Whatever a portal serves, every field comes back actionable: either
    something to do, or a reason it is being left alone."""
    kinds = tuple(FormFieldKind)
    fields = tuple(
        field(label, handle=f"h{index}", kind=kind)
        for index, kind in enumerate(kinds)
        for label in ("Email",)
    ) + tuple(
        field("A question the company wrote?", handle=f"q{index}", kind=kind)
        for index, kind in enumerate(kinds)
    )

    planned = planner.plan(fields, provider=AtsProvider.ASHBY, profile=profile)

    assert len(planned) == len(fields)
    for item in planned:
        if item.disposition is FieldDisposition.SURFACE:
            assert item.surface_reason is not None
        elif item.disposition is FieldDisposition.FILL:
            assert item.value
        else:
            assert item.document_kind is not None


def test_an_empty_form_plans_to_nothing(planner, profile):
    assert planner.plan((), provider=AtsProvider.ASHBY, profile=profile) == ()

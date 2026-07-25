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
from src.domain.value_objects.application_field_slot import (
    ApplicationFieldSlot,
    FieldSensitivity,
)
from src.domain.value_objects.ats_provider import AtsProvider
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus

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


@pytest.fixture
def authorized_profile(profile: UserProfile) -> UserProfile:
    """A candidate who stated their work authorization themselves — a US
    citizen who needs no sponsorship."""
    profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            citizenship_country="United States",
            requires_sponsorship=False,
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    return profile


@pytest.fixture
def eeo_profile(profile: UserProfile) -> UserProfile:
    """A candidate who answered every EEO category. None of it may ever reach
    a form."""
    profile.set_eeo_self_identification(
        EeoSelfIdentification(
            source=ProvenanceSource.ANSWER,
            gender_identity=GenderIdentity.FEMALE,
            race_ethnicity=RaceEthnicity.ASIAN,
            veteran_status=VeteranStatus.PROTECTED_VETERAN,
            disability_status=DisabilityStatus.NO_DISABILITY,
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


# ---- Sensitive fields --------------------------------------------------------


def yes_no(label: str, *, kind: FormFieldKind = FormFieldKind.SELECT) -> FormField:
    """A Yes/No question as the three platforms render one."""
    return field(
        label,
        kind=kind,
        required=True,
        options=(
            FormFieldOption(label="Yes", value="1"),
            FormFieldOption(label="No", value="0"),
        ),
    )


@pytest.mark.parametrize(
    "label",
    [
        "Gender",
        "Race / Ethnicity",
        "Are you a protected veteran?",
        "Disability status",
        "What are your pronouns?",
    ],
)
def test_eeo_is_recognized_and_never_filled(planner, eeo_profile, label):
    """Recognized — so a reviewer is told which question it is — and refused
    even though `eeo_profile` has answered every category."""
    planned = plan_one(planner, eeo_profile, yes_no(label))

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot is Slot.EEO_SELF_IDENTIFICATION
    assert planned.surface_reason is SurfaceReason.REQUIRES_CANDIDATE_ANSWER
    assert planned.value is None
    # Flagged for the review step as the candidate's own choice, not as a gap
    # in their profile.
    assert planned.sensitivity is FieldSensitivity.VOLUNTARY_SELF_ID
    assert planned.requires_confirmation is False


@pytest.mark.parametrize(
    ("label", "expected_slot", "expected_value"),
    [
        (
            "Are you legally authorized to work in the United States? *",
            Slot.WORK_AUTHORIZATION,
            "Yes",
        ),
        (
            "Will you now or in the future require sponsorship?",
            Slot.SPONSORSHIP_REQUIRED,
            "No",
        ),
    ],
)
def test_legal_questions_are_filled_from_attested_data(
    planner, authorized_profile, label, expected_slot, expected_value
):
    """The other half of the policy: leaving a required authorization question
    blank stalls the application, so an exact answer must be given."""
    planned = plan_one(planner, authorized_profile, yes_no(label))

    assert planned.disposition is FieldDisposition.FILL
    assert planned.slot is expected_slot
    assert planned.value == expected_value
    assert planned.sensitivity is FieldSensitivity.LEGAL_ATTESTATION
    # Filled from the candidate's own record, and still theirs to approve.
    assert planned.requires_confirmation is True


@pytest.mark.parametrize("kind", [FormFieldKind.SELECT, FormFieldKind.RADIO])
def test_a_yes_no_legal_question_is_answered_as_a_select_or_a_radio(
    planner, authorized_profile, kind
):
    """A Yes/No radio group is how these questions are most often asked, and
    the harness selects a radio by its own option label."""
    planned = plan_one(
        planner,
        authorized_profile,
        yes_no("Are you legally authorized to work in the US?", kind=kind),
    )

    assert planned.disposition is FieldDisposition.FILL
    assert planned.value == "Yes"


def test_a_legal_question_asked_as_a_checkbox_is_surfaced(planner, authorized_profile):
    """A tick box is unlabelled as to polarity — "I require sponsorship" and
    "I do not require sponsorship" are both real labels, and getting it
    backwards inverts a legal declaration."""
    planned = plan_one(
        planner,
        authorized_profile,
        field("I require visa sponsorship", kind=FormFieldKind.CHECKBOX),
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.slot is Slot.SPONSORSHIP_REQUIRED
    assert planned.surface_reason is SurfaceReason.UNSUPPORTED_FIELD_KIND
    assert planned.value is None


def test_an_unattested_legal_record_is_surfaced_with_its_own_reason(planner, profile):
    """Distinct from "no data": the answer is on file, it just was not stated
    by the candidate, and confirming it on the profile is the fix."""
    profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            requires_sponsorship=False,
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    planned = plan_one(
        planner, profile, yes_no("Are you legally authorized to work in the US?")
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.surface_reason is SurfaceReason.SENSITIVE_DATA_NOT_ATTESTED
    assert planned.value is None


def test_a_legal_question_the_record_cannot_settle_is_surfaced(planner, profile):
    """A visa holder asked about *future* sponsorship — the record does not
    answer it, and approximating is the one thing these fields must not do."""
    profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.VISA_HOLDER,
            source=ProvenanceSource.USER_ENTERED,
        )
    )
    planned = plan_one(
        planner, profile, yes_no("Will you require sponsorship in the future?")
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.surface_reason is SurfaceReason.SENSITIVE_ANSWER_NOT_DERIVABLE


def test_a_legal_question_with_nothing_on_file_reports_the_profile_gap(
    planner, profile
):
    """Same remedy as any other missing profile field, so it reports the same
    reason — a reviewer should not have to learn two words for it."""
    planned = plan_one(
        planner, profile, yes_no("Are you legally authorized to work in the US?")
    )

    assert planned.surface_reason is SurfaceReason.NO_PROFILE_DATA


def test_no_ordinary_field_is_ever_flagged_sensitive(planner, authorized_profile):
    """The flag has to mean something, so it must not be over-applied."""
    for form_field in (
        field("Email", kind=FormFieldKind.EMAIL, name="email"),
        field("First Name", name="job_application[first_name]"),
        field("A question the company wrote?", kind=FormFieldKind.TEXTAREA),
    ):
        planned = plan_one(planner, authorized_profile, form_field)
        assert planned.is_sensitive is False
        assert planned.sensitivity is None
        assert planned.requires_confirmation is False


def test_a_password_field_is_never_filled(planner, profile):
    planned = plan_one(
        planner, profile, field("Email", kind=FormFieldKind.PASSWORD, name="email")
    )

    assert planned.disposition is FieldDisposition.SURFACE
    assert planned.surface_reason is SurfaceReason.UNSUPPORTED_FIELD_KIND


def test_a_field_only_the_candidate_may_fill_is_never_planned_as_a_write(
    planner, profile
):
    """Wider than the password check: a signature line named like a full-name
    field is recognized, and still refused (see `HumanOnlyFieldPolicy`).

    This is the guard that keeps the harness's own refusal
    (`HumanOnlyFieldError`) out of reach. That error is raised at the moment of
    typing and is not caught per field, so a plan that included this write
    would abandon the pass and lose the report for every field already filled
    correctly.
    """
    for form_field in (
        field("Full name", name="job_application[signature]"),
        field("Signature", name="applicant_signature"),
        field("Account access", attributes={"autocomplete": "current-password"}),
    ):
        planned = plan_one(planner, profile, form_field)

        assert planned.disposition is FieldDisposition.SURFACE, form_field
        assert planned.value is None, form_field

    # The one the recognizer *did* match reports being refused rather than
    # unknown, which is the distinction a reviewer needs: ApplyFlow read this
    # field correctly and will still never answer it.
    recognized = plan_one(
        planner, profile, field("Full name", name="job_application[signature]")
    )
    assert recognized.slot is Slot.FULL_NAME
    assert recognized.surface_reason is SurfaceReason.UNSUPPORTED_FIELD_KIND


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

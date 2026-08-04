"""Tests for `AutofillApplicationForm` — the whole pass over a real form
shape, with a fake browser in place of Chromium.

The forms below mirror what the three supported platforms actually serve, so
these tests read as "this Greenhouse form, filled" rather than as a list of
branches.
"""

from datetime import date

import pytest

from src.application.dtos.application_autofill_dtos import (
    AutofillApplicationFormInput,
    FieldAutofillOutcome,
)
from src.application.exceptions import (
    BrowserNavigationError,
    FormFieldNotFillableError,
    RejectedFieldValueError,
    StaleFormFieldError,
    UnsupportedAtsFormError,
)
from src.application.ports.browser_automation_port import (
    FormField,
    FormFieldKind,
    FormFieldOption,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)
from src.application.services.ats_form_field_planner import SurfaceReason
from src.application.use_cases.autofill_application_form import AutofillApplicationForm
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.education_entry import EducationEntry
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import JobPostingNotFoundError, ProfileNotFoundError
from src.domain.value_objects.address import Address
from src.domain.value_objects.application_field_slot import ApplicationFieldSlot
from src.domain.value_objects.eeo_categories import GenderIdentity
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.page_signals import PageSignals
from src.domain.value_objects.profile_links import ProfileLinks
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus
from tests.application.conftest import (
    FakeBrowser,
    FakeBrowserSession,
    InMemoryApplicationDocumentRepository,
    RecordingPdfRenderer,
    SequentialIdGenerator,
    StubJobPostingRepository,
    StubProfileRepository,
)

Slot = ApplicationFieldSlot

GREENHOUSE_URL = "https://boards.greenhouse.io/globex/jobs/4001"
LEVER_URL = "https://jobs.lever.co/globex/8f2a-1b3c/apply"
ASHBY_URL = "https://jobs.ashbyhq.com/globex/1a2b3c4d"


# ---- Fakes -------------------------------------------------------------------


def build_use_case(
    *,
    session: FakeBrowserSession | None = None,
    posting: JobPosting | None = None,
    profile: UserProfile | None = None,
    documents: list[ApplicationDocument] | None = None,
    browser: FakeBrowser | None = None,
    review_sessions: ApplicationReviewSessions | None = None,
) -> tuple[AutofillApplicationForm, FakeBrowser, RecordingPdfRenderer]:
    resolved_browser = browser or FakeBrowser(session)
    renderer = RecordingPdfRenderer()
    use_case = AutofillApplicationForm(
        StubJobPostingRepository(posting),
        StubProfileRepository(profile),
        InMemoryApplicationDocumentRepository(documents),
        resolved_browser,
        renderer,
        review_sessions or ApplicationReviewSessions(SequentialIdGenerator("review")),
    )
    return use_case, resolved_browser, renderer


# ---- Fixtures ----------------------------------------------------------------


@pytest.fixture
def profile() -> UserProfile:
    """A fully-populated candidate, including the two sensitive records that
    must never reach a form."""
    profile = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
        phone="+1 512 555 0100",
        location="Austin, TX",
    )
    profile.set_address(
        Address(
            street_address="120 Congress Ave",
            city="Austin",
            state_or_region="TX",
            postal_code="78701",
            country="United States",
        ),
        ProvenanceSource.USER_ENTERED,
    )
    profile.set_links(
        ProfileLinks(
            linkedin_url="https://www.linkedin.com/in/danareyes",
            github_url="https://github.com/danareyes",
        ),
        ProvenanceSource.USER_ENTERED,
    )
    profile.add_education(
        EducationEntry(
            id="edu-1",
            institution_name="UT Austin",
            degree="B.S.",
            majors=("Computer Science",),
            start_date=date(2012, 8, 1),
            end_date=date(2016, 5, 15),
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            citizenship_country="United States",
            requires_sponsorship=False,
            source=ProvenanceSource.ANSWER,
        )
    )
    profile.set_eeo_self_identification(
        EeoSelfIdentification(
            source=ProvenanceSource.ANSWER, gender_identity=GenderIdentity.FEMALE
        )
    )
    return profile


def posting_at(url: str) -> JobPosting:
    return JobPosting(
        id="job-posting-1",
        source="greenhouse",
        company="Globex",
        title="Senior Platform Engineer",
        apply_url=url,
        description="Platform role.",
    )


@pytest.fixture
def posting() -> JobPosting:
    return posting_at(GREENHOUSE_URL)


def document(
    kind: GeneratedDocumentKind, content: str, *, version: int = 1
) -> ApplicationDocument:
    return ApplicationDocument(
        id=f"doc-{kind.value}-{version}",
        user_id="user-1",
        job_posting_id="job-posting-1",
        document_kind=kind,
        content=content,
        version=version,
        backing_sources=(ProvenanceSource.PARSED_RESUME,),
    )


@pytest.fixture
def documents() -> list[ApplicationDocument]:
    return [
        document(GeneratedDocumentKind.TAILORED_RESUME, "DANA REYES\nEXPERIENCE\n..."),
        document(GeneratedDocumentKind.COVER_LETTER, "Dear Globex team,\n..."),
    ]


def form_field(
    label: str,
    *,
    handle: str,
    kind: FormFieldKind = FormFieldKind.TEXT,
    name: str = "",
    required: bool = False,
    options: tuple[FormFieldOption, ...] = (),
    max_length: int | None = None,
    attributes: dict[str, str] | None = None,
) -> FormField:
    return FormField(
        handle=handle,
        kind=kind,
        label=label,
        name=name,
        required=required,
        options=options,
        max_length=max_length,
        attributes=attributes or {},
    )


def greenhouse_form() -> tuple[FormField, ...]:
    """A representative Greenhouse application: standard fields, an education
    block, a document upload, a company screening question, and the two
    always-asked sensitive questions."""
    return (
        form_field(
            "First Name *",
            handle="f-first",
            name="job_application[first_name]",
            required=True,
        ),
        form_field(
            "Last Name *",
            handle="f-last",
            name="job_application[last_name]",
            required=True,
        ),
        form_field(
            "Email *",
            handle="f-email",
            kind=FormFieldKind.EMAIL,
            name="job_application[email]",
            required=True,
        ),
        form_field(
            "Phone",
            handle="f-phone",
            kind=FormFieldKind.PHONE,
            name="job_application[phone]",
        ),
        form_field(
            "Location (City)", handle="f-location", name="job_application[location]"
        ),
        form_field(
            "Resume/CV *",
            handle="f-resume",
            kind=FormFieldKind.FILE,
            name="job_application[resume]",
            required=True,
        ),
        form_field(
            "Cover Letter",
            handle="f-cover",
            kind=FormFieldKind.TEXTAREA,
            name="job_application[cover_letter_text]",
        ),
        form_field(
            "School",
            handle="f-school",
            name="job_application[educations][][school_name_id]",
        ),
        form_field(
            "Degree", handle="f-degree", name="job_application[educations][][degree_id]"
        ),
        form_field("LinkedIn Profile", handle="f-linkedin", kind=FormFieldKind.URL),
        form_field(
            "Why do you want to work at Globex?",
            handle="f-why",
            kind=FormFieldKind.TEXTAREA,
            required=True,
        ),
        form_field(
            "Are you legally authorized to work in the United States? *",
            handle="f-auth",
            kind=FormFieldKind.SELECT,
            required=True,
            options=(
                FormFieldOption(label="Yes", value="1"),
                FormFieldOption(label="No", value="0"),
            ),
        ),
        form_field(
            "Will you now or in the future require sponsorship? *",
            handle="f-sponsorship",
            kind=FormFieldKind.RADIO,
            required=True,
            options=(
                FormFieldOption(label="Yes", value="1"),
                FormFieldOption(label="No", value="0"),
            ),
        ),
        form_field(
            "Gender",
            handle="f-gender",
            kind=FormFieldKind.SELECT,
            options=(
                FormFieldOption(label="Female", value="2"),
                FormFieldOption(label="Male", value="1"),
                FormFieldOption(label="Decline to self identify", value="0"),
            ),
        ),
        form_field(
            "Are you a protected veteran? *",
            handle="f-veteran",
            kind=FormFieldKind.SELECT,
            required=True,
            options=(
                FormFieldOption(label="I am a protected veteran", value="1"),
                FormFieldOption(label="I am not a protected veteran", value="2"),
            ),
        ),
    )


async def run_greenhouse(profile, posting, documents, **kwargs):
    session = FakeBrowserSession(
        greenhouse_form(), current_url=GREENHOUSE_URL, **kwargs
    )
    use_case, browser, renderer = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )
    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )
    return output, session, renderer


def outcome_for(output, label: str):
    return next(item for item in output.fields if item.label == label)


# ---- The standard fields get filled ------------------------------------------


async def test_standard_fields_are_autofilled_from_the_profile(
    profile, posting, documents
):
    output, session, _ = await run_greenhouse(profile, posting, documents)

    assert dict(session.filled) == {
        "f-first": "Dana",
        "f-last": "Reyes",
        "f-email": "dana@example.com",
        "f-phone": "+1 512 555 0100",
        "f-location": "Austin, TX",
        "f-school": "UT Austin",
        "f-degree": "B.S.",
        "f-linkedin": "https://www.linkedin.com/in/danareyes",
        "f-cover": "Dear Globex team,\n...",
        # The two legal questions, answered exactly from the attested record:
        # a US citizen who stated they need no sponsorship.
        "f-auth": "Yes",
        "f-sponsorship": "No",
    }


async def test_the_resume_is_attached_as_a_rendered_pdf(profile, posting, documents):
    output, session, renderer = await run_greenhouse(profile, posting, documents)

    assert len(session.attached) == 1
    handle, filename, content = session.attached[0]
    assert handle == "f-resume"
    assert filename == "dana-reyes-resume.pdf"
    assert content == b"%PDF-1.4 fake"
    # Rendered from the stored snapshot, not regenerated.
    assert renderer.content == "DANA REYES\nEXPERIENCE\n..."

    attached = outcome_for(output, "Resume/CV *")
    assert attached.outcome == FieldAutofillOutcome.ATTACHED
    assert attached.slot == Slot.RESUME
    assert attached.value == "dana-reyes-resume.pdf"


async def test_a_cover_letter_textarea_receives_the_stored_text(
    profile, posting, documents
):
    output, session, _ = await run_greenhouse(profile, posting, documents)

    pasted = outcome_for(output, "Cover Letter")
    assert pasted.outcome == FieldAutofillOutcome.FILLED
    assert pasted.slot == Slot.COVER_LETTER
    assert session.value_for("f-cover") == "Dear Globex team,\n..."


async def test_the_form_is_read_once_and_the_session_is_parked_for_review(
    profile, posting, documents
):
    """The filled form stays open. The candidate is about to look at it and
    then submit through it, and re-opening the portal to send what was
    already typed would mean filling a real application twice."""
    output, session, _ = await run_greenhouse(profile, posting, documents)

    assert session.read_count == 1
    assert session.closed is False
    assert output.review_session_id is not None
    assert output.review_expires_at is not None
    assert output.can_be_submitted_here is True


async def test_derived_values_are_flagged_in_the_report(profile, posting, documents):
    """The name was split out of one stored field, so a reviewer is pointed
    at it — while values read verbatim are not flagged."""
    output, _, _ = await run_greenhouse(profile, posting, documents)

    assert outcome_for(output, "First Name *").is_derived is True
    assert outcome_for(output, "Last Name *").is_derived is True
    assert outcome_for(output, "Email *").is_derived is False


async def test_the_reported_url_is_where_the_session_actually_landed(
    profile, posting, documents
):
    """Portals redirect apply links, and the report should say which form was
    filled, not which link was followed."""
    session = FakeBrowserSession(
        greenhouse_form(),
        current_url="https://boards.greenhouse.io/globex/jobs/4001/application",
    )
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert output.apply_url.endswith("/application")
    assert output.ats_provider == "greenhouse"


# ---- Unmapped fields are surfaced, not guessed -------------------------------


async def test_a_company_screening_question_is_surfaced_untouched(
    profile, posting, documents
):
    output, session, _ = await run_greenhouse(profile, posting, documents)

    question = outcome_for(output, "Why do you want to work at Globex?")
    assert question.outcome == FieldAutofillOutcome.SURFACED
    assert question.reason == SurfaceReason.UNRECOGNIZED
    assert question.slot is None
    assert question.value is None
    assert "f-why" not in dict(session.filled)


async def test_the_legal_questions_are_answered_and_flagged_for_confirmation(
    profile, posting, documents
):
    """AC1: filled exactly from attested profile data — and flagged, because a
    legal declaration written from stored data is still the candidate's
    statement to make to this particular employer."""
    output, _, _ = await run_greenhouse(profile, posting, documents)

    auth = outcome_for(
        output, "Are you legally authorized to work in the United States? *"
    )
    sponsorship = outcome_for(
        output, "Will you now or in the future require sponsorship? *"
    )

    assert (auth.slot, auth.value) == (Slot.WORK_AUTHORIZATION, "Yes")
    assert (sponsorship.slot, sponsorship.value) == (Slot.SPONSORSHIP_REQUIRED, "No")
    for item in (auth, sponsorship):
        assert item.outcome == FieldAutofillOutcome.FILLED
        assert item.is_sensitive is True
        assert item.sensitivity == "legal_attestation"
        assert item.requires_confirmation is True


async def test_eeo_questions_are_surfaced_never_filled(profile, posting, documents):
    """AC2: the profile answers every EEO category and none of it reaches the
    form. The report names each question so the candidate can decide for this
    application."""
    output, session, _ = await run_greenhouse(profile, posting, documents)

    gender = outcome_for(output, "Gender")
    veteran = outcome_for(output, "Are you a protected veteran? *")
    for item in (gender, veteran):
        assert item.outcome == FieldAutofillOutcome.SURFACED
        assert item.reason == SurfaceReason.REQUIRES_CANDIDATE_ANSWER
        assert item.slot == Slot.EEO_SELF_IDENTIFICATION
        assert item.value is None
        assert item.is_sensitive is True
        assert item.sensitivity == "voluntary_self_id"
        # Nothing was written, so there is nothing to confirm — this one is
        # the candidate's to answer, not to approve.
        assert item.requires_confirmation is False

    written = {handle for handle, _ in session.filled}
    assert written.isdisjoint({"f-gender", "f-veteran"})


async def test_no_eeo_value_reaches_the_form_under_any_label(
    profile, posting, documents
):
    """A blunt sweep over everything written anywhere on the form: no stored
    EEO answer may appear in any field, whatever it was labelled."""
    _, session, _ = await run_greenhouse(profile, posting, documents)

    written = " ".join(value for _, value in session.filled).lower()
    for forbidden in ("female", "male", "asian", "veteran", "disab", "decline"):
        assert forbidden not in written


async def test_the_review_step_can_flag_every_sensitive_field(
    profile, posting, documents
):
    """AC3: the report gives a review UI exactly two lists — what to flag, and
    what must be approved before submission — so it never has to infer
    sensitivity from a slot name."""
    output, _, _ = await run_greenhouse(profile, posting, documents)

    assert [item.label for item in output.sensitive_fields] == [
        "Are you legally authorized to work in the United States? *",
        "Will you now or in the future require sponsorship? *",
        "Gender",
        "Are you a protected veteran? *",
    ]
    assert [item.label for item in output.fields_awaiting_confirmation] == [
        "Are you legally authorized to work in the United States? *",
        "Will you now or in the future require sponsorship? *",
    ]
    # Every sensitive field is one or the other: flagged for approval because
    # it was filled, or waiting on the candidate. None is merely ordinary.
    for item in output.sensitive_fields:
        assert item.requires_confirmation or not item.was_applied


async def test_the_report_separates_what_was_filled_from_what_needs_review(
    profile, posting, documents
):
    output, _, _ = await run_greenhouse(profile, posting, documents)

    assert len(output.fields) == len(greenhouse_form())
    assert [item.label for item in output.fields] == [
        f.label for f in greenhouse_form()
    ]
    assert len(output.applied_fields) == 12
    assert [item.label for item in output.fields_needing_review] == [
        "Why do you want to work at Globex?",
        "Gender",
        "Are you a protected veteran? *",
    ]
    # The ones the portal marks required are what will block submission.
    assert [item.label for item in output.unanswered_required_fields] == [
        "Why do you want to work at Globex?",
        "Are you a protected veteran? *",
    ]


async def test_a_recognized_field_with_no_profile_data_is_reported_as_such(
    posting, documents
):
    """Actionable in a way "unrecognized" is not: filling in the profile
    fixes it for every future application."""
    bare = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    output, session, _ = await run_greenhouse(bare, posting, documents)

    phone = outcome_for(output, "Phone")
    assert phone.outcome == FieldAutofillOutcome.SURFACED
    assert phone.reason == SurfaceReason.NO_PROFILE_DATA
    assert phone.slot == Slot.PHONE
    assert "f-phone" not in dict(session.filled)


# ---- Documents that do not exist yet -----------------------------------------


async def test_an_ungenerated_document_is_surfaced_rather_than_faked(profile, posting):
    output, session, renderer = await run_greenhouse(profile, posting, [])

    resume = outcome_for(output, "Resume/CV *")
    assert resume.outcome == FieldAutofillOutcome.SURFACED
    assert resume.reason == SurfaceReason.DOCUMENT_NOT_GENERATED
    assert resume.slot == Slot.RESUME
    assert session.attached == []
    assert renderer.calls == 0


async def test_a_document_is_rendered_once_even_when_the_form_asks_twice(
    profile, posting, documents
):
    """A form offering both an upload and a paste box must not render the
    same PDF twice, and the two must not be able to disagree."""
    fields = (
        form_field("Resume", handle="f-1", kind=FormFieldKind.FILE, name="resume"),
        form_field(
            "Or paste your resume",
            handle="f-2",
            kind=FormFieldKind.TEXTAREA,
            name="resume_text",
        ),
    )
    session = FakeBrowserSession(fields, current_url=GREENHOUSE_URL)
    use_case, _, renderer = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert renderer.calls == 1
    assert len(session.attached) == 1
    assert session.value_for("f-2") == "DANA REYES\nEXPERIENCE\n..."


async def test_only_the_documents_a_field_actually_takes_are_rendered(
    profile, posting, documents
):
    """This form uploads the resume and pastes the cover letter, so exactly
    one PDF is rendered — the paste box needs the stored text, not a file."""
    _, _, renderer = await run_greenhouse(profile, posting, documents)

    assert renderer.calls == 1
    assert renderer.content == "DANA REYES\nEXPERIENCE\n..."


async def test_a_paste_only_form_renders_no_pdf_at_all(profile, posting, documents):
    fields = (
        form_field(
            "Cover Letter",
            handle="f-cover",
            kind=FormFieldKind.TEXTAREA,
            name="cover_letter_text",
        ),
    )
    session = FakeBrowserSession(fields, current_url=GREENHOUSE_URL)
    use_case, _, renderer = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert renderer.calls == 0
    assert session.value_for("f-cover") == "Dear Globex team,\n..."


async def test_the_newest_document_version_is_the_one_attached(profile, posting):
    older = document(GeneratedDocumentKind.TAILORED_RESUME, "v1 text", version=1)
    newer = document(GeneratedDocumentKind.TAILORED_RESUME, "v2 text", version=2)

    _, _, renderer = await run_greenhouse(profile, posting, [older, newer])

    assert renderer.content == "v2 text"


# ---- Length limits -----------------------------------------------------------


async def test_a_value_longer_than_the_field_allows_is_surfaced_not_truncated(
    profile, posting, documents
):
    """A cover letter clipped mid-sentence still goes to a recruiter with the
    candidate's name on it."""
    fields = (
        form_field(
            "Cover Letter",
            handle="f-cover",
            kind=FormFieldKind.TEXTAREA,
            name="cover_letter_text",
            max_length=5,
        ),
    )
    session = FakeBrowserSession(fields, current_url=GREENHOUSE_URL)
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    item = outcome_for(output, "Cover Letter")
    assert item.outcome == FieldAutofillOutcome.SURFACED
    assert item.reason == SurfaceReason.VALUE_TOO_LONG
    assert item.detail is not None and "at most 5" in item.detail
    assert session.filled == []


# ---- Per-field failures do not abandon the form ------------------------------


async def test_a_value_the_form_refuses_is_reported_with_what_it_accepts(
    profile, posting, documents
):
    """The mapping was right and the value was wrong — a different outcome
    from "we could not read this field", and a different fix."""
    output, session, _ = await run_greenhouse(
        profile,
        posting,
        documents,
        failures={
            "f-degree": RejectedFieldValueError(
                handle="f-degree", value="B.S.", accepted="'Bachelor's Degree'"
            )
        },
    )

    degree = outcome_for(output, "Degree")
    assert degree.outcome == FieldAutofillOutcome.NOT_ACCEPTED
    assert degree.value == "B.S."
    assert degree.detail is not None and "Bachelor's Degree" in degree.detail
    # Everything else still got filled.
    assert session.value_for("f-email") == "dana@example.com"
    assert len(session.attached) == 1


async def test_a_field_that_refuses_input_is_reported_and_the_rest_proceeds(
    profile, posting, documents
):
    output, session, _ = await run_greenhouse(
        profile,
        posting,
        documents,
        failures={
            "f-phone": FormFieldNotFillableError(
                handle="f-phone", reason="element is obscured by an overlay"
            )
        },
    )

    phone = outcome_for(output, "Phone")
    assert phone.outcome == FieldAutofillOutcome.FAILED
    assert phone.detail == "element is obscured by an overlay"
    assert session.value_for("f-first") == "Dana"


async def test_an_upload_that_fails_is_reported_and_the_rest_proceeds(
    profile, posting, documents
):
    output, session, _ = await run_greenhouse(
        profile,
        posting,
        documents,
        failures={
            "f-resume": FormFieldNotFillableError(
                handle="f-resume", reason="the upload control detached"
            )
        },
    )

    resume = outcome_for(output, "Resume/CV *")
    assert resume.outcome == FieldAutofillOutcome.FAILED
    assert session.attached == []
    assert session.value_for("f-email") == "dana@example.com"


async def test_a_stale_handle_abandons_the_whole_pass(profile, posting, documents):
    """The page moved underneath the snapshot, so every remaining handle is
    suspect — continuing risks writing into whatever field drifted into
    position."""
    session = FakeBrowserSession(
        greenhouse_form(),
        current_url=GREENHOUSE_URL,
        failures={
            "f-email": StaleFormFieldError(handle="f-email", reason="signature changed")
        },
    )
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    with pytest.raises(StaleFormFieldError):
        await use_case.execute(
            AutofillApplicationFormInput(
                user_id="user-1", job_posting_id="job-posting-1"
            )
        )

    # ...and the session is still released on the way out.
    assert session.closed is True


# ---- Screenshot --------------------------------------------------------------


async def test_the_filled_form_is_captured_for_review(profile, posting, documents):
    output, session, _ = await run_greenhouse(profile, posting, documents)

    assert session.screenshots == 1
    assert output.screenshot_png == b"\x89PNG fake"


async def test_a_failed_capture_costs_the_proof_not_the_report(
    profile, posting, documents
):
    output, _, _ = await run_greenhouse(
        profile,
        posting,
        documents,
        screenshot_error=BrowserNavigationError(
            url=GREENHOUSE_URL, reason="page crashed"
        ),
    )

    assert output.screenshot_png is None
    assert len(output.applied_fields) == 12


# ---- Scope: only the three supported platforms ------------------------------


@pytest.mark.parametrize(
    "apply_url",
    [
        "https://globex.wd1.myworkdayjobs.com/careers/job/4001",
        "https://www.linkedin.com/jobs/view/4001",
        "https://globex.example.com/careers/apply/4001",
        "https://jobs.smartrecruiters.com/globex/4001",
    ],
)
async def test_an_unsupported_portal_is_refused_before_a_browser_opens(
    profile, documents, apply_url
):
    """Workday and friends are out of scope, and the refusal happens before
    any browser work — reading one with Greenhouse/Lever/Ashby rules would
    not fail, it would fill the wrong fields."""
    browser = FakeBrowser()
    use_case, _, renderer = build_use_case(
        posting=posting_at(apply_url),
        profile=profile,
        documents=documents,
        browser=browser,
    )

    with pytest.raises(UnsupportedAtsFormError) as exc_info:
        await use_case.execute(
            AutofillApplicationFormInput(
                user_id="user-1", job_posting_id="job-posting-1"
            )
        )

    assert exc_info.value.apply_url == apply_url
    assert exc_info.value.job_posting_id == "job-posting-1"
    assert browser.opened == []
    assert renderer.calls == 0


@pytest.mark.parametrize(
    ("apply_url", "expected_provider"),
    [
        (GREENHOUSE_URL, "greenhouse"),
        (LEVER_URL, "lever"),
        (ASHBY_URL, "ashby"),
    ],
)
async def test_all_three_supported_platforms_are_read(
    profile, documents, apply_url, expected_provider
):
    fields = (
        form_field("Full name", handle="f-name", name="name"),
        form_field("Email", handle="f-email", kind=FormFieldKind.EMAIL, name="email"),
    )
    session = FakeBrowserSession(fields, current_url=apply_url)
    use_case, _, _ = build_use_case(
        session=session,
        posting=posting_at(apply_url),
        profile=profile,
        documents=documents,
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert output.ats_provider == expected_provider
    assert session.value_for("f-name") == "Dana Reyes"
    assert session.value_for("f-email") == "dana@example.com"


async def test_a_lever_form_maps_its_own_control_names(profile, documents):
    fields = (
        form_field("Full name✱", handle="f-name", name="name", required=True),
        form_field("Current company", handle="f-org", name="org"),
        form_field(
            "LinkedIn URL", handle="f-li", kind=FormFieldKind.URL, name="urls[LinkedIn]"
        ),
        form_field(
            "GitHub URL", handle="f-gh", kind=FormFieldKind.URL, name="urls[GitHub]"
        ),
        form_field("Resume/CV✱", handle="f-cv", kind=FormFieldKind.FILE, name="resume"),
        form_field(
            "Additional information",
            handle="f-comments",
            kind=FormFieldKind.TEXTAREA,
            name="comments",
        ),
    )
    session = FakeBrowserSession(fields, current_url=LEVER_URL)
    use_case, _, _ = build_use_case(
        session=session,
        posting=posting_at(LEVER_URL),
        profile=profile,
        documents=documents,
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert session.value_for("f-name") == "Dana Reyes"
    assert session.value_for("f-li") == "https://www.linkedin.com/in/danareyes"
    assert session.value_for("f-gh") == "https://github.com/danareyes"
    assert len(session.attached) == 1
    # No work history on this profile, so Lever's `org` field has nothing to
    # say — surfaced, not filled with an adjacent fact.
    assert outcome_for(output, "Current company").reason == (
        SurfaceReason.NO_PROFILE_DATA
    )
    assert outcome_for(output, "Additional information").reason == (
        SurfaceReason.UNRECOGNIZED
    )


async def test_an_ashby_form_maps_through_its_system_field_ids(profile, documents):
    """Ashby leaves `name` empty on its built-in inputs and puts the
    meaningful token on the id."""
    fields = (
        form_field("Name", handle="f-name", attributes={"id": "_systemfield_name"}),
        form_field(
            "Email",
            handle="f-email",
            kind=FormFieldKind.EMAIL,
            attributes={"id": "_systemfield_email"},
        ),
        form_field(
            "Resume",
            handle="f-resume",
            kind=FormFieldKind.FILE,
            attributes={"id": "_systemfield_resume"},
        ),
        form_field(
            "What draws you to Globex?",
            handle="f-custom",
            kind=FormFieldKind.TEXTAREA,
            attributes={"id": "f1d2c3b4-5678-4abc-9def-000000000000"},
        ),
    )
    session = FakeBrowserSession(fields, current_url=ASHBY_URL)
    use_case, _, _ = build_use_case(
        session=session,
        posting=posting_at(ASHBY_URL),
        profile=profile,
        documents=documents,
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert session.value_for("f-name") == "Dana Reyes"
    assert session.value_for("f-email") == "dana@example.com"
    assert len(session.attached) == 1
    assert outcome_for(output, "What draws you to Globex?").reason == (
        SurfaceReason.UNRECOGNIZED
    )


# ---- Preconditions -----------------------------------------------------------


async def test_a_missing_posting_is_refused_before_a_browser_opens(profile):
    browser = FakeBrowser()
    use_case, _, _ = build_use_case(posting=None, profile=profile, browser=browser)

    with pytest.raises(JobPostingNotFoundError):
        await use_case.execute(
            AutofillApplicationFormInput(user_id="user-1", job_posting_id="missing")
        )

    assert browser.opened == []


async def test_a_missing_profile_is_refused_before_a_browser_opens(posting):
    browser = FakeBrowser()
    use_case, _, _ = build_use_case(posting=posting, profile=None, browser=browser)

    with pytest.raises(ProfileNotFoundError):
        await use_case.execute(
            AutofillApplicationFormInput(
                user_id="user-1", job_posting_id="job-posting-1"
            )
        )

    assert browser.opened == []


async def test_a_form_that_presented_no_fields_is_an_empty_report(
    profile, posting, documents
):
    """A dead posting or an interstitial — not an error (see `read_fields`),
    and nothing to fill.

    Nothing to review either, so no browser is left parked: there is no
    field to answer and nothing to submit, and holding a session open for
    fifteen minutes on the candidate's behalf would buy them nothing.
    """
    session = FakeBrowserSession((), current_url=GREENHOUSE_URL)
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert output.fields == []
    assert output.fields_needing_review == []
    assert output.review_session_id is None
    assert output.can_be_submitted_here is False
    assert session.closed is True


async def test_a_navigation_failure_propagates(profile, posting):
    browser = FakeBrowser(
        open_error=BrowserNavigationError(url=GREENHOUSE_URL, reason="timeout")
    )
    use_case, _, _ = build_use_case(posting=posting, profile=profile, browser=browser)

    with pytest.raises(BrowserNavigationError):
        await use_case.execute(
            AutofillApplicationFormInput(
                user_id="user-1", job_posting_id="job-posting-1"
            )
        )


# ---- The policy is the same on every supported platform ---------------------


def sensitive_form() -> tuple[FormField, ...]:
    """The always-asked block, in the shape any of the three platforms serves
    it: two legal questions and one EEO question."""
    yes_no = (
        FormFieldOption(label="Yes", value="1"),
        FormFieldOption(label="No", value="0"),
    )
    return (
        form_field(
            "Are you legally authorized to work in the United States?",
            handle="f-auth",
            kind=FormFieldKind.SELECT,
            required=True,
            options=yes_no,
        ),
        form_field(
            "Will you now or in the future require sponsorship?",
            handle="f-sponsorship",
            kind=FormFieldKind.RADIO,
            required=True,
            options=yes_no,
        ),
        form_field(
            "Gender",
            handle="f-gender",
            kind=FormFieldKind.SELECT,
            options=(FormFieldOption(label="Female", value="2"),),
        ),
    )


@pytest.mark.parametrize("apply_url", [GREENHOUSE_URL, LEVER_URL, ASHBY_URL])
async def test_the_sensitive_policy_is_identical_on_all_three_platforms(
    profile, documents, apply_url
):
    """AC4. The policy lives in one domain service that no platform-specific
    code can reach around, so the same questions get the same treatment
    whichever portal asked them."""
    session = FakeBrowserSession(sensitive_form(), current_url=apply_url)
    use_case, _, _ = build_use_case(
        session=session,
        posting=posting_at(apply_url),
        profile=profile,
        documents=documents,
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert dict(session.filled) == {"f-auth": "Yes", "f-sponsorship": "No"}
    gender = outcome_for(output, "Gender")
    assert gender.outcome == FieldAutofillOutcome.SURFACED
    assert gender.reason == SurfaceReason.REQUIRES_CANDIDATE_ANSWER
    assert [item.label for item in output.fields_awaiting_confirmation] == [
        "Are you legally authorized to work in the United States?",
        "Will you now or in the future require sponsorship?",
    ]


# ---- Exact or nothing, at execution time ------------------------------------


async def test_a_portal_that_refuses_yes_reports_it_instead_of_approximating(
    profile, posting, documents
):
    """A portal labelling its options "Yes, I am authorized" refuses the exact
    "Yes" the policy produced, and the field is reported with the options that
    would have worked — never quietly matched to the closest one."""
    session = FakeBrowserSession(
        sensitive_form(),
        current_url=GREENHOUSE_URL,
        failures={
            "f-auth": RejectedFieldValueError(
                handle="f-auth",
                value="Yes",
                accepted="'Yes, I am authorized to work in the US', 'No'",
            )
        },
    )
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    auth = outcome_for(
        output, "Are you legally authorized to work in the United States?"
    )
    assert auth.outcome == FieldAutofillOutcome.NOT_ACCEPTED
    assert auth.detail is not None and "Yes, I am authorized" in auth.detail
    # Nothing reached the form, so there is nothing to confirm — the candidate
    # has to choose, and one gate pointing at this field is enough.
    assert auth.requires_confirmation is False
    assert auth.is_sensitive is True
    assert auth in output.fields_needing_review


async def test_an_unattested_record_leaves_the_legal_questions_to_the_candidate(
    posting, documents
):
    """A work authorization inferred from a resume rather than stated by the
    candidate is never asserted to an employer, even though it would answer
    the question."""
    parsed = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    parsed.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.CITIZEN,
            requires_sponsorship=False,
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    session = FakeBrowserSession(sensitive_form(), current_url=GREENHOUSE_URL)
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=parsed, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert session.filled == []
    for label in (
        "Are you legally authorized to work in the United States?",
        "Will you now or in the future require sponsorship?",
    ):
        item = outcome_for(output, label)
        assert item.outcome == FieldAutofillOutcome.SURFACED
        assert item.reason == SurfaceReason.SENSITIVE_DATA_NOT_ATTESTED
        assert item.is_sensitive is True


async def test_a_candidate_who_needs_sponsorship_gets_the_truthful_answers(
    posting, documents
):
    """The policy is accuracy, not optimism: a candidate who requires
    sponsorship has that written onto the form, exactly as they stated it."""
    needs_sponsorship = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    needs_sponsorship.set_work_authorization(
        WorkAuthorization(
            status=WorkAuthorizationStatus.REQUIRES_SPONSORSHIP,
            requires_sponsorship=True,
            source=ProvenanceSource.ANSWER,
        )
    )
    session = FakeBrowserSession(sensitive_form(), current_url=GREENHOUSE_URL)
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=needs_sponsorship, documents=documents
    )

    await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    assert dict(session.filled) == {"f-auth": "No", "f-sponsorship": "Yes"}


# ---- Hard boundaries and hand-off --------------------------------------------


LOGIN_WALL_SIGNALS = PageSignals(
    url=GREENHOUSE_URL,
    visible_text="Please sign in to continue to the application.",
)

CAPTCHA_SIGNALS = PageSignals(
    url=GREENHOUSE_URL,
    visible_text="Apply for Senior Platform Engineer",
    frame_urls=("https://www.google.com/recaptcha/api2/anchor?k=6Lc",),
)

SIGNATURE_SIGNALS = PageSignals(
    url=GREENHOUSE_URL,
    visible_text="Apply for Senior Platform Engineer",
    element_markers=("application-form", "signature-pad"),
)


async def run_with_signals(profile, posting, documents, signals: PageSignals):
    session = FakeBrowserSession(
        greenhouse_form(), current_url=GREENHOUSE_URL, signals=signals
    )
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )
    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )
    return output, session


async def test_a_login_wall_stops_the_pass_before_anything_is_typed(
    profile, posting, documents
):
    """The page behind a sign-in prompt is not the application form. Filling
    it would type the candidate's real details into a login box for an
    account that may not exist."""
    output, session = await run_with_signals(
        profile, posting, documents, LOGIN_WALL_SIGNALS
    )

    assert session.filled == []
    assert session.attached == []
    assert output.fields == []
    assert [boundary.kind for boundary in output.boundaries] == ["login"]
    assert output.boundaries[0].stopped_autofill is True
    assert "sign in" in output.boundaries[0].evidence


async def test_a_login_wall_hands_off_with_an_instruction_and_no_session(
    profile, posting, documents
):
    """Nothing to review and nothing to submit, so no browser is parked —
    and the candidate is told what to do rather than shown an error."""
    output, session = await run_with_signals(
        profile, posting, documents, LOGIN_WALL_SIGNALS
    )

    assert output.review_session_id is None
    assert output.requires_handoff is True
    assert output.can_be_submitted_here is False
    assert "sign in" in output.boundaries[0].instruction.casefold()
    assert session.closed is True
    # The candidate still gets to see what ApplyFlow saw.
    assert output.screenshot_png is not None


async def test_a_captcha_does_not_stop_the_form_being_filled(
    profile, posting, documents
):
    """The form around a CAPTCHA is real and filling it is most of what the
    candidate came for. What the CAPTCHA costs them is the in-app submit."""
    output, session = await run_with_signals(
        profile, posting, documents, CAPTCHA_SIGNALS
    )

    assert outcome_for(output, "First Name *").value == "Dana"
    assert session.filled != []
    assert [boundary.kind for boundary in output.boundaries] == ["captcha"]
    assert output.boundaries[0].stopped_autofill is False


async def test_a_captcha_leaves_the_review_open_but_blocks_submitting_here(
    profile, posting, documents
):
    output, session = await run_with_signals(
        profile, posting, documents, CAPTCHA_SIGNALS
    )

    # There is a filled form to review...
    assert output.review_session_id is not None
    assert session.closed is False
    # ...and it is not going out through ApplyFlow.
    assert output.can_be_submitted_here is False
    assert output.boundaries[0].blocks_submission is True


async def test_a_signature_request_is_reported_on_a_filled_form(
    profile, posting, documents
):
    output, _ = await run_with_signals(profile, posting, documents, SIGNATURE_SIGNALS)

    assert output.applied_fields != []
    assert [boundary.kind for boundary in output.boundaries] == ["signature"]
    assert output.can_be_submitted_here is False
    assert "signature" in output.boundaries[0].instruction.casefold()


async def test_an_ordinary_form_reports_no_boundary_at_all(profile, posting, documents):
    output, _, _ = await run_greenhouse(profile, posting, documents)

    assert output.boundaries == []
    assert output.requires_handoff is False
    assert output.can_be_submitted_here is True


# ---- A signature field is never filled ---------------------------------------


def signature_form() -> tuple[FormField, ...]:
    """The shape a signature actually takes on an ATS form: an ordinary text
    input whose label names the candidate's own name."""
    return (
        form_field(
            "First Name *",
            handle="f-first",
            name="job_application[first_name]",
            required=True,
        ),
        form_field(
            "Signature (type your full name)",
            handle="f-signature",
            name="job_application[custom][signature]",
            required=True,
        ),
    )


async def test_a_signature_field_is_surfaced_even_though_it_names_the_candidate(
    profile, posting, documents
):
    """The failure this guard exists to prevent: the label reads as a request
    for the candidate's full name, which ApplyFlow has on file and would
    happily type — and typing someone's name into a signature box is signing
    for them."""
    session = FakeBrowserSession(
        signature_form(), current_url=GREENHOUSE_URL, signals=SIGNATURE_SIGNALS
    )
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    signature = outcome_for(output, "Signature (type your full name)")
    assert signature.outcome == FieldAutofillOutcome.SURFACED.value
    assert signature.reason == SurfaceReason.REQUIRES_CANDIDATE_SIGNATURE.value
    assert signature.value is None
    assert session.value_for("f-signature") is None
    # The rest of the form is still filled — a signature request is not a
    # reason to abandon the application.
    assert session.value_for("f-first") == "Dana"


async def test_a_signature_field_blocks_submitting_and_stays_the_candidates_job(
    profile, posting, documents
):
    session = FakeBrowserSession(
        signature_form(), current_url=GREENHOUSE_URL, signals=SIGNATURE_SIGNALS
    )
    use_case, _, _ = build_use_case(
        session=session, posting=posting, profile=profile, documents=documents
    )

    output = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )

    # Required and unanswered, so the submit gate refuses it too — two
    # independent reasons this application cannot go out unattended.
    assert [item.label for item in output.unanswered_required_fields] == [
        "Signature (type your full name)"
    ]
    assert output.can_be_submitted_here is False

"""End-to-end enforcement of the two sensitive-field rules, checked across
every layer that touches them rather than inside any one of them.

The rules, and why they are opposite
------------------------------------
**Work authorization must be exactly accurate.** Refusing to answer is not
the safe default here — an unanswered required authorization question stalls
the application. So the contract is exact-or-refuse, and the failure this
suite hunts is an answer that is *approximately* right.

**EEO self-identification must never be auto-filled.** Disclosure is
voluntary and is a per-application decision, so the contract is refuse
always, and the failure this suite hunts is any path by which a stored
category reaches a form.

Both are implemented in Epic 01 (the profile records) and Epic 05 (the
policy, the recognizer, the planner, the review). Each of those has its own
unit tests. This file is deliberately *not* another copy of them: it checks
the rules hold across the seams between layers, which is where a rule that
every layer implements correctly can still fail as a whole.

Why it runs in the ordinary suite
---------------------------------
Unlike the epic pipelines in this directory, this check is not gated behind
an env var and drives no browser and no database. It reaches the same
production code they do — the real persistence mappers, the real recognizer,
the real policy, the real planner, the real autofill use case — with the
browser faked. A rule this consequential should not be verified only on the
runs somebody remembered to opt into.

The profile is round-tripped through storage
--------------------------------------------
Every profile here is passed through the real
`SqlAlchemyProfileRepository` mapping functions before it is handed to
autofill, so what the policy reads is what storage would give back rather
than what the test constructed. Those columns are encrypted at rest
(Epic 07) and the mapping is where a `requires_sponsorship=False` could
quietly become `None` — which turns an exact "No" into a refusal, or worse.
No database is needed to exercise that: the mapping is the part that can be
wrong.

Findings from this verification, including the two mis-mappings deliberately
left unfixed, are written up in `docs/sensitive-field-enforcement-check.md`.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from src.application.dtos.application_autofill_dtos import (
    AutofillApplicationFormInput,
    FieldAutofillOutcome,
)
from src.application.dtos.application_review_dtos import AnswerApplicationFieldInput
from src.application.ports.browser_automation_port import (
    FormField,
    FormFieldKind,
    FormFieldOption,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)
from src.application.services.ats_form_field_planner import (
    AtsFormFieldPlanner,
    FieldDisposition,
    SurfaceReason,
)
from src.application.use_cases.answer_application_field import AnswerApplicationField
from src.application.use_cases.autofill_application_form import AutofillApplicationForm
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.user_profile import UserProfile
from src.domain.services.ats_field_mapper import recognize_application_field
from src.domain.services.candidate_fact_extractor import CandidateFactExtractor
from src.domain.services.sensitive_field_policy import decide_sensitive_field
from src.domain.value_objects.application_field_slot import (
    REQUIRES_CANDIDATE_ANSWER,
    ApplicationFieldSlot,
    FieldSensitivity,
    is_sensitive_slot,
    sensitivity_of,
)
from src.domain.value_objects.ats_form_question import AtsFormQuestion
from src.domain.value_objects.ats_provider import AtsProvider
from src.domain.value_objects.eeo_categories import (
    DisabilityStatus,
    GenderIdentity,
    RaceEthnicity,
    VeteranStatus,
)
from src.domain.value_objects.eeo_self_identification import EeoSelfIdentification
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.provenance_source import ProvenanceSource
from src.domain.value_objects.work_authorization import WorkAuthorization
from src.domain.value_objects.work_authorization_status import WorkAuthorizationStatus
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)
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
Status = WorkAuthorizationStatus

SRC = Path(__file__).resolve().parents[2] / "src"

PORTAL_URLS = {
    AtsProvider.GREENHOUSE: "https://boards.greenhouse.io/globex/jobs/4001",
    AtsProvider.LEVER: "https://jobs.lever.co/globex/8f2a-1b3c/apply",
    AtsProvider.ASHBY: "https://jobs.ashbyhq.com/globex/1a2b3c4d",
}

YES_NO = (
    FormFieldOption(label="Yes", value="Yes"),
    FormFieldOption(label="No", value="No"),
)


# ---- Building a candidate ----------------------------------------------------


def candidate(
    *,
    authorization: WorkAuthorization | None = None,
    eeo: EeoSelfIdentification | None = None,
) -> UserProfile:
    """A profile as storage would hand it back.

    The round-trip through the repository's own mapping functions is the
    point — see the module docstring. A profile built in memory and handed
    straight to the planner would prove the policy correct on data no
    deployed process ever sees.
    """
    profile = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    if authorization is not None:
        profile.set_work_authorization(authorization)
    if eeo is not None:
        profile.set_eeo_self_identification(eeo)
    return _through_storage(profile)


def _through_storage(profile: UserProfile) -> UserProfile:
    """`profile`'s sensitive records, mapped to their ORM models and back.

    Only the two sensitive records are round-tripped. The full profile
    mapping needs a `UserProfileModel` with database-assigned columns, and
    the rest of the profile is not what this suite is about.
    """
    mapper = SqlAlchemyProfileRepository
    if profile.work_authorization is not None:
        profile.set_work_authorization(
            mapper._work_authorization_to_entity(  # noqa: SLF001
                mapper._work_authorization_to_model(  # noqa: SLF001
                    profile.work_authorization
                )
            )
        )
    if profile.eeo_self_identification is not None:
        profile.set_eeo_self_identification(
            mapper._eeo_to_entity(  # noqa: SLF001
                mapper._eeo_to_model(profile.eeo_self_identification)  # noqa: SLF001
            )
        )
    return profile


def attested(status: Status, **kwargs: object) -> WorkAuthorization:
    """A work-authorization record the candidate stated themselves."""
    return WorkAuthorization(status=status, source=ProvenanceSource.ANSWER, **kwargs)  # type: ignore[arg-type]


#: Every EEO category answered, so a test that finds nothing on the form has
#: found nothing because the rule held, not because there was nothing to
#: leak.
FULLY_DISCLOSED_EEO = EeoSelfIdentification(
    source=ProvenanceSource.ANSWER,
    gender_identity=GenderIdentity.FEMALE,
    race_ethnicity=RaceEthnicity.ASIAN,
    veteran_status=VeteranStatus.PROTECTED_VETERAN,
    disability_status=DisabilityStatus.HAS_DISABILITY,
)

#: The stored EEO values as they would appear if any of them ever reached a
#: form — what the sweeps below search the written values for.
EEO_VALUES = frozenset(
    {
        FULLY_DISCLOSED_EEO.gender_identity.value,  # type: ignore[union-attr]
        FULLY_DISCLOSED_EEO.race_ethnicity.value,  # type: ignore[union-attr]
        FULLY_DISCLOSED_EEO.veteran_status.value,  # type: ignore[union-attr]
        FULLY_DISCLOSED_EEO.disability_status.value,  # type: ignore[union-attr]
        "Female",
        "Asian",
    }
)


# ---- Driving a whole autofill pass -------------------------------------------


def question(
    label: str,
    *,
    handle: str,
    kind: FormFieldKind = FormFieldKind.SELECT,
    options: tuple[FormFieldOption, ...] = YES_NO,
    required: bool = True,
) -> FormField:
    return FormField(
        name=handle,
        label=label,
        handle=handle,
        kind=kind,
        required=required,
        options=options,
    )


async def run_autofill(
    profile: UserProfile,
    fields: tuple[FormField, ...],
    *,
    provider: AtsProvider = AtsProvider.GREENHOUSE,
) -> tuple[object, FakeBrowserSession, ApplicationReviewSessions]:
    """One real autofill pass over `fields`, with the browser faked.

    Returns the report, the session (so a test can assert on what was
    actually written to the page rather than on what the report claims), and
    the review sessions (so the candidate's own answer can be exercised).
    """
    url = PORTAL_URLS[provider]
    session = FakeBrowserSession(fields, current_url=url)
    review_sessions = ApplicationReviewSessions(SequentialIdGenerator("review"))
    use_case = AutofillApplicationForm(
        StubJobPostingRepository(
            JobPosting(
                id="job-posting-1",
                source=provider.value,
                company="Globex",
                title="Senior Platform Engineer",
                apply_url=url,
                description="Platform role.",
            )
        ),
        StubProfileRepository(profile),
        InMemoryApplicationDocumentRepository(),
        FakeBrowser(session),
        RecordingPdfRenderer(),
        review_sessions,
    )
    report = await use_case.execute(
        AutofillApplicationFormInput(user_id="user-1", job_posting_id="job-posting-1")
    )
    return report, session, review_sessions


def field_labelled(report: object, label: str) -> object:
    """The report entry for `label`.

    Matched on the portal's own label text, required marker and all — that is
    what the report carries, and normalizing it here would let a test pass
    against a field it did not mean.
    """
    for item in report.fields:  # type: ignore[attr-defined]
        if item.label == label:
            return item
    raise AssertionError(
        f"no field labelled {label!r} in "
        f"{[item.label for item in report.fields]}"  # type: ignore[attr-defined]
    )


# ==============================================================================
# AC1 — work authorization, exact through the whole profile → autofill path
# ==============================================================================


#: Every stored shape of a work-authorization record, and the exact answer
#: the two yes/no questions must carry for it. `None` means the record does
#: not settle that question and the field must be surfaced instead.
#:
#: This is the truth table the whole feature exists to get right, written out
#: once so a change to the derivation has to come here and state its case.
AUTHORIZATION_TRUTH_TABLE: tuple[
    tuple[Status, bool | None, str | None, str | None], ...
] = (
    # status,                    requires_sponsorship, authorized?, sponsorship?
    (Status.CITIZEN, None, "Yes", "No"),
    (Status.CITIZEN, False, "Yes", "No"),
    (Status.PERMANENT_RESIDENT, None, "Yes", "No"),
    (Status.PERMANENT_RESIDENT, False, "Yes", "No"),
    # A visa holder is authorized today; whether that needs renewing or
    # transferring is not something the status settles, so sponsorship is
    # refused unless they answered it themselves.
    (Status.VISA_HOLDER, None, "Yes", None),
    (Status.VISA_HOLDER, False, "Yes", "No"),
    (Status.VISA_HOLDER, True, "Yes", "Yes"),
    # Needing a sponsor is what "not authorized as things stand" means.
    (Status.REQUIRES_SPONSORSHIP, None, "No", "Yes"),
    (Status.REQUIRES_SPONSORSHIP, True, "No", "Yes"),
    # Not authorized now says nothing about whether *this* employer would be
    # the one to sponsor them.
    (Status.NOT_AUTHORIZED, None, "No", None),
    (Status.NOT_AUTHORIZED, True, "No", "Yes"),
    # `OTHER` settles nothing at all, by construction.
    (Status.OTHER, None, None, None),
    (Status.OTHER, False, None, "No"),
)


@pytest.mark.parametrize(
    ("status", "sponsorship", "expected_auth", "expected_sponsorship"),
    AUTHORIZATION_TRUTH_TABLE,
)
async def test_the_legal_answers_are_exact_for_every_stored_record(
    status: Status,
    sponsorship: bool | None,
    expected_auth: str | None,
    expected_sponsorship: str | None,
) -> None:
    """AC1. Profile → storage mapping → policy → planner → the bytes written
    to the page, for every shape a work-authorization record can take.

    Asserted against `session.filled` rather than the report: the report is a
    claim about what happened and this is what actually reached the form.
    """
    profile = candidate(
        authorization=attested(status, requires_sponsorship=sponsorship)
    )
    report, session, _ = await run_autofill(
        profile,
        (
            question(
                "Are you legally authorized to work in the United States? *",
                handle="f-auth",
            ),
            question(
                "Will you now or in the future require sponsorship? *",
                handle="f-sponsorship",
            ),
        ),
    )

    written = dict(session.filled)
    expected = {
        handle: value
        for handle, value in (
            ("f-auth", expected_auth),
            ("f-sponsorship", expected_sponsorship),
        )
        if value is not None
    }
    assert written == expected

    # A question the record does not settle is surfaced with a reason, never
    # left silently blank.
    for label, value in (
        (
            "Are you legally authorized to work in the United States? *",
            expected_auth,
        ),
        (
            "Will you now or in the future require sponsorship? *",
            expected_sponsorship,
        ),
    ):
        item = field_labelled(report, label)
        if value is None:
            assert item.outcome == FieldAutofillOutcome.SURFACED  # type: ignore[attr-defined]
            assert item.reason is not None  # type: ignore[attr-defined]
        else:
            assert item.outcome == FieldAutofillOutcome.FILLED  # type: ignore[attr-defined]
            # Filled from stored data, so the candidate confirms it before
            # it is asserted to this employer.
            assert item.requires_confirmation is True  # type: ignore[attr-defined]


async def test_storage_does_not_lose_a_negative_sponsorship_answer() -> None:
    """AC1. `requires_sponsorship=False` survives the encrypted-column
    mapping as `False` and not as `None`.

    Singled out because the two are indistinguishable in most code and are
    not remotely the same here: `False` is an exact "No", while `None` means
    the record does not answer and — for a visa holder — the field is
    surfaced instead. A boolean column that round-tripped falsy-as-missing
    would silently downgrade an answer the candidate gave.
    """
    profile = candidate(
        authorization=attested(Status.VISA_HOLDER, requires_sponsorship=False)
    )

    assert profile.work_authorization is not None
    assert profile.work_authorization.requires_sponsorship is False
    decision = decide_sensitive_field(Slot.SPONSORSHIP_REQUIRED, profile=profile)
    assert decision.answer == "No"


async def test_free_text_legal_details_are_answered_verbatim() -> None:
    """AC1. Citizenship country and visa type are the candidate's own words,
    through storage and onto the form unchanged — never normalized to a
    nearest known value."""
    profile = candidate(
        authorization=attested(
            Status.VISA_HOLDER,
            citizenship_country="Côte d'Ivoire",
            visa_type="H-1B (transfer pending)",
        )
    )
    _, session, _ = await run_autofill(
        profile,
        (
            question(
                "Country of citizenship",
                handle="f-country",
                kind=FormFieldKind.TEXT,
                options=(),
            ),
            question(
                "Visa type",
                handle="f-visa",
                kind=FormFieldKind.TEXT,
                options=(),
            ),
        ),
    )

    assert dict(session.filled) == {
        "f-country": "Côte d'Ivoire",
        "f-visa": "H-1B (transfer pending)",
    }


async def test_a_record_the_candidate_did_not_state_answers_nothing() -> None:
    """AC1. A resume-parsed authorization record is stored and read, and is
    still never asserted to an employer — the attestation gate holds through
    the storage round-trip."""
    profile = candidate(
        authorization=WorkAuthorization(
            status=Status.CITIZEN,
            requires_sponsorship=False,
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    report, session, _ = await run_autofill(
        profile,
        (
            question(
                "Are you legally authorized to work in the United States? *",
                handle="f-auth",
            ),
        ),
    )

    assert session.filled == []
    item = field_labelled(
        report, "Are you legally authorized to work in the United States? *"
    )
    assert item.reason == SurfaceReason.SENSITIVE_DATA_NOT_ATTESTED  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "label",
    [
        "Are you legally authorized to work in the United States without sponsorship?",
        "Are you authorized to work in the US without requiring sponsorship?",
        "Are you eligible to work in the UK without sponsorship?",
    ],
)
@pytest.mark.parametrize("status", [Status.CITIZEN, Status.REQUIRES_SPONSORSHIP])
async def test_a_compound_legal_question_is_surfaced_rather_than_inverted(
    label: str, status: Status
) -> None:
    """AC1 regression. "Authorized to work **without sponsorship**?" is one
    question that reads as two, and the two have opposite polarity.

    Before the guard in `_CONFLICTING_LEGAL_SLOTS`, rule ordering resolved it
    to the sponsorship slot, so a US citizen — "does not require
    sponsorship" — had **"No"** written into a field whose truthful answer is
    **"Yes"**. An inverted legal declaration, on one of the most common
    screening questions on Greenhouse and Lever.

    No stored field states the conjunction the question asks for, so the
    exact-or-refuse contract means refuse: it goes to the candidate.
    """
    profile = candidate(
        authorization=attested(
            status, requires_sponsorship=status is Status.REQUIRES_SPONSORSHIP
        )
    )
    report, session, _ = await run_autofill(
        profile, (question(label, handle="f-compound"),)
    )

    assert session.filled == []
    item = field_labelled(report, label)
    assert item.outcome == FieldAutofillOutcome.SURFACED  # type: ignore[attr-defined]
    assert item.slot is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "label",
    [
        # Sponsorship *history* — the record stores current need, not history.
        "Have you ever been sponsored for a visa?",
        "Are you currently on a visa sponsored by your employer?",
        "Have you previously required sponsorship?",
        # A *date* — no legal slot stores one.
        "Work permit expiry date",
        "Visa expiration date",
        "Visa valid until",
    ],
)
async def test_a_legal_question_the_record_cannot_answer_is_surfaced(
    label: str,
) -> None:
    """AC1 regression, closing findings F2 and F3 of
    `docs/sensitive-field-enforcement-check.md` — both routed there and both
    fixed by the Epic 07 hardening pass.

    Same root cause as the compound question above: the sensitive label rules
    are greedy, matching one phrase without asking whether the label poses a
    *different* question than the slot's canonical one.

    - "Have you ever been sponsored for a visa?" fell past the sponsorship
      rules (which need `sponsor`/`sponsorship`, not `sponsored`) to the bare
      `visa` rule, so a visa holder had `"H-1B"` written into a yes/no field.
    - "Work permit expiry date" matched `work permit` and resolved to
      `WORK_AUTHORIZATION`, which answers Yes/No — so `"Yes"` went into a field
      asking for a date.

    Both were contained on selects and radios, which refuse a value they have
    no option for, and both were written on a **text** input. Neither question
    is one the profile has a field for, so exact-or-refuse means refuse.
    """
    profile = candidate(
        authorization=attested(
            Status.REQUIRES_SPONSORSHIP, requires_sponsorship=True, visa_type="H-1B"
        )
    )
    report, session, _ = await run_autofill(
        profile, (question(label, handle="f-unanswerable"),)
    )

    assert session.filled == [], (
        "a question the record does not answer must reach the candidate, not "
        "receive the nearest stored value"
    )
    item = field_labelled(report, label)
    assert item.outcome == FieldAutofillOutcome.SURFACED  # type: ignore[attr-defined]
    assert item.slot is None  # type: ignore[attr-defined]


async def test_a_current_state_legal_question_is_still_answered() -> None:
    """The other half of the guard above, in the same spirit as the canonical
    sponsorship test below: refusing dates and histories must not have cost the
    present-tense questions the record genuinely answers.

    "Is your work authorization valid?" contains `valid` — and `valid` is
    deliberately *not* one of the disqualifying tokens, precisely so this keeps
    working. Only `until` is.
    """
    profile = candidate(authorization=attested(Status.CITIZEN))
    _, session, _ = await run_autofill(
        profile,
        (question("Is your work authorization valid? *", handle="f-valid"),),
    )

    assert dict(session.filled) == {"f-valid": "Yes"}


async def test_the_canonical_sponsorship_question_is_still_answered() -> None:
    """The other half of the guard above: it must not have bought accuracy by
    surfacing the question it was meant to protect.

    "…require sponsorship for employment **visa status**?" matches the visa
    rules as well as the sponsorship ones, so a blunter "two sensitive slots
    matched" guard would refuse the single most common sponsorship phrasing
    on every portal.
    """
    profile = candidate(authorization=attested(Status.CITIZEN))
    _, session, _ = await run_autofill(
        profile,
        (
            question(
                "Will you now or in the future require sponsorship for "
                "employment visa status? *",
                handle="f-sponsorship",
            ),
        ),
    )

    assert dict(session.filled) == {"f-sponsorship": "No"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [(Status.CITIZEN, "Yes"), (Status.REQUIRES_SPONSORSHIP, "No")],
)
async def test_nothing_between_the_policy_and_the_harness_rewrites_the_answer(
    status: Status, expected: str
) -> None:
    """AC1. The bytes handed to the browser harness are byte-identical to the
    domain policy's decision.

    The layers in between — planner, use case, review session — each have a
    reason to touch a value (trimming, casing, mapping to an option label),
    and any of them doing so here would break the harness's exact-match
    contract or, worse, quietly succeed against a differently-worded option.
    So the two are compared directly rather than both against a literal.

    Whether the *portal* then accepts that exact string is a separate
    question, covered by Epic 05's unit tests against a harness rigged to
    refuse it.
    """
    profile = candidate(authorization=attested(status))
    decision = decide_sensitive_field(Slot.WORK_AUTHORIZATION, profile=profile)
    assert decision.answer == expected

    _, session, _ = await run_autofill(
        profile,
        (
            question(
                "Are you legally authorized to work in the United States? *",
                handle="f-auth",
            ),
        ),
    )

    assert dict(session.filled) == {"f-auth": decision.answer}


# ==============================================================================
# AC2 — EEO self-ID is never auto-filled, anywhere
# ==============================================================================


#: EEO questions in the wordings the three supported portals actually serve,
#: plus several this codebase does not recognize. Both outcomes are correct
#: and the test accepts either — what it refuses is a third: an *answerable*
#: slot, which is the only way a stored category could ever be written.
EEO_WORDINGS = (
    "Gender",
    "Gender Identity",
    "What is your gender?",
    "Sex",
    "Race",
    "Race/Ethnicity",
    "Ethnicity",
    "What is your race or ethnicity?",
    "Are you Hispanic or Latino?",
    "Hispanic/Latino",
    "Ethnic background",
    "Veteran Status",
    "Are you a protected veteran?",
    "Protected Veteran Status",
    "Disability Status",
    "Voluntary Self-Identification of Disability",
    "Do you have a disability?",
    "Are you disabled?",
    "Pronouns",
    "Preferred pronouns",
    "National origin",
    "Sexual orientation",
    "Voluntary Self-Identification",
    "EEO Information",
)


@pytest.mark.parametrize("provider", list(AtsProvider))
@pytest.mark.parametrize("label", EEO_WORDINGS)
def test_no_eeo_wording_is_ever_recognized_as_an_answerable_field(
    label: str, provider: AtsProvider
) -> None:
    """AC2, at the recognizer. Every EEO question resolves to the EEO slot or
    to nothing at all — never to a slot the profile resolver would fill.

    This is the widest of the three checks and the cheapest place to catch a
    regression: a new label rule that claimed "National origin" for `country`
    would put the candidate's mailing-address country into a demographic
    question, and no later layer would know to stop it.
    """
    slot = recognize_application_field(AtsFormQuestion(label=label), provider=provider)

    assert slot in (None, Slot.EEO_SELF_IDENTIFICATION), (
        f"{label!r} on {provider.value} resolved to {slot}, which is a slot "
        "ApplyFlow answers from the profile."
    )


@pytest.mark.parametrize("provider", list(AtsProvider))
async def test_a_fully_disclosed_profile_writes_no_eeo_answer_on_any_portal(
    provider: AtsProvider,
) -> None:
    """AC2, through a whole autofill pass. Every category is on file, the
    form asks all four questions, and nothing is written to any of them —
    on all three supported platforms."""
    profile = candidate(
        authorization=attested(Status.CITIZEN, requires_sponsorship=False),
        eeo=FULLY_DISCLOSED_EEO,
    )
    eeo_fields = tuple(
        question(
            label,
            handle=f"f-eeo-{index}",
            options=(
                FormFieldOption(label="Female", value="Female"),
                FormFieldOption(label="Asian", value="Asian"),
                FormFieldOption(label="Yes", value="Yes"),
            ),
        )
        for index, label in enumerate(
            (
                "Gender",
                "Race/Ethnicity",
                "Are you a protected veteran? *",
                "Disability Status",
            )
        )
    )
    report, session, _ = await run_autofill(
        profile,
        eeo_fields
        + (
            question(
                "Are you legally authorized to work in the United States? *",
                handle="f-auth",
            ),
        ),
        provider=provider,
    )

    # The legal question was answered, so the pass genuinely ran and a silent
    # no-op cannot pass this test.
    assert dict(session.filled) == {"f-auth": "Yes"}

    for item in report.fields:  # type: ignore[attr-defined]
        if item.slot == Slot.EEO_SELF_IDENTIFICATION:
            assert item.outcome == FieldAutofillOutcome.SURFACED
            assert item.reason == SurfaceReason.REQUIRES_CANDIDATE_ANSWER
            assert item.value is None
            assert item.sensitivity == FieldSensitivity.VOLUNTARY_SELF_ID
            # Nothing was written, so there is nothing to confirm — this one
            # is the candidate's to answer, not to approve.
            assert item.requires_confirmation is False


async def test_no_stored_category_appears_in_anything_written_to_the_form() -> None:
    """AC2, as a blunt sweep. Whatever the fields were labelled and whatever
    slot they resolved to, no stored EEO value appears anywhere on the page.

    Deliberately not slot-aware: the previous test proves the EEO *slot* is
    refused, and this one proves no stored category leaked through some other
    field — a "Tell us about yourself" textarea, a demographic question the
    recognizer read as something else.
    """
    profile = candidate(
        authorization=attested(Status.CITIZEN, requires_sponsorship=False),
        eeo=FULLY_DISCLOSED_EEO,
    )
    _, session, _ = await run_autofill(
        profile,
        (
            question("Gender", handle="f-gender", options=()),
            question("Race", handle="f-race", options=()),
            question("Veteran status", handle="f-veteran", options=()),
            question("Disability", handle="f-disability", options=()),
            question("Pronouns", handle="f-pronouns", options=()),
            question("National origin", handle="f-origin", options=()),
            question("Sex", handle="f-sex", options=()),
            question(
                "Anything else you would like us to know?",
                handle="f-free",
                kind=FormFieldKind.TEXTAREA,
                options=(),
                required=False,
            ),
            question(
                "Country",
                handle="f-country",
                kind=FormFieldKind.TEXT,
                options=(),
                required=False,
            ),
        ),
    )

    written = " | ".join(value for _, value in session.filled)
    for leaked in EEO_VALUES:
        assert (
            leaked.lower() not in written.lower()
        ), f"stored EEO value {leaked!r} reached the form: {written!r}"


@pytest.mark.parametrize(
    "eeo",
    [
        None,
        EeoSelfIdentification(source=ProvenanceSource.ANSWER),
        EeoSelfIdentification(
            source=ProvenanceSource.ANSWER,
            gender_identity=GenderIdentity.DECLINE_TO_SELF_IDENTIFY,
            race_ethnicity=RaceEthnicity.DECLINE_TO_SELF_IDENTIFY,
            veteran_status=VeteranStatus.DECLINE_TO_SELF_IDENTIFY,
            disability_status=DisabilityStatus.DECLINE_TO_SELF_IDENTIFY,
        ),
        FULLY_DISCLOSED_EEO,
    ],
    ids=["absent", "empty", "declined-everywhere", "fully-disclosed"],
)
def test_the_refusal_does_not_depend_on_what_is_on_file(
    eeo: EeoSelfIdentification | None,
) -> None:
    """AC2. The same refusal, with the same reason, whatever the record says.

    The declined-everywhere case is the one worth stating plainly: a stored
    "decline to self-identify" is still a disclosure decision the candidate
    made for *another* employer, and carrying it forward would make a
    per-application choice into a standing one just as surely as carrying
    forward an answer would.
    """
    profile = candidate(
        authorization=attested(Status.CITIZEN, requires_sponsorship=False), eeo=eeo
    )

    decision = decide_sensitive_field(Slot.EEO_SELF_IDENTIFICATION, profile=profile)

    assert decision.is_answered is False
    assert decision.refusal is not None
    assert decision.refusal.value == "candidate_choice_only"


async def test_the_candidate_is_the_only_way_an_eeo_answer_reaches_a_form() -> None:
    """AC2, the other side of the rule. Refusing to autofill EEO is only
    right if the candidate can still disclose — so this checks the one path
    that exists, and checks that what it produces is marked as theirs.

    `answered_by_candidate` and the cleared `requires_confirmation` are what
    stop a disclosure the candidate typed from later reading like one
    ApplyFlow filled in for them.
    """
    profile = candidate(
        authorization=attested(Status.CITIZEN, requires_sponsorship=False),
        eeo=FULLY_DISCLOSED_EEO,
    )
    report, session, review_sessions = await run_autofill(
        profile, (question("Gender", handle="f-gender", options=()),)
    )
    assert session.filled == []

    answered = await AnswerApplicationField(review_sessions).execute(
        AnswerApplicationFieldInput(
            user_id="user-1",
            review_session_id=report.review_session_id,  # type: ignore[attr-defined]
            field_id="f-gender",
            value="Female",
        )
    )

    assert dict(session.filled) == {"f-gender": "Female"}
    item = field_labelled(answered, "Gender")
    assert item.value == "Female"  # type: ignore[attr-defined]
    assert item.answered_by_candidate is True  # type: ignore[attr-defined]
    assert item.requires_confirmation is False  # type: ignore[attr-defined]


def test_the_eeo_record_is_unreachable_from_every_form_filling_module() -> None:
    """AC2, structurally. No module outside the allowlist below reads the
    stored EEO record at all.

    The behavioural tests above prove the paths that exist today refuse it.
    This one is about the path somebody adds next: a prompt builder, a new
    resolver, a "prefill from last application" convenience. Each would be a
    perfectly reasonable-looking diff, and each would defeat the rule.

    A static check, in the same spirit as `test_pii_log_call_sites.py` — the
    rule is worth what its enforcement is worth. Parsed rather than grepped,
    so the many docstrings that discuss EEO by name are not mistaken for code
    that touches it.
    """
    #: The complete set of modules that may read the record: the value object
    #: itself, the entity that holds it, and the persistence mapping that
    #: stores and loads it. Nothing between the database and the profile,
    #: and nothing at all on the way to a form.
    allowed = {
        "domain/value_objects/eeo_self_identification.py",
        "domain/entities/user_profile.py",
        "infrastructure/persistence/models.py",
        "infrastructure/persistence/profile_repository_impl.py",
    }
    names = {"EeoSelfIdentification", "eeo_self_identification"}

    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            referenced = (
                node.id
                if isinstance(node, ast.Name)
                else (
                    node.attr
                    if isinstance(node, ast.Attribute)
                    else node.name if isinstance(node, ast.alias) else None
                )
            )
            if referenced in names:
                offenders.append(f"{relative}:{getattr(node, 'lineno', '?')}")

    assert not offenders, (
        "these modules read the stored EEO self-identification record, which "
        "only the profile and its persistence mapping may do: " + ", ".join(offenders)
    )


# ==============================================================================
# AC3 — the same rules across profile, tailoring, and autofill
# ==============================================================================


def test_tailoring_is_never_given_the_eeo_record() -> None:
    """AC3, tailoring. Neither fact view hands a generator anything from the
    EEO record, even with every category answered.

    Tailoring is the layer with no field-level policy to protect it: the
    facts become an LLM prompt, and anything in that prompt can end up in a
    resume or cover letter body — where no review gate is looking for
    demographic data.
    """
    profile = candidate(
        authorization=attested(Status.VISA_HOLDER, visa_type="H-1B"),
        eeo=FULLY_DISCLOSED_EEO,
    )
    extractor = CandidateFactExtractor()

    corpus = " | ".join(
        (
            *extractor.extract(profile, as_of=date(2026, 8, 3)),
            *(fact.text for fact in extractor.extract_provenance_backed(profile)),
        )
    )

    for leaked in EEO_VALUES:
        assert (
            leaked.lower() not in corpus.lower()
        ), f"EEO value {leaked!r} reached the generation corpus: {corpus!r}"


def test_tailoring_may_state_work_authorization_and_says_who_attested_it() -> None:
    """AC3, tailoring, the other rule. Work authorization is the opposite
    case: it belongs in a tailored document, and it travels with the
    provenance the guard validates it against."""
    profile = candidate(authorization=attested(Status.VISA_HOLDER, visa_type="H-1B"))
    facts = CandidateFactExtractor().extract_provenance_backed(profile)

    authorization = [fact for fact in facts if "Work authorization" in fact.text]
    assert len(authorization) == 1
    assert authorization[0].source is ProvenanceSource.ANSWER


def test_every_sensitive_slot_is_settled_by_exactly_one_policy() -> None:
    """AC3, across layers. The two categories are enumerated in one domain
    mapping, and every member of it is decided by `decide_sensitive_field` —
    so a slot cannot be added to one layer's idea of "sensitive" without
    picking up the policy in every other.
    """
    profile = candidate(
        authorization=attested(Status.CITIZEN, requires_sponsorship=False),
        eeo=FULLY_DISCLOSED_EEO,
    )

    for slot in ApplicationFieldSlot:
        if not is_sensitive_slot(slot):
            continue
        decision = decide_sensitive_field(slot, profile=profile)
        assert (decision.answer is None) != (decision.refusal is None)
        if sensitivity_of(slot) is FieldSensitivity.VOLUNTARY_SELF_ID:
            assert decision.is_answered is False

    # And the voluntary category is exactly the never-answered set, so the
    # two ways of asking "may this be filled?" cannot drift apart.
    assert (
        frozenset(
            slot
            for slot in ApplicationFieldSlot
            if sensitivity_of(slot) is FieldSensitivity.VOLUNTARY_SELF_ID
        )
        == REQUIRES_CANDIDATE_ANSWER
    )


@pytest.mark.parametrize("slot", sorted(REQUIRES_CANDIDATE_ANSWER))
def test_the_planner_has_no_branch_that_could_fill_a_voluntary_slot(
    slot: ApplicationFieldSlot,
) -> None:
    """AC3, at the planner. Whatever widget the portal used, a voluntary
    self-ID slot is surfaced.

    Widget kind is the last thing between a decision and a filled field, and
    a `SELECT` whose options happen to match a stored category is exactly the
    shape where an "it fits, so fill it" branch would be tempting.
    """
    profile = candidate(
        authorization=attested(Status.CITIZEN, requires_sponsorship=False),
        eeo=FULLY_DISCLOSED_EEO,
    )

    for kind in FormFieldKind:
        planned = AtsFormFieldPlanner().plan(
            [
                FormField(
                    name="q",
                    label="Gender",
                    handle="h",
                    kind=kind,
                    required=True,
                    options=(FormFieldOption(label="Female", value="Female"),),
                )
            ],
            provider=AtsProvider.GREENHOUSE,
            profile=profile,
        )[0]

        assert (
            planned.disposition is FieldDisposition.SURFACE
        ), f"a {kind.value} widget produced {planned.disposition} for {slot}"
        assert planned.value is None

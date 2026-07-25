"""Tests for `decide_sensitive_field` — the sensitive-field policy itself.

Two opposite rules under test: work authorization must be answered exactly
whenever the record answers it, and EEO self-identification must never be
answered at all.
"""

import pytest

from src.domain.entities.user_profile import UserProfile
from src.domain.exceptions import InvalidValueError
from src.domain.services.sensitive_field_policy import (
    SensitiveFieldDecision,
    SensitiveFieldRefusal,
    decide_sensitive_field,
)
from src.domain.value_objects.application_field_slot import (
    SENSITIVE_SLOTS,
    ApplicationFieldSlot,
    FieldSensitivity,
)
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

Slot = ApplicationFieldSlot
Status = WorkAuthorizationStatus
Refusal = SensitiveFieldRefusal

LEGAL_SLOTS = tuple(
    slot
    for slot, sensitivity in SENSITIVE_SLOTS.items()
    if sensitivity is FieldSensitivity.LEGAL_ATTESTATION
)


def make_profile(
    *,
    work_authorization: WorkAuthorization | None = None,
    eeo: EeoSelfIdentification | None = None,
) -> UserProfile:
    profile = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    profile.set_work_authorization(work_authorization)
    profile.set_eeo_self_identification(eeo)
    return profile


def authorization(
    status: Status = Status.CITIZEN,
    *,
    source: ProvenanceSource = ProvenanceSource.USER_ENTERED,
    citizenship_country: str | None = None,
    visa_type: str | None = None,
    requires_sponsorship: bool | None = None,
) -> WorkAuthorization:
    return WorkAuthorization(
        status=status,
        source=source,
        citizenship_country=citizenship_country,
        visa_type=visa_type,
        requires_sponsorship=requires_sponsorship,
    )


def decide(slot, **kwargs):
    return decide_sensitive_field(slot, profile=make_profile(**kwargs))


# ---- EEO: never answered, unconditionally ------------------------------------


def test_eeo_is_refused_when_nothing_is_on_file():
    decision = decide(Slot.EEO_SELF_IDENTIFICATION)
    assert decision.is_answered is False
    assert decision.refusal is Refusal.CANDIDATE_CHOICE_ONLY


def test_eeo_is_refused_when_every_category_is_on_file():
    """The load-bearing case. The candidate answered all four questions on
    their profile, and none of those answers may be asserted to an employer
    on their behalf — disclosure is a per-application decision."""
    decision = decide(
        Slot.EEO_SELF_IDENTIFICATION,
        eeo=EeoSelfIdentification(
            source=ProvenanceSource.ANSWER,
            gender_identity=GenderIdentity.FEMALE,
            race_ethnicity=RaceEthnicity.ASIAN,
            veteran_status=VeteranStatus.PROTECTED_VETERAN,
            disability_status=DisabilityStatus.HAS_DISABILITY,
        ),
    )

    assert decision.is_answered is False
    assert decision.refusal is Refusal.CANDIDATE_CHOICE_ONLY
    assert decision.answer is None


def test_even_an_explicit_decline_is_not_filled_in_for_the_candidate():
    """ "Decline to self-identify" is itself a disclosure decision, made per
    employer — so ApplyFlow does not submit it either."""
    decision = decide(
        Slot.EEO_SELF_IDENTIFICATION,
        eeo=EeoSelfIdentification(
            source=ProvenanceSource.ANSWER,
            gender_identity=GenderIdentity.DECLINE_TO_SELF_IDENTIFY,
        ),
    )

    assert decision.is_answered is False


def test_eeo_is_refused_regardless_of_the_work_authorization_record():
    """The EEO refusal happens before any data is read, so a fully-populated
    work-authorization record cannot influence it."""
    decision = decide(
        Slot.EEO_SELF_IDENTIFICATION,
        work_authorization=authorization(requires_sponsorship=False),
        eeo=EeoSelfIdentification(
            source=ProvenanceSource.ANSWER, gender_identity=GenderIdentity.MALE
        ),
    )

    assert decision.refusal is Refusal.CANDIDATE_CHOICE_ONLY


# ---- "Are you legally authorized to work?" -----------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.CITIZEN, "Yes"),
        (Status.PERMANENT_RESIDENT, "Yes"),
        # Holding a visa is holding authorization now; whether it will need
        # renewing is the sponsorship question, answered separately.
        (Status.VISA_HOLDER, "Yes"),
        # Needing a sponsor is what "not authorized as things stand" means.
        (Status.REQUIRES_SPONSORSHIP, "No"),
        (Status.NOT_AUTHORIZED, "No"),
    ],
)
def test_authorization_is_answered_exactly_from_the_stored_status(status, expected):
    decision = decide(Slot.WORK_AUTHORIZATION, work_authorization=authorization(status))

    assert decision.answer == expected


def test_an_other_status_settles_nothing_and_is_refused():
    """`OTHER` exists for situations the enum does not model, so it cannot be
    read as either answer — guessing here is a misstatement on a legal
    form."""
    decision = decide(
        Slot.WORK_AUTHORIZATION, work_authorization=authorization(Status.OTHER)
    )

    assert decision.is_answered is False
    assert decision.refusal is Refusal.NOT_DERIVABLE


def test_authorization_ignores_a_future_sponsorship_need():
    """A visa holder who will need sponsorship later is still authorized
    today, and can truthfully answer yes to both questions."""
    decision = decide(
        Slot.WORK_AUTHORIZATION,
        work_authorization=authorization(Status.VISA_HOLDER, requires_sponsorship=True),
    )

    assert decision.answer == "Yes"


# ---- "Will you require sponsorship?" -----------------------------------------


@pytest.mark.parametrize(
    ("requires_sponsorship", "expected"), [(True, "Yes"), (False, "No")]
)
def test_the_candidates_explicit_sponsorship_answer_is_used_verbatim(
    requires_sponsorship, expected
):
    decision = decide(
        Slot.SPONSORSHIP_REQUIRED,
        work_authorization=authorization(requires_sponsorship=requires_sponsorship),
    )

    assert decision.answer == expected


def test_an_explicit_sponsorship_answer_overrides_what_the_status_implies():
    """A citizen who says they will need sponsorship (a second citizenship, a
    move abroad) is telling us something the status does not know. Their own
    answer wins."""
    decision = decide(
        Slot.SPONSORSHIP_REQUIRED,
        work_authorization=authorization(Status.CITIZEN, requires_sponsorship=True),
    )

    assert decision.answer == "Yes"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.CITIZEN, "No"),
        (Status.PERMANENT_RESIDENT, "No"),
        (Status.REQUIRES_SPONSORSHIP, "Yes"),
    ],
)
def test_sponsorship_falls_back_to_the_statuses_that_settle_it(status, expected):
    decision = decide(
        Slot.SPONSORSHIP_REQUIRED, work_authorization=authorization(status)
    )

    assert decision.answer == expected


@pytest.mark.parametrize(
    "status", [Status.VISA_HOLDER, Status.NOT_AUTHORIZED, Status.OTHER]
)
def test_sponsorship_is_refused_for_statuses_that_do_not_settle_the_future(status):
    """The question is "now **or in the future**". A visa can expire, need
    transferring to a new employer, or need extending, and someone not
    currently authorized may or may not need this employer to sponsor them —
    so the candidate answers, not us."""
    decision = decide(
        Slot.SPONSORSHIP_REQUIRED, work_authorization=authorization(status)
    )

    assert decision.is_answered is False
    assert decision.refusal is Refusal.NOT_DERIVABLE


# ---- Free-text legal details -------------------------------------------------


def test_citizenship_country_is_answered_verbatim():
    decision = decide(
        Slot.CITIZENSHIP_COUNTRY,
        work_authorization=authorization(citizenship_country="  Portugal  "),
    )

    assert decision.answer == "Portugal"


def test_visa_type_is_answered_verbatim():
    decision = decide(
        Slot.VISA_TYPE,
        work_authorization=authorization(Status.VISA_HOLDER, visa_type="H-1B"),
    )

    assert decision.answer == "H-1B"


@pytest.mark.parametrize("blank", [None, "", "   "])
@pytest.mark.parametrize("slot", [Slot.CITIZENSHIP_COUNTRY, Slot.VISA_TYPE])
def test_an_unstated_detail_is_refused_rather_than_left_blank(slot, blank):
    decision = decide(
        slot,
        work_authorization=authorization(citizenship_country=blank, visa_type=blank),
    )

    assert decision.is_answered is False
    assert decision.refusal is Refusal.NOT_STATED


# ---- Gate 1: on file ---------------------------------------------------------


@pytest.mark.parametrize("slot", LEGAL_SLOTS)
def test_no_record_on_file_refuses_every_legal_question(slot):
    decision = decide(slot)

    assert decision.is_answered is False
    assert decision.refusal is Refusal.NOT_ON_FILE


# ---- Gate 2: candidate-attested ---------------------------------------------


@pytest.mark.parametrize("slot", LEGAL_SLOTS)
def test_a_resume_parsed_record_is_never_asserted_to_an_employer(slot):
    """The whole record is refused, not just the ambiguous parts. A work
    authorization inferred from resume prose is a claim the candidate never
    made, and this is a form they sign their name to."""
    decision = decide(
        slot,
        work_authorization=authorization(
            Status.CITIZEN,
            source=ProvenanceSource.PARSED_RESUME,
            citizenship_country="United States",
            visa_type="N/A",
            requires_sponsorship=False,
        ),
    )

    assert decision.is_answered is False
    assert decision.refusal is Refusal.NOT_CANDIDATE_ATTESTED


@pytest.mark.parametrize(
    "source", [ProvenanceSource.USER_ENTERED, ProvenanceSource.ANSWER]
)
def test_both_candidate_stated_sources_count_as_attested(source):
    """Typed into the profile, or given as an answer during the gap loop —
    either way the candidate said it."""
    decision = decide(
        Slot.WORK_AUTHORIZATION,
        work_authorization=authorization(Status.CITIZEN, source=source),
    )

    assert decision.answer == "Yes"


def test_attestation_is_checked_before_the_answer_is_derived():
    """An unattested `OTHER` status reports the attestation problem, which is
    the one the candidate can fix, rather than "not derivable"."""
    decision = decide(
        Slot.WORK_AUTHORIZATION,
        work_authorization=authorization(
            Status.OTHER, source=ProvenanceSource.PARSED_RESUME
        ),
    )

    assert decision.refusal is Refusal.NOT_CANDIDATE_ATTESTED


# ---- Misuse ------------------------------------------------------------------


@pytest.mark.parametrize("slot", [Slot.EMAIL, Slot.FULL_NAME, Slot.RESUME])
def test_an_ordinary_slot_is_a_programming_error_here(slot):
    """Crossing the two resolution paths is caught in development rather than
    in a filled form."""
    with pytest.raises(ValueError, match="not a sensitive field"):
        decide(slot)


# ---- The decision object itself ---------------------------------------------


def test_a_decision_is_exactly_one_of_an_answer_or_a_refusal():
    with pytest.raises(InvalidValueError):
        SensitiveFieldDecision()
    with pytest.raises(InvalidValueError):
        SensitiveFieldDecision(answer="Yes", refusal=Refusal.NOT_ON_FILE)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_answer_is_rejected(blank):
    """An empty string written into a legal field asserts nothing but looks
    answered."""
    with pytest.raises(InvalidValueError):
        SensitiveFieldDecision.answered(blank)


# ---- Coverage of the policy --------------------------------------------------


@pytest.mark.parametrize("slot", sorted(SENSITIVE_SLOTS))
def test_every_sensitive_slot_has_a_decision_on_a_fully_populated_profile(slot):
    """No sensitive slot may raise, and every answer must be non-blank — the
    slot enum and this policy cannot drift apart without failing here."""
    decision = decide_sensitive_field(
        slot,
        profile=make_profile(
            work_authorization=authorization(
                Status.VISA_HOLDER,
                source=ProvenanceSource.ANSWER,
                citizenship_country="India",
                visa_type="H-1B",
                requires_sponsorship=True,
            ),
            eeo=EeoSelfIdentification(
                source=ProvenanceSource.ANSWER,
                gender_identity=GenderIdentity.NON_BINARY,
            ),
        ),
    )

    if decision.is_answered:
        assert decision.answer is not None and decision.answer.strip()
    else:
        assert decision.refusal is not None


def test_no_eeo_slot_is_answerable_on_any_profile_shape():
    """A blunt sweep: whatever combination of data a profile carries, the EEO
    slot never produces a value."""
    shapes = [
        {},
        {"work_authorization": authorization()},
        {"eeo": EeoSelfIdentification(source=ProvenanceSource.ANSWER)},
        {
            "work_authorization": authorization(requires_sponsorship=True),
            "eeo": EeoSelfIdentification(
                source=ProvenanceSource.ANSWER,
                gender_identity=GenderIdentity.FEMALE,
                race_ethnicity=RaceEthnicity.WHITE,
                veteran_status=VeteranStatus.NOT_A_PROTECTED_VETERAN,
                disability_status=DisabilityStatus.NO_DISABILITY,
            ),
        },
    ]

    for shape in shapes:
        decision = decide(Slot.EEO_SELF_IDENTIFICATION, **shape)
        assert decision.answer is None
        assert decision.refusal is Refusal.CANDIDATE_CHOICE_ONLY


# ---- Consistency with the Epic 01 data-model flags --------------------------


def test_every_sensitive_slot_is_backed_by_a_record_the_model_flags_sensitive():
    """The slot policy and the data model must agree on what is sensitive.

    Epic 01 marks the sensitive records with `SENSITIVE = True` at the domain
    level (mirrored onto their ORM columns for Epic 07's encryption work). If
    a slot here were backed by a record that flag did not cover, one of the
    two would be wrong — and the disagreement would be invisible without
    this check.
    """
    assert WorkAuthorization.SENSITIVE is True
    assert EeoSelfIdentification.SENSITIVE is True

    backing_records = {
        FieldSensitivity.LEGAL_ATTESTATION: WorkAuthorization,
        FieldSensitivity.VOLUNTARY_SELF_ID: EeoSelfIdentification,
    }
    for sensitivity in SENSITIVE_SLOTS.values():
        assert backing_records[sensitivity].SENSITIVE is True


def test_the_sensitive_slot_policy_cannot_be_edited_at_runtime():
    """Which fields are sensitive is reviewed with the code, never assembled
    by configuration or patched by a caller."""
    with pytest.raises(TypeError):
        SENSITIVE_SLOTS[Slot.EMAIL] = FieldSensitivity.LEGAL_ATTESTATION  # type: ignore[index]

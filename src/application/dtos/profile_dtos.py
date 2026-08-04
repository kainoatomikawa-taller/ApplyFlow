"""DTOs — output contracts for `UserProfile` use cases.

DTOs are plain data with no behavior. Use cases return these instead of
leaking domain entities (or their value objects/enums) across the
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class WorkHistoryOutput:
    id: str
    company_name: str
    job_title: str
    start_date: date
    end_date: date | None
    location: str | None
    description: str | None
    source: str


@dataclass(frozen=True)
class EducationOutput:
    id: str
    institution_name: str
    degree: str
    majors: tuple[str, ...]
    minors: tuple[str, ...]
    #: The majors joined, as the domain derives it. Carried alongside the list so
    #: a client rendering one "field of study" line does not have to re-invent
    #: the join and risk formatting it differently from what forms receive.
    field_of_study: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    source: str


@dataclass(frozen=True)
class SkillOutput:
    id: str
    name: str
    proficiency: str | None
    years_of_experience: int | None
    source: str


@dataclass(frozen=True)
class AddressOutput:
    street_address: str | None
    city: str | None
    state_or_region: str | None
    postal_code: str | None
    country: str | None
    #: None when the address is empty — there is no fact to attribute yet.
    source: str | None


@dataclass(frozen=True)
class ProfileLinksOutput:
    portfolio_url: str | None
    linkedin_url: str | None
    github_url: str | None
    source: str | None


@dataclass(frozen=True)
class QualificationsOutput:
    """The two fields the matching layer filters on rather than fills forms
    from — a held clearance and the highest completed degree.

    Grouped as their own section because they answer a different question from
    the rest of the profile ("would this candidate be disqualified?" rather than
    "what goes in this box?"), and because grouping them is what lets the editor
    explain that they are used for matching only.
    """

    clearance_level: str | None
    highest_degree: str | None


@dataclass(frozen=True)
class ProfileOutput:
    """The whole profile, minus the EEO record.

    EEO is deliberately absent and is served by its own use case and endpoint.
    Two reasons: it keeps the number of modules that touch the record to a
    minimum (see the reachability guard in
    `tests/acceptance/test_sensitive_field_enforcement.py`), and it lets a client
    render the profile without pulling demographic data into a view that has no
    use for it.
    """

    id: str
    user_id: str
    full_name: str
    email: str
    contact_source: str
    phone: str | None
    headline: str | None
    location: str | None
    created_at: datetime
    updated_at: datetime
    #: Blank means something definite for each — see `UserProfile`. Defaulted,
    #: and placed after the required fields, so the many existing constructions
    #: of this DTO (tests, the résumé-parse response) did not all have to change
    #: when the two names were added.
    middle_name: str | None = None
    preferred_name: str | None = None
    address: AddressOutput | None = None
    links: ProfileLinksOutput | None = None
    qualifications: QualificationsOutput | None = None
    #: Defaulted for the same reason the two names above are: every existing
    #: construction of this DTO predates it.
    education_standing: EducationStandingOutput | None = None
    job_search_preferences: JobSearchPreferencesOutput | None = None
    work_history: list[WorkHistoryOutput] = field(default_factory=list)
    education: list[EducationOutput] = field(default_factory=list)
    skills: list[SkillOutput] = field(default_factory=list)


@dataclass(frozen=True)
class ContactDetailsInput:
    """What the contact section submits.

    Also the section that *creates* a profile: `full_name` and `email` are the
    aggregate's only mandatory fields, so this is the one input that can bring a
    profile into existence. See `SaveContactDetails`.
    """

    user_id: str
    full_name: str
    email: str
    phone: str | None = None
    headline: str | None = None
    location: str | None = None
    middle_name: str | None = None
    preferred_name: str | None = None


@dataclass(frozen=True)
class AddressInput:
    user_id: str
    street_address: str | None = None
    city: str | None = None
    state_or_region: str | None = None
    postal_code: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class ProfileLinksInput:
    user_id: str
    portfolio_url: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None


@dataclass(frozen=True)
class QualificationsInput:
    user_id: str
    clearance_level: str | None = None
    highest_degree: str | None = None


@dataclass(frozen=True)
class EducationStandingInput:
    """The candidate's current standing as submitted.

    All three are optional, and submitting nothing clears the section — the same
    full-replace shape as every other profile section. `enrollment_status` of
    "not_enrolled" with the other two empty is a real answer ("I have finished
    studying"), distinct from omitting it.
    """

    user_id: str
    enrollment_status: str | None = None
    degree_in_progress: str | None = None
    expected_graduation: date | None = None


@dataclass(frozen=True)
class EducationStandingOutput:
    #: None when unanswered. Distinct from "not_enrolled", which is an answer.
    enrollment_status: str | None
    degree_in_progress: str | None
    expected_graduation: date | None
    #: False when nothing has been answered, so a client can tell "not enrolled"
    #: from "not asked" without re-deriving the rule.
    is_stated: bool


@dataclass(frozen=True)
class TermInput:
    """One academic term as submitted. `year` omitted means any year."""

    season: str
    year: int | None = None


@dataclass(frozen=True)
class JobSearchPreferencesInput:
    """What the candidate wants to see. Empty lists mean "no preference", which
    is how the candidate turns filtering back off."""

    user_id: str
    employment_types: tuple[str, ...] = ()
    terms: tuple[TermInput, ...] = ()
    functions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TermOutput:
    season: str
    year: int | None
    #: "Summer 2027", or "Summer" when no year is stated. Rendered by the domain
    #: so every surface labels a term the same way.
    label: str


@dataclass(frozen=True)
class JobSearchPreferencesOutput:
    employment_types: tuple[str, ...]
    terms: tuple[TermOutput, ...]
    functions: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkHistoryInput:
    """One work-history entry as submitted.

    `entry_id` is None on create and set on update — the id is server-generated,
    never client-supplied, so a create cannot claim an id that belongs to
    something else.
    """

    user_id: str
    company_name: str
    job_title: str
    start_date: date
    entry_id: str | None = None
    end_date: date | None = None
    location: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class EducationInput:
    user_id: str
    institution_name: str
    degree: str
    entry_id: str | None = None
    majors: tuple[str, ...] = ()
    minors: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None


@dataclass(frozen=True)
class SkillInput:
    user_id: str
    name: str
    entry_id: str | None = None
    proficiency: str | None = None
    years_of_experience: int | None = None


@dataclass(frozen=True)
class WorkAuthorizationInput:
    """The work-authorization section as submitted.

    `consent_acknowledged` has to be true. This is the section that closes the
    hole the profile editor exists to close — until it existed, nothing in
    production could write a work-authorization record at all — and it stores
    GDPR Art. 9 special-category data, which needs a clear affirmative action
    rather than an inference from the request having arrived.

    The acknowledgement travels in the same request as the data, so the candidate
    ticks one box and presses one button (see
    docs/decisions/0004-gdpr-ccpa-groundwork.md). Same shape as
    `ErasureRequestInput.acknowledged`, which guards the other irreversible act
    in this codebase.

    `status` is None to clear the whole record — that is how a candidate
    withdraws data they previously gave. Clearing needs no acknowledgement:
    consent is required to *store*, not to delete.
    """

    user_id: str
    #: `WorkAuthorizationStatus` value, or None to clear the record entirely.
    status: str | None = None
    citizenship_country: str | None = None
    visa_type: str | None = None
    requires_sponsorship: bool | None = None
    details: str | None = None
    consent_acknowledged: bool = False


@dataclass(frozen=True)
class WorkAuthorizationOutput:
    """The stored work-authorization record, plus the two facts a candidate needs
    to understand it.

    `is_candidate_attested` is the difference between a record that can be
    autofilled onto an application and one that is only stored: only the
    candidate's own statement may be asserted to an employer on their behalf (see
    `decide_sensitive_field`). Showing it is what lets the editor explain why a
    résumé-derived record still gets handed back on every form.

    `consent_granted` reflects the ledger, so the editor can pre-tick the box for
    someone who has already agreed rather than making them re-affirm on each edit.
    """

    status: str | None
    citizenship_country: str | None
    visa_type: str | None
    requires_sponsorship: bool | None
    details: str | None
    source: str | None
    is_candidate_attested: bool
    consent_granted: bool


@dataclass(frozen=True)
class EeoSelfIdentificationInput:
    """The voluntary EEO section as submitted.

    Same acknowledgement rule as `WorkAuthorizationInput`, and covered by the
    same consent purpose.

    Every field is independently optional, and each None means "I did not answer
    this category" — which is distinct from `DECLINE_TO_SELF_IDENTIFY`, an answer
    in its own right. Passing all-None clears the record.
    """

    user_id: str
    gender_identity: str | None = None
    race_ethnicity: str | None = None
    veteran_status: str | None = None
    disability_status: str | None = None
    consent_acknowledged: bool = False


@dataclass(frozen=True)
class EeoSelfIdentificationOutput:
    """The stored EEO record, for the candidate's own eyes only.

    ApplyFlow never fills these answers onto an application — that refusal is
    unconditional and lives in `decide_sensitive_field`. This DTO exists so the
    candidate can see, correct, and withdraw what is stored, and so the data
    export can include it. It must not be handed to anything that fills forms.
    """

    gender_identity: str | None
    race_ethnicity: str | None
    veteran_status: str | None
    disability_status: str | None
    source: str | None
    consent_granted: bool

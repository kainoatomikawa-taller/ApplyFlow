"""Pydantic request/response schemas.

These are presentation-layer contracts. Input validation (shape, types)
happens here; business rules are enforced in the domain layer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, EmailStr, Field


class CreateApplicationRequest(BaseModel):
    candidate_email: EmailStr
    company_name: str = Field(min_length=1, max_length=255)
    role_title: str = Field(min_length=1, max_length=255)
    job_description: str = Field(min_length=1)


class AnalyzeApplicationRequest(BaseModel):
    resume_text: str = Field(min_length=1)


class ApplicationResponse(BaseModel):
    id: str
    candidate_email: str
    company_name: str
    role_title: str
    status: str
    match_score: int | None
    tailored_cover_letter: str | None
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    message: str


class ResumeResponse(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    extracted_text: str
    created_at: datetime


class WorkHistoryResponse(BaseModel):
    id: str
    company_name: str
    job_title: str
    start_date: date
    end_date: date | None
    location: str | None
    description: str | None
    source: str


class EducationResponse(BaseModel):
    id: str
    institution_name: str
    degree: str
    majors: list[str]
    minors: list[str]
    #: The majors joined, as forms receive them. Read-only — writes send `majors`.
    field_of_study: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    source: str


class SkillResponse(BaseModel):
    id: str
    name: str
    proficiency: str | None
    years_of_experience: int | None
    source: str


class AddressResponse(BaseModel):
    street_address: str | None = None
    city: str | None = None
    state_or_region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    source: str | None = None


class ProfileLinksResponse(BaseModel):
    portfolio_url: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    source: str | None = None


class QualificationsResponse(BaseModel):
    clearance_level: str | None = None
    highest_degree: str | None = None


class TermResponse(BaseModel):
    season: str
    year: int | None = None
    #: Rendered by the domain so every surface spells a term identically.
    label: str


class JobSearchPreferencesResponse(BaseModel):
    employment_types: list[str] = Field(default_factory=list)
    terms: list[TermResponse] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    """The whole profile, minus the EEO record — that has its own endpoint.

    `middle_name` and `preferred_name` are optional and defaulted, so the
    résumé-parse response (which does not set them) keeps its shape.
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
    middle_name: str | None = None
    preferred_name: str | None = None
    address: AddressResponse | None = None
    links: ProfileLinksResponse | None = None
    qualifications: QualificationsResponse | None = None
    job_search_preferences: JobSearchPreferencesResponse | None = None
    work_history: list[WorkHistoryResponse] = Field(default_factory=list)
    education: list[EducationResponse] = Field(default_factory=list)
    skills: list[SkillResponse] = Field(default_factory=list)


class JobRequirementsResponse(BaseModel):
    degree_level: str | None
    degree_required: bool | None
    clearance_level: str | None
    clearance_required: bool | None
    remote_type: str | None
    work_authorization: str | None
    min_years_experience: int | None
    max_years_experience: int | None
    locations: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    preferences: list[str]


class JobPostingResponse(BaseModel):
    id: str
    source: str
    company: str
    title: str
    apply_url: str
    location: str | None
    is_remote: bool
    status: str
    posted_at: date | None
    created_at: datetime
    requirements: JobRequirementsResponse | None = None


class RankedJobResponse(BaseModel):
    job_posting: JobPostingResponse
    score: int
    rationale: str
    gaps: list[str]
    #: Whether the candidate already applied to this role. False on every
    #: entry unless the caller asked for already-applied jobs to be included —
    #: they are suppressed by default, so the list stays a list of jobs to
    #: apply to.
    already_applied: bool = False


class JobRequirementGapsResponse(BaseModel):
    job_posting_id: str
    gaps: list[str]


class ProvenanceViolationResponse(BaseModel):
    """One assertion the provenance guard removed from generated output,
    and the terms nothing in the candidate's attested data backed."""

    line: str
    unsupported_terms: list[str] = Field(default_factory=list)


class GuardedDocumentResponse(BaseModel):
    """Generated content after the provenance guard has run. `content` is
    post-guard text only — the raw model draft is never serialized.
    `violations` is non-empty when the model asserted something it could
    not support, which is useful to surface and never a request failure on
    its own: the document that came back is still made only of attested
    claims."""

    document_id: str
    job_posting_id: str
    document_kind: str
    content: str
    version: int
    backing_sources: list[str] = Field(default_factory=list)
    violations: list[ProvenanceViolationResponse] = Field(default_factory=list)


class ReviseDocumentRequest(BaseModel):
    """A candidate's edited version of a generated document. `content` is
    the whole document, not a diff — see `ReviseGeneratedDocumentInput`."""

    content: str = Field(min_length=1)


class ApplicationDocumentSummaryResponse(BaseModel):
    """One stored sent-document snapshot, without its text. `content_sha256`
    identifies the exact content so a client can tell versions apart, or
    confirm a document it already holds, without downloading it again."""

    id: str
    job_posting_id: str
    document_kind: str
    version: int
    content_sha256: str
    created_at: datetime
    backing_sources: list[str] = Field(default_factory=list)


class ApplicationDocumentResponse(BaseModel):
    """One stored snapshot including the exact text that was produced —
    what the tracker and interview prep read instead of regenerating a
    document (see `ApplicationDocument`)."""

    id: str
    job_posting_id: str
    document_kind: str
    version: int
    content: str
    content_sha256: str
    created_at: datetime
    backing_sources: list[str] = Field(default_factory=list)


class ResumeSectionResponse(BaseModel):
    """One section of the resume as an ATS parser will read it."""

    heading: str
    lines: list[str] = Field(default_factory=list)


class AtsSafetyViolationResponse(BaseModel):
    """One ATS-safety rule the finished resume breaks. Expected to be absent:
    the formatter enforces these rules, and a finding here means it let
    something through."""

    rule: str
    detail: str
    line: str
    line_number: int


class ResumeExportsResponse(BaseModel):
    """The tailored resume's three renderings, all derived from the same
    guarded text.

    `text` is the plain-text export, `contact_lines`/`sections` the structured
    one, and `pdf_base64` the PDF file. The PDF travels base64-encoded inside
    this JSON rather than from a separate download route: the bytes only exist
    as the product of one guarded generation, so a route that re-rendered them
    would either spend another model call or have to accept caller-supplied
    text — and caller-supplied text is a way around the provenance guard.
    """

    text: str
    pdf_base64: str
    pdf_byte_size: int
    contact_lines: list[str] = Field(default_factory=list)
    sections: list[ResumeSectionResponse] = Field(default_factory=list)


class TailoredResumeResponse(BaseModel):
    document: GuardedDocumentResponse
    exports: ResumeExportsResponse
    ats_safety_violations: list[AtsSafetyViolationResponse] = Field(
        default_factory=list
    )


class GenerateGapQuestionsRequest(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    # Optional override of the "already answered" match strictness; unset
    # falls back to AnswerSimilarityMatcher.DEFAULT_THRESHOLD.
    similarity_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)


class GapResolutionQuestionResponse(BaseModel):
    gap: str
    question: str


class AlreadyAnsweredGapResponse(BaseModel):
    """A gap suppressed because a remembered answer already covers it.
    Exposes the matched record's id and score only — never the remembered
    question or answer text, which is sensitive (see `AnswerMemory`)."""

    gap: str
    answer_memory_id: str
    similarity_score: float


class GapResolutionQuestionsResponse(BaseModel):
    questions: list[GapResolutionQuestionResponse] = Field(default_factory=list)
    already_answered: list[AlreadyAnsweredGapResponse] = Field(default_factory=list)


class ResolveGapAnswerRequest(BaseModel):
    gap: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = ""


class ResolveGapAnswerResponse(BaseModel):
    gap: str
    captured: bool
    answer_memory_id: str | None = None


class SubmitJobMatchFeedbackRequest(BaseModel):
    rating: Literal["thumbs_up", "thumbs_down"]
    score_at_feedback: int = Field(ge=0, le=100)


class JobMatchFeedbackResponse(BaseModel):
    id: str
    user_id: str
    job_posting_id: str
    rating: str
    score_at_feedback: int
    created_at: datetime


class ScoreBucketAgreementResponse(BaseModel):
    range_start: int
    range_end: int
    thumbs_up: int
    thumbs_down: int
    agreement_rate: float | None


class ScoringFeedbackSummaryResponse(BaseModel):
    buckets: list[ScoreBucketAgreementResponse]


class ApplicationBoundaryResponse(BaseModel):
    """A human-only check found on an application page.

    A client renders `instruction` — it is what the candidate does next —
    and shows `evidence` so the hand-off is checkable rather than an
    assertion. `stopped_autofill` and `blocks_submission` are the two
    different consequences and must not be collapsed: a CAPTCHA leaves a
    filled form worth reviewing, a login wall does not.
    """

    kind: str
    evidence: str
    instruction: str
    stopped_autofill: bool
    blocks_submission: bool


class AutofilledFieldResponse(BaseModel):
    """One field on the form and what became of it.

    `value` carries what was written onto a real application — the
    candidate's own contact details, and on the legal fields their
    work-authorization answers. It is here because a review screen exists to
    show exactly that, and for no other reason: it must not be logged.
    """

    field_id: str
    label: str
    kind: str
    required: bool
    outcome: str
    slot: str | None = None
    value: str | None = None
    is_derived: bool = False
    reason: str | None = None
    detail: str | None = None
    is_sensitive: bool = False
    sensitivity: str | None = None
    requires_confirmation: bool = False
    answered_by_candidate: bool = False


class ApplicationAutofillResponse(BaseModel):
    """A filled application form, as the review screen receives it.

    The two id lists are the submission gates, named rather than left for a
    client to re-derive from the flags: whatever is in either of them will be
    refused at submit time, and a UI that computed them differently would
    offer a Submit button that cannot work.
    """

    job_posting_id: str
    apply_url: str
    ats_provider: str
    fields: list[AutofilledFieldResponse]
    screenshot_png_base64: str | None = None
    boundaries: list[ApplicationBoundaryResponse] = Field(default_factory=list)
    review_session_id: str | None = None
    review_expires_at: datetime | None = None
    requires_handoff: bool = False
    can_be_submitted_here: bool = False
    fields_awaiting_confirmation: list[str] = Field(default_factory=list)
    unanswered_required_fields: list[str] = Field(default_factory=list)


class AnswerApplicationFieldRequest(BaseModel):
    """The candidate's own answer to one surfaced field.

    Empty is refused: clearing a field is not what this route is for, and an
    empty string written into a required question looks answered while
    asserting nothing.
    """

    value: str = Field(min_length=1)


class SubmitApplicationRequest(BaseModel):
    """The candidate's instruction to send the application.

    `confirmed_field_ids` are the sensitive values they have looked at and
    approved (`fields_awaiting_confirmation` above). `submit_control_label`
    only has to be given when the form offers more than one way to send it,
    and is the label the candidate saw.
    """

    confirmed_field_ids: list[str] = Field(default_factory=list)
    submit_control_label: str | None = None


class ApplicationSubmissionResponse(BaseModel):
    """What happened when the application was sent.

    `is_confirmed_sent` is the field to trust, not the 200: the press
    succeeded either way, and only the absence of a post-press boundary means
    the portal actually took the application.
    """

    job_posting_id: str
    submitted_at: datetime
    pressed_control: str
    final_url: str
    confirmation_excerpt: str = ""
    screenshot_png_base64: str | None = None
    outstanding_boundaries: list[ApplicationBoundaryResponse] = Field(
        default_factory=list
    )
    is_confirmed_sent: bool = True


class InspectPortalRequest(BaseModel):
    job_posting_id: str = Field(min_length=1)


class HardStopResponse(BaseModel):
    """One boundary found on an application portal, with the case for
    stopping. `evidence` describes the portal's page and carries nothing
    about the candidate, so it is safe to show and to log."""

    kind: str
    refusal_reason: str
    human_action: str
    evidence: list[str] = Field(default_factory=list)


class PortalHandoffResponse(BaseModel):
    """A hand-off's full state — what ApplyFlow hit, where it stopped, and
    how it stands. `paused_url` is the URL the candidate should open to do
    the step themselves; it is frequently not the apply URL."""

    id: str
    job_posting_id: str
    apply_url: str
    paused_url: str
    status: str
    is_open: bool
    created_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str = ""
    hard_stops: list[HardStopResponse] = Field(default_factory=list)


class PortalFieldResponse(BaseModel):
    """One question the portal asks. Carries no field handle: a handle only
    means anything inside the live browser session that minted it, and that
    session is closed before this response is sent."""

    label: str
    kind: str
    name: str = ""
    required: bool = False
    human_only_boundary: str | None = None


class InspectPortalResponse(BaseModel):
    """The result of inspecting a portal. Branch on `is_handed_off`: when it
    is true, `handoff` is set and `fields` is empty — the form is withheld
    rather than merely flagged, so nothing downstream can fill a portal
    ApplyFlow stopped on (see `InspectApplicationPortalOutput`)."""

    job_posting_id: str
    apply_url: str
    landed_url: str
    is_handed_off: bool
    handoff: PortalHandoffResponse | None = None
    fields: list[PortalFieldResponse] = Field(default_factory=list)
    cleared_handoff_id: str | None = None


class ResolvePortalHandoffRequest(BaseModel):
    # Free text, and optional: "I signed in" is useful context, but nothing
    # downstream requires it. Capped at the entity's own limit
    # (`PortalHandoff.MAX_NOTE_LENGTH`) so an over-long note is a 422 here
    # rather than a domain error deeper in.
    note: str = Field(default="", max_length=1000)


class PortalHandoffListResponse(BaseModel):
    handoffs: list[PortalHandoffResponse] = Field(default_factory=list)
    open_count: int = 0


class ReviewedAnswerResponse(BaseModel):
    """One question on a filled application as it stands.

    SENSITIVE: `value` is what goes onto a real application. Returned to its
    owner only, and never logged (see `ApplicationReview`)."""

    key: str
    label: str
    widget_kind: str
    value: str
    required: bool
    origin: str
    slot: str | None = None
    sensitivity: str | None = None
    is_sensitive: bool = False
    needs_decision: bool = False
    explanation: str = ""


class SubmissionBlockerResponse(BaseModel):
    kind: str
    detail: str
    field_key: str | None = None
    field_label: str = ""


class ApplicationReviewResponse(BaseModel):
    """A filled application, everything still waiting on the candidate, and the
    one flag a submit button binds to (`can_submit`)."""

    id: str
    job_posting_id: str
    apply_url: str
    ats_provider: str
    status: str
    is_open: bool
    created_at: datetime
    answers: list[ReviewedAnswerResponse] = Field(default_factory=list)
    blockers: list[SubmissionBlockerResponse] = Field(default_factory=list)
    can_submit: bool = False
    handoff: PortalHandoffResponse | None = None
    unanswered_required_keys: list[str] = Field(default_factory=list)
    screenshot_captured: bool = False
    submitted_at: datetime | None = None
    submission_note: str = ""


class OpenApplicationReviewResponse(BaseModel):
    """The result of filling a form and opening a review over it.

    `review` is null only when the portal is blocked by a hard stop: nothing was
    filled, and `handoff` says why — a correct outcome, which is why it is a 200
    rather than an error."""

    job_posting_id: str
    review: ApplicationReviewResponse | None = None
    handoff: PortalHandoffResponse | None = None
    #: The filled form as a base64 PNG, when the pass captured one. Proof the
    #: candidate can check the answers against; not stored server-side.
    screenshot_base64: str | None = None


class ReviseReviewedAnswerRequest(BaseModel):
    """One decision about one field: write an answer, approve the one that is
    there, or leave it deliberately blank."""

    action: Literal["set", "confirm", "decline"]
    value: str = ""


class SubmitApplicationReviewRequest(BaseModel):
    # Capped at the entity's own limit (`ApplicationReview.MAX_NOTE_LENGTH`) so
    # an over-long note is a 422 here rather than a domain error deeper in.
    note: str = Field(default="", max_length=1000)


class SubmitApplicationReviewResponse(BaseModel):
    """What comes back when the candidate submits.

    Carries `apply_url` because ApplyFlow does not press the portal's submit
    button — it cannot (see `BrowserAutomationPort`). The submission is
    recorded; sending it is the candidate's own act, and this is where they go
    to finish."""

    review: ApplicationReviewResponse
    apply_url: str


class SentDocumentResponse(BaseModel):
    """One document as it went out with an application.

    No `content`: a tracker list never displays document text, and it is the
    most PII-dense content the system holds. `content_sha256` lets a client
    confirm which exact snapshot this is; the text itself is a separate,
    deliberate read (`GET /api/application-documents/{id}`)."""

    id: str
    document_kind: str
    version: int
    content_sha256: str
    created_at: datetime


class UpdateApplicationStatusRequest(BaseModel):
    """Move a tracked application to a new status.

    `status` is validated as a non-empty string here and resolved against the
    lifecycle by the use case — the set of statuses and the legal moves between
    them are domain rules, and a `Literal` here would be a second copy of the
    first that could fall out of step with it.
    """

    status: str = Field(min_length=1)
    # Capped at the value object's own limit
    # (`ApplicationStatusChange.MAX_NOTE_LENGTH`) so an over-long note is a 422
    # here rather than a domain error deeper in.
    note: str = Field(default="", max_length=1000)


class ApplicationStatusChangeResponse(BaseModel):
    """One recorded move in an application's history.

    `previous_status` is null for exactly one entry: the first, recorded when
    the application was sent.
    """

    status: str
    changed_at: datetime
    previous_status: str | None = None
    note: str = ""


class TrackedApplicationResponse(BaseModel):
    """One application the candidate sent, where it stands, and how it got
    there.

    `current_status_since` is what a follow-up view reads: it equals
    `applied_at` until the application first moves, and afterwards says how long
    it has been where it is. `is_open` comes from the domain's own
    terminal-status rule rather than being re-derived from `status` by each
    client, and `allowed_next_statuses` is that same domain's
    `ApplicationStatus.allowed_transitions` — sent so a status control offers
    exactly the moves the PATCH will accept. Empty means the application has
    settled and there is nothing left to choose.

    The documents appear twice, and both are useful. `resume_document_id` /
    `cover_letter_document_id` name the exact snapshots the employer received
    (see `ApplicationDocument`). `resume` / `cover_letter` are those same
    references already resolved — version, digest, and date — so a tracker row
    can say *which* document went out without a request per row. Neither
    carries the text: a client that wants it asks the documents endpoint.
    """

    id: str
    job_posting_id: str
    company_name: str
    role_title: str
    applied_at: datetime
    status: str
    is_open: bool
    current_status_since: datetime
    resume_document_id: str
    cover_letter_document_id: str | None = None
    job_location: str | None = None
    allowed_next_statuses: list[str] = Field(default_factory=list)
    resume: SentDocumentResponse | None = None
    cover_letter: SentDocumentResponse | None = None
    status_history: list[ApplicationStatusChangeResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TrackedApplicationListResponse(BaseModel):
    """A candidate's applications, most recently applied first.

    `open_count` is included because "how many are still live?" is the number
    the tracker's header shows, and counting it client-side over a `limit`-ed
    page would be wrong as soon as the page did not hold everything.
    """

    applications: list[TrackedApplicationResponse] = Field(default_factory=list)
    open_count: int = 0


# -- Data-subject rights: export, erasure, consent ---------------------------
#
# The export and erasure responses carry more explanation than a typical
# response schema, and deliberately: they are the artifacts a subject access
# request is answered with, so each section states what the data is and why it
# is held, and both list the categories this application does *not* hold or
# cannot erase. A copy that is only rows is a copy the recipient cannot check.
# See src/domain/services/personal_data_inventory.py.


class ConsentStateResponse(BaseModel):
    """One consent purpose and where it stands.

    `granted` is the answer to act on; `decided` says whether the user has ever
    been asked, which is a different question. A purpose that is granted because
    it is contract-based rather than because anyone agreed to it reads as
    `granted=true, decided=false`, and a UI that showed only `granted` would be
    showing the user a "yes" they never gave.
    """

    purpose: str
    description: str
    lawful_basis: str
    granted: bool
    decided: bool
    withdrawable: bool
    decided_at: datetime | None = None
    policy_version: str | None = None


class ConsentDecisionResponse(BaseModel):
    """One entry in the consent ledger — the demonstration record."""

    purpose: str
    granted: bool
    decided_at: datetime
    policy_version: str


class RecordConsentRequest(BaseModel):
    """A grant or a withdrawal for the purpose named in the path.

    The purpose is not in the body: it is the resource being addressed. The
    policy version is not in the body either — it is the version this deployment
    is serving, which the client does not get to assert.
    """

    granted: bool


class RecordConsentResponse(BaseModel):
    """The resulting state, plus whether the ledger actually changed.

    `changed` is false when the request restated what was already recorded — a
    client re-sending the state of a toggle it had already rendered. Reported
    rather than hidden so a caller can say "already set" without diffing, and so
    the ledger stays a record of decisions rather than of clicks.
    """

    state: ConsentStateResponse
    changed: bool


class ExportedCategoryResponse(BaseModel):
    """One section of a portable copy."""

    key: str
    description: str
    store: str
    lawful_basis: str
    record_count: int
    #: Stored records as column-name -> value. Untyped on purpose: this carries
    #: everything held, which is what portability means, rather than the subset
    #: some response model happens to describe.
    records: list[dict[str, Any]] = Field(default_factory=list)


class DeferredCategoryResponse(BaseModel):
    """A category that is not in the portable copy, or not erased here — with
    the reason and whoever has to act."""

    key: str
    description: str
    store: str
    lawful_basis: str
    disposition: str
    note: str


class PersonalDataExportResponse(BaseModel):
    """A complete, portable copy of the authenticated user's data."""

    format_version: str
    subject_user_id: str
    generated_at: datetime
    consent_policy_version: str | None = None
    categories: list[ExportedCategoryResponse] = Field(default_factory=list)
    deferred_categories: list[DeferredCategoryResponse] = Field(default_factory=list)
    consents: list[ConsentStateResponse] = Field(default_factory=list)
    consent_history: list[ConsentDecisionResponse] = Field(default_factory=list)
    #: Completeness caveats, stated in the document rather than logged: the
    #: person holding the export is the one who needs to know it may be short.
    limitations: list[str] = Field(default_factory=list)


class ErasureRequest(BaseModel):
    """A request to erase everything erasable about the authenticated user.

    `acknowledged` has to be true, and the endpoint refuses without it. Erasure
    is irreversible and total; an endpoint that ran on an empty body is one an
    accidental POST can trigger.
    """

    acknowledged: bool = False
    reason: str = Field(default="", max_length=1000)


class ErasedCategoryResponse(BaseModel):
    """One category the erasure deleted, and how much."""

    key: str
    description: str
    store: str
    records_erased: int


class ErasureReceiptResponse(BaseModel):
    """The receipt for an erasure request.

    `retained` is beside `erased` for the same reason the export lists deferred
    categories: a receipt of deletions alone invites the reader to conclude the
    remainder was nothing.
    """

    subject_user_id: str
    executed_at: datetime
    total_records_erased: int
    erased: list[ErasedCategoryResponse] = Field(default_factory=list)
    retained: list[DeferredCategoryResponse] = Field(default_factory=list)
    consents_withdrawn: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# -- Profile editor ----------------------------------------------------------
#
# One request schema per section, matching the per-section endpoints. Each `PUT`
# fully replaces its own section, so an omitted field is cleared — that is how a
# candidate deletes a phone number or an address, and it is why these are not
# partial patches.
#
# Shape validation only. The business rules stay in the domain: dates ordering on
# a work-history entry, the unique-skill rule, and "a source is required once a
# group carries data" are all enforced there and would drift if restated here.


class ContactDetailsRequest(BaseModel):
    """The contact section — and the one that creates a profile.

    `full_name` and `email` are the only mandatory fields on the whole profile,
    which is what makes this section able to bring one into existence for a
    candidate who has no résumé to parse.
    """

    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)
    headline: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    #: Leaving these blank means something definite: no middle name, and no
    #: preferred name distinct from the legal one. See `UserProfile`.
    middle_name: str | None = Field(default=None, max_length=255)
    preferred_name: str | None = Field(default=None, max_length=255)


class AddressRequest(BaseModel):
    street_address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    state_or_region: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=255)


class ProfileLinksRequest(BaseModel):
    portfolio_url: str | None = Field(default=None, max_length=2048)
    linkedin_url: str | None = Field(default=None, max_length=2048)
    github_url: str | None = Field(default=None, max_length=2048)


class TermRequest(BaseModel):
    """One academic term. Omitting `year` means any year of that season."""

    season: str = Field(min_length=1, max_length=16)
    year: int | None = Field(default=None, ge=2000, le=2100)


class JobSearchPreferencesRequest(BaseModel):
    """What the candidate wants to see, replacing whatever was stored.

    Empty lists are meaningful and are the documented way to stop filtering —
    which is why neither field has a minimum length. The caps bound a payload,
    they are not a rule about how many kinds of work a person may want.
    """

    employment_types: list[str] = Field(default_factory=list, max_length=8)
    terms: list[TermRequest] = Field(default_factory=list, max_length=12)


class QualificationsRequest(BaseModel):
    """Clearance and highest degree — used for matching, never for filling forms.

    Both are enum values; an unrecognized one is a 422 from the use case rather
    than being silently dropped, because a discarded clearance level would read
    as "not stated" and change which jobs are shown.
    """

    clearance_level: str | None = None
    highest_degree: str | None = None


class WorkHistoryRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    job_title: str = Field(min_length=1, max_length=255)
    start_date: date
    end_date: date | None = None
    location: str | None = Field(default=None, max_length=255)
    description: str | None = None


class EducationRequest(BaseModel):
    institution_name: str = Field(min_length=1, max_length=255)
    degree: str = Field(min_length=1, max_length=255)
    #: Blank and duplicate entries are dropped by the domain, so no `min_length`
    #: on the items — an editor with one row per subject can submit a trailing
    #: empty one. The list caps are there to stop an unbounded payload, not to
    #: express a rule about how many degrees a person may hold.
    majors: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=12
    )
    minors: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=12
    )
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None


class SkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    proficiency: str | None = None
    years_of_experience: int | None = Field(default=None, ge=0, le=80)


class WorkAuthorizationRequest(BaseModel):
    """The legal declarations, plus the acknowledgement that stores them.

    `consent_acknowledged` must be true to save data — this is GDPR Art. 9
    special-category data, and explicit consent means a clear affirmative action
    rather than an inference from the request arriving. The UI renders it as a box
    beside the notice text, so it is one form and one submit.

    `status: null` clears the record, and clearing needs no acknowledgement:
    consent is required to store this data, not to delete it.
    """

    status: str | None = None
    citizenship_country: str | None = Field(default=None, max_length=255)
    visa_type: str | None = Field(default=None, max_length=64)
    requires_sponsorship: bool | None = None
    details: str | None = None
    consent_acknowledged: bool = False


class WorkAuthorizationResponse(BaseModel):
    """The stored record, plus the two things a candidate needs to make sense of it.

    `is_candidate_attested` is why a résumé-derived record still gets handed back
    on every form: only the candidate's own statement may be asserted to an
    employer on their behalf. `consent_granted` lets the editor pre-tick the box
    for someone who has already agreed.
    """

    status: str | None = None
    citizenship_country: str | None = None
    visa_type: str | None = None
    requires_sponsorship: bool | None = None
    details: str | None = None
    source: str | None = None
    is_candidate_attested: bool = False
    consent_granted: bool = False


class EeoSelfIdentificationRequest(BaseModel):
    """Voluntary self-identification. Same acknowledgement rule as above.

    Every category is independently optional, and omitting one means "I did not
    answer this" — distinct from `decline_to_self_identify`, which is an answer.
    All-empty clears the record.
    """

    gender_identity: str | None = None
    race_ethnicity: str | None = None
    veteran_status: str | None = None
    disability_status: str | None = None
    consent_acknowledged: bool = False


class EeoSelfIdentificationResponse(BaseModel):
    """The stored EEO record, for the candidate's own view and the data export.

    ApplyFlow never fills these onto an application — that refusal is
    unconditional. This response must not be handed to anything that fills forms.
    """

    gender_identity: str | None = None
    race_ethnicity: str | None = None
    veteran_status: str | None = None
    disability_status: str | None = None
    source: str | None = None
    consent_granted: bool = False

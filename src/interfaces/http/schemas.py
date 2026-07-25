"""Pydantic request/response schemas.

These are presentation-layer contracts. Input validation (shape, types)
happens here; business rules are enforced in the domain layer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

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


class ProfileResponse(BaseModel):
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
    work_history: list[WorkHistoryResponse]
    education: list[EducationResponse]
    skills: list[SkillResponse]


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

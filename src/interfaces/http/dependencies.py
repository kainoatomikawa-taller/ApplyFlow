"""Composition root — the ONLY place where wiring happens.

This module is the application's composition root. It is the single,
deliberate exception that knows about both `application` use cases and
`infrastructure` implementations, so it can inject concrete adapters into
abstract ports. Controllers depend only on this module's factories and on
application-layer types — never on infrastructure directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.exceptions import AuthenticationError
from src.application.ports.auth_verifier_port import AuthVerifierPort
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.application_review_sessions import (
    ApplicationReviewSessions,
)
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.application.services.relevant_answer_selector import RelevantAnswerSelector
from src.application.services.submitted_application_log import SubmittedApplicationLog
from src.application.use_cases.abandon_portal_handoff import AbandonPortalHandoff
from src.application.use_cases.analyze_job_application import (
    AnalyzeJobApplication,
)
from src.application.use_cases.analyze_scoring_feedback import (
    AnalyzeScoringFeedback,
)
from src.application.use_cases.answer_application_field import AnswerApplicationField
from src.application.use_cases.autofill_application_form import AutofillApplicationForm
from src.application.use_cases.create_job_application import (
    CreateJobApplication,
)
from src.application.use_cases.detect_job_requirement_gaps import (
    DetectJobRequirementGaps,
)
from src.application.use_cases.discard_application_review import (
    DiscardApplicationReview,
)
from src.application.use_cases.generate_cover_letter import GenerateCoverLetter
from src.application.use_cases.generate_gap_resolution_questions import (
    GenerateGapResolutionQuestions,
)
from src.application.use_cases.generate_tailored_resume import GenerateTailoredResume
from src.application.use_cases.get_application_document import GetApplicationDocument
from src.application.use_cases.get_application_review import GetApplicationReview
from src.application.use_cases.get_latest_application_document import (
    GetLatestApplicationDocument,
)
from src.application.use_cases.get_resume import GetResume
from src.application.use_cases.inspect_application_portal import (
    InspectApplicationPortal,
)
from src.application.use_cases.list_application_documents import (
    ListApplicationDocuments,
)
from src.application.use_cases.list_candidate_applications import (
    ListCandidateApplications,
)
from src.application.use_cases.list_job_match_feedback import (
    ListJobMatchFeedback,
)
from src.application.use_cases.list_portal_handoffs import ListPortalHandoffs
from src.application.use_cases.list_resumes import ListResumes
from src.application.use_cases.list_tracked_applications import (
    ListTrackedApplications,
)
from src.application.use_cases.open_application_review import OpenApplicationReview
from src.application.use_cases.parse_resume import ParseResume
from src.application.use_cases.rank_matched_job_postings import (
    RankMatchedJobPostings,
)
from src.application.use_cases.resolve_gap_answer import ResolveGapAnswer
from src.application.use_cases.resume_portal_handoff import ResumePortalHandoff
from src.application.use_cases.revise_generated_document import (
    ReviseGeneratedDocument,
)
from src.application.use_cases.revise_reviewed_answer import ReviseReviewedAnswer
from src.application.use_cases.submit_application_form import SubmitApplicationForm
from src.application.use_cases.submit_application_review import (
    SubmitApplicationReview,
)
from src.application.use_cases.submit_job_application import (
    SubmitJobApplication,
)
from src.application.use_cases.submit_job_match_feedback import (
    SubmitJobMatchFeedback,
)
from src.application.use_cases.update_tracked_application_status import (
    UpdateTrackedApplicationStatus,
)
from src.application.use_cases.upload_resume import UploadResume
from src.domain.services.application_ranking_service import (
    ApplicationRankingService,
)
from src.infrastructure.auth.supabase_jwt_verifier import SupabaseJwtVerifier
from src.infrastructure.browser_automation.playwright_browser_automation import (
    PlaywrightBrowserAutomation,
)
from src.infrastructure.config import get_settings
from src.infrastructure.documents.ats_safe_pdf_renderer import AtsSafePdfRenderer
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient
from src.infrastructure.llm.langchain_resume_analyzer import (
    LangChainResumeAnalyzer,
)
from src.infrastructure.llm.llm_cover_letter_generator import LlmCoverLetterGenerator
from src.infrastructure.llm.llm_gap_resolution_question_generator import (
    LlmGapResolutionQuestionGenerator,
)
from src.infrastructure.llm.llm_job_fit_rationale_generator import (
    LlmJobFitRationaleGenerator,
)
from src.infrastructure.llm.llm_requirement_gap_detector import (
    LlmRequirementGapDetector,
)
from src.infrastructure.llm.llm_resume_parser import LlmResumeParser
from src.infrastructure.llm.llm_tailored_resume_generator import (
    LlmTailoredResumeGenerator,
)
from src.infrastructure.llm.openai_embedding_client import OpenAiEmbeddingClient
from src.infrastructure.persistence.answer_memory_repository_impl import (
    SqlAlchemyAnswerMemoryRepository,
)
from src.infrastructure.persistence.application_document_repository_impl import (
    SqlAlchemyApplicationDocumentRepository,
)
from src.infrastructure.persistence.application_review_repository_impl import (
    SqlAlchemyApplicationReviewRepository,
)
from src.infrastructure.persistence.database import get_session
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)
from src.infrastructure.persistence.job_match_feedback_repository_impl import (
    SqlAlchemyJobMatchFeedbackRepository,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.portal_handoff_repository_impl import (
    SqlAlchemyPortalHandoffRepository,
)
from src.infrastructure.persistence.profile_repository_impl import (
    SqlAlchemyProfileRepository,
)
from src.infrastructure.persistence.resume_repository_impl import (
    SqlAlchemyResumeRepository,
)
from src.infrastructure.persistence.tracked_application_repository_impl import (
    SqlAlchemyTrackedApplicationRepository,
)
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator
from src.infrastructure.storage.local_file_storage import LocalFileStorage
from src.infrastructure.text_extraction.resume_text_extractor import (
    ResumeTextExtractor,
)


def _repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyJobApplicationRepository:
    return SqlAlchemyJobApplicationRepository(session)


def get_create_use_case(
    repository: SqlAlchemyJobApplicationRepository = Depends(_repository),
) -> CreateJobApplication:
    return CreateJobApplication(repository=repository, id_generator=UuidIdGenerator())


def get_analyze_use_case(
    repository: SqlAlchemyJobApplicationRepository = Depends(_repository),
) -> AnalyzeJobApplication:
    return AnalyzeJobApplication(
        repository=repository,
        analyzer=LangChainResumeAnalyzer(get_settings()),
    )


def get_submit_use_case(
    repository: SqlAlchemyJobApplicationRepository = Depends(_repository),
) -> SubmitJobApplication:
    return SubmitJobApplication(repository=repository)


def get_list_use_case(
    repository: SqlAlchemyJobApplicationRepository = Depends(_repository),
) -> ListCandidateApplications:
    return ListCandidateApplications(
        repository=repository,
        ranking_service=ApplicationRankingService(),
    )


def _resume_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyResumeRepository:
    return SqlAlchemyResumeRepository(session)


def _file_storage() -> LocalFileStorage:
    return LocalFileStorage(Path(get_settings().resume_storage_dir))


def get_upload_resume_use_case(
    repository: SqlAlchemyResumeRepository = Depends(_resume_repository),
    storage: LocalFileStorage = Depends(_file_storage),
) -> UploadResume:
    return UploadResume(
        repository=repository,
        storage=storage,
        text_extractor=ResumeTextExtractor(),
        id_generator=UuidIdGenerator(),
    )


def get_resume_use_case(
    repository: SqlAlchemyResumeRepository = Depends(_resume_repository),
) -> GetResume:
    return GetResume(repository=repository)


def get_list_resumes_use_case(
    repository: SqlAlchemyResumeRepository = Depends(_resume_repository),
) -> ListResumes:
    return ListResumes(repository=repository)


def _profile_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyProfileRepository:
    return SqlAlchemyProfileRepository(session)


def get_parse_resume_use_case(
    resume_repository: SqlAlchemyResumeRepository = Depends(_resume_repository),
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> ParseResume:
    return ParseResume(
        resume_repository=resume_repository,
        profile_repository=profile_repository,
        resume_parser=LlmResumeParser(AnthropicLlmClient(get_settings())),
        id_generator=UuidIdGenerator(),
    )


def _job_posting_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyJobPostingRepository:
    return SqlAlchemyJobPostingRepository(session)


def _tracked_application_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyTrackedApplicationRepository:
    return SqlAlchemyTrackedApplicationRepository(session)


def get_rank_matched_jobs_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    tracked_application_repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
) -> RankMatchedJobPostings:
    return RankMatchedJobPostings(
        job_posting_repository=job_posting_repository,
        profile_repository=profile_repository,
        rationale_generator=LlmJobFitRationaleGenerator(
            AnthropicLlmClient(get_settings())
        ),
        tracked_application_repository=tracked_application_repository,
    )


def _answer_memory_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyAnswerMemoryRepository:
    return SqlAlchemyAnswerMemoryRepository(session)


def get_detect_job_requirement_gaps_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    answer_memory_repository: SqlAlchemyAnswerMemoryRepository = Depends(
        _answer_memory_repository
    ),
) -> DetectJobRequirementGaps:
    return DetectJobRequirementGaps(
        job_posting_repository=job_posting_repository,
        profile_repository=profile_repository,
        answer_memory_repository=answer_memory_repository,
        detector=LlmRequirementGapDetector(AnthropicLlmClient(get_settings())),
    )


def get_generate_gap_resolution_questions_use_case(
    answer_memory_repository: SqlAlchemyAnswerMemoryRepository = Depends(
        _answer_memory_repository
    ),
) -> GenerateGapResolutionQuestions:
    return GenerateGapResolutionQuestions(
        generator=LlmGapResolutionQuestionGenerator(AnthropicLlmClient(get_settings())),
        answer_memory_repository=answer_memory_repository,
        embedding_client=OpenAiEmbeddingClient(get_settings()),
    )


def get_resolve_gap_answer_use_case(
    answer_memory_repository: SqlAlchemyAnswerMemoryRepository = Depends(
        _answer_memory_repository
    ),
) -> ResolveGapAnswer:
    return ResolveGapAnswer(
        repository=answer_memory_repository,
        embedding_client=OpenAiEmbeddingClient(get_settings()),
        id_generator=UuidIdGenerator(),
    )


def _provenance_fact_assembler(
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    answer_memory_repository: SqlAlchemyAnswerMemoryRepository = Depends(
        _answer_memory_repository
    ),
) -> ProvenanceFactAssembler:
    return ProvenanceFactAssembler(
        profile_repository=profile_repository,
        answer_memory_repository=answer_memory_repository,
    )


def _application_document_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyApplicationDocumentRepository:
    return SqlAlchemyApplicationDocumentRepository(session)


def _application_document_archive(
    repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> ApplicationDocumentArchive:
    return ApplicationDocumentArchive(
        repository=repository, id_generator=UuidIdGenerator()
    )


def get_generate_tailored_resume_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    fact_assembler: ProvenanceFactAssembler = Depends(_provenance_fact_assembler),
    archive: ApplicationDocumentArchive = Depends(_application_document_archive),
) -> GenerateTailoredResume:
    """The generator, the PDF renderer, and the snapshot archive are the only
    injected collaborators; the guard, the ATS formatter, the ATS validator,
    the structure parser, and the audit recorder are pure defaults the use
    case builds itself, so no wiring mistake here can produce an unguarded or
    unvalidated resume. The archive is required rather than optional for the
    same reason: a resume cannot be handed out without being recorded."""
    return GenerateTailoredResume(
        job_posting_repository=job_posting_repository,
        fact_assembler=fact_assembler,
        generator=LlmTailoredResumeGenerator(AnthropicLlmClient(get_settings())),
        pdf_renderer=AtsSafePdfRenderer(),
        archive=archive,
    )


def _relevant_answer_selector(
    answer_memory_repository: SqlAlchemyAnswerMemoryRepository = Depends(
        _answer_memory_repository
    ),
) -> RelevantAnswerSelector:
    return RelevantAnswerSelector(
        answer_memory_repository=answer_memory_repository,
        embedding_client=OpenAiEmbeddingClient(get_settings()),
    )


def get_generate_cover_letter_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    fact_assembler: ProvenanceFactAssembler = Depends(_provenance_fact_assembler),
    answer_selector: RelevantAnswerSelector = Depends(_relevant_answer_selector),
    archive: ApplicationDocumentArchive = Depends(_application_document_archive),
) -> GenerateCoverLetter:
    """Same shape as the resume factory: the generator, the answer selector,
    and the snapshot archive are the only collaborators that reach outside,
    while the guard, the formatter, and the audit recorder are pure defaults
    the use case builds itself — so no wiring mistake here can produce an
    unguarded or unrecorded letter."""
    return GenerateCoverLetter(
        job_posting_repository=job_posting_repository,
        fact_assembler=fact_assembler,
        generator=LlmCoverLetterGenerator(AnthropicLlmClient(get_settings())),
        answer_selector=answer_selector,
        archive=archive,
    )


def get_revise_generated_document_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    fact_assembler: ProvenanceFactAssembler = Depends(_provenance_fact_assembler),
    archive: ApplicationDocumentArchive = Depends(_application_document_archive),
) -> ReviseGeneratedDocument:
    """No generator here — the candidate wrote the text. Everything else is
    the generation factories' shape: the fact assembler and the archive are
    injected, while the guard, the formatter, and the audit recorder are pure
    defaults the use case builds itself, so no wiring mistake can store an
    edit the guard never validated."""
    return ReviseGeneratedDocument(
        job_posting_repository=job_posting_repository,
        fact_assembler=fact_assembler,
        archive=archive,
    )


def get_application_document_use_case(
    repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> GetApplicationDocument:
    return GetApplicationDocument(repository=repository)


def get_latest_application_document_use_case(
    repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> GetLatestApplicationDocument:
    return GetLatestApplicationDocument(repository=repository)


def get_list_application_documents_use_case(
    repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> ListApplicationDocuments:
    return ListApplicationDocuments(repository=repository)


def get_list_tracked_applications_use_case(
    tracked_application_repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> ListTrackedApplications:
    """The tracker feed takes the document store as well as the tracker,
    because a row's whole point is the snapshots it references — but only to
    *read* them by id. No archive is wired in: nothing on the tracker's read
    path can write a document, and nothing can generate one."""
    return ListTrackedApplications(
        tracked_application_repository=tracked_application_repository,
        document_repository=document_repository,
    )


def get_update_tracked_application_status_use_case(
    tracked_application_repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> UpdateTrackedApplicationStatus:
    """Same two stores, and the document one is still read-only here: a status
    change must not be able to touch what was sent."""
    return UpdateTrackedApplicationStatus(
        tracked_application_repository=tracked_application_repository,
        document_repository=document_repository,
    )


def _job_match_feedback_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyJobMatchFeedbackRepository:
    return SqlAlchemyJobMatchFeedbackRepository(session)


def get_submit_job_match_feedback_use_case(
    feedback_repository: SqlAlchemyJobMatchFeedbackRepository = Depends(
        _job_match_feedback_repository
    ),
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
) -> SubmitJobMatchFeedback:
    return SubmitJobMatchFeedback(
        feedback_repository=feedback_repository,
        job_posting_repository=job_posting_repository,
        id_generator=UuidIdGenerator(),
    )


def get_list_job_match_feedback_use_case(
    repository: SqlAlchemyJobMatchFeedbackRepository = Depends(
        _job_match_feedback_repository
    ),
) -> ListJobMatchFeedback:
    return ListJobMatchFeedback(repository=repository)


def get_analyze_scoring_feedback_use_case(
    repository: SqlAlchemyJobMatchFeedbackRepository = Depends(
        _job_match_feedback_repository
    ),
) -> AnalyzeScoringFeedback:
    return AnalyzeScoringFeedback(repository=repository)


# -- Portal inspection, autofill, review, and submit (Epic 05) ---------------
#
# The only two process-wide singletons in this module, and both have to be:
# the harness owns one browser process shared by every session, and the
# review registry holds the filled forms candidates are currently looking at.
# A per-request instance of either would launch a browser per request — each
# launch costs a process and hundreds of milliseconds — and lose every parked
# review the moment the response was sent.
#
# `@lru_cache` rather than a module global so the instance is still created
# lazily: importing this module must not start a browser, which is what would
# happen to every CLI command and every test that touches it.
#
# One harness serves *both* portal paths — the parked-review autofill flow and
# the persisted inspect/review flow. They arrived on separate branches, each
# with its own singleton; keeping both would have meant two Chromium processes
# for one API, so they share this one and each request still gets its own
# isolated `BrowserContext`.


@lru_cache(maxsize=1)
def get_browser_automation() -> PlaywrightBrowserAutomation:
    """The one Chromium this process drives portals with."""
    return PlaywrightBrowserAutomation(get_settings())


def _browser_automation() -> PlaywrightBrowserAutomation:
    """`Depends(...)` spelling of `get_browser_automation` — same instance."""
    return get_browser_automation()


@lru_cache(maxsize=1)
def get_review_sessions() -> ApplicationReviewSessions:
    """The filled application forms this process is holding open."""
    settings = get_settings()
    return ApplicationReviewSessions(
        UuidIdGenerator(),
        ttl_seconds=settings.autofill_review_ttl_seconds,
        max_parked=settings.autofill_max_parked_reviews,
    )


async def shutdown_portal_automation() -> None:
    """Close every parked review and the browser itself.

    Called from the app's lifespan. Ordered deliberately: reviews first, so
    their contexts are disposed while the browser is still alive, then the
    browser, which is the backstop for anything that escaped.
    """
    await get_review_sessions().close_all()
    await get_browser_automation().shutdown()


async def shutdown_browser_automation() -> None:
    """Release the shared browser, if one was ever launched.

    Idempotent, and deliberately still called from the lifespan after
    `shutdown_portal_automation`: the inspect/review path parks no reviews, so
    this is the backstop that keeps a browser process from outliving the API
    even if nothing ever opened a parked review.
    """
    await get_browser_automation().shutdown()


def _portal_handoff_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyPortalHandoffRepository:
    return SqlAlchemyPortalHandoffRepository(session)


def get_inspect_application_portal_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    handoff_repository: SqlAlchemyPortalHandoffRepository = Depends(
        _portal_handoff_repository
    ),
    browser_automation: PlaywrightBrowserAutomation = Depends(_browser_automation),
) -> InspectApplicationPortal:
    """The detector is not injected: it is a pure default the use case builds
    itself, exactly like the provenance guard on the generation use cases. No
    wiring mistake here can produce an inspection that skipped the
    hard-boundary check."""
    return InspectApplicationPortal(
        job_posting_repository=job_posting_repository,
        handoff_repository=handoff_repository,
        browser_automation=browser_automation,
        id_generator=UuidIdGenerator(),
    )


def get_list_portal_handoffs_use_case(
    repository: SqlAlchemyPortalHandoffRepository = Depends(_portal_handoff_repository),
) -> ListPortalHandoffs:
    return ListPortalHandoffs(repository=repository)


def get_resume_portal_handoff_use_case(
    repository: SqlAlchemyPortalHandoffRepository = Depends(_portal_handoff_repository),
) -> ResumePortalHandoff:
    return ResumePortalHandoff(repository=repository)


def get_abandon_portal_handoff_use_case(
    repository: SqlAlchemyPortalHandoffRepository = Depends(_portal_handoff_repository),
) -> AbandonPortalHandoff:
    return AbandonPortalHandoff(repository=repository)


def _application_review_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyApplicationReviewRepository:
    return SqlAlchemyApplicationReviewRepository(session)


def get_autofill_application_form_use_case(
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
    browser_automation: PlaywrightBrowserAutomation = Depends(_browser_automation),
) -> AutofillApplicationForm:
    """The field planner is a pure default the use case builds itself, so no
    wiring mistake here can put a different set of mapping rules — or a
    different sensitive-field policy — in front of a real form, nor produce a
    pass that skipped the refusal to write into a field only the candidate may
    fill."""
    return AutofillApplicationForm(
        job_posting_repository,
        profile_repository,
        document_repository,
        browser_automation,
        AtsSafePdfRenderer(),
        get_review_sessions(),
    )


def get_answer_application_field_use_case() -> AnswerApplicationField:
    return AnswerApplicationField(get_review_sessions())


def get_submit_application_form_use_case() -> SubmitApplicationForm:
    return SubmitApplicationForm(get_review_sessions())


def get_discard_application_review_use_case() -> DiscardApplicationReview:
    return DiscardApplicationReview(get_review_sessions())


def get_open_application_review_use_case(
    review_repository: SqlAlchemyApplicationReviewRepository = Depends(
        _application_review_repository
    ),
    handoff_repository: SqlAlchemyPortalHandoffRepository = Depends(
        _portal_handoff_repository
    ),
) -> OpenApplicationReview:
    return OpenApplicationReview(
        review_repository=review_repository,
        handoff_repository=handoff_repository,
        id_generator=UuidIdGenerator(),
    )


def get_application_review_use_case(
    review_repository: SqlAlchemyApplicationReviewRepository = Depends(
        _application_review_repository
    ),
    handoff_repository: SqlAlchemyPortalHandoffRepository = Depends(
        _portal_handoff_repository
    ),
) -> GetApplicationReview:
    return GetApplicationReview(
        review_repository=review_repository, handoff_repository=handoff_repository
    )


def get_revise_reviewed_answer_use_case(
    review_repository: SqlAlchemyApplicationReviewRepository = Depends(
        _application_review_repository
    ),
    handoff_repository: SqlAlchemyPortalHandoffRepository = Depends(
        _portal_handoff_repository
    ),
) -> ReviseReviewedAnswer:
    return ReviseReviewedAnswer(
        review_repository=review_repository, handoff_repository=handoff_repository
    )


def get_submit_application_review_use_case(
    review_repository: SqlAlchemyApplicationReviewRepository = Depends(
        _application_review_repository
    ),
    handoff_repository: SqlAlchemyPortalHandoffRepository = Depends(
        _portal_handoff_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
    job_posting_repository: SqlAlchemyJobPostingRepository = Depends(
        _job_posting_repository
    ),
    tracked_application_repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
) -> SubmitApplicationReview:
    """The submit path takes a review store, the hand-off store, and the tracker
    log. Notably no browser: submitting records the candidate's own act, and
    ApplyFlow does not press the portal's button (see
    `SubmitApplicationReview`).

    The log reads the stored Epic 04 snapshots rather than generating anything,
    which is why no generator or LLM client is wired in here — there is no path
    from submitting to producing a document."""
    return SubmitApplicationReview(
        review_repository=review_repository,
        handoff_repository=handoff_repository,
        submitted_application_log=SubmittedApplicationLog(
            tracked_application_repository=tracked_application_repository,
            document_repository=document_repository,
            job_posting_repository=job_posting_repository,
            id_generator=UuidIdGenerator(),
        ),
    )


def _auth_verifier() -> AuthVerifierPort:
    return SupabaseJwtVerifier(get_settings())


def get_current_user(
    authorization: str | None = Header(default=None),
    verifier: AuthVerifierPort = Depends(_auth_verifier),
) -> AuthenticatedUserDTO:
    """Resolve the bearer token on the request to the single authenticated user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or malformed Authorization header."
        )
    token = authorization.split(" ", 1)[1]
    try:
        return verifier.verify(token)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

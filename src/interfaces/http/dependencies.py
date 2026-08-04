"""Composition root — the ONLY place where wiring happens.

This module is the application's composition root. It is the single,
deliberate exception that knows about both `application` use cases and
`infrastructure` implementations, so it can inject concrete adapters into
abstract ports. Controllers depend only on this module's factories and on
application-layer types — never on infrastructure directly.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
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
from src.application.use_cases.erase_user_data import EraseUserData
from src.application.use_cases.export_user_data import ExportUserData
from src.application.use_cases.generate_cover_letter import GenerateCoverLetter
from src.application.use_cases.generate_gap_resolution_questions import (
    GenerateGapResolutionQuestions,
)
from src.application.use_cases.generate_tailored_resume import GenerateTailoredResume
from src.application.use_cases.get_application_document import GetApplicationDocument
from src.application.use_cases.get_application_review import GetApplicationReview
from src.application.use_cases.get_eeo_self_identification import (
    GetEeoSelfIdentification,
)
from src.application.use_cases.get_latest_application_document import (
    GetLatestApplicationDocument,
)
from src.application.use_cases.get_profile import GetProfile
from src.application.use_cases.get_resume import GetResume
from src.application.use_cases.get_tracked_application import GetTrackedApplication
from src.application.use_cases.get_work_authorization import GetWorkAuthorization
from src.application.use_cases.inspect_application_portal import (
    InspectApplicationPortal,
)
from src.application.use_cases.list_application_documents import (
    ListApplicationDocuments,
)
from src.application.use_cases.list_applications_for_job import ListApplicationsForJob
from src.application.use_cases.list_candidate_applications import (
    ListCandidateApplications,
)
from src.application.use_cases.list_job_match_feedback import (
    ListJobMatchFeedback,
)
from src.application.use_cases.list_portal_handoffs import ListPortalHandoffs
from src.application.use_cases.list_resumes import ListResumes
from src.application.use_cases.list_tracked_applications import ListTrackedApplications
from src.application.use_cases.list_user_consents import ListUserConsents
from src.application.use_cases.open_application_review import OpenApplicationReview
from src.application.use_cases.parse_resume import ParseResume
from src.application.use_cases.rank_matched_job_postings import (
    RankMatchedJobPostings,
)
from src.application.use_cases.record_consent import RecordConsent
from src.application.use_cases.remove_education_entry import RemoveEducationEntry
from src.application.use_cases.remove_skill import RemoveSkill
from src.application.use_cases.remove_work_history_entry import RemoveWorkHistoryEntry
from src.application.use_cases.resolve_gap_answer import ResolveGapAnswer
from src.application.use_cases.resume_portal_handoff import ResumePortalHandoff
from src.application.use_cases.revise_generated_document import (
    ReviseGeneratedDocument,
)
from src.application.use_cases.revise_reviewed_answer import ReviseReviewedAnswer
from src.application.use_cases.save_contact_details import SaveContactDetails
from src.application.use_cases.save_education_entry import SaveEducationEntry
from src.application.use_cases.save_eeo_self_identification import (
    SaveEeoSelfIdentification,
)
from src.application.use_cases.save_skill import SaveSkill
from src.application.use_cases.save_work_authorization import SaveWorkAuthorization
from src.application.use_cases.save_work_history_entry import SaveWorkHistoryEntry
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
from src.application.use_cases.update_application_status import UpdateApplicationStatus
from src.application.use_cases.update_education_standing import (
    UpdateEducationStanding,
)
from src.application.use_cases.update_job_search_preferences import (
    UpdateJobSearchPreferences,
)
from src.application.use_cases.update_profile_address import UpdateProfileAddress
from src.application.use_cases.update_profile_links import UpdateProfileLinks
from src.application.use_cases.update_profile_qualifications import (
    UpdateProfileQualifications,
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
from src.infrastructure.persistence.consent_repository_impl import (
    SqlAlchemyConsentRepository,
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
from src.infrastructure.persistence.personal_data_store_impl import (
    SqlAlchemyPersonalDataStore,
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
from src.infrastructure.security.sensitive_access import sensitive_data_access
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
    """The same single browser as `get_browser_automation`, under the name the
    portal-inspection providers below declare as a FastAPI dependency.

    Deliberately a delegation rather than a second singleton: the autofill flow
    and the inspection flow each used to keep their own, which put two Chromium
    processes in one API process — the cost both were written to avoid.
    """
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
    if get_review_sessions.cache_info().currsize:
        await get_review_sessions().close_all()
    await shutdown_browser_automation()


async def shutdown_browser_automation() -> None:
    """Release the shared browser, if one was ever launched. Idempotent.

    Checks the cache before reading it: calling `get_browser_automation()`
    here would *launch* a Chromium in order to shut it down, on every process
    that never opened a portal.

    Still called from the lifespan after `shutdown_portal_automation`, even
    though that already calls it: the inspect/review path parks no reviews, so
    this is the backstop that keeps a browser from outliving the API when
    nothing ever opened a parked review.
    """
    if not get_browser_automation.cache_info().currsize:
        return
    harness = get_browser_automation()
    get_browser_automation.cache_clear()
    await harness.shutdown()


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
        get_browser_automation(),
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


# -- Application tracking (Epic 06) ------------------------------------------
#
# All four take the tracker store and the document store, and nothing else.
# Worth noticing what is absent: no browser, no generator, no LLM client. A
# status change records what an employer did, so there is no path from one to
# producing a document or touching a portal — and there is no wiring here that
# could create one.
#
# The document store is read-only on these paths by construction: they reach it
# only through `SentDocumentResolver`, which can look a snapshot up by id and
# do nothing else. In particular it cannot ask for the *latest* document for a
# job, which is what would let the tracker show something the employer never
# received.


def get_update_application_status_use_case(
    repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> UpdateApplicationStatus:
    return UpdateApplicationStatus(
        repository=repository, document_repository=document_repository
    )


def get_tracked_application_use_case(
    repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> GetTrackedApplication:
    return GetTrackedApplication(
        repository=repository, document_repository=document_repository
    )


def get_list_tracked_applications_use_case(
    repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> ListTrackedApplications:
    return ListTrackedApplications(
        repository=repository, document_repository=document_repository
    )


def get_list_applications_for_job_use_case(
    repository: SqlAlchemyTrackedApplicationRepository = Depends(
        _tracked_application_repository
    ),
    document_repository: SqlAlchemyApplicationDocumentRepository = Depends(
        _application_document_repository
    ),
) -> ListApplicationsForJob:
    return ListApplicationsForJob(
        repository=repository, document_repository=document_repository
    )


# -- Data-subject rights: export, erasure, consent ---------------------------
#
# The export and erasure use cases take one adapter for every store rather than
# a fan of repositories, and the reasons are in `PersonalDataStorePort`: erasure
# order is a foreign-key fact, and a portable copy has to carry stored columns
# rather than what the entities expose. What is worth noticing here is what the
# wiring makes impossible:
#
# - The store gets the *same* session as everything else, so an erasure commits
#   as one transaction rather than as nine.
# - `EraseUserData` gets the consent repository as well as the store, because it
#   records the withdrawal before deleting — the ledger is the record that the
#   erasure was lawful, and the store deliberately cannot delete it.
# - Neither takes the inventory: they default to the declared one. A wiring
#   mistake here therefore cannot narrow what gets exported or erased, which is
#   the one class of bug in this subsystem that would look like success.


def _consent_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyConsentRepository:
    return SqlAlchemyConsentRepository(session)


def _personal_data_store(
    session: AsyncSession = Depends(get_session),
    storage: LocalFileStorage = Depends(_file_storage),
) -> SqlAlchemyPersonalDataStore:
    return SqlAlchemyPersonalDataStore(session, storage)


def get_privacy_policy_version() -> str:
    """The privacy-notice version this deployment serves.

    A dependency rather than a settings read inside the controller so a test can
    override it, and so the two endpoints that stamp a consent decision cannot
    end up reading it from different places.
    """
    return get_settings().privacy_policy_version


def get_export_user_data_use_case(
    store: SqlAlchemyPersonalDataStore = Depends(_personal_data_store),
    consent_repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> ExportUserData:
    return ExportUserData(store=store, consent_repository=consent_repository)


def get_erase_user_data_use_case(
    store: SqlAlchemyPersonalDataStore = Depends(_personal_data_store),
    consent_repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> EraseUserData:
    return EraseUserData(store=store, consent_repository=consent_repository)


def get_record_consent_use_case(
    repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> RecordConsent:
    return RecordConsent(repository=repository)


def get_list_user_consents_use_case(
    repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> ListUserConsents:
    return ListUserConsents(repository=repository)


# -- Profile editor ----------------------------------------------------------
#
# One provider per section, matching the per-section endpoints. All of them share
# the one request-scoped session, so a save is a single transaction.
#
# The two sensitive sections take the consent repository as well as the profile
# one: saving work authorization or EEO records the consent grant in the same
# operation (see `SaveWorkAuthorization`). Nothing here can switch that off — the
# consent repository is not optional on those constructors.


def get_profile_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> GetProfile:
    return GetProfile(repository=repository)


def get_save_contact_details_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> SaveContactDetails:
    """The one section that can create a profile — see `SaveContactDetails`.

    Takes the id generator for exactly that reason: creating needs an id, and the
    other sections never create.
    """
    return SaveContactDetails(repository=repository, id_generator=UuidIdGenerator())


def get_update_profile_address_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> UpdateProfileAddress:
    return UpdateProfileAddress(repository=repository)


def get_update_profile_links_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> UpdateProfileLinks:
    return UpdateProfileLinks(repository=repository)


def get_update_profile_qualifications_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> UpdateProfileQualifications:
    return UpdateProfileQualifications(repository=repository)


def get_update_education_standing_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> UpdateEducationStanding:
    return UpdateEducationStanding(repository=repository)


def get_update_job_search_preferences_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> UpdateJobSearchPreferences:
    return UpdateJobSearchPreferences(repository=repository)


def get_save_work_history_entry_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> SaveWorkHistoryEntry:
    return SaveWorkHistoryEntry(repository=repository, id_generator=UuidIdGenerator())


def get_remove_work_history_entry_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> RemoveWorkHistoryEntry:
    return RemoveWorkHistoryEntry(repository=repository)


def get_save_education_entry_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> SaveEducationEntry:
    return SaveEducationEntry(repository=repository, id_generator=UuidIdGenerator())


def get_remove_education_entry_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> RemoveEducationEntry:
    return RemoveEducationEntry(repository=repository)


def get_save_skill_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> SaveSkill:
    return SaveSkill(repository=repository, id_generator=UuidIdGenerator())


def get_remove_skill_use_case(
    repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
) -> RemoveSkill:
    return RemoveSkill(repository=repository)


def get_work_authorization_use_case(
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    consent_repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> GetWorkAuthorization:
    return GetWorkAuthorization(
        profile_repository=profile_repository,
        consent_repository=consent_repository,
    )


def get_save_work_authorization_use_case(
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    consent_repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> SaveWorkAuthorization:
    """The write path that makes the sensitive-field machinery live.

    The consent repository is a required collaborator, not an optional one: this
    stores special-category data, and the grant that permits it is recorded in the
    same operation. There is no wiring here that could store the data without
    recording the consent.
    """
    return SaveWorkAuthorization(
        profile_repository=profile_repository,
        consent_repository=consent_repository,
    )


def get_eeo_self_identification_use_case(
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    consent_repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> GetEeoSelfIdentification:
    return GetEeoSelfIdentification(
        profile_repository=profile_repository,
        consent_repository=consent_repository,
    )


def get_save_eeo_self_identification_use_case(
    profile_repository: SqlAlchemyProfileRepository = Depends(_profile_repository),
    consent_repository: SqlAlchemyConsentRepository = Depends(_consent_repository),
) -> SaveEeoSelfIdentification:
    return SaveEeoSelfIdentification(
        profile_repository=profile_repository,
        consent_repository=consent_repository,
    )


def _auth_verifier() -> AuthVerifierPort:
    return SupabaseJwtVerifier(get_settings())


async def get_current_user(
    authorization: str | None = Header(default=None),
    verifier: AuthVerifierPort = Depends(_auth_verifier),
) -> AsyncGenerator[AuthenticatedUserDTO, None]:
    """Resolve the bearer token on the request to the single authenticated user,
    and open that user's sensitive-data access scope for the request.

    This is the HTTP layer's one authorized decryption path (Epic 07). The scope
    opens only after the token has verified, so an unauthenticated request never
    gets one — and every controller in this app depends on this function, which
    is what makes "authenticated request" and "may decrypt" the same thing here
    without each controller having to remember. See
    `src/infrastructure/security/sensitive_access.py` for what the scope does
    and, just as importantly, what it does not do (it is not row-level
    authorization; repositories still filter on `user_id`).

    A generator dependency rather than a plain one because the scope has to be
    torn down when the request ends, and `async` rather than sync because a sync
    dependency runs in a worker thread whose context changes do not propagate
    back to the endpoint — the scope would be set somewhere nothing could see it.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or malformed Authorization header."
        )
    token = authorization.split(" ", 1)[1]
    try:
        user = verifier.verify(token)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    with sensitive_data_access(
        subject=user.subject, reason="authenticated HTTP request"
    ):
        yield user

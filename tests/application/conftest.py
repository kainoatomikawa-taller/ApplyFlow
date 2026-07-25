"""Shared fakes for the provenance-guarded generation use cases.

`GenerateTailoredResume` and `GenerateCoverLetter` take the same
collaborators, so their tests share one set of in-memory doubles rather
than each defining its own — the two flows must stay verifiably identical
about what counts as evidence.
"""

from __future__ import annotations

from datetime import date, datetime
from types import TracebackType

import pytest

from src.application.exceptions import StaleFormFieldError
from src.application.ports.browser_automation_port import (
    BrowserAutomationPort,
    BrowserSessionPort,
    FormField,
    SubmitControl,
)
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.resume_pdf_renderer_port import ResumePdfRendererPort
from src.application.services.application_document_archive import (
    ApplicationDocumentArchive,
)
from src.application.services.provenance_fact_assembler import ProvenanceFactAssembler
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.entities.application_document import ApplicationDocument
from src.domain.entities.job_posting import JobPosting
from src.domain.entities.skill import Skill
from src.domain.entities.user_profile import UserProfile
from src.domain.entities.work_history_entry import WorkHistoryEntry
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.value_objects.email_address import EmailAddress
from src.domain.value_objects.generated_document_kind import GeneratedDocumentKind
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.page_signals import PageSignals
from src.domain.value_objects.provenance_source import ProvenanceSource


class StubJobPostingRepository(JobPostingRepository):
    """Only `get_by_id` is exercised by the generation flows; the rest of
    the contract raises so an accidental extra call is loud."""

    def __init__(self, posting: JobPosting | None) -> None:
        self._posting = posting
        self.requested: list[str] = []

    async def get_by_id(self, job_posting_id: str) -> JobPosting | None:
        self.requested.append(job_posting_id)
        return self._posting

    async def add(self, job_posting: JobPosting) -> None:
        raise NotImplementedError  # pragma: no cover

    async def update(self, job_posting: JobPosting) -> None:
        raise NotImplementedError  # pragma: no cover

    async def find_duplicate(
        self,
        *,
        source: str,
        normalized_company: str,
        normalized_title: str,
        normalized_location: str | None,
    ) -> JobPosting | None:
        raise NotImplementedError  # pragma: no cover

    async def list_due_for_staleness_check(
        self, *, as_of: datetime, recheck_after_days: int, batch_size: int
    ) -> list[JobPosting]:
        raise NotImplementedError  # pragma: no cover

    async def list_active(self, *, limit: int = 100) -> list[JobPosting]:
        raise NotImplementedError  # pragma: no cover

    async def list_missing_requirements(self, *, limit: int) -> list[JobPosting]:
        raise NotImplementedError  # pragma: no cover


class StubProfileRepository(ProfileRepository):
    def __init__(self, profile: UserProfile | None) -> None:
        self._profile = profile

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        return self._profile

    async def add(self, profile: UserProfile) -> None:
        raise NotImplementedError  # pragma: no cover

    async def get_by_id(self, profile_id: str) -> UserProfile | None:
        raise NotImplementedError  # pragma: no cover

    async def update(self, profile: UserProfile) -> None:
        raise NotImplementedError  # pragma: no cover

    async def delete(self, profile_id: str) -> None:
        raise NotImplementedError  # pragma: no cover


class StubAnswerMemoryRepository(AnswerMemoryRepository):
    def __init__(self, memories: list[AnswerMemory] | None = None) -> None:
        self._memories = memories or []

    async def list_by_user_id(self, user_id: str) -> list[AnswerMemory]:
        return [m for m in self._memories if m.user_id == user_id]

    async def add(self, answer_memory: AnswerMemory) -> None:
        raise NotImplementedError  # pragma: no cover

    async def get_by_id(self, answer_memory_id: str) -> AnswerMemory | None:
        raise NotImplementedError  # pragma: no cover

    async def delete(self, answer_memory_id: str) -> None:
        raise NotImplementedError  # pragma: no cover


class RecordingGenerator:
    """Stands in for either generator port: returns a scripted draft and
    records what it was asked for, so tests can prove what the use case
    sends to the LLM boundary."""

    def __init__(self, draft: str) -> None:
        self._draft = draft
        self.job_title: str | None = None
        self.company: str | None = None
        self.requirements: tuple[str, ...] = ()
        self.facts: tuple[str, ...] = ()
        # Only the cover-letter port takes highlighted answers; the resume
        # port never passes them, so this stays empty in that flow.
        self.relevant_answers: tuple[str, ...] = ()

    async def generate(
        self,
        *,
        job_title: str,
        company: str,
        requirements: tuple[str, ...],
        facts: tuple[str, ...],
        relevant_answers: tuple[str, ...] = (),
    ) -> str:
        self.job_title = job_title
        self.company = company
        self.requirements = requirements
        self.facts = facts
        self.relevant_answers = relevant_answers
        return self._draft


class RecordingPdfRenderer(ResumePdfRendererPort):
    """Stands in for the real PDF writer: returns marker bytes and records
    what it was asked to render, so tests can assert the PDF is built from
    the guarded text without parsing a PDF here (the renderer's own tests do
    that against `pypdf`)."""

    def __init__(self, pdf: bytes = b"%PDF-1.4 fake") -> None:
        self._pdf = pdf
        self.content: str | None = None
        self.title: str | None = None
        self.calls = 0

    def render(self, content: str, *, title: str) -> bytes:
        self.content = content
        self.title = title
        self.calls += 1
        return self._pdf


class InMemoryApplicationDocumentRepository(ApplicationDocumentRepository):
    """An in-memory snapshot store that keeps the interface's write-once
    shape: `add` only appends, and there is no method that could rewrite
    what is already stored."""

    def __init__(self, documents: list[ApplicationDocument] | None = None) -> None:
        self.documents: list[ApplicationDocument] = list(documents or [])

    async def add(self, document: ApplicationDocument) -> None:
        self.documents.append(document)

    async def get_by_id(self, document_id: str) -> ApplicationDocument | None:
        return next((d for d in self.documents if d.id == document_id), None)

    async def count_versions(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> int:
        return len(
            [
                d
                for d in self.documents
                if d.user_id == user_id
                and d.job_posting_id == job_posting_id
                and d.document_kind is document_kind
            ]
        )

    async def get_latest(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        document_kind: GeneratedDocumentKind,
    ) -> ApplicationDocument | None:
        matches = [
            d
            for d in self.documents
            if d.user_id == user_id
            and d.job_posting_id == job_posting_id
            and d.document_kind is document_kind
        ]
        return max(matches, key=lambda d: d.version, default=None)

    async def list_for_job(
        self, *, user_id: str, job_posting_id: str, limit: int = 100
    ) -> list[ApplicationDocument]:
        matches = [
            d
            for d in self.documents
            if d.user_id == user_id and d.job_posting_id == job_posting_id
        ]
        return self._newest_first(matches)[:limit]

    async def list_by_user_id(
        self, user_id: str, *, limit: int = 100
    ) -> list[ApplicationDocument]:
        matches = [d for d in self.documents if d.user_id == user_id]
        return self._newest_first(matches)[:limit]

    @staticmethod
    def _newest_first(
        documents: list[ApplicationDocument],
    ) -> list[ApplicationDocument]:
        return sorted(documents, key=lambda d: (d.created_at, d.version), reverse=True)


class SequentialIdGenerator(IdGeneratorPort):
    """Predictable ids, so a test can name the snapshot it expects."""

    def __init__(self, prefix: str = "doc") -> None:
        self._prefix = prefix
        self.issued = 0

    def new_id(self) -> str:
        self.issued += 1
        return f"{self._prefix}-{self.issued}"


class FakeBrowserSession(BrowserSessionPort):
    """A browser session that records instead of driving one.

    Shared by the autofill and the review/submit tests, because both halves
    of the flow have to be exercised against the *same* session behavior —
    the submit tests would be worthless against a fake that let a press
    happen more freely than the real harness does.

    What it reproduces from `PlaywrightBrowserSession`, because the use cases
    depend on all of it:

    - a form read, with a per-handle failure it can be told to raise;
    - page signals, so boundary detection has something to detect;
    - submit controls in their own handle namespace, and a press that only
      accepts one of those handles;
    - `pressed`, so a test can assert that nothing was submitted.
    """

    def __init__(
        self,
        fields: tuple[FormField, ...] = (),
        *,
        current_url: str = "https://boards.greenhouse.io/globex/jobs/4001",
        failures: dict[str, Exception] | None = None,
        screenshot_error: Exception | None = None,
        signals: PageSignals | None = None,
        submit_controls: tuple[SubmitControl, ...] = (
            SubmitControl(handle="s1-submit", label="Submit application"),
        ),
        press_error: Exception | None = None,
        signals_after_press: PageSignals | None = None,
    ) -> None:
        self._fields = fields
        self._current_url = current_url
        self._failures = failures or {}
        self._screenshot_error = screenshot_error
        self._signals = signals or PageSignals(url=current_url, visible_text="Apply")
        self._submit_controls = submit_controls
        self._press_error = press_error
        self._signals_after_press = signals_after_press
        self.filled: list[tuple[str, str]] = []
        self.attached: list[tuple[str, str, bytes]] = []
        self.pressed: list[str] = []
        self.read_count = 0
        self.screenshots = 0
        self.closed = False

    @property
    def current_url(self) -> str:
        return self._current_url

    async def read_fields(self) -> tuple[FormField, ...]:
        self.read_count += 1
        return self._fields

    async def fill(self, handle: str, value: str) -> None:
        failure = self._failures.get(handle)
        if failure is not None:
            raise failure
        self.filled.append((handle, value))

    async def attach_file(self, handle: str, *, filename: str, content: bytes) -> None:
        failure = self._failures.get(handle)
        if failure is not None:
            raise failure
        self.attached.append((handle, filename, content))

    async def read_page_signals(self) -> PageSignals:
        if self.pressed and self._signals_after_press is not None:
            return self._signals_after_press
        return self._signals

    async def read_submit_controls(self) -> tuple[SubmitControl, ...]:
        return self._submit_controls

    async def press_submit(self, handle: str) -> None:
        if handle not in {control.handle for control in self._submit_controls}:
            # The real harness looks a submit handle up in its own snapshot,
            # so a form-field handle can never press anything.
            raise StaleFormFieldError(
                handle,
                "it is not part of this session's current submit-control snapshot",
            )
        if self._press_error is not None:
            raise self._press_error
        self.pressed.append(handle)

    async def screenshot(self) -> bytes:
        if self._screenshot_error is not None:
            raise self._screenshot_error
        self.screenshots += 1
        return b"\x89PNG fake"

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> FakeBrowserSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    # Convenience for assertions.
    def value_for(self, handle: str) -> str | None:
        return next((v for h, v in self.filled if h == handle), None)


class FakeBrowser(BrowserAutomationPort):
    def __init__(
        self,
        session: FakeBrowserSession | None = None,
        *,
        open_error: Exception | None = None,
    ) -> None:
        self.session = session
        self._open_error = open_error
        self.opened: list[str] = []
        self.shutdowns = 0

    async def open(self, url: str) -> BrowserSessionPort:
        self.opened.append(url)
        if self._open_error is not None:
            raise self._open_error
        assert self.session is not None
        return self.session

    async def shutdown(self) -> None:
        self.shutdowns += 1


@pytest.fixture
def document_repository() -> InMemoryApplicationDocumentRepository:
    return InMemoryApplicationDocumentRepository()


@pytest.fixture
def archive(
    document_repository: InMemoryApplicationDocumentRepository,
) -> ApplicationDocumentArchive:
    return ApplicationDocumentArchive(
        repository=document_repository, id_generator=SequentialIdGenerator()
    )


@pytest.fixture
def pdf_renderer() -> RecordingPdfRenderer:
    return RecordingPdfRenderer()


@pytest.fixture
def profile() -> UserProfile:
    """A candidate with one dated role, its description, and one skill —
    enough real material for a document to be written from."""
    profile = UserProfile(
        id="profile-1",
        user_id="user-1",
        full_name="Dana Reyes",
        email=EmailAddress("dana@example.com"),
        contact_source=ProvenanceSource.USER_ENTERED,
    )
    profile.add_work_history(
        WorkHistoryEntry(
            id="job-1",
            company_name="Acme Corp",
            job_title="Backend Engineer",
            start_date=date(2019, 3, 1),
            end_date=date(2022, 6, 30),
            description="Built payment services in Python.",
            source=ProvenanceSource.PARSED_RESUME,
        )
    )
    profile.add_skill(
        Skill(id="skill-1", name="Python", source=ProvenanceSource.PARSED_RESUME)
    )
    return profile


@pytest.fixture
def posting() -> JobPosting:
    """A posting whose requirements go beyond the candidate's record: it
    wants Terraform, which nothing in the profile backs."""
    return JobPosting(
        id="job-posting-1",
        source="greenhouse",
        company="Globex",
        title="Senior Platform Engineer",
        apply_url="https://globex.example.com/jobs/1",
        description="Platform role.",
        location="Austin, TX",
        requirements=JobRequirements(required_skills=("Python", "Terraform")),
    )


@pytest.fixture
def answer_memory() -> AnswerMemory:
    return AnswerMemory(
        id="mem-1",
        user_id="user-1",
        question_text="Have you led a team?",
        answer_text="Yes, I led a team of 5 engineers.",
        embedding=[0.1, 0.2],
        source=ProvenanceSource.ANSWER,
    )


@pytest.fixture
def fact_assembler(profile: UserProfile) -> ProvenanceFactAssembler:
    return ProvenanceFactAssembler(
        profile_repository=StubProfileRepository(profile),
        answer_memory_repository=StubAnswerMemoryRepository(),
    )

"""Use case tests using in-memory fakes for the ports/repository.

This demonstrates that the application layer depends only on abstractions:
no database or LLM is required to test it.
"""

import pytest

from src.application.dtos.job_application_dtos import (
    AnalyzeApplicationInput,
    CreateJobApplicationInput,
)
from src.application.ports.id_generator_port import IdGeneratorPort
from src.application.ports.resume_analyzer_port import (
    ResumeAnalysisResult,
    ResumeAnalyzerPort,
)
from src.application.use_cases.analyze_job_application import (
    AnalyzeJobApplication,
)
from src.application.use_cases.create_job_application import (
    CreateJobApplication,
)
from src.application.use_cases.submit_job_application import (
    SubmitJobApplication,
)
from src.domain.entities.job_application import JobApplication
from src.domain.repositories.job_application_repository import (
    JobApplicationRepository,
)


class InMemoryRepo(JobApplicationRepository):
    def __init__(self) -> None:
        self.store: dict[str, JobApplication] = {}

    async def add(self, application: JobApplication) -> None:
        self.store[application.id] = application

    async def get_by_id(self, application_id: str) -> JobApplication | None:
        return self.store.get(application_id)

    async def update(self, application: JobApplication) -> None:
        self.store[application.id] = application

    async def list_by_candidate(self, candidate_email: str):
        return [
            a
            for a in self.store.values()
            if str(a.candidate_email) == candidate_email.lower()
        ]

    async def delete(self, application_id: str) -> None:
        self.store.pop(application_id, None)


class FixedIdGenerator(IdGeneratorPort):
    def new_id(self) -> str:
        return "fixed-id"


class FakeAnalyzer(ResumeAnalyzerPort):
    async def analyze(self, resume_text, job_description) -> ResumeAnalysisResult:
        return ResumeAnalysisResult(match_score=90, cover_letter="Hi!")


@pytest.mark.asyncio
async def test_create_then_analyze_then_submit():
    repo = InMemoryRepo()

    created = await CreateJobApplication(repo, FixedIdGenerator()).execute(
        CreateJobApplicationInput(
            candidate_email="dev@example.com",
            company_name="Acme",
            role_title="Engineer",
            job_description="Build things.",
        )
    )
    assert created.id == "fixed-id"
    assert created.status == "draft"

    analyzed = await AnalyzeJobApplication(repo, FakeAnalyzer()).execute(
        AnalyzeApplicationInput(application_id="fixed-id", resume_text="cv")
    )
    assert analyzed.match_score == 90
    assert analyzed.tailored_cover_letter == "Hi!"

    submitted = await SubmitJobApplication(repo).execute("fixed-id")
    assert submitted.status == "applied"

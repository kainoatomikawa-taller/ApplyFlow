"""Composition root — the ONLY place where wiring happens.

This module is the application's composition root. It is the single,
deliberate exception that knows about both `application` use cases and
`infrastructure` implementations, so it can inject concrete adapters into
abstract ports. Controllers depend only on this module's factories and on
application-layer types — never on infrastructure directly.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.use_cases.analyze_job_application import (
    AnalyzeJobApplication,
)
from src.application.use_cases.create_job_application import (
    CreateJobApplication,
)
from src.application.use_cases.list_candidate_applications import (
    ListCandidateApplications,
)
from src.application.use_cases.submit_job_application import (
    SubmitJobApplication,
)
from src.domain.services.application_ranking_service import (
    ApplicationRankingService,
)
from src.infrastructure.config import get_settings
from src.infrastructure.llm.langchain_resume_analyzer import (
    LangChainResumeAnalyzer,
)
from src.infrastructure.persistence.database import get_session
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator


def _repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyJobApplicationRepository:
    return SqlAlchemyJobApplicationRepository(session)


def get_create_use_case(
    repository: SqlAlchemyJobApplicationRepository = Depends(_repository),
) -> CreateJobApplication:
    return CreateJobApplication(
        repository=repository, id_generator=UuidIdGenerator()
    )


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

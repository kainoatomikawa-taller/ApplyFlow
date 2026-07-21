"""Composition root — the ONLY place where wiring happens.

This module is the application's composition root. It is the single,
deliberate exception that knows about both `application` use cases and
`infrastructure` implementations, so it can inject concrete adapters into
abstract ports. Controllers depend only on this module's factories and on
application-layer types — never on infrastructure directly.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.dtos.auth_dtos import AuthenticatedUserDTO
from src.application.exceptions import AuthenticationError
from src.application.ports.auth_verifier_port import AuthVerifierPort
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
from src.infrastructure.auth.supabase_jwt_verifier import SupabaseJwtVerifier
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

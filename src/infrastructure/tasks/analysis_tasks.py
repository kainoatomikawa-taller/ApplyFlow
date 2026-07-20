"""Celery tasks — thin adapters that invoke application use cases.

A task translates a queued message into a use case invocation. It contains
NO business logic; it only wires dependencies and runs the use case.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.application.dtos.job_application_dtos import AnalyzeApplicationInput
from src.application.use_cases.analyze_job_application import (
    AnalyzeJobApplication,
)
from src.infrastructure.config import get_settings
from src.infrastructure.llm.langchain_resume_analyzer import (
    LangChainResumeAnalyzer,
)
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)
from src.infrastructure.tasks.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="applyflow.analyze_application", bind=True, max_retries=3
)
def analyze_application_task(
    self: Any, application_id: str, resume_text: str
) -> dict[str, Any]:
    """Run the AnalyzeJobApplication use case in the background."""
    try:
        return asyncio.run(_run_analysis(application_id, resume_text))
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=10) from exc


async def _run_analysis(application_id: str, resume_text: str) -> dict[str, Any]:
    settings = get_settings()
    async with async_session_factory() as session:
        repository = SqlAlchemyJobApplicationRepository(session)
        analyzer = LangChainResumeAnalyzer(settings)
        use_case = AnalyzeJobApplication(repository=repository, analyzer=analyzer)
        result = await use_case.execute(
            AnalyzeApplicationInput(
                application_id=application_id, resume_text=resume_text
            )
        )
        return {"id": result.id, "match_score": result.match_score}

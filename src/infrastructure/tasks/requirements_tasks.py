"""Celery task — a thin adapter that invokes ExtractJobRequirements over a
batch of postings still missing them.

Runs on a schedule (see `celery_app.py`'s `beat_schedule`) to keep
`job_postings.requirements` populated for the active ingestion pipeline.
Contains NO business logic; it only wires dependencies, fetches the batch
of pending postings, and runs the use case once per posting. One
posting's extraction failure never sinks the rest of the batch — the same
defensive posture `DetectStaleJobPostings` and `IngestAggregatorJobs` take
toward one bad record.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.application.dtos.job_requirements_dtos import ExtractJobRequirementsInput
from src.application.use_cases.extract_job_requirements import (
    ExtractJobRequirements,
)
from src.infrastructure.config import get_settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient
from src.infrastructure.llm.llm_job_requirements_extractor import (
    LlmJobRequirementsExtractor,
)
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.tasks.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="applyflow.extract_job_requirements", bind=True, max_retries=3
)
def extract_pending_job_requirements_task(self: Any) -> dict[str, int]:
    """Run the ExtractJobRequirements use case over a batch of postings
    still missing requirements, as a background job."""
    try:
        return asyncio.run(_run_extraction())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc


async def _run_extraction() -> dict[str, int]:
    settings = get_settings()
    async with async_session_factory() as session:
        repository = SqlAlchemyJobPostingRepository(session)
        extractor = LlmJobRequirementsExtractor(AnthropicLlmClient(settings))
        use_case = ExtractJobRequirements(repository=repository, extractor=extractor)

        pending = await repository.list_missing_requirements(
            limit=settings.job_requirements_sweep_batch_size
        )

        extracted_count = 0
        failed_count = 0
        for posting in pending:
            try:
                await use_case.execute(
                    ExtractJobRequirementsInput(job_posting_id=posting.id)
                )
                extracted_count += 1
            except Exception:  # noqa: BLE001 - one posting must never sink the batch
                failed_count += 1

        return {
            "checked_count": len(pending),
            "extracted_count": extracted_count,
            "failed_count": failed_count,
        }

"""Celery task — a thin adapter that invokes DetectStaleJobPostings.

Runs on a schedule (see `celery_app.py`'s `beat_schedule`) to keep
`job_postings`'s active set free of postings too old to still be open, or
whose apply link no longer resolves. Contains NO business logic; it only
wires dependencies and runs the use case, and stamps `as_of` with the
current time — the one piece of "real world" state the use case itself
never reads on its own (see `DetectStaleJobPostingsInput`).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from src.application.dtos.job_staleness_dtos import DetectStaleJobPostingsInput
from src.application.use_cases.detect_stale_job_postings import (
    DetectStaleJobPostings,
)
from src.infrastructure.config import get_settings
from src.infrastructure.link_checking.http_apply_url_checker import (
    HttpApplyUrlChecker,
)
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.tasks.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="applyflow.detect_stale_job_postings", bind=True, max_retries=3
)
def detect_stale_job_postings_task(self: Any) -> dict[str, int]:
    """Run the DetectStaleJobPostings use case, as a background job."""
    try:
        return asyncio.run(_run_detection())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc


async def _run_detection() -> dict[str, int]:
    settings = get_settings()
    async with async_session_factory() as session:
        repository = SqlAlchemyJobPostingRepository(session)
        url_checker = HttpApplyUrlChecker(settings)
        use_case = DetectStaleJobPostings(
            repository=repository, url_checker=url_checker
        )
        result = await use_case.execute(
            DetectStaleJobPostingsInput(
                as_of=datetime.now(UTC),
                batch_size=settings.stale_posting_sweep_batch_size,
                stale_after_days=settings.stale_posting_after_days,
                recheck_after_days=settings.stale_posting_recheck_after_days,
                dead_link_after_failures=settings.stale_posting_dead_link_after_failures,
            )
        )
        return {
            "checked_count": result.checked_count,
            "newly_stale_count": result.newly_stale_count,
            "newly_dead_link_count": result.newly_dead_link_count,
            "failed_count": result.failed_count,
        }

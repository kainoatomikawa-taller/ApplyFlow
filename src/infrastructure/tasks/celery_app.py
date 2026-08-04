"""Celery application instance."""

from __future__ import annotations

import logging
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging as celery_setup_logging

from src.infrastructure.config import get_settings
from src.infrastructure.observability import (
    configure_logging,
    harden_existing_handlers,
)

_settings = get_settings()


@celery_setup_logging.connect  # type: ignore[untyped-decorator]
def _configure_worker_logging(
    loglevel: int | str = logging.INFO, **_kwargs: Any
) -> None:
    """Own the worker's logging so the PII scrubber is installed in it.

    Connecting to `setup_logging` tells Celery not to configure logging
    itself, which is the point: Celery's own setup would replace the root
    handler installed here, and a worker is the process most likely to be
    holding candidate data (Epic 07 — see
    src/infrastructure/observability/pii_redaction.py).

    Taking that over means taking on what Celery was doing, so `--loglevel`
    is read off the signal and honoured rather than silently pinned to INFO.
    `harden_existing_handlers` then covers the `celery.*` loggers Celery has
    already created.
    """
    configure_logging(level=loglevel)
    harden_existing_handlers()


celery_app = Celery(
    "applyflow",
    broker=_settings.celery_broker_url.get_secret_value(),
    backend=_settings.celery_result_backend.get_secret_value(),
    include=[
        "src.infrastructure.tasks.analysis_tasks",
        "src.infrastructure.tasks.ingestion_tasks",
        "src.infrastructure.tasks.staleness_tasks",
        "src.infrastructure.tasks.requirements_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Runs the stale-posting / dead-apply-link sweep (see
    # src/infrastructure/tasks/staleness_tasks.py) every 6 hours, so
    # AC "marked on a schedule" is satisfied by Celery beat rather than
    # anything the use case itself does.
    beat_schedule={
        "detect-stale-job-postings": {
            "task": "applyflow.detect_stale_job_postings",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        # Keeps newly ingested postings' `requirements` populated (see
        # src/infrastructure/tasks/requirements_tasks.py) — runs more
        # frequently than the staleness sweep since fresh postings should
        # get classifiable/scoreable soon after ingestion, not hours later.
        "extract-job-requirements": {
            "task": "applyflow.extract_job_requirements",
            "schedule": crontab(minute="*/10"),
        },
    },
)

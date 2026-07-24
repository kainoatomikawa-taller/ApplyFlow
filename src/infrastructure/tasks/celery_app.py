"""Celery application instance."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.infrastructure.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "applyflow",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=[
        "src.infrastructure.tasks.analysis_tasks",
        "src.infrastructure.tasks.ingestion_tasks",
        "src.infrastructure.tasks.staleness_tasks",
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
    },
)

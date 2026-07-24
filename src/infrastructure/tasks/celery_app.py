"""Celery application instance."""

from __future__ import annotations

from celery import Celery

from src.infrastructure.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "applyflow",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=[
        "src.infrastructure.tasks.analysis_tasks",
        "src.infrastructure.tasks.ingestion_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

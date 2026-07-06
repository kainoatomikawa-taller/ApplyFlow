"""Celery implementation of the TaskQueuePort."""

from __future__ import annotations

from src.application.ports.task_queue_port import TaskQueuePort
from src.infrastructure.tasks.analysis_tasks import analyze_application_task


class CeleryTaskQueue(TaskQueuePort):
    def enqueue_analysis(self, application_id: str, resume_text: str) -> None:
        analyze_application_task.delay(application_id, resume_text)

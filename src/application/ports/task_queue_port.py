"""TaskQueuePort — abstraction for dispatching background work.

Implemented by a Celery adapter in the infrastructure layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TaskQueuePort(ABC):
    """Enqueues asynchronous background jobs."""

    @abstractmethod
    def enqueue_analysis(self, application_id: str, resume_text: str) -> None:
        """Schedule an asynchronous resume analysis for an application."""

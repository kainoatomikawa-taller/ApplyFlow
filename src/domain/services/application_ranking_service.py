"""ApplicationRankingService — a pure domain service.

Logic that doesn't naturally belong to a single entity lives here.
This service ranks applications by likelihood of success using only
in-memory business rules (no I/O, no frameworks).
"""

from __future__ import annotations

from src.domain.entities.job_application import JobApplication
from src.domain.value_objects.application_status import ApplicationStatus

# Weight given to how "advanced" the pipeline stage is.
_STATUS_WEIGHT: dict[ApplicationStatus, int] = {
    ApplicationStatus.DRAFT: 0,
    ApplicationStatus.APPLIED: 10,
    ApplicationStatus.INTERVIEWING: 30,
    ApplicationStatus.OFFER: 50,
    ApplicationStatus.REJECTED: -100,
    ApplicationStatus.WITHDRAWN: -100,
}


class ApplicationRankingService:
    """Ranks job applications by a computed priority score."""

    def priority_score(self, application: JobApplication) -> int:
        """Combine match score and pipeline stage into a single priority."""
        match_component = int(application.match_score) if application.match_score else 0
        status_component = _STATUS_WEIGHT[application.status]
        return match_component + status_component

    def rank(self, applications: list[JobApplication]) -> list[JobApplication]:
        """Return applications sorted from highest to lowest priority."""
        return sorted(applications, key=self.priority_score, reverse=True)

"""ListTrackedApplications use case — a candidate's sent applications, most
recently applied first, optionally narrowed to a set of statuses.

Each row carries the exact documents that went out with it, resolved from the
ids frozen onto the row at send time (see `SentDocumentResolver`) — which is
what makes the feed answer "what did I send to whom, and when" in one request.

The tracker's feed, and the thing that makes status worth storing: "what is
still live", "what did I get offers on", "everything I have sent". The filter
runs in the query rather than over the results, because discarding most of a
candidate's applications in Python gets slower exactly as their search gets
longer — see the repository interface.

Which statuses count as "open" is not decided here
-------------------------------------------------
`open_only` is resolved from `ApplicationStatus.is_terminal`, the domain's own
rule. This use case does not carry a list of live statuses, so adding a status
to the lifecycle cannot leave a stale copy of that judgement behind in the
application layer.
"""

from __future__ import annotations

from src.application.dtos.tracked_application_dtos import (
    ListTrackedApplicationsInput,
    TrackedApplicationOutput,
)
from src.application.mappers.tracked_application_mapper import (
    TrackedApplicationMapper,
)
from src.application.services.sent_document_resolver import SentDocumentResolver
from src.domain.exceptions import InvalidValueError
from src.domain.repositories.application_document_repository import (
    ApplicationDocumentRepository,
)
from src.domain.repositories.tracked_application_repository import (
    TrackedApplicationRepository,
)
from src.domain.value_objects.application_status import ApplicationStatus


class ListTrackedApplications:
    def __init__(
        self,
        repository: TrackedApplicationRepository,
        document_repository: ApplicationDocumentRepository,
    ) -> None:
        self._repository = repository
        self._documents = document_repository

    async def execute(
        self, dto: ListTrackedApplicationsInput
    ) -> list[TrackedApplicationOutput]:
        """Return this candidate's applications, newest first.

        Raises:
            InvalidValueError: if `statuses` holds something that is not an
                application status, or if it is combined with `open_only` —
                which is a contradiction, not an intersection.
        """
        if dto.open_only and dto.statuses is not None:
            raise InvalidValueError(
                "Ask for open applications or for specific statuses, not both: "
                "'open_only' already names a set of statuses, and combining "
                "the two hides whichever of them the caller did not mean."
            )

        statuses = self._resolve(dto.statuses) if dto.statuses is not None else None
        if dto.open_only:
            statuses = tuple(
                status
                for status in ApplicationStatus
                if not status.is_terminal and status is not ApplicationStatus.DRAFT
            )

        applications = await self._repository.list_by_user_id(
            dto.user_id, statuses=statuses, limit=dto.limit
        )
        # One resolver for the whole feed, so two applications to the same
        # posting cost one document read rather than two.
        resolver = SentDocumentResolver(self._documents)
        outputs: list[TrackedApplicationOutput] = []
        for application in applications:
            resume, cover_letter = await resolver.resolve(application)
            outputs.append(
                TrackedApplicationMapper.to_output(
                    application, resume=resume, cover_letter=cover_letter
                )
            )
        return outputs

    @staticmethod
    def _resolve(statuses: tuple[str, ...]) -> tuple[ApplicationStatus, ...]:
        resolved: list[ApplicationStatus] = []
        for status in statuses:
            try:
                resolved.append(ApplicationStatus(status))
            except ValueError as exc:
                allowed = ", ".join(
                    candidate.value
                    for candidate in ApplicationStatus
                    if candidate is not ApplicationStatus.DRAFT
                )
                raise InvalidValueError(
                    f"'{status}' is not an application status. Expected one "
                    f"of: {allowed}."
                ) from exc
        # De-duplicated, so repeating a status in the query string cannot
        # change the SQL. Order is irrelevant to an `IN`, and the rows come
        # back ordered by date regardless.
        return tuple(dict.fromkeys(resolved))

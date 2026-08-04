"""GreenhouseBoardClient — AtsBoardClientPort backed by Greenhouse's public
job-board API (`boards-api.greenhouse.io`).

Unauthenticated: any company's public board can be read by token alone,
no API key required. `content=true` is required on the request or
Greenhouse omits each job's full HTML description entirely.

Shape: `{"jobs": [{"title", "absolute_url", "content", "location": {"name"},
"first_published", "updated_at"}]}`. The description is HTML, so it goes through
`html_to_text`. Only `list_jobs` is implemented here — `find_job` comes from
`BoardClientBase` and reads this same mapping.
"""

from __future__ import annotations

import logging

from src.application.ports.ats_board_client_port import BoardJobPosting
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.ats_boards.board_client_base import (
    BoardClientBase,
    build_posting,
)
from src.infrastructure.ats_boards.board_http import get_json_or_none
from src.infrastructure.ats_boards.html_to_text import html_to_text

logger = logging.getLogger(__name__)

_BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseBoardClient(BoardClientBase):
    @property
    def provider(self) -> AtsProvider:
        return AtsProvider.GREENHOUSE

    async def list_jobs(self, *, board_token: str) -> tuple[BoardJobPosting, ...]:
        data = await get_json_or_none(
            self._client,
            _BASE_URL.format(token=board_token),
            service_name="greenhouse",
            params={"content": "true"},
            max_retries=self._max_retries,
            retry_base_delay=self._retry_base_delay,
            retry_max_delay=self._retry_max_delay,
        )
        if not isinstance(data, dict):
            return ()

        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            return ()

        postings: list[BoardJobPosting] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            content = job.get("content")
            posting = build_posting(
                title=job.get("title"),
                apply_url=job.get("absolute_url"),
                description=html_to_text(content) if isinstance(content, str) else "",
                location=_location_name(job.get("location")),
                # Greenhouse publishes no remote flag. A role's remoteness shows
                # up only in its location text or its prose, and inferring it from
                # either would be inventing data.
                is_remote=False,
                posted_at=job.get("first_published") or job.get("updated_at"),
            )
            if posting is not None:
                postings.append(posting)
        return tuple(postings)


def _location_name(value: object) -> str | None:
    """Greenhouse nests the location as `{"name": "Austin, TX"}`."""
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) else None
    return None

"""AshbyBoardClient — AtsBoardClientPort backed by Ashby's public job-board
posting API (`api.ashbyhq.com/posting-api/job-board/{token}`).

Unauthenticated. `descriptionPlain` is preferred over the HTML
`descriptionHtml` field when Ashby provides it, so no HTML stripping is
needed for the common case.

Shape: `{"jobs": [{"title", "jobUrl", "descriptionPlain", "location",
"isRemote", "publishedAt"}]}`. Ashby is the only one of the three that states
remoteness as a boolean. Only `list_jobs` is implemented here — `find_job` comes
from `BoardClientBase` and reads this same mapping.
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

_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


class AshbyBoardClient(BoardClientBase):
    @property
    def provider(self) -> AtsProvider:
        return AtsProvider.ASHBY

    async def list_jobs(self, *, board_token: str) -> tuple[BoardJobPosting, ...]:
        data = await get_json_or_none(
            self._client,
            _BASE_URL.format(token=board_token),
            service_name="ashby",
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
            posting = build_posting(
                title=job.get("title"),
                apply_url=job.get("jobUrl") or job.get("applyUrl"),
                description=_extract_description(job),
                location=job.get("location"),
                is_remote=job.get("isRemote"),
                posted_at=job.get("publishedAt") or job.get("updatedAt"),
            )
            if posting is not None:
                postings.append(posting)
        return tuple(postings)


def _extract_description(job: dict[str, object]) -> str:
    plain = job.get("descriptionPlain")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()

    html = job.get("descriptionHtml")
    if isinstance(html, str) and html.strip():
        return html_to_text(html)

    return ""

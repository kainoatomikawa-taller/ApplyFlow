"""GreenhouseBoardClient — AtsBoardClientPort backed by Greenhouse's public
job-board API (`boards-api.greenhouse.io`).

Unauthenticated: any company's public board can be read by token alone,
no API key required. `content=true` is required on the request or
Greenhouse omits each job's full HTML description entirely.
"""

from __future__ import annotations

import logging

import httpx

from src.application.ports.ats_board_client_port import AtsBoardClientPort
from src.application.ports.listing_resolver_port import ResolvedListingFields
from src.domain.services.job_title_matching import titles_match
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.ats_boards.board_http import get_json_or_none
from src.infrastructure.ats_boards.html_to_text import html_to_text
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseBoardClient(AtsBoardClientPort):
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._max_retries = settings.ats_board_max_retries
        self._retry_base_delay = settings.ats_board_retry_base_delay_seconds
        self._retry_max_delay = settings.ats_board_retry_max_delay_seconds
        self._client = http_client or httpx.AsyncClient(timeout=30.0)

    @property
    def provider(self) -> AtsProvider:
        return AtsProvider.GREENHOUSE

    async def find_job(
        self, *, board_token: str, title: str
    ) -> ResolvedListingFields | None:
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
            return None

        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            return None

        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_title = job.get("title")
            if not isinstance(job_title, str) or not titles_match(job_title, title):
                continue

            apply_url = job.get("absolute_url")
            content = job.get("content")
            if not isinstance(apply_url, str) or not apply_url.strip():
                continue
            if not isinstance(content, str) or not content.strip():
                continue

            description = html_to_text(content)
            if not description:
                continue

            return ResolvedListingFields(apply_url=apply_url, description=description)

        return None

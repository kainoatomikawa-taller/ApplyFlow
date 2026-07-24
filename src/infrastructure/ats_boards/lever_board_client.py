"""LeverBoardClient — AtsBoardClientPort backed by Lever's public postings
API (`api.lever.co/v0/postings/{token}`).

Unauthenticated, and — unlike Greenhouse/Ashby's `{"jobs": [...]}` shape —
returns a bare JSON array of postings directly. `descriptionPlain` is
preferred over the HTML `description` field when Lever provides it, so no
HTML stripping is needed for the common case.
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

_BASE_URL = "https://api.lever.co/v0/postings/{token}"


class LeverBoardClient(AtsBoardClientPort):
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._max_retries = settings.ats_board_max_retries
        self._retry_base_delay = settings.ats_board_retry_base_delay_seconds
        self._retry_max_delay = settings.ats_board_retry_max_delay_seconds
        self._client = http_client or httpx.AsyncClient(timeout=30.0)

    @property
    def provider(self) -> AtsProvider:
        return AtsProvider.LEVER

    async def find_job(
        self, *, board_token: str, title: str
    ) -> ResolvedListingFields | None:
        data = await get_json_or_none(
            self._client,
            _BASE_URL.format(token=board_token),
            service_name="lever",
            params={"mode": "json"},
            max_retries=self._max_retries,
            retry_base_delay=self._retry_base_delay,
            retry_max_delay=self._retry_max_delay,
        )
        if not isinstance(data, list):
            return None

        for posting in data:
            if not isinstance(posting, dict):
                continue
            posting_title = posting.get("text")
            if not isinstance(posting_title, str) or not titles_match(
                posting_title, title
            ):
                continue

            apply_url = posting.get("hostedUrl") or posting.get("applyUrl")
            if not isinstance(apply_url, str) or not apply_url.strip():
                continue

            description = _extract_description(posting)
            if not description:
                continue

            return ResolvedListingFields(apply_url=apply_url, description=description)

        return None


def _extract_description(posting: dict[str, object]) -> str:
    plain = posting.get("descriptionPlain")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()

    html = posting.get("description")
    if isinstance(html, str) and html.strip():
        return html_to_text(html)

    return ""

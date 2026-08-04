"""LeverBoardClient — AtsBoardClientPort backed by Lever's public postings
API (`api.lever.co/v0/postings/{token}`).

Unauthenticated, and — unlike Greenhouse/Ashby's `{"jobs": [...]}` shape —
returns a bare JSON array of postings directly. `descriptionPlain` is
preferred over the HTML `description` field when Lever provides it, so no
HTML stripping is needed for the common case.

Two other Lever peculiarities: the title is `text` rather than `title`, and the
location sits under `categories.location`. `createdAt` is epoch milliseconds,
which `parse_posted_at` handles. Only `list_jobs` is implemented here —
`find_job` comes from `BoardClientBase` and reads this same mapping.
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

_BASE_URL = "https://api.lever.co/v0/postings/{token}"


class LeverBoardClient(BoardClientBase):
    @property
    def provider(self) -> AtsProvider:
        return AtsProvider.LEVER

    async def list_jobs(self, *, board_token: str) -> tuple[BoardJobPosting, ...]:
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
            return ()

        postings: list[BoardJobPosting] = []
        for posting in data:
            if not isinstance(posting, dict):
                continue
            categories = posting.get("categories")
            categories = categories if isinstance(categories, dict) else {}
            built = build_posting(
                title=posting.get("text"),
                apply_url=posting.get("hostedUrl") or posting.get("applyUrl"),
                description=_extract_description(posting),
                location=categories.get("location"),
                # Lever states this explicitly, so it is read rather than guessed.
                is_remote=_is_remote(posting, categories),
                posted_at=posting.get("createdAt"),
            )
            if built is not None:
                postings.append(built)
        return tuple(postings)


def _is_remote(posting: dict[str, object], categories: dict[str, object]) -> bool:
    """Lever exposes remoteness as `workplaceType`, or as the literal word in
    the location category on older boards."""
    workplace = posting.get("workplaceType")
    if isinstance(workplace, str) and workplace.strip().casefold() == "remote":
        return True
    location = categories.get("location")
    return isinstance(location, str) and location.strip().casefold() == "remote"


def _extract_description(posting: dict[str, object]) -> str:
    plain = posting.get("descriptionPlain")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()

    html = posting.get("description")
    if isinstance(html, str) and html.strip():
        return html_to_text(html)

    return ""

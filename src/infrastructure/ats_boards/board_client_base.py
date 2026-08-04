"""Shared plumbing for the three ATS board clients.

Each platform differs only in its URL, its query parameters, and the shape of
the JSON it returns. Everything around that was duplicated three ways: the same
constructor reading the same three retry settings, and the same
find-a-job-by-title loop.

`find_job()` lives here, defined in terms of the subclass's `list_jobs()`. That
is the point of the base class rather than a convenience: the two questions a
caller can ask a board — "what's on it" and "what are this one job's details" —
now read the same board through the same mapping, so they cannot disagree about
what a company has published or about which fields count as complete.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from src.application.ports.ats_board_client_port import (
    AtsBoardClientPort,
    BoardJobPosting,
)
from src.application.ports.listing_resolver_port import ResolvedListingFields
from src.domain.services.job_title_matching import titles_match
from src.infrastructure.config import Settings


class BoardClientBase(AtsBoardClientPort):
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._max_retries = settings.ats_board_max_retries
        self._retry_base_delay = settings.ats_board_retry_base_delay_seconds
        self._retry_max_delay = settings.ats_board_retry_max_delay_seconds
        self._client = http_client or httpx.AsyncClient(timeout=30.0)

    async def find_job(
        self, *, board_token: str, title: str
    ) -> ResolvedListingFields | None:
        """The first posting on this board whose title matches `title`.

        First rather than best: `titles_match` is the domain's own judgement of
        whether two titles name the same role, and a board that lists two
        postings it considers equally named has two openings, not one better
        answer. Taking the first keeps this deterministic and leaves the choice
        where it belongs — with whoever asked for a specific title.
        """
        for posting in await self.list_jobs(board_token=board_token):
            if titles_match(posting.title, title):
                return ResolvedListingFields(
                    apply_url=posting.apply_url, description=posting.description
                )
        return None


def build_posting(
    *,
    title: object,
    apply_url: object,
    description: str,
    location: object = None,
    is_remote: object = False,
    posted_at: object = None,
) -> BoardJobPosting | None:
    """A `BoardJobPosting` from raw JSON values, or None if it is incomplete.

    Every field arrives as `object` because it came out of a third party's JSON
    and nothing has checked it yet. Returning None for an entry missing any of
    the three required fields is what lets each client's mapping loop be a
    comprehension instead of a pile of `continue`s — and it puts the "what counts
    as complete" rule in one place, since `JobPosting` will refuse a blank apply
    URL or description anyway.
    """
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(apply_url, str) or not apply_url.strip():
        return None
    if not description.strip():
        return None
    return BoardJobPosting(
        title=title.strip(),
        apply_url=apply_url.strip(),
        description=description.strip(),
        location=location.strip() or None if isinstance(location, str) else None,
        is_remote=is_remote is True,
        posted_at=parse_posted_at(posted_at),
    )


def parse_posted_at(value: object) -> date | None:
    """A publication date from whatever the board put in the field, or None.

    Handles the two shapes these APIs use — an ISO 8601 timestamp
    (Greenhouse/Ashby) and epoch milliseconds (Lever) — and answers None for
    anything else. None rather than today's date on failure: a posting whose age
    is unknown must not read as one published this morning, because staleness
    checks would then never retire it.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        # Milliseconds, not seconds: Lever's `createdAt` is ms since the epoch,
        # and a value that large read as seconds lands tens of thousands of years
        # out. Guarded rather than assumed, so a seconds-based field still works.
        seconds = value / 1000 if value > 4_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds).date()
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # `fromisoformat` on 3.11+ handles most of what these boards emit; "Z" is
    # normalized because it did not until 3.11 and costs nothing to keep.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None

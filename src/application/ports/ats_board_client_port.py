"""AtsBoardClientPort — an outbound port for reading a company's own ATS board
feed (Greenhouse/Lever/Ashby) directly.

Concrete implementations each wrap one platform's public, unauthenticated
job-board API — callers never know which platform answered, only that they
asked about a specific `board_token`.

Two ways to ask, for two different jobs
---------------------------------------
`find_job()` answers "what are this one listing's apply URL and description?"
It exists for `AtsListingResolver`, which is repairing an aggregator listing
that arrived without them.

`list_jobs()` answers "what is this company hiring for?" — the whole board, for
`IngestBoardJobs` to persist. It is the cheaper source of the two by a wide
margin: these APIs need no key and meter nothing, so a board can be re-read as
often as you like, where an aggregator search costs quota and returns a
truncated description.

`find_job()` is defined in terms of `list_jobs()` in every implementation, so
the two can never disagree about what a board contains.

`None`/empty covers every non-fatal outcome — no matching title, an empty
board, a listing missing a field a caller needs. Callers must never treat
either as an error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from src.application.ports.listing_resolver_port import ResolvedListingFields
from src.domain.value_objects.ats_provider import AtsProvider


@dataclass(frozen=True)
class BoardJobPosting:
    """One opening as published on a company's own ATS board.

    `title`, `apply_url` and `description` are required because a `JobPosting`
    cannot exist without them — an entry missing any of the three is dropped by
    the client rather than surfaced half-built. Everything else is optional
    because the three platforms disagree about what they publish.
    """

    title: str
    apply_url: str
    description: str
    location: str | None = None
    is_remote: bool = False
    #: When the company published it, where the board says. `None` whenever the
    #: field is absent or unparseable — never a guess, and never "today".
    posted_at: date | None = None


class AtsBoardClientPort(ABC):
    """Abstraction over one ATS platform's public job-board feed."""

    @property
    @abstractmethod
    def provider(self) -> AtsProvider:
        """Which platform this client reads from."""

    @abstractmethod
    async def list_jobs(self, *, board_token: str) -> tuple[BoardJobPosting, ...]:
        """Every complete opening on `board_token`'s public board, in the order
        the board lists them.

        Empty when the board has no openings, does not exist, or published
        nothing usable — all ordinary outcomes. Entries missing a title, an apply
        URL, or a description are omitted.

        Raises `src.application.exceptions.ExternalServiceError` if the board's
        feed cannot be fetched after retrying.
        """

    @abstractmethod
    async def find_job(
        self, *, board_token: str, title: str
    ) -> ResolvedListingFields | None:
        """Fetch `board_token`'s public job list and return the apply URL
        + full description of whichever listing's title matches `title`
        (see `src.domain.services.job_title_matching.titles_match`), or
        None if no listing on this board matches.

        Raises `src.application.exceptions.ExternalServiceError` if the
        board's feed cannot be fetched after retrying.
        """

"""AtsBoardClientPort — an outbound port for reading one specific job's
apply URL + full description directly off a company's own ATS board feed
(Greenhouse/Lever/Ashby), given the board's token and the listing's title.

Concrete implementations each wrap one platform's public, unauthenticated
job-board API — `AtsListingResolver` (this port's caller) never knows
which platform answered the call, only that it was asked for a specific
`board_token` (discovered separately via a search-API lookup — see
`ResolvedCompanyBoardRepository`) and title, and either got back a
confident match or `None`. `None` covers every non-fatal outcome (the
board has no job with a matching title, the board is empty, a field the
match needs is missing) — callers must never treat it as an error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.application.ports.listing_resolver_port import ResolvedListingFields
from src.domain.value_objects.ats_provider import AtsProvider


class AtsBoardClientPort(ABC):
    """Abstraction over one ATS platform's public job-board feed."""

    @property
    @abstractmethod
    def provider(self) -> AtsProvider:
        """Which platform this client reads from."""

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

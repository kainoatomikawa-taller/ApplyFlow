"""ResolvedCompanyBoard — a cached record of which ATS platform + board
token a company's public job listings are hosted on, discovered once via
a search API for a company whose aggregator listing arrived without a
usable `apply_url`/`description` (see `JobPosting`, which requires both
non-empty).

Cached permanently and keyed on `normalized_company` alone (see
`normalize_text`), never per-title: discovering WHICH board a company
posts through costs one search-API query, so once found it is never
searched for again, regardless of how many more of that company's
listings arrive without a URL/description. This is the mechanism behind
the "never re-search the same company" quota-conservation requirement —
see `src.infrastructure.search.ats_listing_resolver.AtsListingResolver`.

Deliberately does NOT cache a job-specific apply URL or description —
unlike the board itself, those differ per listing even at the same
company, and are cheap to re-derive from the (free, unauthenticated) ATS
board feed this record points at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.exceptions import InvalidValueError
from src.domain.services.text_normalization import normalize_text
from src.domain.value_objects.ats_provider import AtsProvider


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ResolvedCompanyBoard:
    """A search-API-discovered ATS board reference, cached by company."""

    company: str
    provider: AtsProvider
    board_token: str
    resolved_at: datetime = field(default_factory=_utcnow)

    normalized_company: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if not self.company.strip():
            raise InvalidValueError(
                "ResolvedCompanyBoard requires a non-empty company."
            )
        if not self.board_token.strip():
            raise InvalidValueError(
                "ResolvedCompanyBoard requires a non-empty board_token."
            )

        self.normalized_company = normalize_text(self.company)

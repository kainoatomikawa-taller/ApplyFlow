"""ResolvedListing — a canonical apply URL and description resolved via a
search API for a company whose aggregator listing arrived without one or
both (see `JobPosting`, which requires both non-empty).

Cached permanently and keyed on `normalized_company` alone (see
`normalize_text`), never per-title: once a company has been resolved, every
subsequent listing from that company reuses this record instead of
triggering another search. This is the mechanism behind the "never
re-search the same company" quota-conservation requirement — see
`src.application.ports.listing_resolver_port.ListingResolverPort`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.exceptions import InvalidValueError
from src.domain.services.text_normalization import normalize_text


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ResolvedListing:
    """A search-API resolution result, cached by company."""

    company: str
    apply_url: str
    description: str
    resolved_at: datetime = field(default_factory=_utcnow)

    normalized_company: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if not self.company.strip():
            raise InvalidValueError("ResolvedListing requires a non-empty company.")
        if not self.apply_url.strip():
            raise InvalidValueError("ResolvedListing requires a non-empty apply_url.")
        if not self.description.strip():
            raise InvalidValueError(
                "ResolvedListing requires a non-empty description."
            )

        self.normalized_company = normalize_text(self.company)

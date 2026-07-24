"""JobAggregatorPort — an outbound port for fetching job listings from an
aggregator API (Adzuna, and future sources like LinkedIn/Indeed).

The application layer defines this abstraction; each concrete aggregator
lives in infrastructure and is responsible for its own schema mapping,
pagination mechanics, and rate-limit handling. `IngestAggregatorJobs` (the
use case that drives this port) never knows which aggregator answered the
call or how its API is shaped — it only sees `AggregatorJobListing`, a
shape already close to `JobPosting`'s, minus the fields the use case itself
assigns (`id`, dedup keys).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from src.domain.value_objects.salary_range import SalaryRange


@dataclass(frozen=True)
class AggregatorJobListing:
    """One job listing as read from an aggregator source, already mapped
    onto ApplyFlow's internal shape by that source's adapter."""

    external_id: str
    company: str
    title: str
    apply_url: str
    description: str
    is_remote: bool = False
    location: str | None = None
    salary: SalaryRange | None = None
    posted_at: date | None = None


@dataclass(frozen=True)
class AggregatorPage:
    """One page of aggregator search results."""

    listings: list[AggregatorJobListing] = field(default_factory=list)
    has_more: bool = False


class JobAggregatorPort(ABC):
    """Abstraction over a job-aggregator search API."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """The `JobPosting.source` value this adapter's listings carry."""

    @abstractmethod
    async def fetch_page(
        self, *, keywords: str, location: str | None, page: int
    ) -> AggregatorPage:
        """Fetch one page (1-indexed) of listings matching `keywords`.

        Implementations own their own pagination cursor/offset scheme and
        rate-limit handling (backoff/retry on 429s). Raises
        `src.application.exceptions.ExternalServiceError` if the page
        cannot be fetched after retrying.
        """

"""JobPosting entity — the single internal job model every aggregator
source (LinkedIn, Indeed, Greenhouse, ...) normalizes into.

Everything downstream (matching, tailoring) reads this shape rather than
any source-specific payload, so an aggregator adapter's only job is to
map its raw response onto these fields. `normalized_company`,
`normalized_title`, and `normalized_location` are derived automatically
(never independently settable) so every adapter produces consistent dedup
keys without re-implementing the normalization rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.salary_range import SalaryRange

_WHITESPACE_RE = re.compile(r"\s+")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize(value: str) -> str:
    """Collapse a display string to a stable dedup key: trimmed, lowercased,
    whitespace-collapsed. Not fuzzy matching — just enough to catch the
    same posting rendered with different casing/spacing across sources."""
    return _WHITESPACE_RE.sub(" ", value.strip().lower())


@dataclass
class JobPosting:
    """A single job listing, normalized from an aggregator source."""

    id: str
    source: str
    company: str
    title: str
    apply_url: str
    description: str
    is_remote: bool = False
    location: str | None = None
    salary: SalaryRange | None = None
    posted_at: date | None = None
    created_at: datetime = field(default_factory=_utcnow)

    normalized_company: str = field(init=False, default="")
    normalized_title: str = field(init=False, default="")
    normalized_location: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidValueError("JobPosting requires a non-empty id.")
        if not self.source.strip():
            raise InvalidValueError("JobPosting requires a non-empty source.")
        if not self.company.strip():
            raise InvalidValueError("JobPosting requires a non-empty company.")
        if not self.title.strip():
            raise InvalidValueError("JobPosting requires a non-empty title.")
        if not self.apply_url.strip():
            raise InvalidValueError("JobPosting requires a non-empty apply_url.")
        if not self.description.strip():
            raise InvalidValueError("JobPosting requires a non-empty description.")

        self.normalized_company = _normalize(self.company)
        self.normalized_title = _normalize(self.title)
        self.normalized_location = (
            _normalize(self.location) if self.location else None
        )

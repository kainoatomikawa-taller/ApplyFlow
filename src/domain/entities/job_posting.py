"""JobPosting entity — the single internal job model every aggregator
source (LinkedIn, Indeed, Greenhouse, ...) normalizes into.

Everything downstream (matching, tailoring) reads this shape rather than
any source-specific payload, so an aggregator adapter's only job is to
map its raw response onto these fields. `normalized_company`,
`normalized_title`, and `normalized_location` are derived automatically
(never independently settable) so every adapter produces consistent dedup
keys without re-implementing the normalization rule.

`status`/`last_checked_at`/`consecutive_link_failures` track this
posting's lifecycle past ingestion — see `mark_stale_if_expired` and
`apply_link_check`, the only things allowed to change `status`, and
`JobPostingRepository.list_active`, the "active job set" downstream
matching should read from instead of this table directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import ClassVar

from src.domain.exceptions import InvalidValueError
from src.domain.services.text_normalization import normalize_text
from src.domain.value_objects.job_posting_status import JobPostingStatus
from src.domain.value_objects.job_requirements import JobRequirements
from src.domain.value_objects.link_check_outcome import LinkCheckOutcome
from src.domain.value_objects.salary_range import SalaryRange


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobPosting:
    """A single job listing, normalized from an aggregator source."""

    #: Consecutive TRANSIENT_FAILURE reachability checks (see
    #: `apply_link_check`) required before an ambiguous failure (timeout,
    #: 5xx, connection error) is trusted enough to flag DEAD_LINK. A single
    #: CONFIRMED_DEAD result (404/410) skips this threshold entirely.
    DEFAULT_DEAD_LINK_FAILURE_THRESHOLD: ClassVar[int] = 3
    #: How many days after `posted_at` (or `created_at`, if the source
    #: never reported one) a posting is presumed no longer open, absent
    #: any other signal.
    DEFAULT_STALE_AFTER_DAYS: ClassVar[int] = 45

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

    status: JobPostingStatus = JobPostingStatus.ACTIVE
    last_checked_at: datetime | None = None
    consecutive_link_failures: int = 0

    #: Structured requirement attributes extracted from `description` by
    #: Epic 03's LLM pass (see `JobRequirementsExtractorPort`) — `None`
    #: until that extraction has run for this posting.
    requirements: JobRequirements | None = None

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
        if self.consecutive_link_failures < 0:
            raise InvalidValueError(
                "JobPosting.consecutive_link_failures cannot be negative."
            )

        self.normalized_company = normalize_text(self.company)
        self.normalized_title = normalize_text(self.title)
        self.normalized_location = (
            normalize_text(self.location) if self.location else None
        )

    # ---- Behaviors (business rules live here) --------------------------------

    @property
    def is_active(self) -> bool:
        return self.status == JobPostingStatus.ACTIVE

    def mark_stale_if_expired(
        self, *, as_of: datetime, stale_after_days: int | None = None
    ) -> None:
        """Flag this posting STALE if it is older than `stale_after_days`
        (defaulting to `DEFAULT_STALE_AFTER_DAYS`) and still ACTIVE.

        A no-op once the posting has already left ACTIVE — status is
        one-way (see `JobPostingStatus`), so a posting already flagged is
        never reconsidered here.
        """
        if not self.is_active:
            return

        threshold = (
            self.DEFAULT_STALE_AFTER_DAYS
            if stale_after_days is None
            else stale_after_days
        )
        reference_date = self.posted_at or self.created_at.date()
        if (as_of.date() - reference_date).days >= threshold:
            self.status = JobPostingStatus.STALE

    def apply_link_check(
        self,
        outcome: LinkCheckOutcome,
        *,
        checked_at: datetime,
        dead_link_after_failures: int | None = None,
    ) -> None:
        """Record the outcome of one reachability check against
        `apply_url`.

        A CONFIRMED_DEAD result (the server itself asserting the posting
        is gone) flags DEAD_LINK immediately. A TRANSIENT_FAILURE only
        counts toward `dead_link_after_failures` consecutive occurrences
        before flagging DEAD_LINK, so one bad network blip against an
        otherwise-live posting never wrongly excludes it. A REACHABLE
        result resets the failure streak. No-op on `status` once already
        non-ACTIVE (see `JobPostingStatus`) — `last_checked_at` still
        updates so a caller can tell a check ran.
        """
        self.last_checked_at = checked_at

        if outcome == LinkCheckOutcome.REACHABLE:
            self.consecutive_link_failures = 0
            return

        self.consecutive_link_failures += 1
        if not self.is_active:
            return

        threshold = (
            self.DEFAULT_DEAD_LINK_FAILURE_THRESHOLD
            if dead_link_after_failures is None
            else dead_link_after_failures
        )
        if (
            outcome == LinkCheckOutcome.CONFIRMED_DEAD
            or self.consecutive_link_failures >= threshold
        ):
            self.status = JobPostingStatus.DEAD_LINK

    def set_requirements(self, requirements: JobRequirements) -> None:
        """Attach this posting's Epic 03 extraction result, replacing any
        previously set `requirements` outright — a re-extraction always
        supersedes a stale prior pass rather than merging with it."""
        self.requirements = requirements

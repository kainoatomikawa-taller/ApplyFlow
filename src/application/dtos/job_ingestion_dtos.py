"""DTOs for the job-ingestion use cases — aggregator search and direct board
reads."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.value_objects.ats_provider import AtsProvider


@dataclass(frozen=True)
class IngestAggregatorJobsInput:
    """Search parameters for one ingestion run."""

    keywords: str
    location: str | None = None
    max_pages: int = 1


@dataclass(frozen=True)
class IngestAggregatorJobsOutput:
    """Outcome of one ingestion run."""

    pages_fetched: int
    listings_seen: int
    ingested_count: int
    skipped_duplicate_count: int
    skipped_unresolved_count: int = 0


@dataclass(frozen=True)
class TargetBoard:
    """One company's ATS board to read.

    `company` is supplied rather than derived from `board_token`: the token is a
    URL slug ("acme-corp", "stripe") and it is what gets stored on every posting
    and used for duplicate detection, so a readable name is worth one extra
    argument.
    """

    company: str
    provider: AtsProvider
    board_token: str


@dataclass(frozen=True)
class IngestBoardJobsInput:
    """The boards to read in one run."""

    boards: tuple[TargetBoard, ...] = ()


@dataclass(frozen=True)
class BoardIngestionResult:
    """What came of reading one board.

    Per-board rather than only a total, because one company's board being empty
    or gone is the interesting detail in a multi-board run and a summed count
    hides it. `error` is set when that board could not be read at all — the run
    continues past it.
    """

    company: str
    provider: AtsProvider
    board_token: str
    postings_seen: int = 0
    ingested_count: int = 0
    skipped_duplicate_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class IngestBoardJobsOutput:
    """Outcome of one direct-board ingestion run."""

    results: tuple[BoardIngestionResult, ...] = field(default_factory=tuple)

    @property
    def boards_read(self) -> int:
        return sum(1 for result in self.results if result.error is None)

    @property
    def postings_seen(self) -> int:
        return sum(result.postings_seen for result in self.results)

    @property
    def ingested_count(self) -> int:
        return sum(result.ingested_count for result in self.results)

    @property
    def skipped_duplicate_count(self) -> int:
        return sum(result.skipped_duplicate_count for result in self.results)

    @property
    def failed_boards(self) -> tuple[BoardIngestionResult, ...]:
        return tuple(result for result in self.results if result.error is not None)

"""IngestBoardJobs use case — read companies' own ATS boards and persist every
opening on them as normalized `JobPosting` records.

Why this exists alongside `IngestAggregatorJobs`
------------------------------------------------
The aggregator path answers "what is out there that I don't know about" and pays
for the answer: a metered search API, and — when a listing arrives without an
apply URL or description — a second metered search to work out which platform
hosts that company's board.

This path answers the other question: "what is this company hiring for right
now". Greenhouse, Lever and Ashby publish that unauthenticated and unmetered, so
a named company's board can be re-read as often as you like for nothing. It also
arrives complete: aggregators routinely truncate a description to a paragraph,
where a board returns the posting in full — which matters, because the full text
is what requirement extraction has to read.

Neither replaces the other. Discovery needs the aggregator; depth on the
companies a candidate actually cares about needs this.

One board's failure is not the run's failure
--------------------------------------------
A board token can be wrong, a company can move platforms, a board can be taken
down. Each is recorded against that board as an `error` and the run moves on, so
a typo in one of twenty tokens does not cost the other nineteen. A caller that
wants to treat a failure as fatal has `failed_boards` to check.

Duplicate detection is per source, and that has a consequence
-------------------------------------------------------------
`source` is the platform name, so a posting read from Greenhouse is a different
row from the same job found via Adzuna, and re-reading a board never duplicates
its own rows. Cross-source duplication is real and deliberately not solved here:
deciding which of two records for one job wins is a separate concern from
ingesting either, and the board-sourced row is the better of the two anyway (a
real apply URL, the full description).
"""

from __future__ import annotations

from src.application.dtos.job_ingestion_dtos import (
    BoardIngestionResult,
    IngestBoardJobsInput,
    IngestBoardJobsOutput,
    TargetBoard,
)
from src.application.exceptions import ExternalServiceError
from src.application.ports.ats_board_client_port import AtsBoardClientPort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.job_posting import JobPosting
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.value_objects.ats_provider import AtsProvider


class IngestBoardJobs:
    def __init__(
        self,
        repository: JobPostingRepository,
        board_clients: dict[AtsProvider, AtsBoardClientPort],
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._board_clients = board_clients
        self._id_generator = id_generator

    async def execute(self, dto: IngestBoardJobsInput) -> IngestBoardJobsOutput:
        results: list[BoardIngestionResult] = []
        for board in dto.boards:
            results.append(await self._ingest_one(board))
        return IngestBoardJobsOutput(results=tuple(results))

    async def _ingest_one(self, board: TargetBoard) -> BoardIngestionResult:
        client = self._board_clients.get(board.provider)
        if client is None:
            return self._failed(board, f"no client configured for {board.provider}")

        try:
            postings = await client.list_jobs(board_token=board.board_token)
        except ExternalServiceError as exc:
            # The board could not be read at all. Recorded and skipped rather
            # than raised — see the module docstring.
            return self._failed(board, str(exc))

        ingested = 0
        duplicates = 0
        for posting in postings:
            job_posting = JobPosting(
                id=self._id_generator.new_id(),
                source=board.provider.value,
                company=board.company,
                title=posting.title,
                apply_url=posting.apply_url,
                description=posting.description,
                is_remote=posting.is_remote,
                location=posting.location,
                # Boards publish no salary in these feeds. Left unset rather
                # than inferred from the description.
                salary=None,
                posted_at=posting.posted_at,
            )

            duplicate = await self._repository.find_duplicate(
                source=job_posting.source,
                normalized_company=job_posting.normalized_company,
                normalized_title=job_posting.normalized_title,
                normalized_location=job_posting.normalized_location,
            )
            if duplicate is not None:
                duplicates += 1
                continue

            await self._repository.add(job_posting)
            ingested += 1

        return BoardIngestionResult(
            company=board.company,
            provider=board.provider,
            board_token=board.board_token,
            postings_seen=len(postings),
            ingested_count=ingested,
            skipped_duplicate_count=duplicates,
        )

    @staticmethod
    def _failed(board: TargetBoard, error: str) -> BoardIngestionResult:
        return BoardIngestionResult(
            company=board.company,
            provider=board.provider,
            board_token=board.board_token,
            error=error,
        )

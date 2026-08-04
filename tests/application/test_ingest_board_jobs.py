"""IngestBoardJobs tests using in-memory fakes.

What matters here is not that postings round-trip. It is the three properties
that make a multi-board run safe to re-run and safe to get wrong: re-reading a
board does not duplicate its rows, one bad board does not cost the others, and
the board's own fields survive onto the `JobPosting` rather than being defaulted.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.application.dtos.job_ingestion_dtos import (
    IngestBoardJobsInput,
    TargetBoard,
)
from src.application.exceptions import ExternalServiceError
from src.application.ports.ats_board_client_port import (
    AtsBoardClientPort,
    BoardJobPosting,
)
from src.application.ports.listing_resolver_port import ResolvedListingFields
from src.application.use_cases.ingest_board_jobs import IngestBoardJobs
from src.domain.value_objects.ats_provider import AtsProvider

# Reused rather than re-implemented: this fake already satisfies the whole
# `JobPostingRepository` surface, including the staleness methods this use case
# never touches, and a second copy would drift from it.
from tests.application.test_ingest_aggregator_jobs import FakeJobPostingRepository


class FakeBoardClient(AtsBoardClientPort):
    def __init__(
        self,
        provider: AtsProvider,
        postings: tuple[BoardJobPosting, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self._provider = provider
        self._postings = postings
        self._error = error
        self.calls: list[str] = []

    @property
    def provider(self) -> AtsProvider:
        return self._provider

    async def list_jobs(self, *, board_token: str) -> tuple[BoardJobPosting, ...]:
        self.calls.append(board_token)
        if self._error is not None:
            raise self._error
        return self._postings

    async def find_job(
        self, *, board_token: str, title: str
    ) -> ResolvedListingFields | None:
        return None


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> str:
        self._next += 1
        return f"posting-{self._next}"


def _posting(
    title: str = "Software Engineer Intern", **overrides: object
) -> BoardJobPosting:
    defaults: dict[str, object] = {
        "title": title,
        "apply_url": f"https://boards.greenhouse.io/acme/jobs/{title.lower()}",
        "description": "Build things. " * 20,
    }
    defaults.update(overrides)
    return BoardJobPosting(**defaults)  # type: ignore[arg-type]


def _use_case(repo, clients):
    return IngestBoardJobs(
        repository=repo, board_clients=clients, id_generator=SequentialIds()
    )


_ACME = TargetBoard(
    company="Acme Corp", provider=AtsProvider.GREENHOUSE, board_token="acme"
)


# -- The happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_posting_on_the_board_is_persisted():
    repo = FakeJobPostingRepository()
    client = FakeBoardClient(
        AtsProvider.GREENHOUSE, (_posting("Backend Intern"), _posting("Data Intern"))
    )

    output = await _use_case(repo, {AtsProvider.GREENHOUSE: client}).execute(
        IngestBoardJobsInput(boards=(_ACME,))
    )

    assert client.calls == ["acme"]
    assert output.postings_seen == 2
    assert output.ingested_count == 2
    assert {posting.title for posting in repo.saved} == {
        "Backend Intern",
        "Data Intern",
    }


@pytest.mark.asyncio
async def test_the_source_is_the_platform_and_the_company_is_the_one_supplied():
    """`board_token` is a URL slug; the readable name is what gets stored and what
    duplicate detection compares."""
    repo = FakeJobPostingRepository()
    client = FakeBoardClient(AtsProvider.GREENHOUSE, (_posting(),))

    await _use_case(repo, {AtsProvider.GREENHOUSE: client}).execute(
        IngestBoardJobsInput(boards=(_ACME,))
    )

    assert repo.saved[0].source == "greenhouse"
    assert repo.saved[0].company == "Acme Corp"


@pytest.mark.asyncio
async def test_the_boards_own_fields_reach_the_posting():
    repo = FakeJobPostingRepository()
    client = FakeBoardClient(
        AtsProvider.ASHBY,
        (
            _posting(
                location="Austin, TX",
                is_remote=True,
                posted_at=date(2026, 7, 1),
            ),
        ),
    )

    await _use_case(repo, {AtsProvider.ASHBY: client}).execute(
        IngestBoardJobsInput(
            boards=(
                TargetBoard(
                    company="Acme", provider=AtsProvider.ASHBY, board_token="acme"
                ),
            )
        )
    )

    stored = repo.saved[0]
    assert stored.location == "Austin, TX"
    assert stored.is_remote is True
    assert stored.posted_at == date(2026, 7, 1)
    # Boards publish no salary in these feeds; left unset rather than inferred.
    assert stored.salary is None


# -- Re-running ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_re_reading_the_same_board_ingests_nothing_new():
    """The whole point of the direct path is that a board is free to re-read, so
    re-reading must be harmless."""
    repo = FakeJobPostingRepository()
    clients = {
        AtsProvider.GREENHOUSE: FakeBoardClient(
            AtsProvider.GREENHOUSE, (_posting("Backend Intern"),)
        )
    }

    first = await _use_case(repo, clients).execute(
        IngestBoardJobsInput(boards=(_ACME,))
    )
    second = await _use_case(repo, clients).execute(
        IngestBoardJobsInput(boards=(_ACME,))
    )

    assert first.ingested_count == 1
    assert second.ingested_count == 0
    assert second.skipped_duplicate_count == 1
    assert len(repo.saved) == 1


# -- One board's failure is not the run's failure ------------------------------


@pytest.mark.asyncio
async def test_a_board_that_cannot_be_read_does_not_stop_the_others():
    repo = FakeJobPostingRepository()
    clients = {
        AtsProvider.GREENHOUSE: FakeBoardClient(
            AtsProvider.GREENHOUSE, error=ExternalServiceError("board is gone")
        ),
        AtsProvider.LEVER: FakeBoardClient(AtsProvider.LEVER, (_posting(),)),
    }

    output = await _use_case(repo, clients).execute(
        IngestBoardJobsInput(
            boards=(
                _ACME,
                TargetBoard(
                    company="Other", provider=AtsProvider.LEVER, board_token="other"
                ),
            )
        )
    )

    assert output.ingested_count == 1
    assert output.boards_read == 1
    assert len(output.failed_boards) == 1
    assert output.failed_boards[0].company == "Acme Corp"
    assert "board is gone" in (output.failed_boards[0].error or "")


@pytest.mark.asyncio
async def test_a_provider_with_no_configured_client_is_reported_not_raised():
    repo = FakeJobPostingRepository()

    output = await _use_case(repo, {}).execute(IngestBoardJobsInput(boards=(_ACME,)))

    assert output.ingested_count == 0
    assert len(output.failed_boards) == 1
    assert "no client configured" in (output.failed_boards[0].error or "")


@pytest.mark.asyncio
async def test_an_empty_board_is_an_ordinary_outcome():
    repo = FakeJobPostingRepository()
    client = FakeBoardClient(AtsProvider.GREENHOUSE, ())

    output = await _use_case(repo, {AtsProvider.GREENHOUSE: client}).execute(
        IngestBoardJobsInput(boards=(_ACME,))
    )

    assert output.postings_seen == 0
    assert output.boards_read == 1
    assert output.failed_boards == ()


@pytest.mark.asyncio
async def test_no_boards_is_a_no_op():
    repo = FakeJobPostingRepository()

    output = await _use_case(repo, {}).execute(IngestBoardJobsInput())

    assert output.results == ()
    assert output.ingested_count == 0

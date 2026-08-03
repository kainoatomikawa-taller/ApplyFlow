"""Real-database smoke test for the portal hand-off store.

Exercises `SqlAlchemyPortalHandoffRepository` against an actual Postgres
connection end to end: raise a hand-off, read it back by id and as "the open
one for this posting", refresh its detection, resolve it, and list a
candidate's hand-offs newest first. Also proves the two properties that cannot
be checked against an in-memory fake — the partial unique index really does
allow only one *open* hand-off per posting, and `update` on a row that no
longer exists refuses instead of quietly inserting one.

Skips (rather than fails) when no database is reachable, so `pytest` still
runs for contributors without Postgres running locally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.exc import IntegrityError

from src.domain.entities.job_posting import JobPosting
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.exceptions import PortalHandoffNotFoundError
from src.domain.value_objects.handoff_status import HandoffStatus
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.infrastructure.persistence.database import (
    Base,
    async_session_factory,
    engine,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.portal_handoff_repository_impl import (
    SqlAlchemyPortalHandoffRepository,
)
from src.infrastructure.security.sensitive_access import SensitiveDataAccess

_CAPTCHA = HardStop(
    kind=HardStopKind.CAPTCHA,
    evidence=(
        "the page loads a known CAPTCHA component ('recaptcha')",
        "the page reads 'verify you are human'",
    ),
)
_WALL = HardStop(
    kind=HardStopKind.ACCOUNT_WALL,
    evidence=("the form presents 1 password field",),
)


@pytest.fixture(autouse=True)
def _sensitive_access(sensitive_access: SensitiveDataAccess) -> None:
    """Every test in this file round-trips at least one encrypted column, so the
    whole module runs inside a sensitive-data access scope — standing in for the
    authorized entry point a repository is always called from in production (Epic
    07). See `tests/conftest.py` for the shared fixture, and
    `test_encryption_at_rest.py` for the tests that assert the refusal when no
    scope is open."""


@pytest.fixture
async def schema_ready() -> AsyncIterator[None]:
    # The process-wide engine's pool outlives a test but its connections are
    # bound to the loop that opened them, so a pooled connection from the
    # previous test is unusable here. Disposing on both sides of each test
    # means every one of them opens its own.
    await engine.dispose()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"No reachable database at DATABASE_URL: {exc}")
    yield
    await engine.dispose()


async def _job_posting() -> JobPosting:
    posting = JobPosting(
        id=f"smoke-job-{uuid.uuid4()}",
        source="greenhouse",
        company="Smoke Test Co",
        title="Backend Engineer",
        apply_url="https://smoketestco.example.com/careers/apply",
        description="Build things.",
    )
    async with async_session_factory() as session:
        await SqlAlchemyJobPostingRepository(session).add(posting)
    return posting


def _handoff(
    *,
    user_id: str,
    job_posting_id: str,
    hard_stops: tuple[HardStop, ...] = (_CAPTCHA,),
) -> PortalHandoff:
    return PortalHandoff.raise_for(
        handoff_id=f"smoke-handoff-{uuid.uuid4()}",
        user_id=user_id,
        job_posting_id=job_posting_id,
        apply_url="https://smoketestco.example.com/careers/apply",
        paused_url="https://smoketestco.example.com/login?next=/careers/apply",
        hard_stops=hard_stops,
    )


@pytest.mark.asyncio
async def test_hand_offs_round_trip_against_a_real_database(
    schema_ready: None,
) -> None:
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"
    handoff = _handoff(user_id=user_id, job_posting_id=posting.id)

    async with async_session_factory() as session:
        repository = SqlAlchemyPortalHandoffRepository(session)
        await repository.add(handoff)

        # The boundaries and their evidence survive the JSON column intact —
        # the evidence is the whole case for having stopped.
        stored = await repository.get_by_id(handoff.id)
        assert stored is not None
        assert stored.status is HandoffStatus.AWAITING_USER
        assert stored.is_open is True
        assert stored.kinds == (HardStopKind.CAPTCHA,)
        assert stored.hard_stops[0].evidence == _CAPTCHA.evidence
        assert stored.paused_url.endswith("/login?next=/careers/apply")
        assert stored.last_detected_at == handoff.created_at
        assert stored.resolved_at is None
        assert stored.resolution_note == ""

        # "What is waiting on me for this posting?"
        open_one = await repository.get_open_for_job(
            user_id=user_id, job_posting_id=posting.id
        )
        assert open_one is not None
        assert open_one.id == handoff.id

        # Re-inspecting the same portal updates the same row rather than
        # stacking a second one.
        refreshed = stored.redetected(
            hard_stops=(_WALL,), paused_url="https://smoketestco.example.com/account"
        )
        await repository.update(refreshed)
        reread = await repository.get_by_id(handoff.id)
        assert reread is not None
        assert reread.kinds == (HardStopKind.ACCOUNT_WALL,)
        assert reread.paused_url.endswith("/account")
        assert reread.created_at == handoff.created_at
        assert reread.last_detected_at > handoff.created_at

        # Resolving closes it, and it stops being "the open one".
        await repository.update(reread.resume(note="Signed in as me"))
        resolved = await repository.get_by_id(handoff.id)
        assert resolved is not None
        assert resolved.status is HandoffStatus.RESUMED
        assert resolved.resolved_at is not None
        assert resolved.resolution_note == "Signed in as me"
        assert (
            await repository.get_open_for_job(
                user_id=user_id, job_posting_id=posting.id
            )
            is None
        )


@pytest.mark.asyncio
async def test_only_one_open_hand_off_per_posting_is_allowed(
    schema_ready: None,
) -> None:
    """Enforced by the database, not only by the writer: two concurrent
    inspections would otherwise each raise one, and the candidate would be
    asked to do the same thing twice."""
    posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"

    async with async_session_factory() as session:
        repository = SqlAlchemyPortalHandoffRepository(session)
        await repository.add(_handoff(user_id=user_id, job_posting_id=posting.id))

        with pytest.raises(IntegrityError):
            await repository.add(_handoff(user_id=user_id, job_posting_id=posting.id))

    # A resolved hand-off does not block the next one: a portal that walls,
    # gets resolved, and walls again is a sequence of real events.
    async with async_session_factory() as session:
        repository = SqlAlchemyPortalHandoffRepository(session)
        first = await repository.get_open_for_job(
            user_id=user_id, job_posting_id=posting.id
        )
        assert first is not None
        await repository.update(first.abandon(note="Applying by hand"))
        await repository.add(
            _handoff(user_id=user_id, job_posting_id=posting.id, hard_stops=(_WALL,))
        )

        assert len(await repository.list_for_user(user_id)) == 2


@pytest.mark.asyncio
async def test_the_list_is_scoped_to_the_candidate_and_newest_first(
    schema_ready: None,
) -> None:
    first_posting = await _job_posting()
    second_posting = await _job_posting()
    user_id = f"smoke-user-{uuid.uuid4()}"
    other_user_id = f"smoke-user-{uuid.uuid4()}"
    older = _handoff(user_id=user_id, job_posting_id=first_posting.id)
    newer = _handoff(user_id=user_id, job_posting_id=second_posting.id)

    async with async_session_factory() as session:
        repository = SqlAlchemyPortalHandoffRepository(session)
        await repository.add(older)
        await repository.add(newer)
        await repository.add(
            _handoff(user_id=other_user_id, job_posting_id=first_posting.id)
        )

        listed = await repository.list_for_user(user_id)

        assert [item.id for item in listed] == [newer.id, older.id]


@pytest.mark.asyncio
async def test_updating_a_hand_off_that_no_longer_exists_is_refused(
    schema_ready: None,
) -> None:
    """A blind merge would insert here, resurrecting a hand-off as if it were
    still waiting on the candidate."""
    posting = await _job_posting()
    handoff = _handoff(user_id=f"smoke-user-{uuid.uuid4()}", job_posting_id=posting.id)

    async with async_session_factory() as session:
        repository = SqlAlchemyPortalHandoffRepository(session)

        with pytest.raises(PortalHandoffNotFoundError):
            await repository.update(handoff.resume())

        assert await repository.get_by_id(handoff.id) is None

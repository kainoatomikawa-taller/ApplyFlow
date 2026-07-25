"""Tests for resolving and listing hand-offs — the "resumable after the user
acts" half of the flow.

What is asserted here is mostly about honesty and scoping: resuming records
the candidate's assertion (and does not claim the boundary was verified gone),
abandoning is a real ending rather than a failure, neither can be done twice,
neither can be done to somebody else's hand-off, and the list a candidate reads
tells them what is still waiting without hiding what they already dealt with.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.dtos.portal_handoff_dtos import (
    ListPortalHandoffsInput,
    ResolvePortalHandoffInput,
)
from src.application.use_cases.abandon_portal_handoff import AbandonPortalHandoff
from src.application.use_cases.list_portal_handoffs import ListPortalHandoffs
from src.application.use_cases.resume_portal_handoff import ResumePortalHandoff
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.exceptions import (
    BusinessRuleViolationError,
    PortalHandoffNotFoundError,
)
from src.domain.value_objects.handoff_status import HandoffStatus
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from tests.application.conftest import InMemoryPortalHandoffRepository

_EPOCH = datetime(2026, 7, 25, 9, 0, tzinfo=UTC)
_WALL = HardStop(
    kind=HardStopKind.ACCOUNT_WALL, evidence=("the form presents 1 password field",)
)


def _handoff(
    *,
    handoff_id: str = "handoff-1",
    user_id: str = "user-1",
    job_posting_id: str = "job-1",
    minutes_old: int = 0,
) -> PortalHandoff:
    return PortalHandoff.raise_for(
        handoff_id=handoff_id,
        user_id=user_id,
        job_posting_id=job_posting_id,
        apply_url="https://globex.example.com/apply/4242",
        paused_url="https://globex.example.com/login",
        hard_stops=(_WALL,),
        detected_at=_EPOCH - timedelta(minutes=minutes_old),
    )


def _resolve_input(**overrides: str) -> ResolvePortalHandoffInput:
    defaults = {"user_id": "user-1", "handoff_id": "handoff-1", "note": ""}
    defaults.update(overrides)
    return ResolvePortalHandoffInput(**defaults)


# ---- resuming ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_resuming_closes_the_hand_off_and_keeps_the_candidates_note():
    repository = InMemoryPortalHandoffRepository([_handoff()])
    use_case = ResumePortalHandoff(repository=repository)

    output = await use_case.execute(_resolve_input(note="Signed in as me"))

    assert output.status == HandoffStatus.RESUMED.value
    assert output.is_open is False
    assert output.resolved_at is not None
    assert output.resolution_note == "Signed in as me"
    assert repository.handoffs["handoff-1"].status is HandoffStatus.RESUMED


@pytest.mark.asyncio
async def test_resuming_needs_no_note():
    repository = InMemoryPortalHandoffRepository([_handoff()])

    output = await ResumePortalHandoff(repository=repository).execute(_resolve_input())

    assert output.is_open is False
    assert output.resolution_note == ""


@pytest.mark.asyncio
async def test_the_evidence_survives_the_resolution():
    """A resolved hand-off still has to say what it was about — it is the
    record of why ApplyFlow stopped, read long after the fact."""
    repository = InMemoryPortalHandoffRepository([_handoff()])

    output = await ResumePortalHandoff(repository=repository).execute(_resolve_input())

    assert [stop.kind for stop in output.hard_stops] == [
        HardStopKind.ACCOUNT_WALL.value
    ]
    assert output.hard_stops[0].evidence == ["the form presents 1 password field"]


@pytest.mark.asyncio
async def test_resuming_twice_is_a_business_rule_violation():
    repository = InMemoryPortalHandoffRepository([_handoff()])
    use_case = ResumePortalHandoff(repository=repository)
    await use_case.execute(_resolve_input())

    with pytest.raises(BusinessRuleViolationError):
        await use_case.execute(_resolve_input())


@pytest.mark.asyncio
async def test_someone_elses_hand_off_reads_as_not_found():
    """Never "forbidden": that would confirm the id exists."""
    repository = InMemoryPortalHandoffRepository([_handoff(user_id="user-2")])

    with pytest.raises(PortalHandoffNotFoundError):
        await ResumePortalHandoff(repository=repository).execute(_resolve_input())

    assert repository.handoffs["handoff-1"].is_open is True


@pytest.mark.asyncio
async def test_an_unknown_hand_off_reads_as_not_found():
    repository = InMemoryPortalHandoffRepository()

    with pytest.raises(PortalHandoffNotFoundError):
        await ResumePortalHandoff(repository=repository).execute(_resolve_input())


# ---- abandoning -------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandoning_is_recorded_as_its_own_ending():
    """Not a failure, and not the same as resuming: "I am submitting this one
    myself" is what keeps a permanent account wall from sitting open forever."""
    repository = InMemoryPortalHandoffRepository([_handoff()])

    output = await AbandonPortalHandoff(repository=repository).execute(
        _resolve_input(note="Applying by hand")
    )

    assert output.status == HandoffStatus.ABANDONED.value
    assert output.is_open is False
    assert repository.handoffs["handoff-1"].status is HandoffStatus.ABANDONED


@pytest.mark.asyncio
async def test_an_abandoned_hand_off_cannot_then_be_resumed():
    repository = InMemoryPortalHandoffRepository([_handoff()])
    await AbandonPortalHandoff(repository=repository).execute(_resolve_input())

    with pytest.raises(BusinessRuleViolationError):
        await ResumePortalHandoff(repository=repository).execute(_resolve_input())


@pytest.mark.asyncio
async def test_abandoning_someone_elses_hand_off_reads_as_not_found():
    repository = InMemoryPortalHandoffRepository([_handoff(user_id="user-2")])

    with pytest.raises(PortalHandoffNotFoundError):
        await AbandonPortalHandoff(repository=repository).execute(_resolve_input())


# ---- listing ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_list_is_newest_first_and_counts_what_is_still_waiting():
    repository = InMemoryPortalHandoffRepository(
        [
            _handoff(handoff_id="old", job_posting_id="job-1", minutes_old=90),
            _handoff(handoff_id="new", job_posting_id="job-2", minutes_old=5),
        ]
    )
    await ResumePortalHandoff(repository=repository).execute(
        _resolve_input(handoff_id="old")
    )

    output = await ListPortalHandoffs(repository=repository).execute(
        ListPortalHandoffsInput(user_id="user-1")
    )

    assert [handoff.id for handoff in output.handoffs] == ["new", "old"]
    assert output.open_count == 1


@pytest.mark.asyncio
async def test_resolved_hand_offs_are_included_by_default():
    """Recent history is what stops a candidate doing the same step twice."""
    repository = InMemoryPortalHandoffRepository([_handoff()])
    await ResumePortalHandoff(repository=repository).execute(_resolve_input())

    output = await ListPortalHandoffs(repository=repository).execute(
        ListPortalHandoffsInput(user_id="user-1")
    )

    assert [handoff.status for handoff in output.handoffs] == [
        HandoffStatus.RESUMED.value
    ]
    assert output.open_count == 0


@pytest.mark.asyncio
async def test_open_only_filters_the_list_without_changing_the_count():
    """The count is taken before the filter, so "1 waiting on you" cannot
    disagree with itself between two views of the same data."""
    repository = InMemoryPortalHandoffRepository(
        [
            _handoff(handoff_id="done", job_posting_id="job-1", minutes_old=30),
            _handoff(handoff_id="waiting", job_posting_id="job-2"),
        ]
    )
    await AbandonPortalHandoff(repository=repository).execute(
        _resolve_input(handoff_id="done")
    )

    output = await ListPortalHandoffs(repository=repository).execute(
        ListPortalHandoffsInput(user_id="user-1", open_only=True)
    )

    assert [handoff.id for handoff in output.handoffs] == ["waiting"]
    assert output.open_count == 1


@pytest.mark.asyncio
async def test_a_candidate_only_sees_their_own_hand_offs():
    repository = InMemoryPortalHandoffRepository(
        [
            _handoff(handoff_id="mine"),
            _handoff(handoff_id="theirs", user_id="user-2", job_posting_id="job-2"),
        ]
    )

    output = await ListPortalHandoffs(repository=repository).execute(
        ListPortalHandoffsInput(user_id="user-1")
    )

    assert [handoff.id for handoff in output.handoffs] == ["mine"]

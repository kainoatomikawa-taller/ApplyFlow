"""ListPortalHandoffs use case — what is waiting on the candidate, and what
recently was.

The read behind "ApplyFlow stopped on these applications and needs you". A
hand-off that only existed in the response that created it would not be a
hand-off at all: the candidate leaves to go and do the step, comes back to a
reloaded page, and has to be told what they were in the middle of.

Resolved hand-offs come back too unless `open_only` asks otherwise, because
recent history is what stops someone doing a step twice ("this portal made me
sign in, and I dealt with it yesterday"). `open_count` is reported alongside so
a banner or badge does not have to re-derive it from the list — and so it stays
correct when the list is truncated by `limit`.
"""

from __future__ import annotations

from src.application.dtos.portal_handoff_dtos import (
    ListPortalHandoffsInput,
    ListPortalHandoffsOutput,
)
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository


class ListPortalHandoffs:
    def __init__(self, repository: PortalHandoffRepository) -> None:
        self._repository = repository

    async def execute(self, dto: ListPortalHandoffsInput) -> ListPortalHandoffsOutput:
        handoffs = await self._repository.list_for_user(dto.user_id, limit=dto.limit)
        # Counted before the filter, so "3 waiting on you" cannot disagree
        # with itself depending on which view the caller asked for.
        open_count = sum(1 for handoff in handoffs if handoff.is_open)
        if dto.open_only:
            handoffs = [handoff for handoff in handoffs if handoff.is_open]
        return ListPortalHandoffsOutput(
            handoffs=[PortalHandoffMapper.to_output(item) for item in handoffs],
            open_count=open_count,
        )

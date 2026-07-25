"""AbandonPortalHandoff use case — the candidate is finishing this application
themselves, so ApplyFlow stops waiting on it.

The other legitimate ending to a hand-off, and the reason no hand-off is ever
stuck open. Some boundaries never become automatable: a portal that requires a
real account will require one on the next visit too, and a candidate who has
decided to submit that application by hand should not keep being asked about
it. Without this, "hand-offs waiting on you" would fill up with items that
have no resolution, and a list nobody can clear is a list nobody reads.

Not a failure state, and deliberately not modeled as one — see
`HandoffStatus`. It also is not a withdrawal of the application: what is being
abandoned is *ApplyFlow's automation of this portal*, not the candidate's
interest in the job, which is why it touches nothing but the hand-off.

Same shape and same scoping as `ResumePortalHandoff`: a hand-off belonging to
somebody else reads as not found rather than as forbidden.
"""

from __future__ import annotations

from src.application.dtos.portal_handoff_dtos import (
    PortalHandoffOutput,
    ResolvePortalHandoffInput,
)
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.domain.exceptions import PortalHandoffNotFoundError
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository


class AbandonPortalHandoff:
    def __init__(self, repository: PortalHandoffRepository) -> None:
        self._repository = repository

    async def execute(self, dto: ResolvePortalHandoffInput) -> PortalHandoffOutput:
        handoff = await self._repository.get_by_id(dto.handoff_id)
        if handoff is None or handoff.user_id != dto.user_id:
            raise PortalHandoffNotFoundError(dto.handoff_id)

        abandoned = handoff.abandon(note=dto.note)
        await self._repository.update(abandoned)
        return PortalHandoffMapper.to_output(abandoned)

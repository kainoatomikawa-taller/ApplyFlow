"""ResumePortalHandoff use case — the candidate says they did the human-only
step, so ApplyFlow may work this portal again.

What resuming does and does not claim
------------------------------------
It records the candidate's assertion. It does not verify that the boundary is
gone, and it must not pretend to: the person solves the CAPTCHA or signs in
*in their own browser*, and the next ApplyFlow session shares none of that
state — a fresh headless session on a portal behind a sign-in wall would still
see the wall. A "verified resume" here would therefore either be permanently
impossible to satisfy (dead end for the candidate) or a lie (a claim nobody
checked).

What makes it honest instead is what happens next: the following inspection
re-reads the portal and, if a boundary is still there, opens a *new* hand-off
with fresh evidence (`InspectApplicationPortal`). Resuming does not assert the
wall fell — it asserts the candidate has acted, which is exactly what
ApplyFlow was waiting for. Whether it worked is the portal's answer to give,
and the next inspection asks it.

Scoped to its owner: a hand-off id belonging to somebody else reads as not
found rather than as forbidden, so this endpoint cannot be used to discover
which ids exist.
"""

from __future__ import annotations

from src.application.dtos.portal_handoff_dtos import (
    PortalHandoffOutput,
    ResolvePortalHandoffInput,
)
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.domain.exceptions import PortalHandoffNotFoundError
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository


class ResumePortalHandoff:
    def __init__(self, repository: PortalHandoffRepository) -> None:
        self._repository = repository

    async def execute(self, dto: ResolvePortalHandoffInput) -> PortalHandoffOutput:
        handoff = await self._repository.get_by_id(dto.handoff_id)
        if handoff is None or handoff.user_id != dto.user_id:
            raise PortalHandoffNotFoundError(dto.handoff_id)

        # `resume` raises BusinessRuleViolationError on an already-resolved
        # hand-off (see `HandoffStatus.transition_to`), which is what turns a
        # double-clicked "I've done it" into a rejected second request instead
        # of a rewritten resolution time.
        resumed = handoff.resume(note=dto.note)
        await self._repository.update(resumed)
        return PortalHandoffMapper.to_output(resumed)

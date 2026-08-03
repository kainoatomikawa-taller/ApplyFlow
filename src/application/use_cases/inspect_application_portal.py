"""InspectApplicationPortal use case — opens a posting's application portal,
checks it for boundaries ApplyFlow must not cross, and either hands the form
back or hands the candidate control.

This is the gate every autofill capability sits behind. The order of
operations is the whole design and it is not an optimization:

1. open a browser session on the posting's `apply_url`;
2. read the page's *signals* — what it says, what it loads, what its form
   asks for — without touching anything;
3. ask the domain (`HardStopDetector`) whether that reading contains a
   boundary;
4. **only if it does not**, read the fillable fields and hand them back.

Reading the boundary first is what makes the pause real. A flow that read the
form and then checked would already be holding a filled-in path to a sign-in
page's password box, and "we decided not to use it" is a weaker guarantee
than "we never asked for it". When a boundary is found this use case returns
no fields at all — the caller downstream has nothing to fill, so it cannot
proceed by accident, whether it is a person, a script, or a model.

Persistence, and why the same portal does not pile up hand-offs
---------------------------------------------------------------
A hand-off is written so the pause survives the request that produced it (see
`PortalHandoff`). Inspecting the same portal twice while the candidate has not
acted yet refreshes the *existing* open hand-off rather than adding a second
one: a portal can present a different boundary on a second visit, and the
candidate should see one live hand-off per portal, updated, not a growing pile
of near-duplicates.

Two inspections of the same portal running *concurrently* can both find no open
hand-off and both try to open one. The loser fails on the database's
one-open-per-posting index rather than being merged in here, and that is the
deliberate trade: a failed inspection is retryable and visible, while the
alternative — writing recovery logic that reconciles two live detections — is
complexity in the one flow that most needs to stay readable. The property that
matters is preserved either way: the candidate is never asked to do the same
thing twice.

The one case where ApplyFlow closes a hand-off itself
-----------------------------------------------------
If an inspection finds no boundary while a hand-off is still open for that
posting, the wall the candidate was asked about is *gone* — which is stronger
evidence than their word — so the hand-off is resolved as resumed, noting that
re-inspection cleared it, and the id is reported in
`cleared_handoff_id`. Every other resolution belongs to the candidate
(`ResumePortalHandoff`, `AbandonPortalHandoff`).

Sessions are always closed, including when detection or discovery raises: a
browser context left open per inspection is how a worker runs out of memory a
few hundred applications later.
"""

from __future__ import annotations

import logging

from src.application.dtos.portal_handoff_dtos import (
    InspectApplicationPortalInput,
    InspectApplicationPortalOutput,
)
from src.application.mappers.portal_handoff_mapper import PortalHandoffMapper
from src.application.ports.browser_automation_port import BrowserAutomationPort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.exceptions import JobPostingNotFoundError
from src.domain.repositories.job_posting_repository import JobPostingRepository
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository
from src.domain.services.hard_stop_detector import HardStopDetector
from src.domain.value_objects.hard_stop import HardStop

logger = logging.getLogger(__name__)

#: What is recorded on a hand-off ApplyFlow closed on its own evidence,
#: rather than on the candidate's assertion that they dealt with it.
_CLEARED_BY_REINSPECTION_NOTE = (
    "Cleared automatically: a later inspection of this portal found no hard "
    "boundary on the form."
)


class InspectApplicationPortal:
    def __init__(
        self,
        job_posting_repository: JobPostingRepository,
        handoff_repository: PortalHandoffRepository,
        browser_automation: BrowserAutomationPort,
        id_generator: IdGeneratorPort,
        detector: HardStopDetector | None = None,
    ) -> None:
        self._job_posting_repository = job_posting_repository
        self._handoff_repository = handoff_repository
        self._browser_automation = browser_automation
        self._id_generator = id_generator
        # A pure default the use case builds itself, like the guards on the
        # generation use cases: no wiring mistake can produce an inspection
        # that skipped the boundary check.
        self._detector = detector or HardStopDetector()

    async def execute(
        self, dto: InspectApplicationPortalInput
    ) -> InspectApplicationPortalOutput:
        posting = await self._job_posting_repository.get_by_id(dto.job_posting_id)
        if posting is None:
            raise JobPostingNotFoundError(dto.job_posting_id)

        session = await self._browser_automation.open(posting.apply_url)
        try:
            signals = await session.read_page_signals()
            hard_stops = self._detector.detect(signals)
            if hard_stops:
                return await self._hand_off(
                    dto=dto,
                    apply_url=posting.apply_url,
                    landed_url=signals.url,
                    hard_stops=hard_stops,
                )
            fields = await session.read_fields()
            landed_url = signals.url
        finally:
            await session.close()

        cleared = await self._clear_open_handoff(dto)
        return InspectApplicationPortalOutput(
            job_posting_id=dto.job_posting_id,
            apply_url=posting.apply_url,
            landed_url=landed_url,
            is_handed_off=False,
            handoff=None,
            fields=[PortalHandoffMapper.field_to_output(item) for item in fields],
            cleared_handoff_id=cleared,
        )

    # ---- internals -----------------------------------------------------------

    async def _hand_off(
        self,
        *,
        dto: InspectApplicationPortalInput,
        apply_url: str,
        landed_url: str,
        hard_stops: tuple[HardStop, ...],
    ) -> InspectApplicationPortalOutput:
        """Open or refresh the hand-off for this portal and return it with no
        fields — the pause, enforced by there being nothing to fill."""
        existing = await self._handoff_repository.get_open_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        if existing is None:
            handoff = PortalHandoff.raise_for(
                handoff_id=self._id_generator.new_id(),
                user_id=dto.user_id,
                job_posting_id=dto.job_posting_id,
                apply_url=apply_url,
                paused_url=landed_url,
                hard_stops=hard_stops,
            )
            await self._handoff_repository.add(handoff)
        else:
            handoff = existing.redetected(hard_stops=hard_stops, paused_url=landed_url)
            await self._handoff_repository.update(handoff)

        # Logged because a hand-off is a flow that stopped, and an operator
        # tracing "why did nothing happen for this posting?" needs it. Only
        # the kinds and ids: the evidence is about the portal, but the note is
        # the candidate's own words and is never logged.
        logger.info(
            "Handed off portal automation to the candidate: handoff=%s posting=%s "
            "boundaries=%s",
            handoff.id,
            handoff.job_posting_id,
            ",".join(kind.value for kind in handoff.kinds),
        )
        return InspectApplicationPortalOutput(
            job_posting_id=dto.job_posting_id,
            apply_url=apply_url,
            landed_url=landed_url,
            is_handed_off=True,
            handoff=PortalHandoffMapper.to_output(handoff),
            fields=[],
        )

    async def _clear_open_handoff(
        self, dto: InspectApplicationPortalInput
    ) -> str | None:
        """Resolve an open hand-off whose boundary is no longer on the page."""
        existing = await self._handoff_repository.get_open_for_job(
            user_id=dto.user_id, job_posting_id=dto.job_posting_id
        )
        if existing is None:
            return None
        await self._handoff_repository.update(
            existing.resume(note=_CLEARED_BY_REINSPECTION_NOTE)
        )
        logger.info(
            "A portal hand-off cleared itself: handoff=%s posting=%s",
            existing.id,
            existing.job_posting_id,
        )
        return existing.id

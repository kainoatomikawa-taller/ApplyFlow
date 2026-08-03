"""SQLAlchemy implementation of the PortalHandoffRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.

`update` reads the row first instead of `merge`-ing blindly, because a merge
that finds nothing inserts — and here that would resurrect a hand-off the
candidate already resolved and deleted-by-cascade, presenting it as still
waiting on them. A missing row is `PortalHandoffNotFoundError`.

The stored `hard_stops` JSON is validated on the way back in rather than
trusted: it is a JSON column, so a bad migration or a hand-edited row can put
anything in it, and a hand-off is rebuilt through `HardStop`'s own constructor
so a row with no evidence surfaces as an error instead of showing a candidate
an unexplained halt.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.portal_handoff import PortalHandoff
from src.domain.exceptions import InvalidValueError, PortalHandoffNotFoundError
from src.domain.repositories.portal_handoff_repository import PortalHandoffRepository
from src.domain.value_objects.handoff_status import HandoffStatus
from src.domain.value_objects.hard_stop import HardStop
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.infrastructure.persistence.models import PortalHandoffModel


class SqlAlchemyPortalHandoffRepository(PortalHandoffRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, handoff: PortalHandoff) -> None:
        self._session.add(self._to_model(handoff))
        await self._session.commit()

    async def update(self, handoff: PortalHandoff) -> None:
        model = await self._session.get(PortalHandoffModel, handoff.id)
        if model is None:
            raise PortalHandoffNotFoundError(handoff.id)
        model.apply_url = handoff.apply_url
        model.paused_url = handoff.paused_url
        model.status = handoff.status.value
        model.hard_stops = self._hard_stops_to_json(handoff)
        model.last_detected_at = handoff.last_detected_at or handoff.created_at
        model.resolved_at = handoff.resolved_at
        model.resolution_note = handoff.resolution_note
        await self._session.commit()

    async def get_by_id(self, handoff_id: str) -> PortalHandoff | None:
        model = await self._session.get(PortalHandoffModel, handoff_id)
        return self._to_entity(model) if model else None

    async def get_open_for_job(
        self, *, user_id: str, job_posting_id: str
    ) -> PortalHandoff | None:
        result = await self._session.execute(
            select(PortalHandoffModel)
            .where(
                PortalHandoffModel.user_id == user_id,
                PortalHandoffModel.job_posting_id == job_posting_id,
                PortalHandoffModel.status == HandoffStatus.AWAITING_USER.value,
            )
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    async def list_for_user(
        self, user_id: str, *, limit: int = 100
    ) -> list[PortalHandoff]:
        result = await self._session.execute(
            select(PortalHandoffModel)
            .where(PortalHandoffModel.user_id == user_id)
            .order_by(PortalHandoffModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    # ---- mapping helpers -----------------------------------------------------

    @staticmethod
    def _hard_stops_to_json(handoff: PortalHandoff) -> list[dict[str, Any]]:
        return [
            {"kind": stop.kind.value, "evidence": list(stop.evidence)}
            for stop in handoff.hard_stops
        ]

    @classmethod
    def _to_model(cls, entity: PortalHandoff) -> PortalHandoffModel:
        return PortalHandoffModel(
            id=entity.id,
            user_id=entity.user_id,
            job_posting_id=entity.job_posting_id,
            apply_url=entity.apply_url,
            paused_url=entity.paused_url,
            status=entity.status.value,
            hard_stops=cls._hard_stops_to_json(entity),
            created_at=entity.created_at,
            last_detected_at=entity.last_detected_at or entity.created_at,
            resolved_at=entity.resolved_at,
            resolution_note=entity.resolution_note,
        )

    @staticmethod
    def _to_entity(model: PortalHandoffModel) -> PortalHandoff:
        return PortalHandoff(
            id=model.id,
            user_id=model.user_id,
            job_posting_id=model.job_posting_id,
            apply_url=model.apply_url,
            paused_url=model.paused_url,
            hard_stops=_hard_stops_from_json(model.id, model.hard_stops),
            status=HandoffStatus(model.status),
            created_at=model.created_at,
            last_detected_at=model.last_detected_at,
            resolved_at=model.resolved_at,
            resolution_note=model.resolution_note or "",
        )


def _hard_stops_from_json(handoff_id: str, stored: object) -> tuple[HardStop, ...]:
    """Rebuild the boundaries from the JSON column, refusing a row that no
    longer describes any.

    `HardStop`'s constructor does the validating, so the rule that a hand-off
    must be explainable is enforced in one place regardless of whether the
    value came from a detector or from the database.
    """
    if not isinstance(stored, list):
        raise InvalidValueError(
            f"Portal hand-off '{handoff_id}' has a malformed hard_stops column."
        )
    stops: list[HardStop] = []
    for item in stored:
        if not isinstance(item, dict):
            raise InvalidValueError(
                f"Portal hand-off '{handoff_id}' has a malformed hard stop entry."
            )
        kind = item.get("kind")
        evidence = item.get("evidence")
        try:
            hard_stop_kind = HardStopKind(str(kind))
        except ValueError as exc:
            raise InvalidValueError(
                f"Portal hand-off '{handoff_id}' names an unknown boundary "
                f"kind '{kind}'."
            ) from exc
        stops.append(
            HardStop(
                kind=hard_stop_kind,
                evidence=(
                    tuple(str(line) for line in evidence if str(line).strip())
                    if isinstance(evidence, list)
                    else ()
                ),
            )
        )
    return tuple(stops)

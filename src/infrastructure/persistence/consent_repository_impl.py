"""SQLAlchemy implementation of the ConsentRepository interface.

Maps DB rows <-> domain entities. Never leaks ORM types outward.

Append-only in practice as well as in the interface: `save` inserts the
decisions a record has gained beyond what is already stored and touches nothing
else. There is no UPDATE and no DELETE anywhere in this module, which is what
makes the ledger usable as the GDPR Art. 7(1) demonstration record — a store
that could rewrite a decision proves nothing about what the user chose.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.consent_record import ConsentRecord
from src.domain.repositories.consent_repository import ConsentRepository
from src.domain.value_objects.consent_decision import ConsentDecision
from src.domain.value_objects.consent_purpose import ConsentPurpose
from src.infrastructure.persistence.models import ConsentDecisionModel


class SqlAlchemyConsentRepository(ConsentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, user_id: str, purpose: ConsentPurpose) -> ConsentRecord:
        result = await self._session.execute(
            select(ConsentDecisionModel)
            .where(
                ConsentDecisionModel.user_id == user_id,
                ConsentDecisionModel.purpose == purpose.value,
            )
            .order_by(ConsentDecisionModel.sequence)
        )
        rows = list(result.scalars())
        return self._to_entity(user_id=user_id, purpose=purpose, rows=rows)

    async def list_for_user(self, user_id: str) -> list[ConsentRecord]:
        """One ledger per declared purpose, including never-answered ones.

        A single query for the whole user rather than one per purpose: the
        consent screen and the export both want all of them, and the purposes
        with no rows are filled in from the enum rather than from the database,
        because "this user has never been asked" is a fact about the enum's
        contents and not about the table's.
        """
        result = await self._session.execute(
            select(ConsentDecisionModel)
            .where(ConsentDecisionModel.user_id == user_id)
            .order_by(ConsentDecisionModel.purpose, ConsentDecisionModel.sequence)
        )
        by_purpose: dict[str, list[ConsentDecisionModel]] = {}
        for row in result.scalars():
            by_purpose.setdefault(row.purpose, []).append(row)
        # Iterating the enum, not the rows: a purpose stored under a value this
        # release no longer declares would be silently dropped here. That is the
        # correct reading — the ledger is answered against the purposes the
        # application actually has — and it is why renaming a purpose value is a
        # migration (see `ConsentPurpose`).
        return [
            self._to_entity(
                user_id=user_id,
                purpose=purpose,
                rows=by_purpose.get(purpose.value, []),
            )
            for purpose in ConsentPurpose
        ]

    async def save(self, record: ConsentRecord) -> None:
        """Insert the decisions not yet stored, leaving the rest untouched.

        Counts the stored rows to find where to resume rather than diffing them,
        for the same reason `SqlAlchemyTrackedApplicationRepository.update` does
        with status history: the ledger is append-only and gap-free, so the
        stored count *is* the next sequence number, and re-reading the rows to
        compare would only give a second opportunity to disagree with them.
        """
        result = await self._session.execute(
            select(ConsentDecisionModel.sequence)
            .where(
                ConsentDecisionModel.user_id == record.user_id,
                ConsentDecisionModel.purpose == record.purpose.value,
            )
            .order_by(ConsentDecisionModel.sequence.desc())
            .limit(1)
        )
        highest = result.scalar_one_or_none()
        stored = 0 if highest is None else highest + 1
        for offset, decision in enumerate(record.history[stored:]):
            self._session.add(
                ConsentDecisionModel(
                    user_id=record.user_id,
                    purpose=decision.purpose.value,
                    sequence=stored + offset,
                    granted=decision.granted,
                    decided_at=decision.decided_at,
                    policy_version=decision.policy_version,
                )
            )
        await self._session.commit()

    @staticmethod
    def _to_entity(
        *,
        user_id: str,
        purpose: ConsentPurpose,
        rows: list[ConsentDecisionModel],
    ) -> ConsentRecord:
        return ConsentRecord(
            user_id=user_id,
            purpose=purpose,
            history=tuple(
                ConsentDecision(
                    purpose=purpose,
                    granted=row.granted,
                    decided_at=row.decided_at,
                    policy_version=row.policy_version,
                )
                for row in rows
            ),
        )

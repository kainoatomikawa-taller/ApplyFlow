"""ResolveGapAnswer use case — captures a candidate's response to one
gap-resolution question, or cleanly omits the gap when the candidate has
nothing to add.

Mirrors `StoreAnswer`'s embed-then-persist shape (both produce an
`AnswerMemory` tagged `ProvenanceSource.ANSWER`), but is not implemented
in terms of it — use cases never depend on one another directly — and
adds the one behavior `StoreAnswer` doesn't need: recognizing a decline
via `GapAnswerPolicy` and skipping persistence entirely rather than
writing a fact that isn't there. A declined gap leaves no trace — no
`AnswerMemory` row, no partial record — which is what "cleanly omits the
item" means in practice.
"""

from __future__ import annotations

from src.application.dtos.gap_resolution_dtos import (
    ResolveGapAnswerInput,
    ResolveGapAnswerOutput,
)
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.services.gap_answer_policy import GapAnswerPolicy
from src.domain.value_objects.provenance_source import ProvenanceSource


class ResolveGapAnswer:
    def __init__(
        self,
        repository: AnswerMemoryRepository,
        embedding_client: EmbeddingClientPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._id_generator = id_generator

    async def execute(self, dto: ResolveGapAnswerInput) -> ResolveGapAnswerOutput:
        if GapAnswerPolicy.is_declined(dto.answer_text):
            return ResolveGapAnswerOutput(gap=dto.gap, captured=False)

        embedding = await self._embedding_client.embed(dto.question_text)
        answer_memory = AnswerMemory(
            id=self._id_generator.new_id(),
            user_id=dto.user_id,
            question_text=dto.question_text,
            answer_text=dto.answer_text,
            embedding=embedding,
            source=ProvenanceSource.ANSWER,
        )
        await self._repository.add(answer_memory)

        return ResolveGapAnswerOutput(
            gap=dto.gap, captured=True, answer_memory_id=answer_memory.id
        )

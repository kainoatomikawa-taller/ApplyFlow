"""StoreAnswer use case — remember a candidate's answer to an application
question so it isn't re-asked.

Generates the question's embedding through the Epic 00 embedding layer
(`EmbeddingClientPort`), then persists the pair tagged
`ProvenanceSource.ANSWER` — the only provenance an `AnswerMemory` can ever
carry (see that entity's docstring).
"""

from __future__ import annotations

from src.application.dtos.answer_memory_dtos import AnswerMemoryOutput, StoreAnswerInput
from src.application.mappers.answer_memory_mapper import AnswerMemoryMapper
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.application.ports.id_generator_port import IdGeneratorPort
from src.domain.entities.answer_memory import AnswerMemory
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.value_objects.provenance_source import ProvenanceSource


class StoreAnswer:
    def __init__(
        self,
        repository: AnswerMemoryRepository,
        embedding_client: EmbeddingClientPort,
        id_generator: IdGeneratorPort,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._id_generator = id_generator

    async def execute(self, dto: StoreAnswerInput) -> AnswerMemoryOutput:
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

        return AnswerMemoryMapper.to_output(answer_memory)

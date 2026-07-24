"""ListAnswerMemories use case — list a candidate's remembered answers."""

from __future__ import annotations

from src.application.dtos.answer_memory_dtos import AnswerMemoryOutput
from src.application.mappers.answer_memory_mapper import AnswerMemoryMapper
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository


class ListAnswerMemories:
    def __init__(self, repository: AnswerMemoryRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: str) -> list[AnswerMemoryOutput]:
        answer_memories = await self._repository.list_by_user_id(user_id)
        return [AnswerMemoryMapper.to_output(a) for a in answer_memories]

"""GetAnswerMemory use case — fetch a single remembered answer.

Scoped to the requesting user: an answer memory belonging to someone else
is reported as not found rather than forbidden, so the endpoint never
confirms or denies another user's answer-memory ids exist.
"""

from __future__ import annotations

from src.application.dtos.answer_memory_dtos import AnswerMemoryOutput
from src.application.mappers.answer_memory_mapper import AnswerMemoryMapper
from src.domain.exceptions import AnswerMemoryNotFoundError
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository


class GetAnswerMemory:
    def __init__(self, repository: AnswerMemoryRepository) -> None:
        self._repository = repository

    async def execute(self, answer_memory_id: str, user_id: str) -> AnswerMemoryOutput:
        answer_memory = await self._repository.get_by_id(answer_memory_id)
        if answer_memory is None or answer_memory.user_id != user_id:
            raise AnswerMemoryNotFoundError(answer_memory_id)
        return AnswerMemoryMapper.to_output(answer_memory)

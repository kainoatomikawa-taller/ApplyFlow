"""Mapper between the AnswerMemory entity and its output DTO."""

from __future__ import annotations

from src.application.dtos.answer_memory_dtos import AnswerMemoryOutput
from src.domain.entities.answer_memory import AnswerMemory


class AnswerMemoryMapper:
    """Translates domain entities into output DTOs."""

    @staticmethod
    def to_output(answer_memory: AnswerMemory) -> AnswerMemoryOutput:
        return AnswerMemoryOutput(
            id=answer_memory.id,
            user_id=answer_memory.user_id,
            question_text=answer_memory.question_text,
            answer_text=answer_memory.answer_text,
            embedding=answer_memory.embedding,
            source=answer_memory.source.value,
            created_at=answer_memory.created_at,
        )

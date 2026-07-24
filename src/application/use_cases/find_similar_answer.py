"""FindSimilarAnswer use case — semantic retrieval of a remembered answer.

Embeds the incoming question through the same `EmbeddingClientPort` used
by `StoreAnswer`, then asks `AnswerSimilarityMatcher` (a pure domain
service) to find the closest previously-remembered answer among this
user's `AnswerMemory` records. Returns `None` when nothing clears the
similarity threshold — the caller (e.g. an autofill flow) decides what to
do with "no match found"; this use case never returns a low-confidence
guess dressed up as a hit.
"""

from __future__ import annotations

from src.application.dtos.answer_memory_dtos import (
    AnswerMatchOutput,
    FindSimilarAnswerInput,
)
from src.application.mappers.answer_memory_mapper import AnswerMemoryMapper
from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.services.answer_similarity_matcher import AnswerSimilarityMatcher


class FindSimilarAnswer:
    def __init__(
        self,
        repository: AnswerMemoryRepository,
        embedding_client: EmbeddingClientPort,
        matcher: AnswerSimilarityMatcher | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._matcher = matcher or AnswerSimilarityMatcher()

    async def execute(self, dto: FindSimilarAnswerInput) -> AnswerMatchOutput | None:
        question_embedding = await self._embedding_client.embed(dto.question_text)
        candidates = await self._repository.list_by_user_id(dto.user_id)

        match = self._matcher.find_best_match(
            question_embedding, candidates, threshold=dto.threshold
        )
        if match is None:
            return None
        return AnswerMemoryMapper.to_match_output(match)
